using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Globalization;
using System.Reactive.Disposables;
using System.Reactive.Linq;
using System.Threading;
using Bonsai;

namespace AvcSim
{
    // A simulated mouse on the wheel. It runs at Speed (cm/s, jittered per trial) and licks the left spout depending on
    // where it is in the virtual corridor, as reported by the task itself (MouseVirtualPosition and the reward zone
    // RewardFloorVirtualPos..RewardCeilVirtualPos, all in cm). Running drives the simulated Behavior board's encoder;
    // licks drive the simulated LicketySplit. One behaviour is drawn per trial when TrialNumber changes:
    //   Hit     (default)            lick LicksPerBout times, starting ReactionTime after passing ZoneMargin of the zone
    //   Miss    (MissRate)           run through the zone without licking
    //   NoLick  (NoLickRate)         no licks at all this trial
    //   plus, on Hit/Miss trials, WrongLickRate: a bout of WrongLicks licks before the zone (wrong licks; enough of them
    //   reach the stage's punished-lick limit).
    // While licking inside the zone the mouse slows to ZoneSpeedFactor x speed. Output: one line per trial plan.
    [Combinator]
    [WorkflowElementCategory(ElementCategory.Transform)]
    [Description("SIMULATION: mouse that runs on the wheel and licks according to the virtual position.")]
    public class SimMouse
    {
        public SimMouse()
        {
            Speed = 25;
            SpeedJitter = 0.15;
            ZoneSpeedFactor = 0.5;
            LicksPerBout = 4;
            LickRate = 8;
            LickDuration = 0.04;
            ReactionTime = 0.15;
            ZoneMargin = 0.2;
            WrongLickRate = 0.1;
            WrongLicks = 8;
            MissRate = 0.1;
            NoLickRate = 0.05;
            Seed = -1;
        }

        [Description("Running speed in cm/s.")]
        public double Speed { get; set; }

        [Description("Per-trial speed variation (standard deviation as a fraction of Speed).")]
        public double SpeedJitter { get; set; }

        [Description("Speed factor while licking inside the reward zone.")]
        public double ZoneSpeedFactor { get; set; }

        [Description("Licks in a reward-zone bout.")]
        public int LicksPerBout { get; set; }

        [Description("Lick rate within a bout, in Hz.")]
        public double LickRate { get; set; }

        [Description("Duration of each lick contact, in seconds.")]
        public double LickDuration { get; set; }

        [Description("Delay from reaching the lick point in the zone to the first lick, in seconds.")]
        public double ReactionTime { get; set; }

        [Description("Fraction of the reward zone width passed before the mouse decides to lick.")]
        public double ZoneMargin { get; set; }

        [Description("Probability per trial of a bout of wrong licks before the reward zone.")]
        public double WrongLickRate { get; set; }

        [Description("Licks in a wrong-lick bout.")]
        public int WrongLicks { get; set; }

        [Description("Probability per trial of not licking in the reward zone.")]
        public double MissRate { get; set; }

        [Description("Probability per trial of not licking at all.")]
        public double NoLickRate { get; set; }

        [Description("Random seed (-1 = random).")]
        public int Seed { get; set; }

        [Description("Optional CSV file logging each trial's plan and lick bouts.")]
        public string LogPath { get; set; }

        sealed class Inputs
        {
            public double Position;
            public double Floor = double.NaN;
            public double Ceil = double.NaN;
            public int Trial;
            public bool HasTrial;
        }

        sealed class Plan
        {
            public int Trial;
            public string Kind;
            public double Speed;
            public bool Wrong;
            public double WrongFraction;
            public bool WrongDone;
            public bool ZoneDone;
        }

        struct Transition
        {
            public double Time;
            public bool Contact;
        }

        public IObservable<string> Process(IObservable<double> position, IObservable<double> rewardFloor,
                                           IObservable<double> rewardCeil, IObservable<int> trialNumber)
        {
            return Observable.Create<string>(observer =>
            {
                var inputs = new Inputs();
                var subscriptions = new CompositeDisposable(
                    position.Subscribe(value => { lock (inputs) inputs.Position = value; }),
                    rewardFloor.Subscribe(value => { lock (inputs) inputs.Floor = value; }),
                    rewardCeil.Subscribe(value => { lock (inputs) inputs.Ceil = value; }),
                    trialNumber.Subscribe(value => { lock (inputs) { inputs.Trial = value; inputs.HasTrial = true; } }));
                var cancellation = new CancellationTokenSource();
                var log = SimCsvLog.Create(LogPath, "Trial,HarpTime,Event,Detail,PositionCm,RewardFloorCm,RewardCeilCm");
                var thread = new Thread(() =>
                {
                    try { Run(observer, inputs, log, cancellation.Token); }
                    catch (Exception ex) { observer.OnError(ex); }
                });
                thread.IsBackground = true;
                thread.Name = "SimMouse";
                thread.Start();
                return Disposable.Create(() =>
                {
                    cancellation.Cancel();
                    thread.Join(1000);
                    subscriptions.Dispose();
                    SimWorld.WheelSpeed = 0;
                    if (log != null) log.Dispose();
                });
            });
        }

