using Bonsai;
using System;
using System.ComponentModel;
using System.Reactive.Linq;

[Combinator]
[Description("Emits a read-only Zapit query each time an input arrives: whether a stimulus config is loaded, the current state, or the number of conditions. The answer arrives in the Value field of the reply.")]
[WorkflowElementCategory(ElementCategory.Transform)]
public class CreateZapitQuery
{
    public CreateZapitQuery()
    {
        Query = ZapitQuery.IsStimConfigLoaded;
    }

    [Description("Which query to send. IsStimConfigLoaded answers 1 or 0; GetState answers 0 idle, 1 stimulating, 2 ramp-down; GetNumConditions answers the count in the loaded config.")]
    public ZapitQuery Query { get; set; }

    public IObservable<ZapitCommand> Process<TSource>(IObservable<TSource> source)
    {
        return source.Select(input => ZapitCommand.Query(Query));
    }
}
