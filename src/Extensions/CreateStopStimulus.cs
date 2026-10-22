using Bonsai;
using System;
using System.ComponentModel;
using System.Reactive.Linq;

[Combinator]
[Description("Emits a Zapit StopStimulus command each time an input arrives. Zapit ramps the laser down and returns to idle.")]
[WorkflowElementCategory(ElementCategory.Transform)]
public class CreateStopStimulus
{
    public IObservable<ZapitCommand> Process<TSource>(IObservable<TSource> source)
    {
        return source.Select(input => ZapitCommand.Stop());
    }
}
