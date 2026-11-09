// SIMULATION STAND-IN for Bonsai.Dsp 2.9 (sim/fakes, built by sim/setup.sh into an assembly named Bonsai.Dsp).
//
// The real Bonsai.Dsp does all its buffer work through OpenCV.Net, whose native OpenCV 2.4.13 DLLs are Windows-only,
// so even the scalar overloads (Difference on doubles runs an OpenCV FIR filter) fail on macOS. This assembly keeps the
// nodes main.bonsai uses with the same namespace, type names, enum types, XML properties and Process/Generate overloads,
// so the workflow deserializes and builds exactly as on the rig:
//   * Matrix nodes (MatrixReader, FunctionGenerator, Rescale, Tile, ConvertScale) pass shape-only Mats (see the
//     OpenCV.Net stand-in): right rows/cols/depth, no samples. Timing matches the real nodes: MatrixReader and
//     FunctionGenerator pace their buffers at SampleRate exactly like the real ones (checked against the IL).
//   * Scalar overloads compute real values: Rescale(double) and Difference(double) are what the task logic uses
//     (BonVision ParameterRange for ITIs/track lengths, and the running-wheel ticks -> cm conversion).
//   * MatrixWriter writes byte[] streams for real (the Harp binary logs written by UclOpen.Logging LogHarpDevice).
// Anything else from Bonsai.Dsp is missing on purpose: a workflow that uses it fails to load with a clear error.
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Reactive.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Threading.Tasks;
using System.Xml.Serialization;
using Bonsai;
using Bonsai.IO;
using OpenCV.Net;

[assembly: AssemblyTitle("Bonsai.Dsp (simulation stand-in: shape-only buffers, no native OpenCV)")]
[assembly: AssemblyVersion("2.9.0.0")]

namespace Bonsai.Dsp
{
    public enum FunctionWaveform
    {
        Sine,
        Square,
        Triangular,
        Sawtooth
    }

    public enum MatrixLayout
    {
        RowMajor,
        ColumnMajor
    }

    public enum RescaleMethod
    {
        Linear,
        Clamp
    }

    static class SimPath
    {
        // Workflows written on Windows use backslashes in relative paths (e.g. waveforms\error_tone.wav).
        public static string Normalize(string path)
        {
            if (string.IsNullOrEmpty(path) || Path.DirectorySeparatorChar == '\\') return path;
            return path.Replace('\\', '/');
        }
    }

    static class MatOps
    {
        public static TArray Cast<TArray>(Mat result)
        {
            if (!typeof(TArray).IsAssignableFrom(typeof(Mat)))
            {
                throw new NotSupportedException("The simulation Bonsai.Dsp only supports Mat buffers, not " + typeof(TArray).Name + ".");
            }
            return (TArray)(object)result;
        }

        public static Mat AsMat<TArray>(TArray input)
        {
            var mat = input as Mat;
            if (mat == null) throw new NotSupportedException("The simulation Bonsai.Dsp only supports Mat buffers.");
            return mat;
        }
    }

    [Combinator]
    [WorkflowElementCategory(ElementCategory.Transform)]
    public abstract class ArrayTransform
    {
        public abstract IObservable<TArray> Process<TArray>(IObservable<TArray> source) where TArray : Arr;
    }

    [DefaultProperty("Path")]
    [Description("Generates a sequence of signal sample buffers from the specified raw binary input stream. (SIM: shape-only buffers, paced like the real node)")]
    public class MatrixReader : Source<Mat>
    {
        public MatrixReader()
        {
            ChannelCount = 1;
            BufferLength = 441;
            Depth = Depth.U16;
            Layout = MatrixLayout.ColumnMajor;
        }

        [Description("The name of the raw binary file.")]
        public string Path { get; set; }

        [Browsable(false)]
        [Obsolete]
        public string FileName
        {
            get { return Path; }
            set { Path = value; }
        }

        [Description("The byte offset at which to start reading the raw binary file.")]
        public long Offset { get; set; }

        [Description("The sample rate of the signal, in Hz. If positive, buffers are emitted at this rate.")]
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
        [XmlIgnore]
        public bool FrequencySpecified
        {
            get { return false; }
        }

        [Description("The number of channels in the signal.")]
        public int ChannelCount { get; set; }

