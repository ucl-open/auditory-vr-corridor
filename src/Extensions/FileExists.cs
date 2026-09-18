using Bonsai;
using System;
using System.ComponentModel;
using System.Reactive.Linq;

/// <summary>
/// Reports whether the file at each incoming path exists.
///
/// Used to decide whether an animal already has saved lick spout positions: if the file is there it
/// is read and the positions restored, if not the defaults in Init Positions are left alone. Ported
/// from the av-dome workflow, which stores the same per-animal files in the same folder.
/// </summary>
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
