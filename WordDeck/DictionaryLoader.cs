using System.IO.Compression;
using System.Reflection;
using System.Text;

namespace WordDeck;

internal static class DictionaryLoader
{
    public static DictionaryPackage LoadEmbeddedOxford()
    {
        Assembly assembly = Assembly.GetExecutingAssembly();
        string[] resourceNames = assembly.GetManifestResourceNames()
            .Where(name => name.Contains("oxford3000_uk.tsv.gz.b64part", StringComparison.OrdinalIgnoreCase))
            .OrderBy(name => name, StringComparer.OrdinalIgnoreCase)
            .ToArray();

        if (resourceNames.Length == 0)
            throw new InvalidOperationException("Embedded Oxford 3000 dictionary was not found.");

        var base64 = new StringBuilder();
        foreach (string resourceName in resourceNames)
        {
            using Stream stream = assembly.GetManifestResourceStream(resourceName)
                ?? throw new InvalidOperationException($"Unable to open embedded dictionary resource: {resourceName}.");
            using var reader = new StreamReader(stream, Encoding.ASCII, false);
            base64.Append(reader.ReadToEnd().Trim());
        }

        byte[] compressed = Convert.FromBase64String(base64.ToString());
        using var memory = new MemoryStream(compressed);
        using var gzip = new GZipStream(memory, CompressionMode.Decompress);
        using var dictionaryReader = new StreamReader(gzip, Encoding.UTF8, true);
        return Parse(dictionaryReader.ReadToEnd());
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
