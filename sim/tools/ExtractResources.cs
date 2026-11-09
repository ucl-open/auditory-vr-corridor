// Copies the embedded .bonsai workflows out of assemblies (used by sim/setup.sh).
// Bonsai resolves IncludeWorkflow paths like "UclOpen.Logging:LogController.bonsai" to the manifest resource
// "UclOpen.Logging.LogController.bonsai"; files are written under that resource name so sim/make_harness.py can make
// patched local copies of the includes it needs to change.
// Usage: mono ExtractResources.exe OUT_DIR ASSEMBLY.dll...
using System;
using System.IO;
using System.Reflection;

static class ExtractResources
{
    static int Main(string[] args)
    {
        if (args.Length < 2)
        {
            Console.Error.WriteLine("usage: mono ExtractResources.exe OUT_DIR ASSEMBLY.dll...");
            return 64;
        }
        Directory.CreateDirectory(args[0]);
        var count = 0;
        for (int i = 1; i < args.Length; i++)
        {
            var assembly = Assembly.ReflectionOnlyLoadFrom(args[i]);
            foreach (var name in assembly.GetManifestResourceNames())
            {
                if (!name.EndsWith(".bonsai", StringComparison.Ordinal)) continue;
                using (var stream = assembly.GetManifestResourceStream(name))
                using (var file = File.Create(Path.Combine(args[0], name)))
                {
                    stream.CopyTo(file);
                }
                count++;
            }
        }
        Console.WriteLine(count + " embedded workflows extracted to " + args[0]);
        return 0;
    }
}
