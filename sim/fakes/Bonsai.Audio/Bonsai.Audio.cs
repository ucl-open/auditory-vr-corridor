// SIMULATION STAND-IN for Bonsai.Audio 2.9 (sim/fakes, built by sim/setup.sh into an assembly named Bonsai.Audio).
//
// The real Bonsai.Audio plays through OpenAL (Windows openal.redist) and returns OpenCV Mats (native, Windows-only).
// main.bonsai uses AudioReader to load the error tone once at startup, and has AudioPlayback in disabled nodes (which
// must still deserialize). This assembly keeps both with the same namespace, type names, enum type (OpenTK's
// ALSourceState) and XML properties:
//   * AudioReader reads the RIFF/WAV header for real (channels, sample rate, bit depth, length) and emits shape-only Mats
//     (rows = channels, cols = samples); a missing file fails like the real node.
//   * AudioPlayback passes buffers through without playing anything.
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.IO;
using System.Reactive.Linq;
using System.Reflection;
using System.Text;
using Bonsai;
using OpenCV.Net;
using OpenTK.Audio.OpenAL;

[assembly: AssemblyTitle("Bonsai.Audio (simulation stand-in: no audio device, shape-only buffers)")]
[assembly: AssemblyVersion("2.9.0.0")]

namespace Bonsai.Audio
{
    [DefaultProperty("FileName")]
    [Description("Generates a sequence of buffered audio samples from an uncompressed RIFF/WAV file. (SIM: header read for real, shape-only buffers)")]
    public class AudioReader : Source<Mat>
    {
        [Description("The name of the WAV file.")]
        public string FileName { get; set; }

        [Description("The length of the sample buffer, in milliseconds (0 = the whole file in one buffer).")]
        public double BufferLength { get; set; }

        [Description("The sample rate used for playback (0 = the file's own sample rate).")]
        public int SampleRate { get; set; }

        internal struct WaveInfo
        {
            public int Channels;
            public int SampleRate;
            public int BitsPerSample;
            public long DataBytes;
        }

        internal static WaveInfo ReadHeader(string fileName)
        {
            using (var reader = new BinaryReader(File.OpenRead(fileName)))
            {
                if (Encoding.ASCII.GetString(reader.ReadBytes(4)) != "RIFF") throw new InvalidOperationException("Not a RIFF file: " + fileName);
                reader.ReadInt32();
                if (Encoding.ASCII.GetString(reader.ReadBytes(4)) != "WAVE") throw new InvalidOperationException("Not a WAVE file: " + fileName);
                var info = new WaveInfo();
                var stream = reader.BaseStream;
                while (stream.Position + 8 <= stream.Length)
                {
                    var id = Encoding.ASCII.GetString(reader.ReadBytes(4));
                    var size = reader.ReadUInt32();
                    if (id == "fmt ")
                    {
                        reader.ReadInt16();                       // format tag
                        info.Channels = reader.ReadInt16();
                        info.SampleRate = reader.ReadInt32();
                        reader.ReadInt32();                       // byte rate
                        reader.ReadInt16();                       // block align
                        info.BitsPerSample = reader.ReadInt16();
                        stream.Position += size - 16;
                    }
                    else if (id == "data")
                    {
                        info.DataBytes = Math.Min(size, stream.Length - stream.Position);
                        return info;
                    }
                    else stream.Position += size + (size & 1);
                }
                throw new InvalidOperationException("No data chunk in WAV file: " + fileName);
            }
        }

        IEnumerable<Mat> CreateReader()
        {
            var fileName = FileName ?? string.Empty;
            if (Path.DirectorySeparatorChar != '\\') fileName = fileName.Replace('\\', '/');
            var info = ReadHeader(fileName);                      // FileNotFoundException like the real node
            var depth = info.BitsPerSample == 8 ? Depth.U8 : info.BitsPerSample == 32 ? Depth.F32 : Depth.S16;
            var bytesPerFrame = Math.Max(1, info.Channels * info.BitsPerSample / 8);
            var totalSamples = info.DataBytes / bytesPerFrame;
            var sampleRate = SampleRate > 0 ? SampleRate : info.SampleRate;
            var bufferSamples = BufferLength > 0 ? (long)(BufferLength * sampleRate / 1000.0) : totalSamples;
            if (bufferSamples <= 0) yield break;
            for (long position = 0; position + bufferSamples <= totalSamples; position += bufferSamples)
            {
                yield return new Mat(info.Channels, (int)bufferSamples, depth, 1);
            }
        }

        public override IObservable<Mat> Generate()
        {
            return Observable.Defer(() => CreateReader().ToObservable());
        }

        public IObservable<Mat> Generate<TSource>(IObservable<TSource> source)
        {
            return Observable.Defer(() => source.Zip(CreateReader(), (x, buffer) => buffer));
        }
    }

    [Description("Plays the sequence of buffered samples to the specified audio device. (SIM: nothing is played; buffers pass through)")]
    public class AudioPlayback : Sink<Mat>
    {
        public AudioPlayback()
        {
            SampleRate = 44100;
        }

        [Description("The name of the audio device used for playback.")]
        public string DeviceName { get; set; }

        [Description("The name of the audio source used for playback.")]
        public string SourceName { get; set; }

        [Description("The sample rate, in Hz, used to playback the sound buffers.")]
        public int SampleRate { get; set; }

        [Browsable(false)]
        [Obsolete]
        public int? Frequency
        {
            get { return null; }
            set { if (value.HasValue) SampleRate = value.Value; }
        }

        [Browsable(false)]
        [Obsolete]
        [System.Xml.Serialization.XmlIgnore]
        public bool FrequencySpecified
        {
            get { return false; }
        }

        [Description("The optional state of the audio source after the buffers are queued.")]
        public ALSourceState? State { get; set; }

        public override IObservable<Mat> Process(IObservable<Mat> source)
        {
            return source;
        }
    }
}
