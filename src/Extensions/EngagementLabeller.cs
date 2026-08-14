using System;
using System.Collections.Generic;

namespace UclOpen.Engagement
{
    /// <summary>
    /// Labels each trial of a session as engaged or disengaged with the task.
    ///
    /// A mouse partway through a session often keeps running normally but stops licking. Those
    /// stretches are not failed trials - the animal is not attempting the task - and scoring them
    /// as failures makes performance look far worse than it is. Running speed does not separate
    /// the two states, so whether a trial contained any lick is the only usable signal.
    ///
    /// The signal is read as a sequence rather than trial by trial. Dropping individual no-lick
    /// trials would be circular, because it removes only failures and so raises the hit rate by
    /// construction. Judging contiguous epochs is a different claim: a dry trial inside a good run
    /// is kept, and a lone lick inside a long dead stretch does not rescue it.
    ///
    /// This is a direct port of the offline analysis in Python (pandas rolling mean plus an epoch
    /// merge) and must stay numerically identical to it, so that live labels and the later offline
    /// analysis of the same session agree. It is deliberately free of any Bonsai dependency so it
    /// can be compiled and tested on its own against the Python reference.
    /// </summary>
    public static class EngagementLabeller
    {
        /// <summary>
        /// Fraction of trials containing a lick, in a window centred on each trial.
        ///
        /// Matches pandas rolling(window, min_periods=1, center=True).mean(): the window at trial i
        /// spans [i - window/2, i + (window-1)/2], truncated rather than skipped at the ends of the
        /// session. For an odd window that is symmetric; for an even one pandas reaches one further
        /// back than forward, which is why odd windows are preferred.
        /// </summary>
        public static double[] LickFraction(IList<bool> licked, int window)
        {
            if (licked == null) throw new ArgumentNullException("licked");
            if (window < 1) throw new ArgumentOutOfRangeException("window", "window must be at least 1");

            var fraction = new double[licked.Count];
            int back = window / 2;
            int forward = (window - 1) / 2;

            for (int i = 0; i < licked.Count; i++)
            {
                int lo = Math.Max(0, i - back);
                int hi = Math.Min(licked.Count - 1, i + forward);
                int licks = 0;
                for (int j = lo; j <= hi; j++)
                {
                    if (licked[j]) licks++;
                }
                fraction[i] = (double)licks / (hi - lo + 1);
            }
            return fraction;
        }

        /// <summary>
        /// Flips the shortest epoch into its neighbours until none is shorter than minLength.
        /// Terminates because every flip strictly reduces the number of epochs. Where several
        /// epochs are equally short the earliest is flipped first, matching numpy's argmin.
        /// </summary>
        public static bool[] MergeShortEpochs(bool[] engaged, int minLength)
        {
            if (engaged == null) throw new ArgumentNullException("engaged");
            var labels = (bool[])engaged.Clone();

            while (true)
            {
                // Start index of each run of equal labels
                var starts = new List<int>();
                if (labels.Length > 0) starts.Add(0);
                for (int i = 1; i < labels.Length; i++)
                {
                    if (labels[i] != labels[i - 1]) starts.Add(i);
                }
                if (starts.Count <= 1) return labels;   // a single epoch cannot be too short

                int shortest = 0;
                int shortestLength = int.MaxValue;
                for (int k = 0; k < starts.Count; k++)
                {
                    int end = (k + 1 < starts.Count) ? starts[k + 1] : labels.Length;
                    int length = end - starts[k];
                    if (length < shortestLength)   // strict, so ties keep the earliest
                    {
                        shortestLength = length;
                        shortest = k;
                    }
                }
                if (shortestLength >= minLength) return labels;

                int from = starts[shortest];
                int to = (shortest + 1 < starts.Count) ? starts[shortest + 1] : labels.Length;
                bool flipped = !labels[from];
                for (int i = from; i < to; i++)
                {
                    labels[i] = flipped;
                }
            }
        }

        /// <summary>Engagement label for every trial given so far.</summary>
        public static bool[] Label(IList<bool> licked, int window, double threshold, int minEpoch)
        {
            var fraction = LickFraction(licked, window);
            var engaged = new bool[fraction.Length];
            for (int i = 0; i < fraction.Length; i++)
            {
                engaged[i] = fraction[i] > threshold;
            }
            return MergeShortEpochs(engaged, minEpoch);
        }

        /// <summary>
        /// How many trials behind the present a label can be trusted.
        ///
        /// The centred window looks (window-1)/2 trials ahead, so the label for trial i is settled
        /// once trial i + Delay has finished, and cannot change afterwards. Derived from the window
        /// rather than hardcoded, so changing the window cannot silently desynchronise the live
        /// labels from the offline ones. Note this is the *forward* reach, which for an even window
        /// is one less than window/2.
        /// </summary>
        public static int Delay(int window)
        {
            return (window - 1) / 2;
        }
    }
}
