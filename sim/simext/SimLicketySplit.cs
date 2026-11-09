using System;
using System.ComponentModel;
using System.Reactive.Disposables;
using System.Reactive.Linq;
using AllenNeuralDynamics.LicketySplit;
using Bonsai;
using Bonsai.Harp;

namespace AvcSim
{
    // Stands in for the LicketySplit lick detector (AllenNeuralDynamics.LicketySplit Device) inside the sim copy of
    // UclOpen.Devices LicketySplit.bonsai, so the include's own Parse(LickState) -> Equal(Channel0) logic produces
    // LickStateLeft exactly as on the rig (true when a lick starts, false when it ends).
    // Events: LickState (address 32) on every lick contact change made by the simulated mouse (Channel0 / None),
    // TimestampSeconds once per second when Heartbeat is Enabled, and timestamped echoes of Write commands
    // (the include writes the trigger thresholds at startup).
    [Combinator(MethodName = "Generate")]
    [WorkflowElementCategory(ElementCategory.Source)]
    [Description("SIMULATION: LicketySplit lick detector driven by the simulated mouse.")]
    public class SimLicketySplit
    {
        public SimLicketySplit()
        {
            OperationMode = OperationMode.Active;
            OperationLed = LedState.On;
            VisualIndicators = LedState.On;
            Heartbeat = EnableFlag.Enabled;
        }

        public OperationMode OperationMode { get; set; }
        public LedState OperationLed { get; set; }
        public bool DumpRegisters { get; set; }
        public LedState VisualIndicators { get; set; }
        public EnableFlag Heartbeat { get; set; }
        public bool IgnoreErrors { get; set; }
        [Description("Ignored in the simulation (no serial port).")]
        public string PortName { get; set; }

        public IObservable<HarpMessage> Generate()
        {
            return Generate(Observable.Never<HarpMessage>());
        }

        public IObservable<HarpMessage> Generate(IObservable<HarpMessage> source)
        {
            return Observable.Create<HarpMessage>(observer =>
            {
                var gate = SimWorld.Gate ?? new object();
                Action<HarpMessage> emit = message => { lock (gate) observer.OnNext(message); };
                var commands = source.Subscribe(command =>
                {
                    if (command == null || command.MessageType != MessageType.Write) return;
                    var payloadType = command.PayloadType & ~PayloadType.Timestamp;
                    emit(HarpMessage.FromPayload(command.Address, SimWorld.HarpNow(), MessageType.Write, payloadType, command.GetPayload()));
                }, error => { }, () => { });
                var licks = SimWorld.LickContacts.Subscribe(contact =>
                    emit(LickState.FromPayload(SimWorld.HarpNow(), MessageType.Event, contact ? LickChannels.Channel0 : LickChannels.None)));
                var heartbeat = Heartbeat == EnableFlag.Enabled
                    ? Observable.Interval(TimeSpan.FromSeconds(1)).Subscribe(_ =>
                    {
                        var now = SimWorld.HarpNow();
                        emit(TimestampSeconds.FromPayload(now, MessageType.Event, (uint)Math.Floor(now)));
                    })
                    : Disposable.Empty;
                SimWorld.Log("licketysplit", "simulated LicketySplit started (licks from the simulated mouse)");
                return new CompositeDisposable(commands, licks, heartbeat);
            });
        }
    }
}