        void Run(IObserver<string> observer, Inputs inputs, SimCsvLog log, CancellationToken token)
        {
            var random = Seed >= 0 ? new Random(Seed) : new Random();
            var pending = new Queue<Transition>();
            Plan plan = null;
            var contact = false;
            SimWorld.WheelSpeed = Speed;
            while (!token.IsCancellationRequested)
            {
                double position, floor, ceil;
                int trial;
                bool hasTrial;
                lock (inputs)
                {
                    position = inputs.Position;
                    floor = inputs.Floor;
                    ceil = inputs.Ceil;
                    trial = inputs.Trial;
                    hasTrial = inputs.HasTrial;
                }
                var now = SimWorld.HarpNow();

                if (hasTrial && (plan == null || plan.Trial != trial))
                {
                    plan = DrawPlan(random, trial);
                    var text = string.Format(CultureInfo.InvariantCulture, "trial {0}: {1}{2}, {3:F1} cm/s",
                        plan.Trial, plan.Kind, plan.Wrong ? " + wrong licks" : "", plan.Speed);
                    if (log != null) log.Write(trial, now, "Plan", plan.Kind + (plan.Wrong ? "+WrongLicks" : ""), position, floor, ceil);
                    if (trial > 0) SimWorld.Log("mouse", text);
                    var gate = SimWorld.Gate;
                    if (gate != null) lock (gate) observer.OnNext(text);
                    else observer.OnNext(text);
                }

                var zoneKnown = !double.IsNaN(floor) && !double.IsNaN(ceil) && ceil > floor;
                if (plan != null && pending.Count == 0 && zoneKnown && position > 0)
                {
                    if (plan.Wrong && !plan.WrongDone && position >= plan.WrongFraction * floor && position < floor)
                    {
                        plan.WrongDone = true;
                        Schedule(pending, now, WrongLicks);
                        if (log != null) log.Write(trial, now, "WrongLickBout", WrongLicks + " licks", position, floor, ceil);
                    }
                    else if (plan.Kind == "Hit" && !plan.ZoneDone && position >= floor + ZoneMargin * (ceil - floor) && position <= ceil)
                    {
                        plan.ZoneDone = true;
                        Schedule(pending, now + ReactionTime, LicksPerBout);
                        if (log != null) log.Write(trial, now, "ZoneLickBout", LicksPerBout + " licks after " + ReactionTime + " s", position, floor, ceil);
                    }
                }

                while (pending.Count > 0 && pending.Peek().Time <= now)
                {
                    contact = pending.Dequeue().Contact;
                    var lickTime = SimWorld.HarpNow();
                    SimWorld.SetLickContact(contact);
                    if (contact && log != null) log.Write(trial, lickTime, "Lick", "", position, floor, ceil);
                }

                var speed = plan != null ? plan.Speed : Speed;
                var licking = pending.Count > 0 || contact;
                var inZone = zoneKnown && position >= floor && position <= ceil;
                SimWorld.WheelSpeed = licking && inZone ? speed * ZoneSpeedFactor : speed;
                Thread.Sleep(2);
            }
            if (contact) SimWorld.SetLickContact(false);
        }

        Plan DrawPlan(Random random, int trial)
        {
            var plan = new Plan { Trial = trial };
            var r = random.NextDouble();
            plan.Kind = r < NoLickRate ? "NoLick" : r < NoLickRate + MissRate ? "Miss" : "Hit";
            plan.Wrong = plan.Kind != "NoLick" && random.NextDouble() < WrongLickRate;
            plan.WrongFraction = 0.3 + 0.5 * random.NextDouble();
            // Box-Muller normal draw for the trial's speed
            var gaussian = Math.Sqrt(-2.0 * Math.Log(1.0 - random.NextDouble())) * Math.Cos(2.0 * Math.PI * random.NextDouble());
            plan.Speed = Math.Max(0.2 * Speed, Speed * (1.0 + SpeedJitter * gaussian));
            return plan;
        }

        void Schedule(Queue<Transition> pending, double start, int licks)
        {
            var interval = 1.0 / Math.Max(0.1, LickRate);
            var duration = Math.Min(LickDuration, 0.8 * interval);
            for (int i = 0; i < licks; i++)
            {
                var onset = start + i * interval;
                pending.Enqueue(new Transition { Time = onset, Contact = true });
                pending.Enqueue(new Transition { Time = onset + duration, Contact = false });
            }
        }
    }
}