        [Description("The number of samples in each buffer (0 = the whole file in one buffer).")]
        public int BufferLength { get; set; }

        [Description("The bit depth of individual samples.")]
        public Depth Depth { get; set; }

        [Description("The sequential memory layout of the samples in the file.")]
        public MatrixLayout Layout { get; set; }

        IEnumerable<Mat> CreateReader()
        {
            var path = SimPath.Normalize(Path);
            if (string.IsNullOrEmpty(path)) throw new InvalidOperationException("A valid path must be specified.");
            var length = new FileInfo(path).Length;   // throws FileNotFoundException like the real node
            var depth = Depth;
            var channelCount = ChannelCount;
            var depthSize = Mat.DepthSize(depth);
            var offset = Offset;
            var bufferLength = BufferLength;
            if (bufferLength == 0) bufferLength = (int)((length - offset) / depthSize / channelCount);
            var bufferBytes = (long)bufferLength * channelCount * depthSize;
            if (bufferBytes <= 0) yield break;
            // the real reader stops at the first partial buffer
            for (var position = Math.Max(0, offset); position + bufferBytes <= length; position += bufferBytes)
            {
                yield return new Mat(channelCount, bufferLength, depth, 1);
            }
        }

        public override IObservable<Mat> Generate()
        {
            return Observable.Create<Mat>((observer, cancellationToken) =>
            {
                return Task.Factory.StartNew(() =>
                {
                    using (var reader = CreateReader().GetEnumerator())
                    using (var sampleSignal = new ManualResetEvent(false))
                    {
                        var stopwatch = new Stopwatch();
                        while (!cancellationToken.IsCancellationRequested)
                        {
                            stopwatch.Restart();
                            if (!reader.MoveNext()) break;
                            observer.OnNext(reader.Current);
                            var sampleRate = SampleRate;
                            var sampleInterval = sampleRate > 0 ? 1000.0 / sampleRate : 0.0;
                            var dueTime = Math.Max(0.0, sampleInterval * BufferLength - stopwatch.Elapsed.TotalMilliseconds);
                            if (dueTime > 0) sampleSignal.WaitOne(TimeSpan.FromMilliseconds(dueTime));
                        }
                        observer.OnCompleted();
                    }
                }, cancellationToken, TaskCreationOptions.LongRunning, TaskScheduler.Default);
            });
        }

        public IObservable<Mat> Generate<TSource>(IObservable<TSource> source)
        {
            return Observable.Defer(() => source.Zip(CreateReader(), (x, buffer) => buffer));
        }
    }

    [Description("Generates signal waveforms following any of a set of common periodic functions. (SIM: shape-only buffers, paced like the real node)")]
    public class FunctionGenerator : Source<Mat>
    {
        public FunctionGenerator()
        {
            BufferLength = 441;
            Frequency = 100;
            SampleRate = 44100;
            Amplitude = 1;
        }

        [Description("The number of samples in each output buffer.")]
        public int BufferLength { get; set; }

        [Description("The frequency of the signal waveform, in Hz.")]
        public double Frequency { get; set; }

        [Description("The periodic waveform used to sample the signal.")]
        public FunctionWaveform Waveform { get; set; }

        [Description("The sample rate of the generated signal waveform, in Hz.")]
        public int SampleRate { get; set; }

        [Browsable(false)]
        [Obsolete]
        public int? PlaybackRate
        {
            get { return null; }
            set { if (value.HasValue) SampleRate = value.Value; }
        }

        [Browsable(false)]
        [Obsolete]
        [XmlIgnore]
        public bool PlaybackRateSpecified
        {
            get { return false; }
        }

        [Description("The optional bit depth of each element in the output buffer.")]
        public Depth? Depth { get; set; }

        [Browsable(false)]
        [XmlIgnore]
        public bool DepthSpecified
        {
            get { return Depth.HasValue; }
        }

        [Description("The amplitude of the signal waveform.")]
        public double Amplitude { get; set; }

        [Description("The optional DC-offset of the signal waveform.")]
        public double Offset { get; set; }

        [Description("The optional phase offset, in radians, of the signal waveform.")]
        public double Phase { get; set; }

        Mat CreateBuffer()
        {
            return new Mat(1, BufferLength, Depth.GetValueOrDefault(OpenCV.Net.Depth.F64), 1);
        }

