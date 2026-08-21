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
    public string License { get; set; } = string.Empty;
    public int SentenceCount { get; set; }
}

internal sealed class SentencePackStore
{
    private const int ManifestVersion = 1;
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

        SentencePack pack = SentencePackIo.Read(fullSource);
        string safeId = SafeFileName(pack.PackId);
        string generation = DateTime.UtcNow.ToString("yyyyMMddHHmmssfff") + "-" + Guid.NewGuid().ToString("N");
        string portableFileName = $"{safeId}.{generation}.json.gz";
        string sqliteFileName = $"{safeId}.{generation}.sqlite";
        string portablePath = Path.Combine(DirectoryPath, portableFileName);
        string sqlitePath = Path.Combine(DirectoryPath, sqliteFileName);
        string portableTemp = portablePath + ".tmp";
        string sqliteTemp = sqlitePath + ".tmp";
        string manifestPath = ManifestPath(safeId);
        string manifestBackupPath = ManifestBackupPath(safeId);
        string manifestTemp = manifestPath + ".tmp";

        try
        {
            SentencePackIo.WriteGZip(portableTemp, pack);
            SentencePackSqlitePrototype.Build(sqliteTemp, pack);
            SqliteConnection.ClearAllPools();

            SentencePack stagedPortable = SentencePackIo.Read(portableTemp);
            var stagedSqlite = new SentencePackSqliteCorpus(sqliteTemp);
            RequireSamePack(pack, stagedPortable.PackId, stagedPortable.License, stagedPortable.SentenceCount, "portable staged pack");
            RequireSamePack(pack, stagedSqlite.PackId, stagedSqlite.License, stagedSqlite.SentenceCount, "SQLite staged pack");
            SqliteConnection.ClearAllPools();

            File.Move(portableTemp, portablePath, false);
            File.Move(sqliteTemp, sqlitePath, false);

            var manifest = new SentencePackInstallManifest
            {
                Version = ManifestVersion,
                PackId = pack.PackId,
                Generation = generation,
                PortableFileName = portableFileName,
                SqliteFileName = sqliteFileName,
                License = pack.License,
                SentenceCount = pack.SentenceCount
            };
            File.WriteAllText(manifestTemp, JsonSerializer.Serialize(manifest, new JsonSerializerOptions { WriteIndented = true }));

            if (TryReadManifest(manifestPath, out SentencePackInstallManifest? previousManifest) && previousManifest is not null)
                File.Copy(manifestPath, manifestBackupPath, true);

            File.Move(manifestTemp, manifestPath, true);

            DeleteIfExists(Path.Combine(DirectoryPath, safeId + ".json"));
            DeleteIfExists(Path.Combine(DirectoryPath, safeId + ".json.gz"));
            DeleteIfExists(Path.Combine(DirectoryPath, safeId + ".sqlite"));

            CleanupOldGenerations(safeId, manifest, ReadManifestOrNull(manifestBackupPath));

            var corpus = new SentencePackSqliteCorpus(sqlitePath);
            return new InstalledSentencePack(
                portablePath,
                pack.PackId,
                pack.License,
                pack.SentenceCount,
                corpus,
                sqlitePath,
                pack);
        }
        catch
        {
            SqliteConnection.ClearAllPools();
            SentencePackInstallManifest? committed = ReadManifestOrNull(manifestPath);
            bool currentGenerationCommitted = committed is not null &&
                string.Equals(committed.Generation, generation, StringComparison.Ordinal);
            if (!currentGenerationCommitted)
            {
                DeleteIfExists(portablePath);
                DeleteIfExists(sqlitePath);
            }
            throw;
        }
        finally
        {
            SqliteConnection.ClearAllPools();
            DeleteIfExists(portableTemp);
            DeleteIfExists(sqliteTemp);
            DeleteIfExists(manifestTemp);
        }
    }

    public IReadOnlyList<InstalledSentencePack> LoadInstalled()
    {
        var result = new List<InstalledSentencePack>();
        var representedPackIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (string manifestPath in Directory.EnumerateFiles(DirectoryPath, "*.installed.json", SearchOption.TopDirectoryOnly)
                     .OrderBy(path => path, StringComparer.OrdinalIgnoreCase))
        {
            SentencePackInstallManifest? manifest = ReadManifestOrNull(manifestPath);
            if (manifest is null)
            {
                string safeId = Path.GetFileName(manifestPath)[..^".installed.json".Length];
                manifest = ReadManifestOrNull(ManifestBackupPath(safeId));
            }
            if (manifest is null) continue;

            try
            {
                InstalledSentencePack installed = LoadManifestGeneration(manifest);
                if (representedPackIds.Add(installed.PackId)) result.Add(installed);
            }
            catch
            {
                string safeId = SafeFileName(manifest.PackId);
                SentencePackInstallManifest? backup = ReadManifestOrNull(ManifestBackupPath(safeId));
                if (backup is null) continue;
                try
                {
                    InstalledSentencePack installed = LoadManifestGeneration(backup);
                    if (representedPackIds.Add(installed.PackId)) result.Add(installed);
                }
                catch { }
            }
        }

        foreach (string sqlitePath in Directory.EnumerateFiles(DirectoryPath, "*.sqlite", SearchOption.TopDirectoryOnly)
                     .OrderBy(path => path, StringComparer.OrdinalIgnoreCase))
        {
            try
            {
                var corpus = new SentencePackSqliteCorpus(sqlitePath);
                string safeId = SafeFileName(corpus.PackId);
                string expectedLegacySqlite = Path.Combine(DirectoryPath, safeId + ".sqlite");
                if (!PathEquals(sqlitePath, expectedLegacySqlite) || representedPackIds.Contains(corpus.PackId))
                    continue;

                string gzipPath = Path.Combine(DirectoryPath, safeId + ".json.gz");
                string jsonPath = Path.Combine(DirectoryPath, safeId + ".json");
                string portablePath = File.Exists(gzipPath) ? gzipPath : File.Exists(jsonPath) ? jsonPath : sqlitePath;
                result.Add(new InstalledSentencePack(portablePath, corpus.PackId, corpus.License, corpus.SentenceCount, corpus, sqlitePath));
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
                if (representedPackIds.Contains(pack.PackId)) continue;
                string safeId = SafeFileName(pack.PackId);
                string expected = Path.Combine(DirectoryPath, safeId + (SentencePackIo.IsGZipPath(path) ? ".json.gz" : ".json"));
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

    private InstalledSentencePack LoadManifestGeneration(SentencePackInstallManifest manifest)
    {
        ValidateManifest(manifest);
        string portablePath = Path.Combine(DirectoryPath, manifest.PortableFileName);
        string sqlitePath = Path.Combine(DirectoryPath, manifest.SqliteFileName);
        if (!File.Exists(portablePath) || !File.Exists(sqlitePath))
            throw new InvalidDataException("Committed SentencePack generation is incomplete.");

        var corpus = new SentencePackSqliteCorpus(sqlitePath);
        if (!string.Equals(corpus.PackId, manifest.PackId, StringComparison.Ordinal) ||
            !string.Equals(corpus.License, manifest.License, StringComparison.Ordinal) ||
            corpus.SentenceCount != manifest.SentenceCount)
            throw new InvalidDataException("Committed SentencePack manifest and SQLite metadata do not match.");

        return new InstalledSentencePack(portablePath, corpus.PackId, corpus.License, corpus.SentenceCount, corpus, sqlitePath);
    }

    private void ValidateManifest(SentencePackInstallManifest manifest)
    {
        if (manifest.Version != ManifestVersion) throw new InvalidDataException("Unsupported SentencePack install manifest version.");
        string safeId = SafeFileName(manifest.PackId);
        if (string.IsNullOrWhiteSpace(manifest.Generation) || manifest.Generation.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 ||
            manifest.Generation.Contains('/') || manifest.Generation.Contains('\\'))
            throw new InvalidDataException("SentencePack generation identifier is unsafe.");
        string expectedPortable = $"{safeId}.{manifest.Generation}.json.gz";
        string expectedSqlite = $"{safeId}.{manifest.Generation}.sqlite";
        if (!string.Equals(manifest.PortableFileName, expectedPortable, StringComparison.Ordinal) ||
            !string.Equals(manifest.SqliteFileName, expectedSqlite, StringComparison.Ordinal))
            throw new InvalidDataException("SentencePack manifest contains unexpected file names.");
        if (string.IsNullOrWhiteSpace(manifest.License) || manifest.SentenceCount <= 0)
            throw new InvalidDataException("SentencePack manifest metadata is incomplete.");
    }

    private static void RequireSamePack(SentencePack expected, string id, string license, int count, string source)
    {
        if (!string.Equals(expected.PackId, id, StringComparison.Ordinal) ||
            !string.Equals(expected.License, license, StringComparison.Ordinal) ||
            expected.SentenceCount != count)
            throw new InvalidDataException($"{source} metadata does not match the validated SentencePack source.");
    }

    private string ManifestPath(string safeId) => Path.Combine(DirectoryPath, safeId + ".installed.json");
    private string ManifestBackupPath(string safeId) => Path.Combine(DirectoryPath, safeId + ".installed.backup.json");

    private static bool TryReadManifest(string path, out SentencePackInstallManifest? manifest)
    {
        manifest = ReadManifestOrNull(path);
        return manifest is not null;
    }

    private static SentencePackInstallManifest? ReadManifestOrNull(string path)
    {
        try
        {
            return File.Exists(path) ? JsonSerializer.Deserialize<SentencePackInstallManifest>(File.ReadAllText(path)) : null;
        }
        catch { return null; }
    }

    private void CleanupOldGenerations(string safeId, SentencePackInstallManifest current, SentencePackInstallManifest? previous)
    {
        var keep = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            current.PortableFileName,
            current.SqliteFileName
        };
        if (previous is not null)
        {
            keep.Add(previous.PortableFileName);
            keep.Add(previous.SqliteFileName);
        }

        foreach (string path in Directory.EnumerateFiles(DirectoryPath, safeId + ".*", SearchOption.TopDirectoryOnly))
        {
            string name = Path.GetFileName(path);
            if (keep.Contains(name) || name.EndsWith(".installed.json", StringComparison.OrdinalIgnoreCase) ||
                name.EndsWith(".installed.backup.json", StringComparison.OrdinalIgnoreCase))
                continue;
            if (name.EndsWith(".json.gz", StringComparison.OrdinalIgnoreCase) || name.EndsWith(".sqlite", StringComparison.OrdinalIgnoreCase))
                DeleteIfExists(path);
        }
    }

    private static bool PathEquals(string left, string right) =>
        string.Equals(Path.GetFullPath(left), Path.GetFullPath(right), StringComparison.OrdinalIgnoreCase);

    private static void DeleteIfExists(string path)
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
