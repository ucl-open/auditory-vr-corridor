using System;

/// <summary>
/// The five commands understood by the Zapit TCP server. The numeric value is the
/// command byte on the wire (byte 0 of every 16-byte request).
/// </summary>
public enum ZapitCommandType : byte
{
    StopStimulus = 0,
    StartStimulus = 1,
    IsStimConfigLoaded = 2,
    GetState = 3,
    GetNumConditions = 4
}

/// <summary>
/// The read-only queries, exposed separately so a query operator cannot start or stop a stimulus.
/// </summary>
public enum ZapitQuery : byte
{
    IsStimConfigLoaded = 2,
    GetState = 3,
    GetNumConditions = 4
}

/// <summary>
/// Zapit pointer state as reported by the GetState query (byte 9 of the reply).
/// </summary>
public enum ZapitState : byte
{
    Idle = 0,
    Stimulating = 1,
    RampDown = 2,
    Unknown = 255
}

/// <summary>
/// One request to the Zapit TCP server. Only StartStimulus carries arguments; a null argument
/// is not sent and Zapit applies its own default (see zapit.pointer.sendSamples).
/// Wire format, 16 bytes little-endian: [0] command, [1] argument-key bitmask,
/// [2] boolean-value bitmask, [3] condition number, [4..7] stimDuration (float32, seconds),
/// [8..11] laserPower (float32, mW), [12..15] startDelay (float32, seconds).
/// </summary>
public class ZapitCommand
{
    public const int MessageLength = 16;

    // Bit positions shared by the key and value bitmasks.
    private const byte ConditionNumberBit = 1;
    private const byte LaserOnBit = 2;
    private const byte HardwareTriggeredBit = 4;
    private const byte LoggingBit = 8;
    private const byte VerboseBit = 16;
    private const byte StimDurationBit = 32;
    private const byte LaserPowerBit = 64;
    private const byte StartDelayBit = 128;

    public ZapitCommandType Command { get; set; }

    /// <summary>Stimulus condition index, 1 to 254. Null lets Zapit draw a random condition.</summary>
    public int? ConditionNumber { get; set; }

    /// <summary>True fires the laser; false moves the galvos with the laser off. Zapit default: true.</summary>
    public bool? LaserOn { get; set; }

    /// <summary>True makes the DAQ wait for a TTL trigger; false stimulates on receipt. Zapit default: true.</summary>
    public bool? HardwareTriggered { get; set; }

    /// <summary>Whether Zapit writes its own trial log for this stimulus. Zapit default: true.</summary>
    public bool? Logging { get; set; }

    /// <summary>Debug printing on the Zapit side. Zapit default: false.</summary>
    public bool? Verbose { get; set; }

    /// <summary>Stimulus duration in seconds. Null or zero plays until StopStimulus.</summary>
    public float? StimDuration { get; set; }

    /// <summary>Laser power in mW. Null uses the value in the Zapit stimulus config.</summary>
    public float? LaserPower { get; set; }

    /// <summary>Delay before onset in seconds. Only honoured by Zapit when StimDuration is set.</summary>
    public float? StartDelay { get; set; }

    public static ZapitCommand Stop()
    {
        var command = new ZapitCommand();
        command.Command = ZapitCommandType.StopStimulus;
        return command;
    }

    public static ZapitCommand Query(ZapitQuery query)
    {
        var command = new ZapitCommand();
        command.Command = (ZapitCommandType)(byte)query;
        return command;
    }

    /// <summary>
    /// Serialises the command into the 16-byte request frame.
    /// </summary>
    public byte[] ToBytes()
    {
        var message = new byte[MessageLength];
        message[0] = (byte)Command;
        if (Command != ZapitCommandType.StartStimulus)
        {
            return message;
        }

        byte keys = 0;
        byte values = 0;
        if (ConditionNumber.HasValue)
        {
            var condition = ConditionNumber.Value;
            if (condition < 1 || condition > 254)
            {
                throw new ArgumentOutOfRangeException(
                    "ConditionNumber",
                    string.Format("Zapit condition numbers run from 1 to 254; got {0}.", condition));
            }
            keys = (byte)(keys | ConditionNumberBit);
            message[3] = (byte)condition;
        }
        if (LaserOn.HasValue)
        {
            keys = (byte)(keys | LaserOnBit);
            if (LaserOn.Value) values = (byte)(values | LaserOnBit);
        }
        if (HardwareTriggered.HasValue)
        {
            keys = (byte)(keys | HardwareTriggeredBit);
            if (HardwareTriggered.Value) values = (byte)(values | HardwareTriggeredBit);
        }
        if (Logging.HasValue)
        {
            keys = (byte)(keys | LoggingBit);
            if (Logging.Value) values = (byte)(values | LoggingBit);
        }
        if (Verbose.HasValue)
        {
            keys = (byte)(keys | VerboseBit);
            if (Verbose.Value) values = (byte)(values | VerboseBit);
        }
        if (StimDuration.HasValue)
        {
            keys = (byte)(keys | StimDurationBit);
            WriteSingle(message, 4, StimDuration.Value);
        }
        if (LaserPower.HasValue)
        {
            keys = (byte)(keys | LaserPowerBit);
            WriteSingle(message, 8, LaserPower.Value);
        }
        if (StartDelay.HasValue)
        {
            keys = (byte)(keys | StartDelayBit);
            WriteSingle(message, 12, StartDelay.Value);
        }
        message[1] = keys;
        message[2] = values;
        return message;
    }

    private static void WriteSingle(byte[] buffer, int offset, float value)
    {
        var bytes = BitConverter.GetBytes(value);
        if (!BitConverter.IsLittleEndian)
        {
            Array.Reverse(bytes);
        }
        Array.Copy(bytes, 0, buffer, offset, bytes.Length);
    }

    public override string ToString()
    {
        if (Command != ZapitCommandType.StartStimulus)
        {
            return Command.ToString();
        }
        return string.Format(
            "StartStimulus(condition={0}, laserOn={1}, hardwareTriggered={2}, duration={3}, power={4}, delay={5})",
            FormatArgument(ConditionNumber),
            FormatArgument(LaserOn),
            FormatArgument(HardwareTriggered),
            FormatArgument(StimDuration),
            FormatArgument(LaserPower),
            FormatArgument(StartDelay));
    }

    private static string FormatArgument(object value)
    {
        return value == null ? "default" : value.ToString();
    }
}
