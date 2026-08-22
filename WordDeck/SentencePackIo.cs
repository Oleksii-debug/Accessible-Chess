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
        bool gzip = IsGZipPath(path) || HasGZipMagic(file);
        file.Position = 0;
        if (gzip)
        {
            using var compressed = new GZipStream(file, CompressionMode.Decompress, leaveOpen: false);
            return Read(compressed);
        }
        return Read(file);
    }

    private static bool HasGZipMagic(FileStream file)
    {
        if (file.Length < 2) return false;
        int first = file.ReadByte();
        int second = file.ReadByte();
        return first == 0x1F && second == 0x8B;
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
