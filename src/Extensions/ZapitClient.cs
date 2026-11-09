using Bonsai;
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Net.Sockets;
using System.Reactive.Linq;

// This copy differs from av-dome's ZapitClient.cs in one way: when the connection closes (the workflow stops, or the
// session ends with an error) it first sends Zapit a StopStimulus. This task only sends continuous stimuli, which Zapit
// plays until it is told to stop, so a session stopped mid-trial would otherwise leave the laser or the sham stimulus
// (galvos and masking light) running after Bonsai has gone. The stop is best effort: it waits about a second for Zapit's
// reply, ignores any error (Zapit closed or unreachable), and then closes the socket as before. No command is sent after it.
[Combinator]
[Description("TCP client for the Zapit optogenetics server. Connects when the workflow starts and disconnects when it stops; each ZapitCommand is written as a 16-byte request and the 15-byte reply is returned as a ZapitReply. Requests are serialised on a dedicated thread so trial logic never blocks on the socket. Before disconnecting it sends Zapit a StopStimulus, so a continuous stimulus never outlives the workflow.")]
[WorkflowElementCategory(ElementCategory.Transform)]
public class ZapitClient
{
    public ZapitClient()
    {
        Host = "127.0.0.1";
        Port = 1488;
        ReceiveTimeout = 5000;
    }

    [Description("Host name or IP address of the PC running Zapit. Use 127.0.0.1 when Zapit runs on this rig PC.")]
    public string Host { get; set; }

    [Description("TCP port of the Zapit server: tcpServer.port in the Zapit settings file, 1488 by default.")]
    public int Port { get; set; }

    [Description("Milliseconds to wait for a reply before failing. Zapit answers StartStimulus only after the waveforms are written to the DAQ.")]
    public int ReceiveTimeout { get; set; }

    public IObservable<ZapitReply> Process(IObservable<ZapitCommand> source)
    {
        // Each command becomes a deferred background call; Concat runs them one at a time in
        // arrival order. The socket sees strict request/reply.
        // No scheduler object to dispose, so an error tears down cleanly through Using.
        return Observable.Using(
            () => new ZapitConnection(Host, Port, ReceiveTimeout),
            connection => source
                .Select(command => Observable.Defer(() => Observable.Start(() => connection.SendReceive(command))))
                .Concat());
    }

    /// <summary>
    /// Owns the socket for the lifetime of one subscription.
    /// </summary>
    private class ZapitConnection : IDisposable
    {
        // How long Dispose waits for Zapit to answer the final StopStimulus.
        private const int StopReplyTimeout = 1000;

        private readonly TcpClient client;
        private readonly NetworkStream stream;
        private readonly object gate = new object();
        private readonly string endpoint;
        private bool disposed;

        public ZapitConnection(string host, int port, int receiveTimeout)
        {
            endpoint = string.Format("{0}:{1}", host, port);
            client = new TcpClient();
            try
            {
                client.Connect(host, port);
            }
            catch (SocketException ex)
            {
                client.Close();
                throw new InvalidOperationException(string.Format(
                    "Could not connect to Zapit at {0}. Is Zapit running with tcpServer.enable set to true in its settings file? ({1})",
                    endpoint, ex.Message), ex);
            }
            client.NoDelay = true;
            client.ReceiveTimeout = receiveTimeout;
            stream = client.GetStream();
        }

        public ZapitReply SendReceive(ZapitCommand command)
        {
            var request = command.ToBytes();
            var response = new byte[ZapitReply.MessageLength];
            lock (gate)
            {
                if (disposed)
                {
                    // A request queued just before the workflow stopped: the final StopStimulus has been sent already.
                    throw new ObjectDisposedException(string.Format("Zapit connection to {0}", endpoint));
                }
                try
                {
                    stream.Write(request, 0, request.Length);
                    var read = 0;
                    while (read < response.Length)
                    {
                        var count = stream.Read(response, read, response.Length - read);
                        if (count <= 0)
                        {
                            throw new IOException("Zapit closed the connection.");
                        }
                        read += count;
                    }
                }
                catch (IOException ex)
                {
                    throw new IOException(string.Format(
                        "Zapit at {0} did not answer {1}: {2}", endpoint, command, ex.Message), ex);
                }
            }
            var reply = ZapitReply.Parse(response);
            if (reply.Command != command.Command)
            {
                // The server always echoes the command byte; anything else means the stream is out of step.
                throw new InvalidOperationException(string.Format(
                    "Zapit at {0} is out of synch. It answered {1} while {2} was pending; closing the connection.",
                    endpoint, reply.Command, command.Command));
            }
            return reply;
        }

        public void Dispose()
        {
            // Taking the gate waits for a request in flight (at most ReceiveTimeout), so the StopStimulus is the last
            // command Zapit receives on this connection.
            lock (gate)
            {
                if (disposed) return;
                disposed = true;
                TryStopStimulus();
                stream.Dispose();
                client.Close();
            }
        }

        // Best effort: send StopStimulus and wait up to StopReplyTimeout for the 15-byte reply. Errors are ignored,
        // because the connection is closing anyway and Zapit may already be gone.
        private void TryStopStimulus()
        {
            try
            {
                var deadline = Stopwatch.StartNew();
                client.SendTimeout = StopReplyTimeout;
                var request = ZapitCommand.Stop().ToBytes();
                stream.Write(request, 0, request.Length);

                var response = new byte[ZapitReply.MessageLength];
                var read = 0;
                while (read < response.Length)
                {
                    var remaining = StopReplyTimeout - (int)deadline.ElapsedMilliseconds;
                    if (remaining <= 0) break;
                    client.ReceiveTimeout = remaining;
                    var count = stream.Read(response, read, response.Length - read);
                    if (count <= 0) break;
                    read += count;
                }
            }
            catch (Exception)
            {
                // Zapit closed, unreachable or slow: nothing more can be done from here.
            }
        }
    }
}
