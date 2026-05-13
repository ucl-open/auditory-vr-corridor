using Bonsai;
using System;
using System.ComponentModel;
using System.Collections.Generic;
using System.Linq;
using System.Reactive.Linq;
using Harp.StepperDriver;

[Combinator]
[Description("")]
[WorkflowElementCategory(ElementCategory.Transform)]
public class UnpackSwitchTriggers
{
    public IObservable<bool[]> Process(IObservable<DigitalInputStates> source)
    {
        return source.Select(value =>
        {
            string str;
            try
            {
                str = value.ToString();
            }
            catch (ArgumentOutOfRangeException)
            {
                str = "Input0, Input1, Input2";
                Console.WriteLine("Error in ToString, using default values");
            }
            String[] tempVals = str.Split(new[] { ", " }, StringSplitOptions.RemoveEmptyEntries);
            bool[] triggers = new bool[3];
            triggers[0] = tempVals.Contains("Input0");
            triggers[1] = tempVals.Contains("Input1");
            triggers[2] = tempVals.Contains("Input2");
            return triggers;
        });
    }
}
