namespace WordDeck;

internal sealed record InstalledSentencePack(string Path, SentencePack Pack);

internal sealed class SentencePackStore
{
    private readonly string _root;
    public string DirectoryPath { get; }

    public SentencePackStore()
        : this(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WordDeck"))
    {
    }

    internal SentencePackStore(string root)
    {
        if (string.IsNullOrWhiteSpace(root))
            throw new ArgumentException("SentencePack root must not be blank.", nameof(root));

        _root = root;
        DirectoryPath = Path.Combine(_root, "SentencePacks");
        Directory.CreateDirectory(DirectoryPath);
    }

    public InstalledSentencePack Import(string sourcePath)
    {
        if (string.IsNullOrWhiteSpace(sourcePath))
            throw new ArgumentException("SentencePack source path is required.", nameof(sourcePath));

        string fullSource = Path.GetFullPath(sourcePath);
        if (!File.Exists(fullSource))
            throw new FileNotFoundException("SentencePack file was not found.", fullSource);

        SentencePack pack = SentencePackJson.Parse(File.ReadAllText(fullSource));
        string destination = Path.Combine(DirectoryPath, SafeFileName(pack.PackId) + ".json");
        string canonical = SentencePackJson.Serialize(pack);

        string temp = destination + ".tmp";
        File.WriteAllText(temp, canonical);
        File.Move(temp, destination, true);
        return new InstalledSentencePack(destination, pack);
    }

    public IReadOnlyList<InstalledSentencePack> LoadInstalled()
    {
        var result = new List<InstalledSentencePack>();
        foreach (string path in Directory.EnumerateFiles(DirectoryPath, "*.json", SearchOption.TopDirectoryOnly)
                     .OrderBy(path => path, StringComparer.OrdinalIgnoreCase))
        {
            try
            {
                SentencePack pack = SentencePackJson.Parse(File.ReadAllText(path));
                result.Add(new InstalledSentencePack(path, pack));
            }
            catch
            {
                // A malformed optional pack must never prevent WordDeck from starting.
            }
        }

        return result
            .GroupBy(item => item.Pack.PackId, StringComparer.OrdinalIgnoreCase)
            .Select(group => group.First())
            .OrderBy(item => item.Pack.PackId, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    public InstalledSentencePack? Find(string packId)
    {
        if (string.IsNullOrWhiteSpace(packId))
            return null;
        return LoadInstalled().FirstOrDefault(item => string.Equals(item.Pack.PackId, packId, StringComparison.OrdinalIgnoreCase));
    }

    internal static string SafeFileName(string packId)
    {
        if (string.IsNullOrWhiteSpace(packId))
            throw new InvalidDataException("SentencePack id is required before installation.");

        string value = packId.Trim();
        foreach (char invalid in Path.GetInvalidFileNameChars())
            value = value.Replace(invalid, '_');
        value = value.Replace('/', '_').Replace('\\', '_');
        if (value.Length == 0)
            throw new InvalidDataException("SentencePack id cannot be converted to a safe file name.");
        return value;
    }
}
