using Bonsai;
using System;
using System.ComponentModel;
using System.IO;
using System.Net.Sockets;
using System.Reactive.Linq;

[Combinator]
[Description("TCP client for the Zapit optogenetics server. Connects when the workflow starts and disconnects when it stops; each ZapitCommand is written as a 16-byte request and the 15-byte reply is returned as a ZapitReply. Requests are serialised on a dedicated thread so trial logic never blocks on the socket.")]
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
        private readonly TcpClient client;
        private readonly NetworkStream stream;
        private readonly object gate = new object();
        private readonly string endpoint;

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
            lock (gate)
            {
                stream.Dispose();
                client.Close();
            }
        }
    }
}
