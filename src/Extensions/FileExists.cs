using Bonsai;
using System;
using System.ComponentModel;
using System.Reactive.Linq;

// Used to check whether an animal already has saved lick spout positions.
[Combinator]
[Description("Reports whether the file at each incoming path exists.")]
[WorkflowElementCategory(ElementCategory.Transform)]
public class FileExists
{
    public IObservable<bool> Process(IObservable<string> source)
    {
        return source.Select(path => System.IO.File.Exists(path));
    }
}
