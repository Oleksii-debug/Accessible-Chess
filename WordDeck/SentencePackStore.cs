using System.Security.Cryptography;
using System.Text.Json;
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

internal sealed class SentencePackInstallManifest
{
    public int Version { get; set; } = 1;
    public string PackId { get; set; } = string.Empty;
    public string Generation { get; set; } = string.Empty;
    public string PortableFileName { get; set; } = string.Empty;
    public string SqliteFileName { get; set; } = string.Empty;
    public long PortableLength { get; set; }
    public long SqliteLength { get; set; }
    public string PortableSha256 { get; set; } = string.Empty;
    public string SqliteSha256 { get; set; } = string.Empty;
    public string License { get; set; } = string.Empty;
    public int SentenceCount { get; set; }
}

internal sealed class SentencePackStore
{
    private const int ManifestVersion = 1;
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
        EnsureNoCaseInsensitiveIdentityCollision(pack.PackId);
        string generation = DateTime.UtcNow.ToString("yyyyMMddHHmmssfff") + "-" + Guid.NewGuid().ToString("N");
        string portableFileName = $"{safeId}.{generation}.json.gz";
        string sqliteFileName = $"{safeId}.{generation}.sqlite";
        string portablePath = ControlledPath(portableFileName);
        string sqlitePath = ControlledPath(sqliteFileName);
        string portableTemp = ControlledPath(portableFileName + ".tmp");
        string sqliteTemp = ControlledPath(sqliteFileName + ".tmp");
        string manifestPath = ManifestPath(safeId);
        string manifestBackupPath = ManifestBackupPath(safeId);
        string manifestBackupTempPath = manifestBackupPath + ".tmp";
        string manifestTemp = ControlledPath(safeId + ".installed.json.tmp");
        bool committed = false;
        SentencePackInstallManifest? previousManifest = null;

