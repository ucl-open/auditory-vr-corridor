// Headless Bonsai runner for Mono (macOS/Linux): loads a .bonsai workflow with Bonsai.Core's own serializer, builds it
// and runs it the way `Bonsai.exe --no-editor` does, without the editor, visualizers or any Windows-only assemblies.
//
// Usage: mono BonsaiRun.exe <workflow.bonsai> [--lib <dir>]... [--timeout <seconds>] [--serialize]
//   --lib        folder of assemblies to load (repeatable); every *.dll in it is loaded up front and assembly
//                references are resolved from these folders, like Bonsai's Packages folder.
//   --timeout    stop the workflow after this many seconds (0 = run until it completes, fails or is stopped).
//   --serialize  run Rx's timer and thread-pool callbacks (Delay, Timer, Throttle, ...) one at a time under a global
//                lock that the simulated devices also take for each event they emit (AppDomain data "AvcSim.Gate").
//                Without it the threads run freely, as in Bonsai on the rig, and lock-order races inside the workflow
//                can deadlock it; with it they cannot interleave mid-event (threads Rx starts itself, e.g.
//                ObserveOn(NewThreadScheduler), are not included).
//
// The workflow runs from its own folder (Environment.CurrentDirectory), as Bonsai does, so relative paths resolve the
// same way. A workflow node can stop the run cleanly (all sinks flushed and closed) by setting the EventWaitHandle that
// this runner publishes as AppDomain data "AvcSim.StopEvent" (see sim/simext SimControl); Ctrl+C does the same.
//
// Exit codes: 0 completed or stopped (sim stop condition, timeout or Ctrl+C); 1 workflow runtime error;
//             2 build error; 3 workflow could not be loaded/deserialized; 5 deadlock inside the workflow (all thread
//             stacks are printed to stdout); 64 bad arguments.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading;
using System.Xml;
using Bonsai;
using Bonsai.Expressions;

static class BonsaiRun
{
    static readonly List<string> LibDirs = new List<string>();
    static readonly Dictionary<string, Assembly> Loaded = new Dictionary<string, Assembly>(StringComparer.OrdinalIgnoreCase);

    static Assembly Resolve(object sender, ResolveEventArgs e)
    {
        var name = new AssemblyName(e.Name).Name;
        Assembly assembly;
        lock (Loaded)
        {
            if (Loaded.TryGetValue(name, out assembly)) return assembly;
            foreach (var dir in LibDirs)
            {
                foreach (var ext in new[] { ".dll", ".exe" })
                {
                    var path = Path.Combine(dir, name + ext);
                    if (File.Exists(path))
                    {
                        assembly = Assembly.LoadFrom(path);
                        Loaded[name] = assembly;
                        return assembly;
                    }
                }
            }
        }
        return null;
    }

    static int Main(string[] args)
    {
        string workflowPath = null;
        double timeout = 0;
        var serialize = false;
        for (int i = 0; i < args.Length; i++)
        {
            if (args[i] == "--lib" && i + 1 < args.Length) LibDirs.Add(Path.GetFullPath(args[++i]));
            else if (args[i] == "--serialize") serialize = true;
            else if (args[i] == "--timeout" && i + 1 < args.Length)
                timeout = double.Parse(args[++i], System.Globalization.CultureInfo.InvariantCulture);
            else if (args[i].StartsWith("--")) { Console.Error.WriteLine("unknown option " + args[i]); return 64; }
            else workflowPath = Path.GetFullPath(args[i]);
        }
        if (workflowPath == null || !File.Exists(workflowPath))
        {
            Console.Error.WriteLine("usage: mono BonsaiRun.exe <workflow.bonsai> [--lib <dir>]... [--timeout <seconds>] [--serialize]");
            return 64;
        }

        AppDomain.CurrentDomain.AssemblyResolve += Resolve;
        foreach (var dir in LibDirs)
        {
            var files = Directory.GetFiles(dir, "*.dll");
            Array.Sort(files, StringComparer.Ordinal);
            foreach (var file in files)
            {
                try { var a = Assembly.LoadFrom(file); lock (Loaded) Loaded[a.GetName().Name] = a; }
                catch (Exception ex) { Log("skip " + Path.GetFileName(file) + ": " + ex.GetType().Name + " " + ex.Message); }
            }
        }
        return WorkflowRunner.Run(workflowPath, timeout, serialize);
    }

    internal static void Log(string message)
    {
        Console.Error.WriteLine("[run " + DateTime.Now.ToString("HH:mm:ss.fff") + "] " + message);
    }
}

// Everything that touches Bonsai or Rx types lives here (and Main has no lambdas), so those assemblies are only loaded
// after Main has registered the resolver for the --lib folders.
static class WorkflowRunner
{
    static void Log(string message)
    {
        BonsaiRun.Log(message);
    }

