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
    public int Version { get; set; } = 2;
    public string PackId { get; set; } = string.Empty;
    public string Generation { get; set; } = string.Empty;
    public string PortableFileName { get; set; } = string.Empty;
    public string SqliteFileName { get; set; } = string.Empty;
    public string License { get; set; } = string.Empty;
    public string Provenance { get; set; } = string.Empty;
    public int SentenceCount { get; set; }
    public int SourcePackVersion { get; set; }
    public string LogicalSha256 { get; set; } = string.Empty;
    public string PortableSha256 { get; set; } = string.Empty;
}

internal sealed class SentencePackStore
{
    private const int ManifestVersion = 2;
    private readonly string _root;
    private readonly Action<string>? _testCheckpoint;
    private static readonly JsonSerializerOptions ManifestJson = new() { PropertyNameCaseInsensitive = true, WriteIndented = true };

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
        SentencePackStructuralLimits.Validate(pack);
        _testCheckpoint?.Invoke("source-validated");

        string safeId = SafeFileName(pack.PackId);
        EnsureNoCaseInsensitiveIdentityCollision(safeId);

        string logicalSha = SentencePackDerivativeIdentity.LogicalFingerprint(pack);
        string generation = "g-" + logicalSha[..12] + "-" + Guid.NewGuid().ToString("N");
        string portableFileName = $"{safeId}.{generation}.json.gz";
        string sqliteFileName = $"{safeId}.{generation}.sqlite";
        string portablePath = ControlledPath(portableFileName);
        string sqlitePath = ControlledPath(sqliteFileName);
        string portableTemp = ControlledPath(portableFileName + ".tmp");
        string sqliteTemp = ControlledPath(sqliteFileName + ".tmp");
        string manifestPath = ManifestPath(safeId);
        string backupManifestPath = ManifestBackupPath(safeId);
        string manifestTemp = ControlledPath(safeId + ".installed.json." + Guid.NewGuid().ToString("N") + ".tmp");
        string backupTemp = ControlledPath(safeId + ".installed.backup.json." + Guid.NewGuid().ToString("N") + ".tmp");
        bool generationInstalled = false;
        bool committed = false;

