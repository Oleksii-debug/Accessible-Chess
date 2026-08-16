using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;

namespace WordDeck;

internal static class DictionaryLoader
{
    private const string BuiltInOxfordId = "oxford-3000-en-uk";

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
        return Parse(dictionaryReader.ReadToEnd(), BuiltInOxfordId, "Oxford 3000 English-Ukrainian");
    }

    public static DictionaryPackage LoadFromFile(string path)
    {
        string text = File.ReadAllText(path, Encoding.UTF8);
        byte[] hash = SHA256.HashData(Encoding.UTF8.GetBytes(text));
        string fallbackId = $"imported-{Convert.ToHexString(hash)[..12].ToLowerInvariant()}";
        string fallbackName = Path.GetFileNameWithoutExtension(path);
        DictionaryPackage package = Parse(text, fallbackId, fallbackName);

        if (package.Id.Equals(BuiltInOxfordId, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException($"Imported dictionaries cannot use the reserved built-in dictionary ID '{BuiltInOxfordId}'.");

        return package;
    }

    public static DictionaryPackage Parse(string text) =>
        Parse(text, "imported-dictionary", "Imported dictionary");

    private static DictionaryPackage Parse(string text, string fallbackId, string fallbackName)
    {
        var metadata = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        var entries = new List<DictionaryEntry>();
        var entryIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        using var reader = new StringReader(text);
        string? line;
        bool firstDataLineSeen = false;
        int sourceLine = 0;
        while ((line = reader.ReadLine()) is not null)
        {
            sourceLine++;
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
            if (!firstDataLineSeen)
            {
                firstDataLineSeen = true;
                if (parts.Length >= 4 && parts[0].Trim().Equals("entryId", StringComparison.OrdinalIgnoreCase))
                    continue;
            }

            if (parts.Length < 4)
                throw new InvalidDataException($"Dictionary row {sourceLine} must contain at least four tab-separated columns: entryId, level, source, target.");

            string entryId = parts[0].Trim();
            string level = parts[1].Trim();
            string source = parts[2].Trim();
            string target = string.Join("\t", parts.Skip(3)).Trim();

            if (source.Length == 0)
                throw new InvalidDataException($"Dictionary row {sourceLine} has an empty source word.");
            if (target.Length == 0)
                throw new InvalidDataException($"Dictionary row {sourceLine} has an empty translation.");

            if (entryId.Length == 0)
                entryId = $"{fallbackId}:{entries.Count + 1}";

            if (!entryIds.Add(entryId))
                throw new InvalidDataException($"Dictionary contains duplicate entry ID '{entryId}' at source line {sourceLine}.");

            entries.Add(new DictionaryEntry(entryId, level, source, target));
        }

        if (entries.Count == 0)
            throw new InvalidDataException("Dictionary contains no usable entries.");

        string id = metadata.GetValueOrDefault("id", fallbackId).Trim();
        string name = metadata.GetValueOrDefault("name", fallbackName).Trim();
        string sourceLanguage = metadata.GetValueOrDefault("sourceLanguage", "en").Trim();
        string targetLanguage = metadata.GetValueOrDefault("targetLanguage", "uk").Trim();

        if (id.Length == 0) id = fallbackId;
        if (name.Length == 0) name = fallbackName;
        if (sourceLanguage.Length == 0) sourceLanguage = "en";
        if (targetLanguage.Length == 0) targetLanguage = "uk";

        return new DictionaryPackage
        {
            Id = id,
            Name = name,
            SourceLanguage = sourceLanguage,
            TargetLanguage = targetLanguage,
            Entries = entries
        };
    }
}
