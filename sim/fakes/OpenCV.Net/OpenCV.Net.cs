// SIMULATION STAND-IN for OpenCV.Net 3.4.2 (sim/fakes, built by sim/setup.sh into an assembly named OpenCV.Net).
//
// The real OpenCV.Net is a managed wrapper that P/Invokes the OpenCV 2.4.13 native Windows DLLs, which do not exist on
// macOS, so creating any real Mat fails here. The simulation only needs audio buffers to flow through the workflow with
// the right shape (rows = channels, cols = samples) and depth, so this Mat carries its shape and depth but no sample
// data. Type names, namespace and the Depth values match the real package, so XmlSerializer (TypeArguments="p5:Mat")
// and the sim Bonsai.Dsp / Bonsai.Audio stand-ins can use it in place of the real one.
using System;
using System.Reflection;

[assembly: AssemblyTitle("OpenCV.Net (simulation stand-in: shape-only Mat, no native OpenCV)")]
[assembly: AssemblyVersion("3.4.2.0")]

namespace OpenCV.Net
{
    public enum Depth
    {
        U8 = 0,
        S8 = 1,
        U16 = 2,
        S16 = 3,
        S32 = 4,
        F32 = 5,
        F64 = 6,
        UserType = 7
    }

    public struct Size : IEquatable<Size>
    {
        public int Width;
        public int Height;

        public Size(int width, int height)
        {
            Width = width;
            Height = height;
        }

        public static Size Zero
        {
            get { return new Size(0, 0); }
        }

        public bool Equals(Size other)
        {
            return Width == other.Width && Height == other.Height;
        }

        public override bool Equals(object obj)
        {
            return obj is Size && Equals((Size)obj);
        }

        public override int GetHashCode()
        {
            return Width * 397 ^ Height;
        }

        public override string ToString()
        {
            return "{Width=" + Width + ", Height=" + Height + "}";
        }
    }

    // Base of all OpenCV arrays (the real one wraps a native handle).
    public abstract class Arr : IDisposable
    {
        public abstract Size Size { get; }

        public virtual int ElementType
        {
            get { return 0; }
        }

        public void Close()
        {
            Dispose();
        }

        public virtual void Dispose()
        {
        }
    }

    // A matrix with a shape and a depth but no data: rows x cols elements of `channels` channels each.
    public class Mat : Arr
    {
        public const int AutoStep = int.MaxValue;
        readonly int rows;
        readonly int cols;
        readonly Depth depth;
        readonly int channels;

        public Mat(int rows, int cols, Depth depth, int channels)
        {
            if (rows < 0 || cols < 0) throw new ArgumentOutOfRangeException("rows", "Matrix dimensions must be non-negative.");
            if (channels < 1 || channels > 4) throw new ArgumentOutOfRangeException("channels", "OpenCV matrices have 1 to 4 channels.");
            this.rows = rows;
            this.cols = cols;
            this.depth = depth;
            this.channels = channels;
        }

        public Mat(Size size, Depth depth, int channels)
            : this(size.Height, size.Width, depth, channels)
        {
        }

        public int Rows { get { return rows; } }

        public int Cols { get { return cols; } }

        public Depth Depth { get { return depth; } }

        public int Channels { get { return channels; } }

        public int ElementSize { get { return DepthSize(depth) * channels; } }

        public int Step { get { return cols * ElementSize; } }

        public override Size Size { get { return new Size(cols, rows); } }

        // There is never any pixel data in the simulation.
        public IntPtr Data { get { return IntPtr.Zero; } }

        public Mat Clone()
        {
            return new Mat(rows, cols, depth, channels);
        }

        public static int DepthSize(Depth depth)
        {
            switch (depth)
            {
                case Depth.U8:
                case Depth.S8: return 1;
                case Depth.U16:
                case Depth.S16: return 2;
                case Depth.S32:
                case Depth.F32: return 4;
                case Depth.F64: return 8;
                default: return 1;
            }
        }

        public override string ToString()
        {
            return string.Format("Mat({0}x{1} {2}C{3}, simulated: shape only)", rows, cols, depth, channels);
        }
    }
}
