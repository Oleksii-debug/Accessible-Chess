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
    private readonly Action<string>? _testCheckpoint;
    public string DirectoryPath { get; }

    public SentencePackStore()
        : this(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WordDeck"))
    {
    }

    internal SentencePackStore(string root, Action<string>? testCheckpoint = null)
    {
        if (string.IsNullOrWhiteSpace(root))
            throw new ArgumentException("SentencePack root must not be blank.", nameof(root));

        _root = root;
        _testCheckpoint = testCheckpoint;
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
        // separately built disk-backed SQLite corpus and do not repeat this eager load.
        SentencePack pack = SentencePackIo.Read(fullSource);
        string safeId = SafeFileName(pack.PackId);
        string destination = Path.Combine(DirectoryPath, safeId + ".json.gz");
        string sqliteDestination = Path.Combine(DirectoryPath, safeId + ".sqlite");
        string transactionId = Guid.NewGuid().ToString("N");
        string temp = destination + "." + transactionId + ".tmp";
        string sqliteTemp = sqliteDestination + "." + transactionId + ".tmp";
        string portableBackup = destination + "." + transactionId + ".rollback";
        string sqliteBackup = sqliteDestination + "." + transactionId + ".rollback";

        bool oldPortableBackedUp = false;
        bool oldSqliteBackedUp = false;
        bool newPortableInstalled = false;
        bool newSqliteInstalled = false;
        bool committed = false;

        try
        {
            SentencePackIo.WriteGZip(temp, pack);
            SentencePackSqlitePrototype.Build(sqliteTemp, pack);

            // Validate the complete candidate before touching the currently usable installation.
            var candidate = new SentencePackSqliteCorpus(sqliteTemp);
            ValidateCompanionMatchesPortable(candidate, pack);
            _testCheckpoint?.Invoke("candidate-validated");

            // Microsoft.Data.Sqlite pools connections by default. Release pooled native handles
            // before moving the existing Windows files.
            SqliteConnection.ClearAllPools();

            if (File.Exists(destination))
            {
                File.Move(destination, portableBackup, false);
                oldPortableBackedUp = true;
            }
            if (File.Exists(sqliteDestination))
            {
                File.Move(sqliteDestination, sqliteBackup, false);
                oldSqliteBackedUp = true;
            }

            _testCheckpoint?.Invoke("old-installation-backed-up");

            File.Move(temp, destination, false);
            newPortableInstalled = true;
            _testCheckpoint?.Invoke("portable-installed");

            File.Move(sqliteTemp, sqliteDestination, false);
            newSqliteInstalled = true;
            _testCheckpoint?.Invoke("sqlite-installed");

            var installedCorpus = new SentencePackSqliteCorpus(sqliteDestination);
            ValidateCompanionMatchesPortable(installedCorpus, pack);
            _testCheckpoint?.Invoke("replacement-validated");

            committed = true;
            TryDelete(portableBackup);
            TryDelete(sqliteBackup);

            string legacyJson = Path.Combine(DirectoryPath, safeId + ".json");
            if (File.Exists(legacyJson)) File.Delete(legacyJson);

            return new InstalledSentencePack(
                destination,
                pack.PackId,
                pack.License,
                pack.SentenceCount,
                installedCorpus,
                sqliteDestination,
                pack);
        }
        catch
        {
            SqliteConnection.ClearAllPools();

            if (newPortableInstalled) TryDelete(destination);
            if (newSqliteInstalled) TryDelete(sqliteDestination);

            RestoreRollback(portableBackup, destination, oldPortableBackedUp);
            RestoreRollback(sqliteBackup, sqliteDestination, oldSqliteBackedUp);
            throw;
        }
        finally
        {
            SqliteConnection.ClearAllPools();
            TryDelete(temp);
            TryDelete(sqliteTemp);
            if (committed)
            {
                TryDelete(portableBackup);
                TryDelete(sqliteBackup);
            }
            // If rollback itself could not be restored, intentionally leave the .rollback file
            // in place rather than deleting the last recoverable bytes.
        }
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

    private static void ValidateCompanionMatchesPortable(SentencePackSqliteCorpus corpus, SentencePack pack)
    {
        if (!string.Equals(corpus.PackId, pack.PackId, StringComparison.Ordinal) ||
            !string.Equals(corpus.License, pack.License, StringComparison.Ordinal) ||
            !string.Equals(corpus.Provenance, pack.Provenance, StringComparison.Ordinal) ||
            corpus.SentenceCount != pack.SentenceCount)
        {
            throw new InvalidDataException("SQLite SentencePack companion metadata does not match the validated portable pack.");
        }
    }

    private static void RestoreRollback(string backup, string destination, bool expected)
    {
        if (!expected || !File.Exists(backup)) return;
        try
        {
            if (File.Exists(destination)) File.Delete(destination);
            File.Move(backup, destination, false);
        }
        catch
        {
            // Preserve the rollback file. A later/manual recovery still has the last known-good bytes.
        }
    }

    private static void TryDelete(string path)
    {
        try { if (File.Exists(path)) File.Delete(path); } catch { }
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