    [System.Runtime.CompilerServices.MethodImpl(System.Runtime.CompilerServices.MethodImplOptions.NoInlining)]
    internal static int Run(string workflowPath, double timeout, bool serialize)
    {
        if (serialize)
        {
            RxGate.Install();
            Log("serialized: Rx timer/thread-pool callbacks and the simulated devices run one at a time (--serialize)");
        }

        // Stop handle for the simulation (sim/simext SimControl.RequestStop) and for Ctrl+C
        var stop = new ManualResetEvent(false);
        AppDomain.CurrentDomain.SetData("AvcSim.StopEvent", stop);
        Console.CancelKeyPress += (sender, e) => { e.Cancel = true; AppDomain.CurrentDomain.SetData("AvcSim.StopReason", "Ctrl+C"); stop.Set(); };

        Environment.CurrentDirectory = Path.GetDirectoryName(workflowPath);   // Bonsai runs a workflow from its own folder
        WorkflowBuilder builder;
        try
        {
            using (var reader = XmlReader.Create(workflowPath))
            {
                builder = (WorkflowBuilder)WorkflowBuilder.Serializer.Deserialize(reader);
            }
        }
        catch (Exception ex) { Log("LOAD ERROR: " + Describe(ex, null)); return 3; }
        Log("loaded " + workflowPath + " (" + builder.Workflow.Count + " top-level nodes)");

        IObservable<System.Reactive.Unit> observable;
        try { observable = builder.Workflow.BuildObservable(); }
        catch (Exception ex) { Log("BUILD ERROR: " + Describe(ex, builder.Workflow)); return 2; }
        Log("built OK, running" + (timeout > 0 ? " (timeout " + timeout + " s)" : ""));

        var done = new ManualResetEvent(false);
        Exception error = null;
        var started = DateTime.Now;
        IDisposable subscription = null;
        try
        {
            if (serialize)
            {
                lock (RxGate.Gate) subscription = observable.Subscribe(_ => { }, ex => { error = ex; done.Set(); }, () => done.Set());
            }
            else subscription = observable.Subscribe(_ => { }, ex => { error = ex; done.Set(); }, () => done.Set());
        }
        catch (Exception ex) { error = ex; }

        string result;
        if (error == null)
        {
            var index = timeout > 0
                ? WaitHandle.WaitAny(new WaitHandle[] { done, stop }, TimeSpan.FromSeconds(timeout))
                : WaitHandle.WaitAny(new WaitHandle[] { done, stop });
            if (index == 0) result = error == null ? "workflow completed" : "workflow error";
            else if (index == 1) result = "stopped: " + (AppDomain.CurrentDomain.GetData("AvcSim.StopReason") ?? "stop requested");
            else result = "timeout reached (" + timeout + " s)";
        }
        else result = "workflow error";

        // Stop every node (sinks flush and close their files). Disposal runs on its own thread because a deadlock
        // inside the workflow (threads waiting on each other's Rx locks) also blocks disposal forever.
        var deadlock = AppDomain.CurrentDomain.GetData("AvcSim.Deadlock") as string;
        var disposed = new ManualResetEvent(false);
        var disposer = new Thread(() =>
        {
            try { if (subscription != null) subscription.Dispose(); }
            catch (Exception ex) { Log("error while stopping: " + Describe(ex, builder.Workflow)); }
            finally { disposed.Set(); }
        });
        disposer.IsBackground = true;
        disposer.Start();
        var stopped = disposed.WaitOne(TimeSpan.FromSeconds(deadlock != null ? 5 : 30));
        deadlock = AppDomain.CurrentDomain.GetData("AvcSim.Deadlock") as string ?? (stopped ? null : "the workflow did not stop within 30 s");

        var elapsed = (DateTime.Now - started).TotalSeconds;
        if (deadlock != null)
        {
            Log("DEADLOCK after " + elapsed.ToString("F1") + " s: " + deadlock + ". Thread stacks follow on stdout ('Full thread dump').");
            DumpThreads();
            Environment.Exit(5);
        }
        if (error != null)
        {
            Log("WORKFLOW ERROR after " + elapsed.ToString("F1") + " s: " + Describe(error, builder.Workflow));
            return 1;
        }
        Log("RESULT: " + result + " after " + elapsed.ToString("F1") + " s");
        return 0;
    }

    // Mono prints every managed thread's stack to stdout on SIGQUIT.
    static void DumpThreads()
    {
        try
        {
            Console.Out.Flush();
            using (var kill = System.Diagnostics.Process.Start("kill", "-QUIT " + System.Diagnostics.Process.GetCurrentProcess().Id))
            {
                kill.WaitForExit(2000);
            }
            Thread.Sleep(1500);
            Console.Out.Flush();
        }
        catch (Exception ex) { Log("could not dump threads: " + ex.Message); }
    }

