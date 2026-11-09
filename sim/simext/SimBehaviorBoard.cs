using System;
using System.Collections.Concurrent;
using System.ComponentModel;
using System.Globalization;
using System.Net.Sockets;
using System.Reactive.Disposables;
using System.Reactive.Linq;
using System.Threading;
using Bonsai;
using Bonsai.Harp;
using Harp.Behavior;

namespace AvcSim
{
    // Stands in for the Harp Behavior board (Harp.Behavior Device) inside the sim copy of UclOpen.Devices
    // BehaviorBoard.bonsai: same input (BehaviorCommands) and output (BehaviorEvents) as the real device.
    //
    // Events, timestamped on the shared simulated Harp clock:
    //   * AnalogData (address 44) at SampleRate (1 kHz like the real board) with Encoder = the wheel's 16-bit quadrature
    //     count (wraps like the real register), driven by the simulated mouse's speed (SimWorld.WheelSpeed) through
    //     CountsPerRev and WheelDiameterMm, so the workflow's own RunningWheel conversion turns it back into cm.
    //   * TimestampSeconds (address 8) once per second when Heartbeat is Enabled.
    //   * Every Write command is echoed back as a timestamped Write message, as real Harp devices do.
    // Command effects:
    //   * EncoderReset (EncoderPort2) sets the encoder count to 0.
    //   * OutputSet DO1/DO2 = reward valve opening (logged, width from PulseDO1/PulseDO2).
    //   * OutputSet DO3 = Zapit trigger TTL: one byte is sent to TriggerHost:TriggerPort (the mock Zapit server's
    //     trigger port, normally its command port + 1) when TriggerPort > 0.
    [Combinator(MethodName = "Generate")]
    [WorkflowElementCategory(ElementCategory.Source)]
    [Description("SIMULATION: Harp Behavior board with a wheel encoder driven by the simulated mouse.")]
    public class SimBehaviorBoard
    {
        public SimBehaviorBoard()
        {
            OperationMode = OperationMode.Active;
            OperationLed = LedState.On;
            VisualIndicators = LedState.On;
            Heartbeat = EnableFlag.Enabled;
            SampleRate = 1000;
            CountsPerRev = 4096;
            WheelDiameterMm = 75;
            TriggerHost = "127.0.0.1";
            DeadlockSeconds = 5;
        }

        // Same settable properties as Bonsai.Harp.Device, so the device's externalized mappings still apply.
        public OperationMode OperationMode { get; set; }
        public LedState OperationLed { get; set; }
        public bool DumpRegisters { get; set; }
        public LedState VisualIndicators { get; set; }
        public EnableFlag Heartbeat { get; set; }
        public bool IgnoreErrors { get; set; }
        [Description("Ignored in the simulation (no serial port).")]
        public string PortName { get; set; }

        [Description("AnalogData events per second (the real board sends 1000).")]
        public int SampleRate { get; set; }

        [Description("Encoder counts per wheel revolution.")]
        public double CountsPerRev { get; set; }

        [Description("Wheel diameter in mm.")]
        public double WheelDiameterMm { get; set; }

        [Description("Host receiving one byte per DO3 TTL (the mock Zapit trigger port).")]
        public string TriggerHost { get; set; }

        [Description("TCP port receiving one byte per DO3 TTL; 0 = do not send.")]
        public int TriggerPort { get; set; }

        [Description("Optional CSV file logging valve openings, TTLs and encoder resets.")]
        public string LogPath { get; set; }

        [Description("Seconds a single sample may stay inside the workflow before it is reported as a deadlock.")]
        public double DeadlockSeconds { get; set; }

        public IObservable<HarpMessage> Generate()
        {
            return Generate(Observable.Never<HarpMessage>());
        }

        public IObservable<HarpMessage> Generate(IObservable<HarpMessage> source)
        {
            return Observable.Create<HarpMessage>(observer =>
            {
                var commands = new ConcurrentQueue<HarpMessage>();
                var cancellation = new CancellationTokenSource();
                var log = SimCsvLog.Create(LogPath, "HarpTime,Event,Detail");
                var trigger = new TriggerSender(TriggerHost, TriggerPort);
                var commandSubscription = source.Subscribe(
                    command => { if (command != null) commands.Enqueue(command); },
                    error => { },
                    () => { });
                var thread = new Thread(() =>
                {
                    try { Run(observer, commands, log, trigger, cancellation.Token); }
                    catch (Exception ex) { observer.OnError(ex); }
                });
                var watchdog = new Timer(Watchdog, null, 1000, 1000);
                thread.IsBackground = true;
                thread.Name = "SimBehaviorBoard";
                thread.Start();
                SimWorld.Log("board", "simulated Behavior board started (" + SampleRate + " Hz AnalogData, encoder "
                    + CountsPerRev + " counts/rev, wheel " + WheelDiameterMm + " mm"
                    + (TriggerPort > 0 ? ", DO3 TTL -> " + TriggerHost + ":" + TriggerPort : "") + ")");
                return Disposable.Create(() =>
                {
                    watchdog.Dispose();
                    cancellation.Cancel();
                    commandSubscription.Dispose();
                    thread.Join(1000);
                    trigger.Dispose();
                    if (log != null) log.Dispose();
                    var n = Math.Max(1, processedSamples);
                    var toUs = 1e6 / System.Diagnostics.Stopwatch.Frequency;
                    SimWorld.Log("board", string.Format(CultureInfo.InvariantCulture,
                        "{0} AnalogData samples; workflow processing per sample on the Harp thread: mean {1:F0} us, max {2:F1} ms, {3} samples over 1 ms; "
                        + "after start-up {4} samples were emitted >10 ms late and {5} >50 ms late (max {6:F0} ms; start-up {7:F0} ms)",
                        processedSamples, processingTicks * toUs / n, maxProcessingTicks * toUs / 1000.0, slowSamples,
                        lateSamples, veryLateSamples, maxLag * 1000, startupLag * 1000));
                });
            });
        }

