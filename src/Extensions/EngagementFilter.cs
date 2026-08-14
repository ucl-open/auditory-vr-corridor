using Bonsai;
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Reactive.Linq;
using UclOpen.Engagement;

/// <summary>
/// The engagement readout for the trial that has just settled.
/// </summary>
public class EngagementState
{
    /// <summary>Trial this label describes, counting from 0. Lags the current trial by Delay.</summary>
    public int Trial { get; set; }

    /// <summary>True if the animal was attempting the task during that trial.</summary>
    public bool Engaged { get; set; }

    /// <summary>Trials in the current epoch, up to and including Trial.</summary>
    public int EpochTrials { get; set; }

    /// <summary>Seconds from the start of the current epoch to the end of Trial.</summary>
    public double EpochSeconds { get; set; }

    /// <summary>Trials with a settled label so far, i.e. everything except the last Delay trials.</summary>
    public int SettledTrials { get; set; }

    /// <summary>Settled trials labelled engaged so far this session.</summary>
    public int EngagedTrials { get; set; }

    /// <summary>
    /// Fraction of the settled session spent engaged. Multiplying this by EngagedHitRate gives back
    /// the raw hit rate, so the two together decompose performance without discarding anything.
    /// </summary>
    public double EngagedFraction { get; set; }

    /// <summary>Of those, how many were rewarded.</summary>
    public int EngagedRewarded { get; set; }

    /// <summary>Hit rate over engaged trials only, or NaN before any engaged trial.</summary>
    public double EngagedHitRate { get; set; }

    /// <summary>Trials run but not yet labelled, i.e. the delay.</summary>
    public int Pending { get; set; }

    public override string ToString()
    {
        return string.Format("trial {0}: {1}, epoch {2} trials / {3:0}s, session engaged {4:P0} ({5}/{6}), engaged hit rate {7:P0} ({8}/{9})",
                             Trial, Engaged ? "engaged" : "disengaged", EpochTrials, EpochSeconds,
                             EngagedFraction, EngagedTrials, SettledTrials,
                             EngagedHitRate, EngagedRewarded, EngagedTrials);
    }
}

/// <summary>
/// Labels the animal as engaged or disengaged with the task, live during a session.
///
/// Takes one item per completed trial - whether it contained a lick, whether it was rewarded, and
/// the time it ended - and emits the label for the trial DELAY trials back, where DELAY is what the
/// centred averaging window needs in order to be final. That label is exact: it is produced by the
/// same algorithm the offline analysis uses, just reported late, so the live and offline labels of
/// a session agree outside its final DELAY trials.
///
/// Nothing is emitted until the first label is computable, which is after RollWindow/2 trials.
/// </summary>
[Combinator]
[Description("Labels the animal as engaged or disengaged with the task, from whether each trial contained a lick.")]
[WorkflowElementCategory(ElementCategory.Transform)]
public class EngagementFilter
{
    int rollWindow = 25;
    double rollThreshold = 0.5;
    int minEpoch = 10;

    [Description("Trials averaged around each trial when deciding engagement. Use an odd value: pandas centres an even window asymmetrically, so the live and offline labels would differ.")]
    public int RollWindow
    {
        get { return rollWindow; }
        set { rollWindow = Math.Max(1, value); }
    }

    [Description("Lick fraction below which the animal counts as disengaged.")]
    public double RollThreshold
    {
        get { return rollThreshold; }
        set { rollThreshold = value; }
    }

    [Description("Shortest epoch allowed, in trials. Shorter epochs are absorbed into their neighbours. Keep at or below 20, above which real working periods start being swallowed.")]
    public int MinEpoch
    {
        get { return minEpoch; }
        set { minEpoch = Math.Max(1, value); }
    }

    /// <summary>
    /// Item1: did the trial contain a lick (LickCount &gt; 0).
    /// Item2: was the trial rewarded.
    /// Item3: time the trial ended, in seconds since the session started.
    /// </summary>
    public IObservable<EngagementState> Process(IObservable<Tuple<bool, bool, double>> source)
    {
        return Observable.Defer(() =>
        {
            // The algorithm is defined over the session so far, not over a sliding window of
            // events, so the whole session is kept. A few hundred trials, so this is free.
            var licked = new List<bool>();
            var rewarded = new List<bool>();
            var endedAt = new List<double>();

            return source.Select(trial =>
            {
                licked.Add(trial.Item1);
                rewarded.Add(trial.Item2);
                endedAt.Add(trial.Item3);

                int delay = EngagementLabeller.Delay(rollWindow);
                int settled = licked.Count - delay;          // trials whose label can no longer change
                if (settled < 1) return null;

                var labels = EngagementLabeller.Label(licked, rollWindow, rollThreshold, minEpoch);
                int trialIndex = settled - 1;                // newest settled trial

                // Current epoch: walk back while the label is unchanged
                int epochStart = trialIndex;
                while (epochStart > 0 && labels[epochStart - 1] == labels[trialIndex]) epochStart--;

                // Hit rate over settled engaged trials only
                int engagedTrials = 0, engagedRewarded = 0;
                for (int i = 0; i < settled; i++)
                {
                    if (!labels[i]) continue;
                    engagedTrials++;
                    if (rewarded[i]) engagedRewarded++;
                }

                return new EngagementState
                {
                    Trial = trialIndex,
                    Engaged = labels[trialIndex],
                    EpochTrials = trialIndex - epochStart + 1,
                    // Measured from the end of the trial before the epoch began, so the epoch's own
                    // first trial is included. Uses the true epoch start, not the moment the label
                    // appeared, which is DELAY trials later.
                    EpochSeconds = endedAt[trialIndex] - endedAt[Math.Max(0, epochStart - 1)],
                    SettledTrials = settled,
                    EngagedTrials = engagedTrials,
                    EngagedFraction = (double)engagedTrials / settled,
                    EngagedRewarded = engagedRewarded,
                    EngagedHitRate = engagedTrials > 0 ? (double)engagedRewarded / engagedTrials : double.NaN,
                    Pending = delay,
                };
            }).Where(state => state != null);
        });
    }
}
