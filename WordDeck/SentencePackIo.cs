using System.IO.Compression;
using System.Text.Json;

namespace WordDeck;

internal static class SentencePackIo
{
    internal const long MaxPortableFileBytes = 512L * 1024 * 1024;
    internal const long MaxDecompressedJsonBytes = 768L * 1024 * 1024;

    private static readonly JsonSerializerOptions ReadOptions = new() { PropertyNameCaseInsensitive = true };
    private static readonly JsonSerializerOptions WriteOptions = new() { WriteIndented = true };

    public static bool IsGZipPath(string path) => path.EndsWith(".gz", StringComparison.OrdinalIgnoreCase);

    public static SentencePack Read(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
            throw new ArgumentException("SentencePack path is required.", nameof(path));
        string fullPath = Path.GetFullPath(path);
        FileInfo info = new(fullPath);
        if (!info.Exists)
            throw new FileNotFoundException("SentencePack file was not found.", fullPath);
        if (info.Length <= 0)
            throw new InvalidDataException("SentencePack file is empty.");
        if (info.Length > MaxPortableFileBytes)
            throw new InvalidDataException($"SentencePack file exceeds the {MaxPortableFileBytes / (1024 * 1024)} MiB import limit.");

        using FileStream file = new(fullPath, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (IsGZipPath(fullPath))
        {
            using var gzip = new GZipStream(file, CompressionMode.Decompress, leaveOpen: false);
            using var limited = new LimitedReadStream(gzip, MaxDecompressedJsonBytes);
            return ReadCore(limited);
        }

        using var plainLimited = new LimitedReadStream(file, MaxDecompressedJsonBytes);
        return ReadCore(plainLimited);
    }

    public static SentencePack Read(Stream utf8Json)
    {
        ArgumentNullException.ThrowIfNull(utf8Json);
        using var limited = new LimitedReadStream(utf8Json, MaxDecompressedJsonBytes, leaveOpen: true);
        return ReadCore(limited);
    }

    private static SentencePack ReadCore(Stream utf8Json)
    {
        try
        {
            SentencePack pack = JsonSerializer.Deserialize<SentencePack>(utf8Json, ReadOptions)
                ?? throw new InvalidDataException("SentencePack JSON is empty.");
            SentencePackStructuralLimits.Validate(pack);
            return pack;
        }
        catch (JsonException ex)
        {
            throw new InvalidDataException("SentencePack JSON is malformed or exceeds supported structural limits.", ex);
        }
    }

    public static void WriteGZip(string path, SentencePack pack)
    {
        SentencePackStructuralLimits.Validate(pack);
        string fullPath = Path.GetFullPath(path);
        string? directory = Path.GetDirectoryName(fullPath);
        if (!string.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);
        using FileStream file = new(fullPath, FileMode.Create, FileAccess.Write, FileShare.None);
        using var gzip = new GZipStream(file, CompressionLevel.SmallestSize, leaveOpen: false);
        JsonSerializer.Serialize(gzip, pack, WriteOptions);
    }

    private sealed class LimitedReadStream : Stream
    {
        private readonly Stream _inner;
        private readonly long _limit;
        private readonly bool _leaveOpen;
        private long _read;

        public LimitedReadStream(Stream inner, long limit, bool leaveOpen = false)
        {
            _inner = inner ?? throw new ArgumentNullException(nameof(inner));
            if (limit <= 0) throw new ArgumentOutOfRangeException(nameof(limit));
            _limit = limit;
            _leaveOpen = leaveOpen;
        }

        public override bool CanRead => _inner.CanRead;
        public override bool CanSeek => false;
        public override bool CanWrite => false;
        public override long Length => throw new NotSupportedException();
        public override long Position { get => _read; set => throw new NotSupportedException(); }

        public override int Read(byte[] buffer, int offset, int count)
        {
            int allowed = AllowedCount(count);
            int actual = _inner.Read(buffer, offset, allowed);
            Account(actual);
            return actual;
        }

        public override int Read(Span<byte> buffer)
        {
            int allowed = AllowedCount(buffer.Length);
            int actual = _inner.Read(buffer[..allowed]);
            Account(actual);
            return actual;
        }

        public override async ValueTask<int> ReadAsync(Memory<byte> buffer, CancellationToken cancellationToken = default)
        {
            int allowed = AllowedCount(buffer.Length);
            int actual = await _inner.ReadAsync(buffer[..allowed], cancellationToken).ConfigureAwait(false);
            Account(actual);
            return actual;
        }

        private int AllowedCount(int requested)
        {
            long remaining = _limit - _read;
            if (remaining <= 0)
            {
                int probe = _inner.ReadByte();
                if (probe >= 0)
                    throw new InvalidDataException($"SentencePack decompressed JSON exceeds the {_limit / (1024 * 1024)} MiB import limit.");
                return 0;
            }
            return (int)Math.Min(requested, remaining);
        }

        private void Account(int count)
        {
            _read += count;
            if (_read > _limit)
                throw new InvalidDataException($"SentencePack decompressed JSON exceeds the {_limit / (1024 * 1024)} MiB import limit.");
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing && !_leaveOpen)
                _inner.Dispose();
            base.Dispose(disposing);
        }

        public override void Flush() => throw new NotSupportedException();
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
    }
}
