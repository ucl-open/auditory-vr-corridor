using Bonsai;
using System;
using System.ComponentModel;
using System.Reactive.Linq;

[Combinator]
[Description("Throws an InvalidOperationException carrying the input string as its message, terminating the workflow with an error. Used by watchdogs to fail loudly instead of stalling silently.")]
[WorkflowElementCategory(ElementCategory.Sink)]
public class ThrowError
{
    public IObservable<string> Process(IObservable<string> source)
    {
        return source.Do(message =>
        {
            throw new InvalidOperationException(message);
        });
    }
}