        try
        {
            SentencePackIo.WriteGZip(portableTemp, pack);
            _testCheckpoint?.Invoke("portable-staged");
            _testCheckpoint?.Invoke("before-sqlite-build");

            SentencePackSqlitePrototype.Build(sqliteTemp, pack);
            _testCheckpoint?.Invoke("sqlite-built");
            SentencePackDerivativeIdentity.Stamp(sqliteTemp, pack, portableTemp);
            _testCheckpoint?.Invoke("identity-stamped");

            var stagedCorpus = new SentencePackSqliteCorpus(sqliteTemp);
            ValidateCompanionMatchesPortable(stagedCorpus, pack, sqliteTemp, portableTemp);
            _testCheckpoint?.Invoke("candidate-validated");

            string portableSha = SentencePackDerivativeIdentity.FileHash(portableTemp);
            var manifest = new SentencePackInstallManifest
            {
                Version = ManifestVersion,
                PackId = pack.PackId,
                Generation = generation,
                PortableFileName = portableFileName,
                SqliteFileName = sqliteFileName,
                License = pack.License,
                Provenance = pack.Provenance,
                SentenceCount = pack.SentenceCount,
                SourcePackVersion = pack.Version,
                LogicalSha256 = logicalSha,
                PortableSha256 = portableSha
            };
            ValidateManifest(manifest);

            SqliteConnection.ClearAllPools();
            File.Move(portableTemp, portablePath, false);
            File.Move(sqliteTemp, sqlitePath, false);
            generationInstalled = true;
            _testCheckpoint?.Invoke("generation-files-installed");

            ValidateGenerationFiles(manifest, portablePath, sqlitePath);

            File.WriteAllText(manifestTemp, JsonSerializer.Serialize(manifest, ManifestJson));
            _testCheckpoint?.Invoke("manifest-staged");
            SentencePackInstallManifest stagedManifest = ReadManifestRequired(manifestTemp);
            ValidateManifest(stagedManifest);
            ValidateGenerationFiles(stagedManifest, portablePath, sqlitePath);
            _testCheckpoint?.Invoke("manifest-validated");

            SentencePackInstallManifest? previous = ReadManifestOrNull(manifestPath);
            if (previous is not null)
            {
                try
                {
                    ValidateManifest(previous);
                    string previousText = JsonSerializer.Serialize(previous, ManifestJson);
                    File.WriteAllText(backupTemp, previousText);
                    _ = ReadManifestRequired(backupTemp);
                    File.Move(backupTemp, backupManifestPath, true);
                }
                catch
                {
                    // Do not destroy an already-valid backup merely because the current manifest is corrupt.
                    TryDelete(backupTemp);
                }
            }

            _testCheckpoint?.Invoke("before-manifest-commit");
            File.Move(manifestTemp, manifestPath, true);
            committed = true;

            TryDelete(ControlledPath(safeId + ".json"));
            TryDelete(ControlledPath(safeId + ".json.gz"));
            TryDelete(ControlledPath(safeId + ".sqlite"));
            CleanupOldGenerations(safeId, manifest, ReadManifestOrNull(backupManifestPath));

            return LoadManifestGeneration(manifest, portablePack: pack);
        }
        catch
        {
            SqliteConnection.ClearAllPools();
            if (!committed && generationInstalled)
            {
                TryDelete(portablePath);
                TryDelete(sqlitePath);
            }
            throw;
        }
        finally
        {
            SqliteConnection.ClearAllPools();
            TryDelete(portableTemp);
            TryDelete(sqliteTemp);
            TryDelete(manifestTemp);
            TryDelete(backupTemp);
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
            InstalledSentencePack? installed = TryLoadManifestThenBackup(manifestPath, ManifestBackupPath(safeId));
            if (installed is not null && representedPackIds.Add(installed.PackId))
                result.Add(installed);
        }

        // A backup without a readable current manifest remains recoverable and visible.
        foreach (string backupPath in Directory.EnumerateFiles(DirectoryPath, "*.installed.backup.json", SearchOption.TopDirectoryOnly)
                     .OrderBy(path => path, StringComparer.OrdinalIgnoreCase))
        {
            string safeId = Path.GetFileName(backupPath)[..^".installed.backup.json".Length];
            if (File.Exists(ManifestPath(safeId))) continue;
            InstalledSentencePack? installed = TryLoadManifestThenBackup(backupPath, null);
            if (installed is not null && representedPackIds.Add(installed.PackId))
                result.Add(installed);
        }

        // Legacy exact-name SQLite remains supported. Immutable generation files are never
        // discovered by filename alone; they become active only through a validated manifest.
        foreach (string sqlitePath in Directory.EnumerateFiles(DirectoryPath, "*.sqlite", SearchOption.TopDirectoryOnly)
                     .Where(path => !IsGenerationAssetName(Path.GetFileName(path)))
                     .OrderBy(path => path, StringComparer.OrdinalIgnoreCase))
        {
            try
            {
                var corpus = new SentencePackSqliteCorpus(sqlitePath);
                string safeId = SafeFileName(corpus.PackId);
                string expected = ControlledPath(safeId + ".sqlite");
                if (!PathEquals(sqlitePath, expected) || representedPackIds.Contains(corpus.PackId)) continue;

                string gzipPath = ControlledPath(safeId + ".json.gz");
                string jsonPath = ControlledPath(safeId + ".json");
                string? portablePath = File.Exists(gzipPath) ? gzipPath : File.Exists(jsonPath) ? jsonPath : null;
                if (portablePath is not null && !SentencePackDerivativeIdentity.MatchesInstalledPortable(sqlitePath, portablePath, allowLegacyUnstamped: true))
                    continue;

                result.Add(new InstalledSentencePack(portablePath ?? sqlitePath, corpus.PackId, corpus.License, corpus.SentenceCount, corpus, sqlitePath));
                representedPackIds.Add(corpus.PackId);
            }
            catch { }
        }

