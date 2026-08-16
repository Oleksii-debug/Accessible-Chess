using System.IO.Compression;
using System.Reflection;
using System.Text;

namespace WordDeck;

internal static class DictionaryLoader
{
    public static DictionaryPackage LoadEmbeddedOxford()
    {
        Assembly assembly = Assembly.GetExecutingAssembly();
        string? resourceName = assembly.GetManifestResourceNames()
            .FirstOrDefault(name => name.EndsWith("oxford3000_uk.tsv.gz", StringComparison.OrdinalIgnoreCase));

        if (resourceName is null)
            throw new InvalidOperationException("Embedded Oxford 3000 dictionary was not found.");

        using Stream stream = assembly.GetManifestResourceStream(resourceName)
            ?? throw new InvalidOperationException("Unable to open embedded Oxford 3000 dictionary.");
        using var gzip = new GZipStream(stream, CompressionMode.Decompress);
        using var reader = new StreamReader(gzip, Encoding.UTF8, true);
        return Parse(reader.ReadToEnd());
    }

    public static DictionaryPackage LoadFromFile(string path) => Parse(File.ReadAllText(path, Encoding.UTF8));

    public static DictionaryPackage Parse(string text)
    {
        var metadata = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        var entries = new List<DictionaryEntry>();

        using var reader = new StringReader(text);
        string? line;
        bool headerSeen = false;
        while ((line = reader.ReadLine()) is not null)
        {
            if (string.IsNullOrWhiteSpace(line))
                continue;

            if (line.StartsWith('#'))
            {
                int equals = line.IndexOf('=');
                if (equals > 1)
                    metadata[line[1..equals].Trim()] = line[(equals + 1)..].Trim();
                continue;
            }

            string[] parts = line.Split('\t');
            if (!headerSeen && parts.Length >= 4 && parts[0].Equals("entryId", StringComparison.OrdinalIgnoreCase))
            {
                headerSeen = true;
                continue;
            }

            if (parts.Length < 4)
                continue;

            string source = parts[2].Trim();
            string target = string.Join("\t", parts.Skip(3)).Trim();
            if (source.Length == 0 || target.Length == 0)
                continue;

            entries.Add(new DictionaryEntry(parts[0].Trim(), parts[1].Trim(), source, target));
        }

        if (entries.Count == 0)
            throw new InvalidDataException("Dictionary contains no usable entries.");

        return new DictionaryPackage
        {
            Id = metadata.GetValueOrDefault("id", "imported-dictionary"),
            Name = metadata.GetValueOrDefault("name", "Imported dictionary"),
            SourceLanguage = metadata.GetValueOrDefault("sourceLanguage", "en"),
            TargetLanguage = metadata.GetValueOrDefault("targetLanguage", "uk"),
            Entries = entries
        };
    }
}
