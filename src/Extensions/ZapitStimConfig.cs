using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;

/// <summary>
/// Reads the condition numbers from a Zapit stimulus config file (YAML) without a YAML library.
/// A condition is a "stimLocationsNN:" key at the start of a line (the top level of the file), and NN is its
/// condition number. Zapit loads stimLocations01, stimLocations02, ... in order and numbers conditions by their
/// position, so the numbers must be exactly 1 to N. gen_session.py applies the same rule to the same file.
/// </summary>
public static class ZapitStimConfig
{
    // The same pattern as gen_session.py. Indented keys, comments and quoted keys never match.
    private static readonly Regex ConditionKey = new Regex(@"^stimLocations(\d+)\s*:", RegexOptions.CultureInvariant);

    /// <summary>
    /// Returns the condition numbers in the Zapit stimulus config at <paramref name="path"/>, sorted: always 1 to N.
    /// Throws InvalidOperationException if the file is missing or unreadable, has no conditions, or its condition
    /// numbers are not exactly 1 to N.
    /// </summary>
    public static List<int> ReadConditionNumbers(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            throw new InvalidOperationException(
                "No Zapit stimulus config was given (optogenetics.zapitConfigPath is empty). " +
                "Set it to the stimulus config YAML that is loaded in Zapit.");
        }
        if (!File.Exists(path))
        {
            throw new InvalidOperationException(string.Format(
                "The Zapit stimulus config was not found: '{0}'.", path));
        }

        string[] lines;
        try
        {
            lines = File.ReadAllLines(path);
        }
        catch (IOException ex)
        {
            throw new InvalidOperationException(string.Format(
                "Could not read the Zapit stimulus config '{0}': {1}", path, ex.Message), ex);
        }
        catch (UnauthorizedAccessException ex)
        {
            throw new InvalidOperationException(string.Format(
                "Could not read the Zapit stimulus config '{0}': {1}", path, ex.Message), ex);
        }

        var numbers = new List<int>();
        foreach (var line in lines)
        {
            var match = ConditionKey.Match(line);
            if (!match.Success) continue;

            int number;
            if (!int.TryParse(match.Groups[1].Value, NumberStyles.None, CultureInfo.InvariantCulture, out number))
            {
                throw new InvalidOperationException(string.Format(
                    "The Zapit stimulus config '{0}' has a condition key whose number cannot be read: '{1}'.",
                    path, line.Trim()));
            }
            numbers.Add(number);
        }

        if (numbers.Count == 0)
        {
            throw new InvalidOperationException(string.Format(
                "The Zapit stimulus config '{0}' has no conditions: no line starts with a stimLocationsNN key.", path));
        }

        numbers.Sort();
        for (int i = 0; i < numbers.Count; i++)
        {
            if (numbers[i] != i + 1)
            {
                throw new InvalidOperationException(string.Format(
                    "The Zapit stimulus config '{0}' numbers its conditions {1}. They must be exactly 1 to {2}, with no " +
                    "gaps or repeats, because Zapit numbers conditions by their position in the file.",
                    path, Describe(numbers), numbers.Count));
            }
        }
        return numbers;
    }

    // Zapit's stopOptoStim ramps the laser down in whole stimulus cycles. A ramp-down of one cycle or less
    // (offRampDownDuration_ms <= 1000 / stimModulationFreqHz) takes a shortcut that writes zeros without stopping the DAQ
    // task, so on a hardware-triggered rig the next trial's stimulus would start as soon as it is sent instead of at the TTL.
    // gen_session.py applies the same rule to the same file.
    private static readonly Regex TopLevelKey = new Regex(@"^([A-Za-z_]\w*)\s*:", RegexOptions.Multiline | RegexOptions.CultureInvariant);
    private static readonly Regex RampDown = new Regex(@"offRampDownDuration_ms\s*:\s*([0-9.eE+-]+)", RegexOptions.CultureInvariant);
    private static readonly Regex ModulationFrequency = new Regex(@"stimModulationFreqHz\s*:\s*([0-9.eE+-]+)", RegexOptions.CultureInvariant);

    /// <summary>
    /// Throws InvalidOperationException if any condition in the Zapit stimulus config at <paramref name="path"/> has no
    /// offRampDownDuration_ms, or one that is not longer than one stimulus cycle. Does nothing when the file gives no
    /// stimModulationFreqHz, which Zapit itself refuses.
    /// </summary>
    public static void CheckRampDowns(string path)
    {
        string text;
        try
        {
            text = File.ReadAllText(path);
        }
        catch (Exception ex)
        {
            throw new InvalidOperationException(string.Format(
                "Could not read the Zapit stimulus config '{0}': {1}", path, ex.Message), ex);
        }

        var blocks = new Dictionary<string, string>();
        var keys = TopLevelKey.Matches(text);
        for (int i = 0; i < keys.Count; i++)
        {
            var end = i + 1 < keys.Count ? keys[i + 1].Index : text.Length;
            blocks[keys[i].Groups[1].Value] = text.Substring(keys[i].Index, end - keys[i].Index);
        }

        string block;
        var frequency = Match.Empty;
        if (blocks.TryGetValue("stimModulationFreqHz", out block)) frequency = ModulationFrequency.Match(block);
        if (!frequency.Success && blocks.TryGetValue("stimLocations01", out block)) frequency = ModulationFrequency.Match(block);
        if (!frequency.Success) return;
        var hz = double.Parse(frequency.Groups[1].Value, NumberStyles.Float, CultureInfo.InvariantCulture);
        var cycleMs = 1000.0 / hz;

        var problems = new List<string>();
        foreach (var pair in blocks)
        {
            if (!ConditionKey.IsMatch(pair.Key + ":")) continue;
            var ramp = RampDown.Match(pair.Value);
            if (!ramp.Success)
            {
                problems.Add(pair.Key + " has no offRampDownDuration_ms");
                continue;
            }
            var rampMs = double.Parse(ramp.Groups[1].Value, NumberStyles.Float, CultureInfo.InvariantCulture);
            if (rampMs <= cycleMs)
            {
                problems.Add(string.Format(CultureInfo.InvariantCulture,
                    "{0} ramps down over {1} ms, which is not longer than one {2} Hz cycle ({3} ms)", pair.Key, rampMs, hz, cycleMs));
            }
        }
        if (problems.Count > 0)
        {
            throw new InvalidOperationException(string.Format(
                "The Zapit stimulus config '{0}': {1}. Zapit would then leave its DAQ running after each stop, so a hardware-triggered " +
                "trial would start before its TTL. Use a ramp-down longer than one cycle (250 ms is Zapit's usual).",
                path, string.Join("; ", problems.ToArray())));
        }
    }

    private static string Describe(List<int> numbers)
    {
        var text = new StringBuilder();
        for (int i = 0; i < numbers.Count; i++)
        {
            if (i > 0) text.Append(", ");
            text.Append(numbers[i].ToString(CultureInfo.InvariantCulture));
        }
        return text.ToString();
    }
}