        // Time the workflow takes to process each AnalogData sample on this thread (the real board's serial thread
        // does the same work), and a watchdog for samples that never return (a deadlock inside the workflow).
        long lastProgress;       // Stopwatch timestamp of the last sample the workflow finished processing
        long processedSamples;
        long processingTicks;
        long maxProcessingTicks;
        long slowSamples;        // samples that took more than 1 ms to process
        double maxLag;           // how far (s) the board fell behind the Harp clock before emitting a sample
        long lateSamples;        // samples emitted more than 10 ms after their timestamp
        long veryLateSamples;    // ... more than 50 ms
        double startupLag;       // largest lag in the first 5 s (workflow start-up, before the session begins)

        // A sample that has not come back from the workflow (or a board thread that cannot get the --serialize lock)
        // for DeadlockSeconds: samples are due every millisecond, so the workflow's threads are stuck.
        void Watchdog(object state)
        {
            var since = Interlocked.Read(ref lastProgress);
            if (since == 0) return;
            var seconds = (double)(System.Diagnostics.Stopwatch.GetTimestamp() - since) / System.Diagnostics.Stopwatch.Frequency;
            if (seconds < DeadlockSeconds || AppDomain.CurrentDomain.GetData("AvcSim.Deadlock") != null) return;
            AppDomain.CurrentDomain.SetData("AvcSim.Deadlock", "the Behavior board thread has been blocked for " + seconds.ToString("F0", CultureInfo.InvariantCulture) + " s");
            SimWorld.Log("board", "DEADLOCK: the simulated Behavior board (Harp) thread has been blocked for "
                + seconds.ToString("F0", CultureInfo.InvariantCulture) + " s (no sample processed); asking the runner to stop and dump all threads");
            SimControl.RequestStop("deadlock detected in the workflow");
        }

        void Emit(IObserver<HarpMessage> observer, HarpMessage message)
        {
            var start = System.Diagnostics.Stopwatch.GetTimestamp();
            observer.OnNext(message);
            var end = System.Diagnostics.Stopwatch.GetTimestamp();
            Interlocked.Exchange(ref lastProgress, end);
            var elapsed = end - start;
            processedSamples++;
            processingTicks += elapsed;
            if (elapsed > maxProcessingTicks) maxProcessingTicks = elapsed;
            if (elapsed * 1000 > System.Diagnostics.Stopwatch.Frequency) slowSamples++;
        }

        void Run(IObserver<HarpMessage> observer, ConcurrentQueue<HarpMessage> commands, SimCsvLog log,
                 TriggerSender trigger, CancellationToken token)
        {
            Interlocked.Exchange(ref lastProgress, System.Diagnostics.Stopwatch.GetTimestamp());
            var sampleRate = SampleRate > 0 ? SampleRate : 1000;
            var dt = 1.0 / sampleRate;
            var ticksPerCm = CountsPerRev / (Math.PI * WheelDiameterMm / 10.0);
            var pulseWidths = new int[4];
            var ticks = 0.0;
            var t0 = Math.Ceiling(SimWorld.HarpNow() * sampleRate) / sampleRate;
            long sample = 0;
            long lastHeartbeat = long.MinValue;
            while (!token.IsCancellationRequested)
            {
                var now = SimWorld.HarpNow();
                while (!token.IsCancellationRequested)
                {
                    var t = t0 + sample * dt;
                    if (t > now) break;
                    var gate = SimWorld.Gate;
                    if (gate != null) Monitor.Enter(gate);
                    try
                    {
                        HarpMessage command;
                        while (commands.TryDequeue(out command))
                        {
                            HandleCommand(observer, command, t, ref ticks, pulseWidths, log, trigger);
                        }

                        ticks += SimWorld.WheelSpeed * dt * ticksPerCm;
                        var encoder = unchecked((short)(long)Math.Round(ticks));
                        var lag = SimWorld.HarpNow() - t;
                        if (t - t0 < 5) { if (lag > startupLag) startupLag = lag; }
                        else
                        {
                            if (lag > maxLag) maxLag = lag;
                            if (lag > 0.01) lateSamples++;
                            if (lag > 0.05) veryLateSamples++;
                        }
                        Emit(observer, AnalogData.FromPayload(t, MessageType.Event, new AnalogDataPayload(0, encoder, 0)));

                        var second = (long)Math.Floor(t);
                        if (Heartbeat == EnableFlag.Enabled && second != lastHeartbeat)
                        {
                            lastHeartbeat = second;
                            observer.OnNext(TimestampSeconds.FromPayload(t, MessageType.Event, (uint)second));
                        }
                    }
                    finally
                    {
                        if (gate != null) Monitor.Exit(gate);
                    }
                    sample++;
                }
                Thread.Sleep(1);
            }
        }