        public override IObservable<Mat> Generate()
        {
            return Observable.Create<Mat>((observer, cancellationToken) =>
            {
                return Task.Factory.StartNew(() =>
                {
                    var bufferLength = BufferLength;
                    if (bufferLength <= 0) throw new InvalidOperationException("Buffer length must be a positive integer.");
                    var sampleRate = SampleRate;
                    if (sampleRate <= 0) throw new InvalidOperationException("Sample rate must be a positive integer.");
                    long counter = 0;
                    using (var sampleSignal = new ManualResetEvent(false))
                    {
                        var stopwatch = Stopwatch.StartNew();
                        var bufferInterval = 1000.0 / ((double)sampleRate / bufferLength);
                        while (!cancellationToken.IsCancellationRequested)
                        {
                            counter++;
                            observer.OnNext(CreateBuffer());
                            var waitMs = (int)(bufferInterval * counter - stopwatch.ElapsedMilliseconds);
                            if (waitMs > 0) sampleSignal.WaitOne(waitMs);
                        }
                    }
                }, cancellationToken, TaskCreationOptions.LongRunning, TaskScheduler.Default);
            });
        }

        public IObservable<Mat> Generate<TSource>(IObservable<TSource> source)
        {
            return source.Select(x => CreateBuffer());
        }
    }

    [Description("Rescales each element in the sequence to a new range following the specified linear relationship. (SIM: real values for doubles, shape-only for buffers)")]
    public class Rescale : ArrayTransform
    {
        public Rescale()
        {
            Max = 1;
            RangeMax = 1;
        }

        [Description("The lower bound of the range of values in the input sequence.")]
        public double Min { get; set; }

        [Description("The upper bound of the range of values in the input sequence.")]
        public double Max { get; set; }

        [Description("The lower bound of the range of values after the rescale operation.")]
        public double RangeMin { get; set; }

        [Description("The upper bound of the range of values after the rescale operation.")]
        public double RangeMax { get; set; }

        [Description("The method used to rescale values in the input sequence.")]
        public RescaleMethod RescaleType { get; set; }

        // Same arithmetic as the real node: scale = (rangeMax - rangeMin) / (max - min), shift = -min * scale + rangeMin,
        // properties read for every element (so property mappings apply immediately)
        public IObservable<double> Process(IObservable<double> source)
        {
            return source.Select(input =>
            {
                var rangeMin = RangeMin;
                var rangeMax = RangeMax;
                var scale = (rangeMax - rangeMin) / (Max - Min);
                var shift = -Min * scale + rangeMin;
                var output = input * scale + shift;
                if (RescaleType == RescaleMethod.Clamp)
                {
                    output = Math.Max(Math.Min(output, Math.Max(rangeMin, rangeMax)), Math.Min(rangeMin, rangeMax));
                }
                return output;
            });
        }

        // The real node converts the buffer to F32 (CV.ConvertScale into an F32 output)
        public override IObservable<TArray> Process<TArray>(IObservable<TArray> source)
        {
            return source.Select(input =>
            {
                var mat = MatOps.AsMat(input);
                return MatOps.Cast<TArray>(new Mat(mat.Rows, mat.Cols, OpenCV.Net.Depth.F32, mat.Channels));
            });
        }
    }

    [Description("Replicates each array in the sequence along the horizontal or vertical dimensions. (SIM: shape-only)")]
    public class Tile : ArrayTransform
    {
        public Tile()
        {
            RowTiles = 1;
            ColumnTiles = 1;
        }

        [Description("The number of times to replicate the array along the vertical dimension.")]
        public int RowTiles { get; set; }

        [Description("The number of times to replicate the array along the horizontal dimension.")]
        public int ColumnTiles { get; set; }

        public override IObservable<TArray> Process<TArray>(IObservable<TArray> source)
        {
            return source.Select(input =>
            {
                var mat = MatOps.AsMat(input);
                return MatOps.Cast<TArray>(new Mat(mat.Rows * RowTiles, mat.Cols * ColumnTiles, mat.Depth, mat.Channels));
            });
        }
    }

    [Description("Converts each array in the sequence to the specified bit depth, with optional linear transformation. (SIM: shape-only)")]
    public class ConvertScale : ArrayTransform
    {
        public ConvertScale()
        {
            Scale = 1;
        }