        try
        {
            SentencePackIo.WriteGZip(portableTemp, pack);
            _testCheckpoint?.Invoke("portable-staged");
            _testCheckpoint?.Invoke("before-sqlite-build");
            SentencePackSqlitePrototype.Build(sqliteTemp, pack);
            SentencePackDerivativeIdentity.Stamp(sqliteTemp, pack, portableTemp);
            SqliteConnection.ClearAllPools();
            _testCheckpoint?.Invoke("sqlite-built");
            _testCheckpoint?.Invoke("before-candidate-validation");

            SentencePack stagedPortable = SentencePackIo.Read(portableTemp);
            SentencePackLicenseValidator.ValidateForInstallation(stagedPortable);
            var stagedSqlite = new SentencePackSqliteCorpus(sqliteTemp);
            RequireSamePack(pack, stagedPortable.PackId, stagedPortable.License, stagedPortable.SentenceCount, "portable staged pack");
            RequireSamePack(pack, stagedSqlite.PackId, stagedSqlite.License, stagedSqlite.SentenceCount, "SQLite staged pack");
            SentencePackDerivativeIdentity.VerifyCandidate(sqliteTemp, pack, portableTemp);
            SqliteConnection.ClearAllPools();
            _testCheckpoint?.Invoke("candidate-validated");

            // Stage the current activation pointer as the rollback candidate, but do not
            // replace the durable backup until the new manifest has actually committed.
            // A pre-commit failure therefore cannot destroy the previous rollback point.
            if (TryReadManifest(manifestPath, out previousManifest) && previousManifest is not null)
            {
                _ = LoadManifestGeneration(previousManifest);
                File.WriteAllText(manifestBackupTempPath, File.ReadAllText(manifestPath));
                _testCheckpoint?.Invoke("old-installation-backed-up");
            }

            File.Move(portableTemp, portablePath, false);
            _testCheckpoint?.Invoke("portable-generation-installed");
            _testCheckpoint?.Invoke("portable-installed");
            File.Move(sqliteTemp, sqlitePath, false);
            _testCheckpoint?.Invoke("sqlite-generation-installed");
            _testCheckpoint?.Invoke("sqlite-installed");

            var manifest = new SentencePackInstallManifest
            {
                Version = ManifestVersion,
                PackId = pack.PackId,
                Generation = generation,
                PortableFileName = portableFileName,
                SqliteFileName = sqliteFileName,
                PortableLength = new FileInfo(portablePath).Length,
                SqliteLength = new FileInfo(sqlitePath).Length,
                PortableSha256 = FileSha256(portablePath),
                SqliteSha256 = FileSha256(sqlitePath),
                License = pack.License,
                SentenceCount = pack.SentenceCount
            };
            ValidateManifest(manifest);
            File.WriteAllText(manifestTemp, JsonSerializer.Serialize(manifest, new JsonSerializerOptions { WriteIndented = true }));
            _testCheckpoint?.Invoke("before-manifest-commit");

            // One atomic pointer change activates the complete generation. The previous
            // pointer was already staged in a separate file. If the process is killed in
            // the tiny interval before backup promotion, startup also recognizes that
            // staged rollback pointer and can still recover the last-known-good generation.
            File.Move(manifestTemp, manifestPath, true);
            committed = true;
            PromotePreparedBackup(manifestBackupTempPath, manifestBackupPath);
            _testCheckpoint?.Invoke("manifest-committed");

            DeleteIfExists(ControlledPath(safeId + ".json"));
            DeleteIfExists(ControlledPath(safeId + ".json.gz"));
            DeleteIfExists(ControlledPath(safeId + ".sqlite"));
            CleanupOldGenerations(safeId, manifest, ReadManifestOrNull(manifestBackupPath));
            return LoadManifestGeneration(manifest, retainPortablePack: pack);
        }
        catch
        {
            SqliteConnection.ClearAllPools();
            if (committed)
            {
                // Managed failures after activation still finish publishing the staged
                // rollback pointer. A hard process loss leaves the temp pointer for the
                // startup recovery path below.
                PromotePreparedBackup(manifestBackupTempPath, manifestBackupPath);
            }
            else
            {
                DeleteIfExists(portablePath);
                DeleteIfExists(sqlitePath);
                DeleteIfExists(manifestBackupTempPath);
            }
            throw;
        }
        finally
        {
            SqliteConnection.ClearAllPools();
            DeleteIfExists(portableTemp);
            DeleteIfExists(sqliteTemp);
            DeleteIfExists(manifestTemp);
            if (!committed) DeleteIfExists(manifestBackupTempPath);
        }
    }

    public IReadOnlyList<InstalledSentencePack> LoadInstalled()
    {
        var result = new List<InstalledSentencePack>();
        var representedPackIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (string manifestPath in Directory.EnumerateFiles(DirectoryPath, "*.installed.json", SearchOption.TopDirectoryOnly)
                     .OrderBy(path => path, StringComparer.OrdinalIgnoreCase))
        {
            string safeId = Path.GetFileName(manifestPath)[..^".installed.json".Length];
            InstalledSentencePack? installed = TryLoadGeneration(ReadManifestOrNull(manifestPath))
                ?? TryLoadGeneration(ReadManifestOrNull(ManifestBackupTempPath(safeId)))
                ?? TryLoadGeneration(ReadManifestOrNull(ManifestBackupPath(safeId)));
            if (installed is not null && representedPackIds.Add(installed.PackId)) result.Add(installed);
        }

        // Backward compatibility for pre-manifest installs. Generation files without
        // a manifest are ignored so interrupted imports cannot become active.
        foreach (string sqlitePath in Directory.EnumerateFiles(DirectoryPath, "*.sqlite", SearchOption.TopDirectoryOnly)
                     .OrderBy(path => path, StringComparer.OrdinalIgnoreCase))
        {
            try
            {
                var corpus = new SentencePackSqliteCorpus(sqlitePath);
                string safeId = SafeFileName(corpus.PackId);
                string expectedSqlite = ControlledPath(safeId + ".sqlite");
                if (!PathEquals(sqlitePath, expectedSqlite) || representedPackIds.Contains(corpus.PackId)) continue;
                string gzipPath = ControlledPath(safeId + ".json.gz");
                string jsonPath = ControlledPath(safeId + ".json");
                string? portablePath = File.Exists(gzipPath) ? gzipPath : File.Exists(jsonPath) ? jsonPath : null;
                if (portablePath is not null && !SentencePackDerivativeIdentity.MatchesInstalledPortable(sqlitePath, portablePath)) continue;
                result.Add(new InstalledSentencePack(portablePath ?? sqlitePath, corpus.PackId, corpus.License, corpus.SentenceCount, corpus, sqlitePath));
                representedPackIds.Add(corpus.PackId);
            }
            catch { }
        }

        IEnumerable<string> portablePaths = Directory.EnumerateFiles(DirectoryPath, "*.json", SearchOption.TopDirectoryOnly)
            .Concat(Directory.EnumerateFiles(DirectoryPath, "*.json.gz", SearchOption.TopDirectoryOnly))
            .Where(path => !path.EndsWith(".installed.json", StringComparison.OrdinalIgnoreCase) &&
                           !path.EndsWith(".installed.backup.json", StringComparison.OrdinalIgnoreCase))
            .OrderByDescending(SentencePackIo.IsGZipPath)
            .ThenBy(path => path, StringComparer.OrdinalIgnoreCase);
        foreach (string path in portablePaths)
        {
            try
            {
                SentencePack pack = SentencePackIo.Read(path);
                SentencePackLicenseValidator.ValidateForInstallation(pack);
                if (representedPackIds.Contains(pack.PackId)) continue;
                string safeId = SafeFileName(pack.PackId);
                string expected = ControlledPath(safeId + (SentencePackIo.IsGZipPath(path) ? ".json.gz" : ".json"));
                if (!PathEquals(path, expected)) continue;
                representedPackIds.Add(pack.PackId);
                result.Add(new InstalledSentencePack(path, pack.PackId, pack.License, pack.SentenceCount, pack, null, pack));
            }
            catch { }
        }
        return result.OrderBy(item => item.PackId, StringComparer.OrdinalIgnoreCase).ToList();
    }

    public InstalledSentencePack? Find(string packId)
    {
        if (string.IsNullOrWhiteSpace(packId)) return null;
        return LoadInstalled().FirstOrDefault(item => string.Equals(item.PackId, packId, StringComparison.OrdinalIgnoreCase));
    }

    // Explicit integrity path: full hashes/portable parsing stay out of normal startup.
    internal void VerifyIntegrity(string packId)
    {
        string safeId = SafeFileName(packId);
        SentencePackInstallManifest? manifest = ReadManifestOrNull(ManifestPath(safeId))
            ?? ReadManifestOrNull(ManifestBackupTempPath(safeId))
            ?? ReadManifestOrNull(ManifestBackupPath(safeId))
            ?? throw new InvalidDataException("No committed SentencePack manifest exists for integrity verification.");
        ValidateManifest(manifest);
        string portablePath = ControlledPath(manifest.PortableFileName);
        string sqlitePath = ControlledPath(manifest.SqliteFileName);
        if (!File.Exists(portablePath) || !File.Exists(sqlitePath))
            throw new InvalidDataException("Committed SentencePack generation is incomplete.");
        if (!string.Equals(FileSha256(portablePath), manifest.PortableSha256, StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(FileSha256(sqlitePath), manifest.SqliteSha256, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Committed SentencePack generation hash does not match its manifest.");
        SentencePack portable = SentencePackIo.Read(portablePath);
        SentencePackLicenseValidator.ValidateForInstallation(portable);
        SentencePackDerivativeIdentity.VerifyCandidate(sqlitePath, portable, portablePath);
        var corpus = new SentencePackSqliteCorpus(sqlitePath);
        RequireSamePack(portable, corpus.PackId, corpus.License, corpus.SentenceCount, "integrity-checked SQLite pack");
    }

    private InstalledSentencePack? TryLoadGeneration(SentencePackInstallManifest? manifest)
    {
        if (manifest is null) return null;
        try { return LoadManifestGeneration(manifest); }
        catch { return null; }
    }

    private InstalledSentencePack LoadManifestGeneration(SentencePackInstallManifest manifest, SentencePack? retainPortablePack = null)
    {
        ValidateManifest(manifest);
        string portablePath = ControlledPath(manifest.PortableFileName);
        string sqlitePath = ControlledPath(manifest.SqliteFileName);
        if (!File.Exists(portablePath) || !File.Exists(sqlitePath))
            throw new InvalidDataException("Committed SentencePack generation is incomplete.");
        if (new FileInfo(portablePath).Length != manifest.PortableLength || new FileInfo(sqlitePath).Length != manifest.SqliteLength)
            throw new InvalidDataException("Committed SentencePack generation size does not match its manifest.");

        var corpus = new SentencePackSqliteCorpus(sqlitePath);
        RequireSamePack(manifest, corpus.PackId, corpus.License, corpus.SentenceCount, "committed SQLite pack");
        if (!SentencePackDerivativeIdentity.MatchesExpectedPortableHash(sqlitePath, manifest.PortableSha256))
            throw new InvalidDataException("Committed SQLite metadata does not match the manifest portable-source identity.");
        return new InstalledSentencePack(portablePath, corpus.PackId, corpus.License, corpus.SentenceCount, corpus, sqlitePath, retainPortablePack);
    }

    private void ValidateManifest(SentencePackInstallManifest manifest)
    {
        if (manifest.Version != ManifestVersion) throw new InvalidDataException("Unsupported SentencePack install manifest version.");
        string safeId = SafeFileName(manifest.PackId);
        if (string.IsNullOrWhiteSpace(manifest.Generation) || manifest.Generation.Length > 100 ||
            manifest.Generation.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 ||
            manifest.Generation.Contains('/') || manifest.Generation.Contains('\\'))
            throw new InvalidDataException("SentencePack generation identifier is unsafe.");
        string expectedPortable = $"{safeId}.{manifest.Generation}.json.gz";
        string expectedSqlite = $"{safeId}.{manifest.Generation}.sqlite";
        if (!string.Equals(manifest.PortableFileName, expectedPortable, StringComparison.Ordinal) ||
            !string.Equals(manifest.SqliteFileName, expectedSqlite, StringComparison.Ordinal))
            throw new InvalidDataException("SentencePack manifest contains unexpected file names.");
        if (manifest.PortableLength <= 0 || manifest.SqliteLength <= 0)
            throw new InvalidDataException("SentencePack manifest file sizes are missing or invalid.");
        if (!IsSha256(manifest.PortableSha256) || !IsSha256(manifest.SqliteSha256))
            throw new InvalidDataException("SentencePack manifest integrity hashes are missing or malformed.");
        if (string.IsNullOrWhiteSpace(manifest.License) || manifest.SentenceCount <= 0)
            throw new InvalidDataException("SentencePack manifest metadata is incomplete.");
        _ = ControlledPath(manifest.PortableFileName);
        _ = ControlledPath(manifest.SqliteFileName);
    }

    private void EnsureNoCaseInsensitiveIdentityCollision(string packId)
    {
        IEnumerable<string> manifestPointers = Directory.EnumerateFiles(DirectoryPath, "*.installed.json", SearchOption.TopDirectoryOnly)
            .Concat(Directory.EnumerateFiles(DirectoryPath, "*.installed.backup.json", SearchOption.TopDirectoryOnly))
            .Concat(Directory.EnumerateFiles(DirectoryPath, "*.installed.backup.json.tmp", SearchOption.TopDirectoryOnly));
        foreach (string path in manifestPointers)
        {
            SentencePackInstallManifest? manifest = ReadManifestOrNull(path);
            if (manifest is null) continue;
            if (string.Equals(manifest.PackId, packId, StringComparison.OrdinalIgnoreCase) &&
                !string.Equals(manifest.PackId, packId, StringComparison.Ordinal))
                throw new InvalidDataException($"SentencePack id '{packId}' collides with committed pack id '{manifest.PackId}' on Windows case-insensitive storage.");
        }
        foreach (string path in Directory.EnumerateFiles(DirectoryPath, "*.sqlite", SearchOption.TopDirectoryOnly))
        {
            string name = Path.GetFileNameWithoutExtension(path);
            if (name.Contains('.')) continue;
            if (string.Equals(name, packId, StringComparison.OrdinalIgnoreCase) && !string.Equals(name, packId, StringComparison.Ordinal))
                throw new InvalidDataException($"SentencePack id '{packId}' collides with legacy installed id '{name}' on Windows case-insensitive storage.");
        }
    }

    private string ManifestPath(string safeId) => ControlledPath(safeId + ".installed.json");
    private string ManifestBackupPath(string safeId) => ControlledPath(safeId + ".installed.backup.json");
    private string ManifestBackupTempPath(string safeId) => ManifestBackupPath(safeId) + ".tmp";
    private static bool TryReadManifest(string path, out SentencePackInstallManifest? manifest)
    {
        manifest = ReadManifestOrNull(path);
        return manifest is not null;
    }
    private static SentencePackInstallManifest? ReadManifestOrNull(string path)
    {
        try { return File.Exists(path) ? JsonSerializer.Deserialize<SentencePackInstallManifest>(File.ReadAllText(path)) : null; }
        catch { return null; }
    }

    private static void PromotePreparedBackup(string preparedPath, string backupPath)
    {
        if (File.Exists(preparedPath)) File.Move(preparedPath, backupPath, true);
    }

    private void CleanupOldGenerations(string safeId, SentencePackInstallManifest current, SentencePackInstallManifest? previous)
    {
        var keep = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { current.PortableFileName, current.SqliteFileName };
        if (previous is not null) { keep.Add(previous.PortableFileName); keep.Add(previous.SqliteFileName); }
        foreach (string path in Directory.EnumerateFiles(DirectoryPath, safeId + ".*", SearchOption.TopDirectoryOnly))
        {
            string name = Path.GetFileName(path);
            if (keep.Contains(name) || name.EndsWith(".installed.json", StringComparison.OrdinalIgnoreCase) ||
                name.EndsWith(".installed.backup.json", StringComparison.OrdinalIgnoreCase) ||
                name.EndsWith(".installed.backup.json.tmp", StringComparison.OrdinalIgnoreCase)) continue;
            if (name.EndsWith(".json.gz", StringComparison.OrdinalIgnoreCase) || name.EndsWith(".sqlite", StringComparison.OrdinalIgnoreCase)) DeleteIfExists(path);
        }
    }

    private string ControlledPath(string fileName)
    {
        string root = Path.GetFullPath(DirectoryPath).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar) + Path.DirectorySeparatorChar;
        string candidate = Path.GetFullPath(Path.Combine(DirectoryPath, fileName));
        if (!candidate.StartsWith(root, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("SentencePack path escaped the controlled installation directory.");
        return candidate;
    }

    private static void RequireSamePack(SentencePack expected, string id, string license, int count, string source)
    {
        if (!string.Equals(expected.PackId, id, StringComparison.Ordinal) || !string.Equals(expected.License, license, StringComparison.Ordinal) || expected.SentenceCount != count)
            throw new InvalidDataException($"{source} metadata does not match the validated SentencePack source.");
    }
    private static void RequireSamePack(SentencePackInstallManifest expected, string id, string license, int count, string source)
    {
        if (!string.Equals(expected.PackId, id, StringComparison.Ordinal) || !string.Equals(expected.License, license, StringComparison.Ordinal) || expected.SentenceCount != count)
            throw new InvalidDataException($"{source} metadata does not match the committed SentencePack manifest.");
    }

    private static string FileSha256(string path)
    {
        using FileStream stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }
    private static bool IsSha256(string? value) => value is { Length: 64 } && value.All(char.IsAsciiHexDigit);
    private static bool PathEquals(string left, string right) => string.Equals(Path.GetFullPath(left), Path.GetFullPath(right), StringComparison.OrdinalIgnoreCase);
    private static void DeleteIfExists(string path) { try { if (File.Exists(path)) File.Delete(path); } catch { } }

    internal static string SafeFileName(string packId)
    {
        if (string.IsNullOrWhiteSpace(packId)) throw new InvalidDataException("SentencePack id is required before installation.");
        string value = packId.Trim();
        if (value.Length == 0 || value.Length > 120) throw new InvalidDataException("SentencePack id must contain 1 to 120 characters.");
        if (!string.Equals(value, packId, StringComparison.Ordinal)) throw new InvalidDataException("SentencePack id cannot start or end with whitespace.");
        if (value is "." or ".." || value.EndsWith(".", StringComparison.Ordinal) || value.EndsWith(' ')) throw new InvalidDataException("SentencePack id is not a safe Windows file name.");
        if (value.Contains('/') || value.Contains('\\') || value.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
            throw new InvalidDataException("SentencePack id contains a path separator or invalid file-name character.");
        if (IsWindowsDeviceName(value)) throw new InvalidDataException("SentencePack id is reserved by Windows and cannot be installed safely.");
        return value;
    }

    private static bool IsWindowsDeviceName(string value)
    {
        string stem = value.Split('.')[0];
        if (stem.Equals("CON", StringComparison.OrdinalIgnoreCase) || stem.Equals("PRN", StringComparison.OrdinalIgnoreCase) ||
            stem.Equals("AUX", StringComparison.OrdinalIgnoreCase) || stem.Equals("NUL", StringComparison.OrdinalIgnoreCase)) return true;
        if (stem.Length == 4 && int.TryParse(stem[3..], out int number) && number is >= 1 and <= 9)
            return stem.StartsWith("COM", StringComparison.OrdinalIgnoreCase) || stem.StartsWith("LPT", StringComparison.OrdinalIgnoreCase);
        return false;
    }
}
