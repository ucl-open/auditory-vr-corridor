// Simulation-only Bonsai operators for running main.bonsai headless on a Mac (built by sim/setup.sh into
// SimExtensions.dll, XML namespace clr-namespace:AvcSim;assembly=SimExtensions). Nothing here is used on the rig.
//
// SimWorld is the state the simulated devices share inside one Bonsai process, the way the real animal, wheel and lick
// spout share the rig: the simulated mouse sets the wheel speed (read by the simulated Behavior board's encoder) and
// makes lick contacts (read by the simulated LicketySplit), and every device timestamps its Harp messages from one
// Harp clock.
using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reactive.Subjects;
using System.Reflection;
using System.Threading;

[assembly: AssemblyTitle("AvcSim: simulated Harp devices, mouse and rig configuration for headless Bonsai runs")]

namespace AvcSim
{
    public static class SimWorld
    {
        static readonly Stopwatch Clock = Stopwatch.StartNew();
        static long speedBits = BitConverter.DoubleToInt64Bits(0.0);
        static readonly Subject<bool> lickContacts = new Subject<bool>();
        static double harpTimeOffset = 1000.0;

        // Harp time (seconds) shared by all simulated Harp devices, as if synchronised by the clock synchroniser.
        public static double HarpNow()
        {
            return Volatile.Read(ref harpTimeOffset) + Clock.Elapsed.TotalSeconds;
        }

        // Harp time when the simulation process started (set before any device starts).
        public static double HarpTimeOffset
        {
            get { return Volatile.Read(ref harpTimeOffset); }
            set { Volatile.Write(ref harpTimeOffset, value); }
        }

        // Wheel speed in cm/s at the wheel surface, set by the simulated mouse.
        public static double WheelSpeed
        {
            get { return BitConverter.Int64BitsToDouble(Interlocked.Read(ref speedBits)); }
            set { Interlocked.Exchange(ref speedBits, BitConverter.DoubleToInt64Bits(value)); }
        }

        // Lick contacts on the left spout (true = tongue touching, false = released), made by the simulated mouse.
        public static IObservable<bool> LickContacts
        {
            get { return lickContacts; }
        }

        // Global lock of BonsaiRun --serialize (null otherwise): each simulated device event is emitted while holding it,
        // as are Rx's timer callbacks, so the workflow's threads cannot interleave mid-event.
        public static readonly object Gate = AppDomain.CurrentDomain.GetData("AvcSim.Gate");

        public static void SetLickContact(bool contact)
        {
            if (Gate != null) lock (Gate) lickContacts.OnNext(contact);
            else lock (lickContacts) lickContacts.OnNext(contact);
        }

        public static void Log(string source, string message)
        {
            Console.Error.WriteLine(string.Format(CultureInfo.InvariantCulture, "[sim {0:F3}] {1}: {2}", HarpNow(), source, message));
        }
    }

    // Small thread-safe CSV event log (one file per simulated device), written next to the session logs.
    sealed class SimCsvLog : IDisposable
    {
        readonly StreamWriter writer;

        SimCsvLog(string path, string header)
        {
            var directory = Path.GetDirectoryName(Path.GetFullPath(path));
            if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);
            writer = new StreamWriter(path, false) { AutoFlush = true };
            writer.WriteLine(header);
        }

        public static SimCsvLog Create(string path, string header)
        {
            return string.IsNullOrEmpty(path) ? null : new SimCsvLog(path, header);
        }

        public void Write(params object[] values)
        {
            var fields = new string[values.Length];
            for (int i = 0; i < values.Length; i++)
            {
                var value = values[i];
                var text = value is double ? ((double)value).ToString("F6", CultureInfo.InvariantCulture)
                         : Convert.ToString(value, CultureInfo.InvariantCulture) ?? string.Empty;
                if (text.IndexOfAny(new[] { ',', '"', '\n' }) >= 0) text = "\"" + text.Replace("\"", "\"\"") + "\"";
                fields[i] = text;
            }
            lock (writer) writer.WriteLine(string.Join(",", fields));
        }

        public void Dispose()
        {
            lock (writer) writer.Dispose();
        }
    }
}