        static void HandleCommand(IObserver<HarpMessage> observer, HarpMessage command, double t, ref double ticks,
                                  int[] pulseWidths, SimCsvLog log, TriggerSender trigger)
        {
            if (command.MessageType != MessageType.Write)
            {
                // Register reads (DumpRegisters) are not modelled; real reads are filtered out of the logs anyway.
                return;
            }

            switch (command.Address)
            {
                case EncoderReset.Address:
                    if ((EncoderReset.GetPayload(command) & EncoderInputs.EncoderPort2) != 0)
                    {
                        ticks = 0;
                        if (log != null) log.Write(t, "EncoderReset", "EncoderPort2");
                    }
                    break;
                case PulseDO1.Address: pulseWidths[1] = PulseDO1.GetPayload(command); break;
                case PulseDO2.Address: pulseWidths[2] = PulseDO2.GetPayload(command); break;
                case PulseDO3.Address: pulseWidths[3] = PulseDO3.GetPayload(command); break;
                case OutputSet.Address:
                    var outputs = OutputSet.GetPayload(command);
                    if ((outputs & DigitalOutputs.DO1) != 0) Valve(1, t, pulseWidths, log);
                    if ((outputs & DigitalOutputs.DO2) != 0) Valve(2, t, pulseWidths, log);
                    if ((outputs & DigitalOutputs.DO3) != 0)
                    {
                        var sent = trigger.Send();
                        if (log != null) log.Write(t, "ZapitTTL", "DO3 width " + pulseWidths[3] + " ms" + (sent ? "" : " (no trigger port)"));
                        SimWorld.Log("board", string.Format(CultureInfo.InvariantCulture, "DO3 TTL (Zapit trigger) at Harp {0:F3}", t));
                    }
                    break;
            }

            // Real Harp devices answer every write with a timestamped Write message carrying the register value.
            var payloadType = command.PayloadType & ~PayloadType.Timestamp;
            observer.OnNext(HarpMessage.FromPayload(command.Address, t, MessageType.Write, payloadType, command.GetPayload()));
        }

        static void Valve(int line, double t, int[] pulseWidths, SimCsvLog log)
        {
            if (log != null) log.Write(t, "Valve", "DO" + line + " width " + pulseWidths[line] + " ms");
            SimWorld.Log("board", string.Format(CultureInfo.InvariantCulture, "reward valve DO{0} opened at Harp {1:F3} ({2} ms)", line, t, pulseWidths[line]));
        }

        // Sends one byte per TTL on a background thread over a persistent TCP connection (reconnects if dropped).
        sealed class TriggerSender : IDisposable
        {
            readonly string host;
            readonly int port;
            readonly BlockingCollection<byte> queue = new BlockingCollection<byte>();
            readonly Thread thread;

            public TriggerSender(string host, int port)
            {
                this.host = host;
                this.port = port;
                if (port <= 0) return;
                thread = new Thread(Loop) { IsBackground = true, Name = "SimBehaviorBoard.Trigger" };
                thread.Start();
            }

            public bool Send()
            {
                if (port <= 0) return false;
                queue.Add(1);
                return true;
            }

            void Loop()
            {
                TcpClient client = null;
                try
                {
                    foreach (var value in queue.GetConsumingEnumerable())
                    {
                        for (int attempt = 0; attempt < 2; attempt++)
                        {
                            try
                            {
                                if (client == null) { client = new TcpClient(); client.NoDelay = true; client.Connect(host, port); }
                                client.GetStream().Write(new[] { value }, 0, 1);
                                break;
                            }
                            catch (Exception ex)
                            {
                                if (client != null) client.Close();
                                client = null;
                                if (attempt == 1) SimWorld.Log("board", "could not send TTL to " + host + ":" + port + ": " + ex.Message);
                            }
                        }
                    }
                }
                finally { if (client != null) client.Close(); }
            }

            public void Dispose()
            {
                queue.CompleteAdding();
                if (thread != null) thread.Join(500);
            }
        }
    }
}
