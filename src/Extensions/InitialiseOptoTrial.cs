using Bonsai;
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Reactive.Linq;
using UclOpenAuditoryVrCorridorDataSchema;

// The optogenetics part of av-dome's InitialiseTrial operator, rewritten for this task. The rest of the trial is drawn by
// main.bonsai, so this only decides, for each new trial, whether the laser is on and which Zapit condition is presented.
// Differences from av-dome:
// - Sham trials: in an optogenetics session every trial sends a StartStimulus. Laser-off trials (warmup included) still get
//   a real condition, so the galvos move and the masking light comes on exactly as on laser-on trials.
// - Stim and sham conditions are drawn from separate shuffled queues, so each set is balanced on its own.
// - OptogeneticMaxDuration (stimDuration) is set on every trial: Bonsai stops the stimulus at the outcome or after this many
//   seconds, whichever comes first. Zapit itself only ever gets continuous stimuli.
// - Conditions come from ZapitStimConfig (no YamlDotNet), which also checks that they are numbered 1 to N.
[Combinator]
[Description("Draws the optogenetics for each new trial: laser on or off, and which condition from the Zapit stimulus config to present. In an optogenetics session every trial gets a condition (laser-off trials are sham stimuli). Input is the trial number (from 1) and the task parameters.")]
[WorkflowElementCategory(ElementCategory.Transform)]
public class InitialiseOptoTrial
{
    public InitialiseOptoTrial()
    {
        Seed = -1;
    }

    [Description("Seed for the draws. -1 (recommended) uses a new random seed each session. Every trial's draw is logged in the TrialLog, so a session can be reconstructed either way.")]
    public int Seed { get; set; }

    // Instance state: this operator sits inside TaskLogic's per-trial Defer, which calls Process again on every trial with
    // the same instance, so state kept inside Process would be lost between trials. Reset on trial 1, so each session starts
    // with a fresh random stream and fresh queues.
    private Random random;
    private List<int> conditions; // null until read from the Zapit stimulus config, on the first trial of an optogenetics session
    private readonly ConditionQueue stimQueue = new ConditionQueue();
    private readonly ConditionQueue shamQueue = new ConditionQueue();

    public IObservable<OptoTrial> Process(IObservable<Tuple<int, UclOpenAuditoryVrCorridorTaskParameters>> source)
    {
        // Trial numbers start at 1; anything below is ignored, as in the previous version of this operator.
        return source.Where(input => input.Item1 > 0).Select(input => Draw(input.Item1, input.Item2));
    }

    private OptoTrial Draw(int trialNumber, UclOpenAuditoryVrCorridorTaskParameters parameters)
    {
        if (parameters == null)
        {
            throw new ArgumentNullException("parameters", "InitialiseOptoTrial needs the task parameters.");
        }
        if (trialNumber == 1 || random == null)
        {
            Reset();
        }

        var trial = new OptoTrial();
        trial.TrialNumber = trialNumber;
        var optogenetics = parameters.Optogenetics;
        if (optogenetics == null || !optogenetics.Enabled)
        {
            // Not an optogenetics session: nothing is sent to Zapit.
            trial.OptogeneticEnabled = false;
            trial.OptogeneticCondition = 0;
            trial.OptogeneticMaxDuration = 0;
            return trial;
        }

        if (conditions == null)
        {
            Validate(optogenetics);
            conditions = ZapitStimConfig.ReadConditionNumbers(optogenetics.ZapitConfigPath);
            Console.WriteLine("InitialiseOptoTrial: Zapit stimulus config '" + optogenetics.ZapitConfigPath + "' has " +
                conditions.Count + " conditions");
        }

        // Warmup trials are never laser-on. After warmup the laser is on with probability stimProbability.
        var laserOn = trialNumber > optogenetics.WarmupTrials && random.NextDouble() < optogenetics.StimProbability;
        trial.OptogeneticEnabled = laserOn;
        trial.OptogeneticCondition = NextCondition(laserOn ? stimQueue : shamQueue, optogenetics.PseudorandomSelection);
        trial.OptogeneticMaxDuration = optogenetics.StimDuration;
        return trial;
    }

