using Bonsai;
using System;
using System.ComponentModel;
using System.Reactive.Linq;
using UclOpenAuditoryVrCorridorDataSchema;

// Startup check for optogenetics sessions. Bonsai sends Zapit condition numbers that it reads from the session's stimulus
// config (optogenetics.zapitConfigPath), and Zapit presents whatever it has at that position in the config it has loaded.
// If the two files differ, the wrong sites would be stimulated without any error, so the session stops at startup instead.
[Combinator]
[Description("Compares Zapit's GetNumConditions reply with the number of conditions in the session's Zapit stimulus config, and stops the session if they differ or Zapit answered with an error. Passes the reply through when they match. Input is the GetNumConditions reply and the task parameters.")]
[WorkflowElementCategory(ElementCategory.Transform)]
public class CheckZapitConditionCount
{
    public IObservable<ZapitReply> Process(IObservable<Tuple<ZapitReply, UclOpenAuditoryVrCorridorTaskParameters>> source)
    {
        return source.Select(input =>
        {
            Check(input.Item1, input.Item2);
            return input.Item1;
        });
    }

    private static void Check(ZapitReply reply, UclOpenAuditoryVrCorridorTaskParameters parameters)
    {
        if (reply == null)
        {
            throw new ArgumentNullException("reply", "CheckZapitConditionCount needs Zapit's GetNumConditions reply.");
        }
        if (reply.Command != ZapitCommandType.GetNumConditions)
        {
            // A wiring mistake: only the answer to GetNumConditions carries the condition count.
            throw new InvalidOperationException(string.Format(
                "CheckZapitConditionCount expects Zapit's GetNumConditions reply but received {0}.", reply));
        }
        if (parameters == null || parameters.Optogenetics == null)
        {
            throw new ArgumentNullException("parameters", "CheckZapitConditionCount needs the task parameters.");
        }

        var path = parameters.Optogenetics.ZapitConfigPath;
        var count = ZapitStimConfig.ReadConditionNumbers(path).Count;
        ZapitStimConfig.CheckRampDowns(path);
        if (reply.IsError)
        {
            throw new InvalidOperationException(string.Format(
                "Zapit answered GetNumConditions with an error ({0}), so the number of conditions it has loaded is unknown. " +
                "The session's stimulus config {1} has {2} - load the same file in Zapit and restart the workflow.",
                reply, path, count));
        }
        if (reply.Value != count)
        {
            throw new InvalidOperationException(string.Format(
                "Zapit has {0} conditions loaded but the session's stimulus config {1} has {2} - load the same file in Zapit " +
                "and restart the workflow.",
                reply.Value, path, count));
        }
    }
}
