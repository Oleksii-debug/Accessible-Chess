using Microsoft.Data.Sqlite;

namespace WordDeck;

internal sealed record InstalledSentencePack(
    string Path,
    string PackId,
    string License,
    int SentenceCount,
    ISentenceCorpus Corpus,
    string? SqlitePath = null,
    SentencePack? PortablePack = null);

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

            // Microsoft.Data.Sqlite pools connections by default. The build connection has been
            // disposed, but its pooled native handle can still keep the Windows file open. Clear
            // the provider pool before the atomic replace so import/replacement is deterministic.
            SqliteConnection.ClearAllPools();

            File.Move(temp, destination, true);
            File.Move(sqliteTemp, sqliteDestination, true);
        }
        finally
        {
            // Also release any read-only pooled handle from a prior installed corpus before cleanup.
            SqliteConnection.ClearAllPools();
            if (File.Exists(temp)) File.Delete(temp);
            if (File.Exists(sqliteTemp)) File.Delete(sqliteTemp);
        }

        string legacyJson = Path.Combine(DirectoryPath, safeId + ".json");
        if (File.Exists(legacyJson)) File.Delete(legacyJson);

        var sqliteCorpus = new SentencePackSqliteCorpus(sqliteDestination);
        return new InstalledSentencePack(
            destination,
            pack.PackId,
            pack.License,
            pack.SentenceCount,
            sqliteCorpus,
            sqliteDestination,
            pack);
    }

    public IReadOnlyList<InstalledSentencePack> LoadInstalled()
    {
        var result = new List<InstalledSentencePack>();
        var representedPaths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var representedPackIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        // Runtime-first discovery: a valid SQLite companion contains all metadata needed by the UI,
        // so normal restart/study does not deserialize the potentially very large gzip interchange
        // file. The portable file remains installed for provenance/export/backwards compatibility.
        foreach (string sqlitePath in Directory.EnumerateFiles(DirectoryPath, "*.sqlite", SearchOption.TopDirectoryOnly)
                     .OrderBy(path => path, StringComparer.OrdinalIgnoreCase))
        {
            try
            {
                var corpus = new SentencePackSqliteCorpus(sqlitePath);
                string safeId = SafeFileName(corpus.PackId);
                string gzipPath = Path.Combine(DirectoryPath, safeId + ".json.gz");
                string jsonPath = Path.Combine(DirectoryPath, safeId + ".json");
                string portablePath = File.Exists(gzipPath) ? gzipPath : File.Exists(jsonPath) ? jsonPath : sqlitePath;

                result.Add(new InstalledSentencePack(
                    portablePath,
                    corpus.PackId,
                    corpus.License,
                    corpus.SentenceCount,
                    corpus,
                    sqlitePath));
                representedPackIds.Add(corpus.PackId);
                representedPaths.Add(gzipPath);
                representedPaths.Add(jsonPath);
            }
            catch
            {
                // A corrupt optional SQLite companion must not block startup. Its portable pack,
                // when present and valid, is considered below as the backwards-compatible fallback.
            }
        }

        IEnumerable<string> portablePaths = Directory.EnumerateFiles(DirectoryPath, "*.json", SearchOption.TopDirectoryOnly)
            .Concat(Directory.EnumerateFiles(DirectoryPath, "*.json.gz", SearchOption.TopDirectoryOnly))
            .OrderByDescending(SentencePackIo.IsGZipPath)
            .ThenBy(path => path, StringComparer.OrdinalIgnoreCase);

        foreach (string path in portablePaths)
        {
            if (representedPaths.Contains(path))
                continue;

            try
            {
                SentencePack pack = SentencePackIo.Read(path);
                if (!representedPackIds.Add(pack.PackId))
                    continue;

                result.Add(new InstalledSentencePack(
                    path,
                    pack.PackId,
                    pack.License,
                    pack.SentenceCount,
                    pack,
                    null,
                    pack));
            }
            catch
            {
                // A broken optional pack must never prevent WordDeck from starting.
            }
        }

        return result
            .GroupBy(item => item.PackId, StringComparer.OrdinalIgnoreCase)
            .Select(group => group.First())
            .OrderBy(item => item.PackId, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    public InstalledSentencePack? Find(string packId)
    {
        if (string.IsNullOrWhiteSpace(packId))
            return null;
        return LoadInstalled().FirstOrDefault(item => string.Equals(item.PackId, packId, StringComparison.OrdinalIgnoreCase));
    }

    internal static string SafeFileName(string packId)
    {
        if (string.IsNullOrWhiteSpace(packId))
            throw new InvalidDataException("SentencePack id is required before installation.");

        string value = packId.Trim();
        if (value.Length == 0 || value.Length > 120)
            throw new InvalidDataException("SentencePack id must contain 1 to 120 characters.");
        if (!string.Equals(value, packId, StringComparison.Ordinal))
            throw new InvalidDataException("SentencePack id cannot start or end with whitespace.");
        if (value is "." or ".." || value.EndsWith(".", StringComparison.Ordinal) || value.EndsWith(' '))
            throw new InvalidDataException("SentencePack id is not a safe Windows file name.");
        if (value.Contains('/') || value.Contains('\\') || value.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
            throw new InvalidDataException("SentencePack id contains a path separator or invalid file-name character.");
        if (IsWindowsDeviceName(value))
            throw new InvalidDataException("SentencePack id is reserved by Windows and cannot be installed safely.");
        return value;
    }

    private static bool IsWindowsDeviceName(string value)
    {
        string stem = value.Split('.')[0];
        if (stem.Equals("CON", StringComparison.OrdinalIgnoreCase) ||
            stem.Equals("PRN", StringComparison.OrdinalIgnoreCase) ||
            stem.Equals("AUX", StringComparison.OrdinalIgnoreCase) ||
            stem.Equals("NUL", StringComparison.OrdinalIgnoreCase))
            return true;
        if (stem.Length == 4 && int.TryParse(stem[3..], out int number) && number is >= 1 and <= 9)
            return stem.StartsWith("COM", StringComparison.OrdinalIgnoreCase) || stem.StartsWith("LPT", StringComparison.OrdinalIgnoreCase);
        return false;
    }
}
