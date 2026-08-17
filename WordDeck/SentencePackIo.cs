using System.IO.Compression;
using System.Text.Json;

namespace WordDeck;

internal static class SentencePackIo
{
    private static readonly JsonSerializerOptions ReadOptions = new() { PropertyNameCaseInsensitive = true };
    private static readonly JsonSerializerOptions WriteOptions = new() { WriteIndented = true };

    public static bool IsGZipPath(string path) => path.EndsWith(".gz", StringComparison.OrdinalIgnoreCase);

    public static SentencePack Read(string path)
    {
        using FileStream file = File.OpenRead(path);
        if (IsGZipPath(path))
        {
            using var gzip = new GZipStream(file, CompressionMode.Decompress, leaveOpen: false);
            return Read(gzip);
        }
        return Read(file);
    }

    public static SentencePack Read(Stream utf8Json)
    {
        SentencePack pack = JsonSerializer.Deserialize<SentencePack>(utf8Json, ReadOptions)
            ?? throw new InvalidDataException("SentencePack JSON is empty.");
        pack.Validate();
        return pack;
    }

    public static void WriteGZip(string path, SentencePack pack)
    {
        pack.Validate();
        using FileStream file = new(path, FileMode.Create, FileAccess.Write, FileShare.None);
        using var gzip = new GZipStream(file, CompressionLevel.SmallestSize, leaveOpen: false);
        JsonSerializer.Serialize(gzip, pack, WriteOptions);
    }
}