    static string Describe(Exception ex, ExpressionBuilderGraph workflow)
    {
        var text = ex.GetType().Name + ": " + ex.Message;
        for (var e = ex; e != null; e = e.InnerException)
        {
            ExpressionBuilder node = null;
            var build = e as WorkflowBuildException;
            var runtime = e as WorkflowRuntimeException;
            if (build != null) node = build.Builder;
            else if (runtime != null) node = runtime.Builder;
            if (node != null)
            {
                var path = workflow != null ? FindPath(workflow, node, "") : null;
                text += "\n    at node: " + (path ?? ExpressionBuilder.GetElementDisplayName(node));
                break;
            }
        }
        for (var inner = ex.InnerException; inner != null; inner = inner.InnerException)
            text += "\n    <- " + inner.GetType().Name + ": " + inner.Message;
        if (Environment.GetEnvironmentVariable("BONSAIRUN_STACK") == "1") text += "\n" + ex;
        return text;
    }

    // Path of a node in the workflow tree, e.g. /TaskLogic[11]/BeepTimer[0]/HarpBeat[0]/Every50thSample[3]
    static string FindPath(ExpressionBuilderGraph workflow, ExpressionBuilder target, string prefix)
    {
        var nodes = workflow.ToList();
        for (int i = 0; i < nodes.Count; i++)
        {
            var value = nodes[i].Value;
            var name = ExpressionBuilder.GetElementDisplayName(value);
            var here = prefix + "/" + name + "[" + i + "]";
            if (ReferenceEquals(value, target) || ReferenceEquals(ExpressionBuilder.Unwrap(value), target)) return here;
            var nested = ExpressionBuilder.Unwrap(value) as IWorkflowExpressionBuilder;
            if (nested != null && nested.Workflow != null)
            {
                var found = FindPath(nested.Workflow, target, here);
                if (found != null) return found;
            }
        }
        return null;
    }
}

// Global lock for --serialize, installed through Rx 2.2's platform enlightenment hook so that every callback of
// Scheduler.Default (used by Delay, Timer, Throttle, Sample, DelaySubscription, ...) runs while holding it.
static class RxGate
{
    internal static readonly object Gate = new object();

    internal static void Install()
    {
        var original = System.Reactive.PlatformServices.PlatformEnlightenmentProvider.Current;
        System.Reactive.PlatformServices.PlatformEnlightenmentProvider.Current = new Provider(original);
        AppDomain.CurrentDomain.SetData("AvcSim.Gate", Gate);
    }

    static void Run(Action<object> action, object state)
    {
        lock (Gate)
        {
            var start = System.Diagnostics.Stopwatch.GetTimestamp();
            action(state);
            var ms = (System.Diagnostics.Stopwatch.GetTimestamp() - start) * 1000.0 / System.Diagnostics.Stopwatch.Frequency;
            if (ms > 100)
            {
                var target = action.Target != null ? action.Target.GetType().FullName : action.Method.DeclaringType.FullName;
                BonsaiRun.Log("slow serialized callback: " + ms.ToString("F0") + " ms in " + target + "." + action.Method.Name);
            }
        }
    }

    sealed class Provider : System.Reactive.PlatformServices.IPlatformEnlightenmentProvider
    {
        readonly System.Reactive.PlatformServices.IPlatformEnlightenmentProvider original;

        public Provider(System.Reactive.PlatformServices.IPlatformEnlightenmentProvider original)
        {
            this.original = original;
        }

        public T GetService<T>(params object[] args) where T : class
        {
            var service = original != null ? original.GetService<T>(args) : null;
            if (typeof(T) == typeof(System.Reactive.Concurrency.IConcurrencyAbstractionLayer))
            {
                return (T)(object)new Cal((System.Reactive.Concurrency.IConcurrencyAbstractionLayer)service);
            }
            return service;
        }
    }

    sealed class Cal : System.Reactive.Concurrency.IConcurrencyAbstractionLayer
    {
        readonly System.Reactive.Concurrency.IConcurrencyAbstractionLayer inner;

        public Cal(System.Reactive.Concurrency.IConcurrencyAbstractionLayer inner)
        {
            if (inner == null) throw new InvalidOperationException("Rx platform services provide no concurrency layer to wrap.");
            this.inner = inner;
        }

        public IDisposable StartTimer(Action<object> action, object state, TimeSpan dueTime)
        {
            return inner.StartTimer(s => Run(action, s), state, dueTime);
        }

        public IDisposable StartPeriodicTimer(Action action, TimeSpan period)
        {
            return inner.StartPeriodicTimer(() => Run(_ => action(), null), period);
        }

        public IDisposable QueueUserWorkItem(Action<object> action, object state)
        {
            return inner.QueueUserWorkItem(s => Run(action, s), state);
        }

        public void Sleep(TimeSpan timeout)
        {
            inner.Sleep(timeout);
        }

        public System.Reactive.Concurrency.IStopwatch StartStopwatch()
        {
            return inner.StartStopwatch();
        }

        public bool SupportsLongRunning
        {
            get { return inner.SupportsLongRunning; }
        }

        // Long-running loops (e.g. EventLoopScheduler) would hold the lock forever: not serialized.
        public void StartThread(Action<object> action, object state)
        {
            inner.StartThread(action, state);
        }
    }
}
