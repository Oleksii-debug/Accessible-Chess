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

        _root = Path.GetFullPath(root);
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

        _testCheckpoint?.Invoke("before-source-read");
        SentencePack pack = SentencePackIo.Read(fullSource);
        SentencePackLicenseValidator.ValidateForInstallation(pack);
        _testCheckpoint?.Invoke("source-validated");

        string safeId = SafeFileName(pack.PackId);
        string destination = ControlledPath(safeId + ".json.gz");
        string sqliteDestination = ControlledPath(safeId + ".sqlite");
        EnsureNoCaseInsensitiveIdentityCollision(safeId);

        string transactionId = Guid.NewGuid().ToString("N");
        string temp = ControlledPath(safeId + ".json.gz." + transactionId + ".tmp");
        string sqliteTemp = ControlledPath(safeId + ".sqlite." + transactionId + ".tmp");
        string portableBackup = ControlledPath(safeId + ".json.gz." + transactionId + ".rollback");
        string sqliteBackup = ControlledPath(safeId + ".sqlite." + transactionId + ".rollback");

        bool oldPortableBackedUp = false;
        bool oldSqliteBackedUp = false;
        bool newPortableInstalled = false;
        bool newSqliteInstalled = false;
        bool committed = false;

        try
        {
            SentencePackIo.WriteGZip(temp, pack);
            _testCheckpoint?.Invoke("portable-staged");
            _testCheckpoint?.Invoke("before-sqlite-build");

            SentencePackSqlitePrototype.Build(sqliteTemp, pack);
            SentencePackDerivativeIdentity.Stamp(sqliteTemp, pack, temp);
            _testCheckpoint?.Invoke("sqlite-built");
            _testCheckpoint?.Invoke("before-candidate-validation");

            var candidate = new SentencePackSqliteCorpus(sqliteTemp);
            ValidateCompanionMatchesPortable(candidate, pack, sqliteTemp, temp);
            _testCheckpoint?.Invoke("candidate-validated");

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
            ValidateCompanionMatchesPortable(installedCorpus, pack, sqliteDestination, destination);
            _testCheckpoint?.Invoke("replacement-validated");

            committed = true;
            TryDelete(portableBackup);
            TryDelete(sqliteBackup);

            string legacyJson = ControlledPath(safeId + ".json");
            if (File.Exists(legacyJson))
                File.Delete(legacyJson);

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
        }
    }

    public IReadOnlyList<InstalledSentencePack> LoadInstalled()
    {
        var result = new List<InstalledSentencePack>();
        var representedPaths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var representedPackIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (string sqlitePath in Directory.EnumerateFiles(DirectoryPath, "*.sqlite", SearchOption.TopDirectoryOnly)
                     .OrderBy(path => path, StringComparer.OrdinalIgnoreCase))
        {
            try
            {
                var corpus = new SentencePackSqliteCorpus(sqlitePath);
                string safeId = SafeFileName(corpus.PackId);
                string gzipPath = ControlledPath(safeId + ".json.gz");
                string jsonPath = ControlledPath(safeId + ".json");
                string? portablePath = File.Exists(gzipPath) ? gzipPath : File.Exists(jsonPath) ? jsonPath : null;

                // A Round-2 derivative that carries source identity metadata must match the
                // installed portable source byte-for-byte. Pre-Round-2 databases without the
                // metadata remain readable for compatibility until the user explicitly reimports.
                if (portablePath is not null &&
                    !SentencePackDerivativeIdentity.MatchesInstalledPortable(sqlitePath, portablePath))
                {
                    continue;
                }

                string surfacedPath = portablePath ?? sqlitePath;
                result.Add(new InstalledSentencePack(
                    surfacedPath,
                    corpus.PackId,
                    corpus.License,
                    corpus.SentenceCount,
                    corpus,
                    sqlitePath));
                representedPackIds.Add(corpus.PackId);
                if (portablePath is not null)
                {
                    representedPaths.Add(gzipPath);
                    representedPaths.Add(jsonPath);
                }
            }
            catch
            {
                // Corrupt/incompatible/stale optional SQLite is ignored. A valid portable source
                // can still be discovered below; study never opens an invalidated database.
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
                SentencePackLicenseValidator.ValidateForInstallation(pack);
                SafeFileName(pack.PackId);
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
                // Broken optional portable packs never prevent WordDeck startup.
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

    private void EnsureNoCaseInsensitiveIdentityCollision(string safeId)
    {
        foreach (string path in Directory.EnumerateFiles(DirectoryPath, "*", SearchOption.TopDirectoryOnly))
        {
            string name = Path.GetFileName(path);
            string? existingId = InstalledFileIdentity(name);
            if (existingId is null)
                continue;
            if (string.Equals(existingId, safeId, StringComparison.OrdinalIgnoreCase) &&
                !string.Equals(existingId, safeId, StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    $"SentencePack id '{safeId}' would collide with installed pack id '{existingId}' on Windows case-insensitive storage.");
            }
        }
    }

    private static string? InstalledFileIdentity(string fileName)
    {
        if (fileName.EndsWith(".json.gz", StringComparison.OrdinalIgnoreCase))
            return fileName[..^8];
        if (fileName.EndsWith(".sqlite", StringComparison.OrdinalIgnoreCase))
            return fileName[..^7];
        if (fileName.EndsWith(".json", StringComparison.OrdinalIgnoreCase))
            return fileName[..^5];
        return null;
    }

    private string ControlledPath(string fileName)
    {
        string root = Path.GetFullPath(DirectoryPath).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar) + Path.DirectorySeparatorChar;
        string candidate = Path.GetFullPath(Path.Combine(DirectoryPath, fileName));
        if (!candidate.StartsWith(root, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("SentencePack path escaped the controlled installation directory.");
        return candidate;
    }

    private static void ValidateCompanionMatchesPortable(
        SentencePackSqliteCorpus corpus,
        SentencePack pack,
        string sqlitePath,
        string portablePath)
    {
        if (!string.Equals(corpus.PackId, pack.PackId, StringComparison.Ordinal) ||
            !string.Equals(corpus.License, pack.License, StringComparison.Ordinal) ||
            !string.Equals(corpus.Provenance, pack.Provenance, StringComparison.Ordinal) ||
            corpus.SentenceCount != pack.SentenceCount)
        {
            throw new InvalidDataException("SQLite SentencePack companion metadata does not match the validated portable pack.");
        }
        SentencePackDerivativeIdentity.VerifyCandidate(sqlitePath, pack, portablePath);
    }

    private static void RestoreRollback(string backup, string destination, bool expected)
    {
        if (!expected || !File.Exists(backup))
            return;
        try
        {
            if (File.Exists(destination)) File.Delete(destination);
            File.Move(backup, destination, false);
        }
        catch
        {
            // Preserve rollback bytes if automatic restoration itself fails.
        }
    }

    private static void TryDelete(string path)
    {
        try
        {
            if (File.Exists(path)) File.Delete(path);
        }
        catch
        {
        }
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
        SentenceTokenizer.ValidateUnicode(value, "SentencePack id");
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
