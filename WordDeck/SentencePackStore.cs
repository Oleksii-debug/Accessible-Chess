namespace WordDeck;

internal sealed record InstalledSentencePack(
    string Path,
    SentencePack Pack,
    ISentenceCorpus? RuntimeCorpus = null,
    string? SqlitePath = null)
{
    public ISentenceCorpus Corpus => RuntimeCorpus ?? Pack;
    public string PackId => Corpus.PackId;
    public string License => Corpus.License;
    public int SentenceCount => Corpus.SentenceCount;
}

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

        // Import validates the portable interchange pack once. Large-pack study sessions use the
        // separately built disk-backed SQLite corpus and do not need to repeat this eager load.
        SentencePack pack = SentencePackIo.Read(fullSource);
        string safeId = SafeFileName(pack.PackId);
        string destination = Path.Combine(DirectoryPath, safeId + ".json.gz");
        string sqliteDestination = Path.Combine(DirectoryPath, safeId + ".sqlite");
        string temp = destination + ".tmp";
        string sqliteTemp = sqliteDestination + ".tmp";

        try
        {
            SentencePackIo.WriteGZip(temp, pack);
            SentencePackSqlitePrototype.Build(sqliteTemp, pack);

            // Both new representations are complete and validated before replacing the previous files.
            File.Move(temp, destination, true);
            File.Move(sqliteTemp, sqliteDestination, true);
        }
        finally
        {
            if (File.Exists(temp)) File.Delete(temp);
            if (File.Exists(sqliteTemp)) File.Delete(sqliteTemp);
        }

        string legacyJson = Path.Combine(DirectoryPath, safeId + ".json");
        if (File.Exists(legacyJson)) File.Delete(legacyJson);

        var sqliteCorpus = new SentencePackSqliteCorpus(sqliteDestination);
        return new InstalledSentencePack(destination, pack, sqliteCorpus, sqliteDestination);
    }

    public IReadOnlyList<InstalledSentencePack> LoadInstalled()
    {
        var result = new List<InstalledSentencePack>();
        IEnumerable<string> paths = Directory.EnumerateFiles(DirectoryPath, "*.json", SearchOption.TopDirectoryOnly)
            .Concat(Directory.EnumerateFiles(DirectoryPath, "*.json.gz", SearchOption.TopDirectoryOnly))
            .OrderByDescending(SentencePackIo.IsGZipPath)
            .ThenBy(path => path, StringComparer.OrdinalIgnoreCase);

        foreach (string path in paths)
        {
            try
            {
                SentencePack pack = SentencePackIo.Read(path);
                string sqlitePath = Path.Combine(DirectoryPath, SafeFileName(pack.PackId) + ".sqlite");
                ISentenceCorpus? runtime = null;
                if (File.Exists(sqlitePath))
                {
                    var sqlite = new SentencePackSqliteCorpus(sqlitePath);
                    if (string.Equals(sqlite.PackId, pack.PackId, StringComparison.OrdinalIgnoreCase) &&
                        sqlite.SentenceCount == pack.SentenceCount)
                        runtime = sqlite;
                }
                result.Add(new InstalledSentencePack(path, pack, runtime, runtime is null ? null : sqlitePath));
            }
            catch
            {
                // A broken optional pack must never prevent WordDeck from starting.
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
