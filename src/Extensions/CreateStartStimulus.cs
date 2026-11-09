using Bonsai;
using System;
using System.ComponentModel;
using System.Reactive.Linq;

[Combinator]
[Description("Emits a Zapit StartStimulus command, built from the operator properties, each time an input arrives. Map ConditionNumber, StimDuration and StartDelay from the trial data to stimulate the condition drawn for that trial.")]
[WorkflowElementCategory(ElementCategory.Transform)]
public class CreateStartStimulus
{
    public CreateStartStimulus()
    {
        ConditionNumber = 0;
        LaserOn = true;
        HardwareTriggered = false;
        Logging = true;
        StimDuration = 0;
        LaserPower = 0;
        StartDelay = 0;
    }

    [Description("Condition index in the Zapit stimulus config, 1 to 254. 0 lets Zapit draw a random condition; the reply reports which one was presented.")]
    public int ConditionNumber { get; set; }

    [Description("True fires the laser. False moves the galvos with the laser off (a sham trial).")]
    public bool LaserOn { get; set; }

    [Description("True makes the Zapit DAQ wait for a TTL trigger; false starts the stimulus as soon as Zapit receives the command.")]
    public bool HardwareTriggered { get; set; }

    [Description("Whether Zapit writes its own trial log entry for this stimulus.")]
    public bool Logging { get; set; }

    [Description("Stimulus duration in seconds. 0 leaves the duration unset, so the stimulus plays until a StopStimulus command.")]
    public double StimDuration { get; set; }

    [Description("Laser power in mW. 0 leaves the power unset, so Zapit uses the value in its stimulus config.")]
    public double LaserPower { get; set; }

    [Description("Delay from command receipt to stimulus onset, in seconds. Zapit only honours it when StimDuration is set.")]
    public double StartDelay { get; set; }

    public IObservable<ZapitCommand> Process<TSource>(IObservable<TSource> source)
    {
        return source.Select(input => Build());
    }

    private ZapitCommand Build()
    {
        var command = new ZapitCommand();
        command.Command = ZapitCommandType.StartStimulus;
        if (ConditionNumber > 0) command.ConditionNumber = ConditionNumber;
        command.LaserOn = LaserOn;
        command.HardwareTriggered = HardwareTriggered;
        command.Logging = Logging;
        if (StimDuration > 0) command.StimDuration = (float)StimDuration;
        if (LaserPower > 0) command.LaserPower = (float)LaserPower;
        if (StartDelay > 0) command.StartDelay = (float)StartDelay;
        return command;
    }
}