        IEnumerable<string> portablePaths = Directory.EnumerateFiles(DirectoryPath, "*.json", SearchOption.TopDirectoryOnly)
            .Concat(Directory.EnumerateFiles(DirectoryPath, "*.json.gz", SearchOption.TopDirectoryOnly))
            .Where(path => !path.EndsWith(".installed.json", StringComparison.OrdinalIgnoreCase) &&
                           !path.EndsWith(".installed.backup.json", StringComparison.OrdinalIgnoreCase) &&
                           !IsGenerationAssetName(Path.GetFileName(path)))
            .OrderByDescending(SentencePackIo.IsGZipPath)
            .ThenBy(path => path, StringComparer.OrdinalIgnoreCase);

        foreach (string path in portablePaths)
        {
            try
            {
                SentencePack pack = SentencePackIo.Read(path);
                SentencePackLicenseValidator.ValidateForInstallation(pack);
                string safeId = SafeFileName(pack.PackId);
                string expected = ControlledPath(safeId + (SentencePackIo.IsGZipPath(path) ? ".json.gz" : ".json"));
                if (!PathEquals(path, expected) || representedPackIds.Contains(pack.PackId)) continue;
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

    private InstalledSentencePack? TryLoadManifestThenBackup(string primaryPath, string? backupPath)
    {
        SentencePackInstallManifest? primary = ReadManifestOrNull(primaryPath);
        if (primary is not null)
        {
            try { return LoadManifestGeneration(primary); }
            catch { }
        }

        if (!string.IsNullOrWhiteSpace(backupPath))
        {
            SentencePackInstallManifest? backup = ReadManifestOrNull(backupPath);
            if (backup is not null)
            {
                try { return LoadManifestGeneration(backup); }
                catch { }
            }
        }
        return null;
    }

    private InstalledSentencePack LoadManifestGeneration(SentencePackInstallManifest manifest, SentencePack? portablePack = null)
    {
        ValidateManifest(manifest);
        string portablePath = ControlledPath(manifest.PortableFileName);
        string sqlitePath = ControlledPath(manifest.SqliteFileName);
        ValidateGenerationFiles(manifest, portablePath, sqlitePath);
        var corpus = new SentencePackSqliteCorpus(sqlitePath);
        return new InstalledSentencePack(portablePath, corpus.PackId, corpus.License, corpus.SentenceCount, corpus, sqlitePath, portablePack);
    }

    private void ValidateGenerationFiles(SentencePackInstallManifest manifest, string portablePath, string sqlitePath)
    {
        if (!File.Exists(portablePath) || !File.Exists(sqlitePath))
            throw new InvalidDataException("Committed SentencePack generation is incomplete.");
        if (!string.Equals(SentencePackDerivativeIdentity.FileHash(portablePath), manifest.PortableSha256, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("SentencePack portable generation hash does not match its manifest.");

        var corpus = new SentencePackSqliteCorpus(sqlitePath);
        if (!string.Equals(corpus.PackId, manifest.PackId, StringComparison.Ordinal) ||
            !string.Equals(corpus.License, manifest.License, StringComparison.Ordinal) ||
            !string.Equals(corpus.Provenance, manifest.Provenance, StringComparison.Ordinal) ||
            corpus.SentenceCount != manifest.SentenceCount)
            throw new InvalidDataException("SentencePack manifest and SQLite metadata do not match.");

        RequireSqliteMetadata(sqlitePath, SentencePackDerivativeIdentity.FingerprintKey, manifest.LogicalSha256);
        RequireSqliteMetadata(sqlitePath, SentencePackDerivativeIdentity.PortableHashKey, manifest.PortableSha256);
        RequireSqliteMetadata(sqlitePath, SentencePackDerivativeIdentity.SourceVersionKey, manifest.SourcePackVersion.ToString(System.Globalization.CultureInfo.InvariantCulture));
    }

    private static void RequireSqliteMetadata(string sqlitePath, string key, string expected)
    {
        string? actual = SentencePackDerivativeIdentity.ReadMetadata(sqlitePath, key);
        if (!string.Equals(actual, expected, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException($"SentencePack SQLite derivative metadata '{key}' does not match its active manifest.");
    }

    private static void ValidateCompanionMatchesPortable(SentencePackSqliteCorpus corpus, SentencePack pack, string sqlitePath, string portablePath)
    {
        if (!string.Equals(corpus.PackId, pack.PackId, StringComparison.Ordinal) ||
            !string.Equals(corpus.License, pack.License, StringComparison.Ordinal) ||
            !string.Equals(corpus.Provenance, pack.Provenance, StringComparison.Ordinal) ||
            corpus.SentenceCount != pack.SentenceCount)
            throw new InvalidDataException("SQLite SentencePack companion metadata does not match the validated portable pack.");
        SentencePackDerivativeIdentity.VerifyCandidate(sqlitePath, pack, portablePath);
    }

    private void ValidateManifest(SentencePackInstallManifest manifest)
    {
        if (manifest.Version != ManifestVersion)
            throw new InvalidDataException("Unsupported SentencePack install manifest version.");
        string safeId = SafeFileName(manifest.PackId);
        if (!IsSafeGeneration(manifest.Generation))
            throw new InvalidDataException("SentencePack generation identifier is unsafe.");
        string expectedPortable = $"{safeId}.{manifest.Generation}.json.gz";
        string expectedSqlite = $"{safeId}.{manifest.Generation}.sqlite";
        if (!string.Equals(manifest.PortableFileName, expectedPortable, StringComparison.Ordinal) ||
            !string.Equals(manifest.SqliteFileName, expectedSqlite, StringComparison.Ordinal))
            throw new InvalidDataException("SentencePack manifest contains unexpected generation file names.");
        SentencePack.RequireCanonicalValue(manifest.License, "SentencePack manifest license");
        SentencePack.RequireCanonicalValue(manifest.Provenance, "SentencePack manifest provenance");
        if (manifest.SentenceCount <= 0 || manifest.SentenceCount > SentencePackStructuralLimits.MaxSentences)
            throw new InvalidDataException("SentencePack manifest sentence count is invalid.");
        if (manifest.SourcePackVersion != SentencePack.CurrentVersion)
            throw new InvalidDataException("SentencePack manifest source version is unsupported.");
        if (!IsSha256(manifest.LogicalSha256) || !IsSha256(manifest.PortableSha256))
            throw new InvalidDataException("SentencePack manifest identity hash is invalid.");
        _ = ControlledPath(manifest.PortableFileName);
        _ = ControlledPath(manifest.SqliteFileName);
    }

    private static bool IsSafeGeneration(string value) =>
        !string.IsNullOrWhiteSpace(value) && value.Length <= 80 && value.StartsWith("g-", StringComparison.Ordinal) &&
        value.All(ch => char.IsAsciiLetterOrDigit(ch) || ch == '-');

    private static bool IsSha256(string value) =>
        value is { Length: 64 } && value.All(Uri.IsHexDigit);

    private void EnsureNoCaseInsensitiveIdentityCollision(string safeId)
    {
        foreach (string path in Directory.EnumerateFiles(DirectoryPath, "*", SearchOption.TopDirectoryOnly))
        {
            string? existingId = InstalledFileIdentity(Path.GetFileName(path));
            if (existingId is null) continue;
            if (string.Equals(existingId, safeId, StringComparison.OrdinalIgnoreCase) &&
                !string.Equals(existingId, safeId, StringComparison.Ordinal))
                throw new InvalidDataException($"SentencePack id '{safeId}' would collide with installed pack id '{existingId}' on Windows case-insensitive storage.");
        }
    }

    private static string? InstalledFileIdentity(string fileName)
    {
        const string activeSuffix = ".installed.json";
        const string backupSuffix = ".installed.backup.json";
        if (fileName.EndsWith(backupSuffix, StringComparison.OrdinalIgnoreCase)) return fileName[..^backupSuffix.Length];
        if (fileName.EndsWith(activeSuffix, StringComparison.OrdinalIgnoreCase)) return fileName[..^activeSuffix.Length];
        int generation = fileName.IndexOf(".g-", StringComparison.OrdinalIgnoreCase);
        if (generation > 0) return fileName[..generation];
        if (fileName.EndsWith(".json.gz", StringComparison.OrdinalIgnoreCase)) return fileName[..^8];
        if (fileName.EndsWith(".sqlite", StringComparison.OrdinalIgnoreCase)) return fileName[..^7];
        if (fileName.EndsWith(".json", StringComparison.OrdinalIgnoreCase)) return fileName[..^5];
        return null;
    }

    private void CleanupOldGenerations(string safeId, SentencePackInstallManifest current, SentencePackInstallManifest? previous)
    {
        var keep = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { current.PortableFileName, current.SqliteFileName };
        if (previous is not null)
        {
            try
            {
                ValidateManifest(previous);
                keep.Add(previous.PortableFileName);
                keep.Add(previous.SqliteFileName);
            }
            catch { }
        }

        foreach (string path in Directory.EnumerateFiles(DirectoryPath, safeId + ".g-*", SearchOption.TopDirectoryOnly))
        {
            string name = Path.GetFileName(path);
            if (keep.Contains(name)) continue;
            if (name.EndsWith(".json.gz", StringComparison.OrdinalIgnoreCase) || name.EndsWith(".sqlite", StringComparison.OrdinalIgnoreCase))
                TryDelete(path);
        }
    }

    private static bool IsGenerationAssetName(string fileName) => fileName.IndexOf(".g-", StringComparison.OrdinalIgnoreCase) > 0;

    private string ManifestPath(string safeId) => ControlledPath(safeId + ".installed.json");
    private string ManifestBackupPath(string safeId) => ControlledPath(safeId + ".installed.backup.json");

    private static SentencePackInstallManifest ReadManifestRequired(string path)
    {
        try
        {
            return JsonSerializer.Deserialize<SentencePackInstallManifest>(File.ReadAllText(path), ManifestJson)
                ?? throw new InvalidDataException("SentencePack install manifest is empty.");
        }
        catch (JsonException ex)
        {
            throw new InvalidDataException("SentencePack install manifest is malformed.", ex);
        }
    }

    private static SentencePackInstallManifest? ReadManifestOrNull(string path)
    {
        try { return File.Exists(path) ? ReadManifestRequired(path) : null; }
        catch { return null; }
    }

    private string ControlledPath(string fileName)
    {
        string root = Path.GetFullPath(DirectoryPath).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar) + Path.DirectorySeparatorChar;
        string candidate = Path.GetFullPath(Path.Combine(DirectoryPath, fileName));
        if (!candidate.StartsWith(root, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("SentencePack path escaped the controlled installation directory.");
        return candidate;
    }

    private static bool PathEquals(string left, string right) =>
        string.Equals(Path.GetFullPath(left), Path.GetFullPath(right), StringComparison.OrdinalIgnoreCase);

    private static void TryDelete(string path)
    {
        try { if (File.Exists(path)) File.Delete(path); } catch { }
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
        if (stem.Equals("CON", StringComparison.OrdinalIgnoreCase) || stem.Equals("PRN", StringComparison.OrdinalIgnoreCase) ||
            stem.Equals("AUX", StringComparison.OrdinalIgnoreCase) || stem.Equals("NUL", StringComparison.OrdinalIgnoreCase)) return true;
        if (stem.Length == 4 && int.TryParse(stem[3..], out int number) && number is >= 1 and <= 9)
            return stem.StartsWith("COM", StringComparison.OrdinalIgnoreCase) || stem.StartsWith("LPT", StringComparison.OrdinalIgnoreCase);
        return false;
    }
}
