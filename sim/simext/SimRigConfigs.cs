using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Globalization;
using System.Linq;
using System.Reactive.Linq;
using System.Reflection;
using Bonsai;

namespace AvcSim
{
    // Replaces the RigConfigs node (Params) in the harness: instead of picking a rig by the PC's name it returns a
    // RigSpecificConfigs (the class in src/Extensions/RigConfigs.cs, compiled into Extensions.dll) filled with test
    // values. Fields are discovered by reflection at run time, so new fields in RigConfigs.cs (e.g. the Zapit ones) are
    // picked up without changing this code: known names get the values below, anything else gets a type default and is
    // listed in the console output.
    [Combinator(MethodName = "Generate")]
    [WorkflowElementCategory(ElementCategory.Source)]
    [Description("SIMULATION: rig configuration with test values (replaces RigConfigs).")]
    public class SimRigConfigs
    {
        public SimRigConfigs()
        {
            RigName = "SIM-MAC";
            ValveOpenTime = 80;
            ZapitHost = "127.0.0.1";
            ZapitPort = 1488;
            ZapitHardwareTriggered = true;
            ZapitTriggerPulseWidth = 5;
        }

        public string RigName { get; set; }
        public double ValveOpenTime { get; set; }
        public string ZapitHost { get; set; }
        public int ZapitPort { get; set; }
        public bool ZapitHardwareTriggered { get; set; }
        public double ZapitTriggerPulseWidth { get; set; }

        public IObservable<RigSpecificConfigs> Generate()
        {
            return Observable.Defer(() => Observable.Return(Create()));
        }

        public IObservable<RigSpecificConfigs> Generate<TSource>(IObservable<TSource> source)
        {
            return source.Select(_ => Create());
        }

        object ValueFor(string name, Type type, List<string> unknown)
        {
            if (name == "ValveOpenTime") return ValveOpenTime;
            if (name == "ZapitHost") return ZapitHost;
            if (name == "ZapitPort") return ZapitPort;
            if (name == "ZapitHardwareTriggered") return ZapitHardwareTriggered;
            if (name == "ZapitTriggerPulseWidth") return ZapitTriggerPulseWidth;
            if (name.StartsWith("COMPort", StringComparison.Ordinal)) return "SIM";
            if (name.StartsWith("SerialNumber", StringComparison.Ordinal)) return "SIM";
            if (name == "AudioDeviceName") return "SIM (no audio)";
            if (name == "MeshMapFilePath") return "SIM (no projector)";
            if (name.StartsWith("Motor", StringComparison.Ordinal) && name.EndsWith("InPosition", StringComparison.Ordinal)) return 0;
            unknown.Add(name);
            if (type == typeof(string)) return "SIM";
            return type.IsValueType ? Activator.CreateInstance(type) : null;
        }

        RigSpecificConfigs Create()
        {
            var configs = new RigSpecificConfigs();
            var unknown = new List<string>();
            var summary = new List<string>();
            const BindingFlags flags = BindingFlags.Public | BindingFlags.Instance;
            foreach (var field in typeof(RigSpecificConfigs).GetFields(flags))
            {
                var value = Convert(ValueFor(field.Name, field.FieldType, unknown), field.FieldType);
                field.SetValue(configs, value);
                summary.Add(field.Name + "=" + System.Convert.ToString(value, CultureInfo.InvariantCulture));
            }
            foreach (var property in typeof(RigSpecificConfigs).GetProperties(flags).Where(p => p.CanWrite))
            {
                var value = Convert(ValueFor(property.Name, property.PropertyType, unknown), property.PropertyType);
                property.SetValue(configs, value, null);
                summary.Add(property.Name + "=" + System.Convert.ToString(value, CultureInfo.InvariantCulture));
            }
            Console.WriteLine("Rig config: " + RigName + " (simulated)");
            SimWorld.Log("rigconfigs", string.Join(", ", summary));
            if (unknown.Count > 0)
            {
                SimWorld.Log("rigconfigs", "WARNING: no sim value for RigSpecificConfigs." + string.Join(", ", unknown)
                    + " (type defaults used) - add them to sim/simext/SimRigConfigs.cs");
            }
            return configs;
        }

        static object Convert(object value, Type type)
        {
            if (value == null || type.IsInstanceOfType(value)) return value;
            var target = Nullable.GetUnderlyingType(type) ?? type;
            return System.Convert.ChangeType(value, target, CultureInfo.InvariantCulture);
        }
    }

    // Stops the headless run (sim/runner BonsaiRun) cleanly after the given number of completed trials: counts true
    // values of TrialEnded (the same signal the TrialLogger writes a row on) and then waits DelaySeconds so every
    // logger has written that trial before all nodes are disposed.
    [Combinator]
    [WorkflowElementCategory(ElementCategory.Sink)]
    [Description("SIMULATION: stops the headless run after N completed trials.")]
    public class StopAfterTrials
    {
        public StopAfterTrials()
        {
            DelaySeconds = 1;
        }

        [Description("Completed trials after which the run stops (0 = never).")]
        public int Trials { get; set; }

        [Description("Seconds to wait after the last trial ends before stopping.")]
        public double DelaySeconds { get; set; }

        public IObservable<bool> Process(IObservable<bool> source)
        {
            return Observable.Defer(() =>
            {
                var count = 0;
                return source.Do(ended =>
                {
                    if (!ended || Trials <= 0) return;
                    count++;
                    if (count == Trials)
                    {
                        var reason = Trials + " trials completed";
                        SimWorld.Log("control", reason + ", stopping in " + DelaySeconds + " s");
                        Observable.Timer(TimeSpan.FromSeconds(DelaySeconds)).Subscribe(_ => SimControl.RequestStop(reason));
                    }
                });
            });
        }
    }

    public static class SimControl
    {
        // Asks the headless runner to stop the workflow (dispose every node so files are flushed and closed).
        public static void RequestStop(string reason)
        {
            AppDomain.CurrentDomain.SetData("AvcSim.StopReason", reason);
            var handle = AppDomain.CurrentDomain.GetData("AvcSim.StopEvent") as System.Threading.EventWaitHandle;
            if (handle != null) handle.Set();
            else SimWorld.Log("control", "stop requested (" + reason + ") but no headless runner is listening");
        }
    }
}
