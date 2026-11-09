using System;

/// <summary>
/// One 15-byte reply from the Zapit TCP server, parsed into fields.
/// Wire format: [0..7] MATLAB datenum of the reply as a double (1 or -1 are connection
/// status codes rather than times), [8] echo of the command byte, [9] result
/// (presented condition for StartStimulus, otherwise the query result),
/// [10] laser state for StartStimulus, [11..14] unused. 255 in a result byte means error.
/// </summary>
public class ZapitReply
{
    public const int MessageLength = 15;
    private const byte ErrorSentinel = 255;

    // datenum(1899,12,30): the offset between MATLAB datenum and OLE Automation dates.
    private const double OleAutomationEpochDatenum = 693960.0;

    /// <summary>The raw MATLAB datenum from the reply, kept for logging.</summary>
    public double ServerDatenum { get; set; }

    /// <summary>The Zapit PC clock at the time of the reply, or null when the datenum was a status code.</summary>
    public DateTime? ServerTime { get; set; }

    /// <summary>The command this reply answers, echoed by the server.</summary>
    public ZapitCommandType Command { get; set; }

    /// <summary>The command as its wire byte, for CSV logging without enum names.</summary>
    public int CommandCode
    {
        get { return (int)Command; }
    }

    /// <summary>
    /// Presented condition number for StartStimulus; loaded flag, state code or condition
    /// count for the queries; 1 for StopStimulus. 255 when the server reported an error.
    /// </summary>
    public int Value { get; set; }

    /// <summary>1 if the laser was on for a StartStimulus reply, 0 if off, 255 otherwise.</summary>
    public int LaserOn { get; set; }

    /// <summary>True when the server flagged the request as failed.</summary>
    public bool IsError { get; set; }

    /// <summary>The Zapit state for GetState replies; Unknown for everything else.</summary>
    public ZapitState State
    {
        get
        {
            if (Command != ZapitCommandType.GetState || Value > 2) return ZapitState.Unknown;
            return (ZapitState)(byte)Value;
        }
    }

    public static ZapitReply Parse(byte[] buffer)
    {
        if (buffer == null || buffer.Length < MessageLength)
        {
            throw new ArgumentException(
                string.Format("Zapit reply must be {0} bytes.", MessageLength), "buffer");
        }

        var reply = new ZapitReply();
        var datenumBytes = new byte[8];
        Array.Copy(buffer, 0, datenumBytes, 0, 8);
        if (!BitConverter.IsLittleEndian)
        {
            Array.Reverse(datenumBytes);
        }
        reply.ServerDatenum = BitConverter.ToDouble(datenumBytes, 0);
        reply.Command = (ZapitCommandType)buffer[8];
        reply.Value = buffer[9];
        reply.LaserOn = buffer[10];

        // A datenum below the OLE epoch is a status code (1 connected, -1 error), not a time.
        if (reply.ServerDatenum > OleAutomationEpochDatenum)
        {
            reply.ServerTime = DateTime.FromOADate(reply.ServerDatenum - OleAutomationEpochDatenum);
        }
        reply.IsError = reply.ServerDatenum < 0 || reply.Value == ErrorSentinel;
        return reply;
    }

    public override string ToString()
    {
        return string.Format(
            "ZapitReply({0}, value={1}, laserOn={2}, error={3}, serverTime={4})",
            Command, Value, LaserOn, IsError,
            ServerTime.HasValue ? ServerTime.Value.ToString("HH:mm:ss.fff") : "n/a");
    }
}