    private void Reset()
    {
        random = Seed != -1 ? new Random(Seed) : new Random(Guid.NewGuid().GetHashCode());
        conditions = null;
        stimQueue.Clear();
        shamQueue.Clear();
    }

    private int NextCondition(ConditionQueue queue, bool pseudorandom)
    {
        if (pseudorandom)
        {
            return queue.Next(conditions, random);
        }
        return conditions[random.Next(conditions.Count)];
    }

    const double MaxTrialTimeSec = 12.0;        // main.bonsai Params/InitVars MaxTrialTimeSec; task.py MAX_TRIAL_TIME_SEC
    const double StimDurationMarginSec = 0.25;  // task.py STIM_DURATION_MARGIN_SEC

    // The schema already enforces these; checked again because a bad value would silently change every trial.
    private static void Validate(OptogeneticsConfig optogenetics)
    {
        if (!(optogenetics.StimProbability >= 0 && optogenetics.StimProbability <= 1))
        {
            throw new InvalidOperationException(string.Format(
                "optogenetics.stimProbability must be between 0 and 1; got {0}.", optogenetics.StimProbability));
        }
        // The stimulus starts on a beep and the first tone pip comes LeadTime later, so LeadTime must be 1 to 20 whole 50 ms beeps.
        // A smaller value would let the trial-end detectors arm before the stimulus starts.
        var beeps = optogenetics.LeadTime / 0.05;
        if (!(Math.Abs(beeps - Math.Round(beeps)) < 1e-6 && Math.Round(beeps) >= 1 && Math.Round(beeps) <= 20))
        {
            throw new InvalidOperationException(string.Format(
                "optogenetics.leadTime must be a multiple of 0.05 s from 0.05 to 1; got {0}.", optogenetics.LeadTime));
        }
        // The laser is meant to stay on until the outcome, so the cap must be longer than the longest trial: the workflow's
        // MaxTrialTimeSec (12 s, counted from the first tone pip, LeadTime after onset, on trial 1 and one beep earlier later) plus a margin.
        var shortestCap = MaxTrialTimeSec + optogenetics.LeadTime + StimDurationMarginSec;
        if (!(optogenetics.StimDuration >= shortestCap - 1e-9) || double.IsInfinity(optogenetics.StimDuration))
        {
            throw new InvalidOperationException(string.Format(
                "optogenetics.stimDuration must be at least {0} s (the 12 s timeout from the first tone pip, plus leadTime, plus {1} s), "
                + "or a timeout trial's laser would stop before its outcome; got {2}.", shortestCap, StimDurationMarginSec, optogenetics.StimDuration));
        }
    }

    /// <summary>
    /// The conditions in a shuffled order (Fisher-Yates), handed out one at a time and reshuffled when used up,
    /// so every block of N draws presents each condition once.
    /// </summary>
    private sealed class ConditionQueue
    {
        private readonly List<int> order = new List<int>();
        private int position;

        public void Clear()
        {
            order.Clear();
            position = 0;
        }

        public int Next(List<int> conditions, Random random)
        {
            if (position >= order.Count)
            {
                order.Clear();
                order.AddRange(conditions);
                for (int i = order.Count - 1; i > 0; i--)
                {
                    int j = random.Next(i + 1);
                    int swap = order[i];
                    order[i] = order[j];
                    order[j] = swap;
                }
                position = 0;
            }
            return order[position++];
        }
    }
}

// Optogenetics for one trial. Field names match av-dome's Trial class where they overlap, so the logs of the two tasks line up.
public class OptoTrial
{
    public int TrialNumber;  // Trial this draw is for, as in the TrialNumber subject
    public bool OptogeneticEnabled;  // Laser on. False on sham (laser-off) trials and in sessions without optogenetics
    public int OptogeneticCondition;  // Zapit condition (its stimLocations number) presented on this trial, laser on or off. 0 when optogenetics is off
    public double OptogeneticMaxDuration;  // Longest the stimulus stays on, in seconds; normally stopped at the outcome. 0 when optogenetics is off

    public override string ToString()
    {
        return string.Format(
            "OptoTrial(trial={0}, laserOn={1}, condition={2}, maxDuration={3})",
            TrialNumber, OptogeneticEnabled, OptogeneticCondition, OptogeneticMaxDuration);
    }
}