        [Description("The optional bit depth of each element in the output array.")]
        public Depth? Depth { get; set; }

        [Browsable(false)]
        [XmlIgnore]
        public bool DepthSpecified
        {
            get { return Depth.HasValue; }
        }

        [Description("The scale factor applied to each element of the array.")]
        public double Scale { get; set; }

        [Description("The value added to each element of the array after scaling.")]
        public double Shift { get; set; }

        public override IObservable<TArray> Process<TArray>(IObservable<TArray> source)
        {
            return source.Select(input =>
            {
                var mat = MatOps.AsMat(input);
                return MatOps.Cast<TArray>(new Mat(mat.Rows, mat.Cols, Depth.GetValueOrDefault(mat.Depth), mat.Channels));
            });
        }
    }

    [Description("Calculates the Nth difference between adjacent samples in the input signal. (SIM: real values for doubles)")]
    public class Difference : Transform<Mat, Mat>
    {
        public Difference()
        {
            Order = 1;
        }

        [Description("The order of the difference (1 = first difference).")]
        public int Order { get; set; }

        public override IObservable<Mat> Process(IObservable<Mat> source)
        {
            return source.Select(input => input.Clone());
        }

        // FIR difference with binomial kernel and zero initial history (the real node runs the same kernel through an
        // OpenCV FIR filter): order 1 -> x[n] - x[n-1].
        public IObservable<double> Process(IObservable<double> source)
        {
            return Observable.Defer(() =>
            {
                var order = Math.Max(1, Order);
                var history = new double[order];
                var kernel = new double[order + 1];   // coefficients for x[n-k], k = 0..order
                for (int k = 0; k <= order; k++)
                {
                    kernel[k] = Binomial(order, k) * (k % 2 == 0 ? 1 : -1);
                }
                return source.Select(input =>
                {
                    var output = kernel[0] * input;
                    for (int k = 1; k <= order; k++) output += kernel[k] * history[k - 1];
                    for (int k = order - 1; k > 0; k--) history[k] = history[k - 1];
                    history[0] = input;
                    return output;
                });
            });
        }

        static long Binomial(int n, int k)
        {
            long result = 1;
            for (int i = 1; i <= k; i++) result = result * (n - k + i) / i;
            return result;
        }
    }

    [Description("Writes each array-like object in the sequence to a raw binary output stream. (SIM: byte arrays are written for real)")]
    public class MatrixWriter : StreamSink<ArraySegment<byte>, BinaryWriter>
    {
        [Description("The sequential memory layout used to store the sample buffers.")]
        public MatrixLayout Layout { get; set; }

        protected override BinaryWriter CreateWriter(Stream stream)
        {
            return new BinaryWriter(stream);
        }

        protected override void Write(BinaryWriter writer, ArraySegment<byte> input)
        {
            writer.Write(input.Array, input.Offset, input.Count);
        }

        public IObservable<byte[]> Process(IObservable<byte[]> source)
        {
            return Process(source, input => new ArraySegment<byte>(input));
        }

        public IObservable<TElement[]> Process<TElement>(IObservable<TElement[]> source) where TElement : struct
        {
            return Process(source, input =>
            {
                var bytes = new byte[Buffer.ByteLength(input)];
                Buffer.BlockCopy(input, 0, bytes, 0, bytes.Length);
                return new ArraySegment<byte>(bytes);
            });
        }

        public IObservable<TElement> Process<TElement>(IObservable<TElement> source) where TElement : struct
        {
            return Process(source, input =>
            {
                var size = Marshal.SizeOf(typeof(TElement));
                var bytes = new byte[size];
                var handle = GCHandle.Alloc(bytes, GCHandleType.Pinned);
                try { Marshal.StructureToPtr(input, handle.AddrOfPinnedObject(), false); }
                finally { handle.Free(); }
                return new ArraySegment<byte>(bytes);
            });
        }

        // Shape-only buffers have no samples: write zeros of the right size so file sizes stay realistic.
        public IObservable<Mat> Process(IObservable<Mat> source)
        {
            return Process(source, input => new ArraySegment<byte>(new byte[(long)input.Rows * input.Cols * input.ElementSize]));
        }
    }
}
