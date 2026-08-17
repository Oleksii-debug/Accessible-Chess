using Microsoft.Data.Sqlite;
using System.Diagnostics;
using System.Text.Json;

namespace WordDeck;

internal sealed record SentencePackSqliteMetrics(
    long DatabaseBytes,
    long BuildMilliseconds,
    long QueryMilliseconds,
    long ManagedBytesDelta,
    long WorkingSetBytesDelta,
    int ResultCount);

internal static class SentencePackSqlitePrototype
{
    private const int SchemaVersion = 2;
    private static readonly JsonSerializerOptions JsonOptions = new() { PropertyNameCaseInsensitive = true };

    public static void Build(string databasePath, SentencePack pack)
    {
        pack.Validate();
        string fullPath = Path.GetFullPath(databasePath);
        Directory.CreateDirectory(Path.GetDirectoryName(fullPath) ?? ".");
        if (File.Exists(fullPath)) File.Delete(fullPath);

        using var connection = Open(fullPath, readOnly: false);
        using (SqliteCommand command = connection.CreateCommand())
        {
            command.CommandText = """
                PRAGMA journal_mode=OFF;
                PRAGMA synchronous=OFF;
                PRAGMA temp_store=MEMORY;
                CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
                CREATE TABLE sentences(
                    sentence_num INTEGER PRIMARY KEY,
                    stable_id TEXT NOT NULL,
                    english TEXT NOT NULL,
                    ukrainian TEXT NOT NULL,
                    source TEXT NOT NULL,
                    license_override TEXT,
                    source_sentence_id TEXT,
                    translation_sentence_id TEXT,
                    difficulty_value INTEGER NOT NULL,
                    off_list_token_count INTEGER NOT NULL,
                    quality_flags TEXT,
                    lemma_override TEXT
                );
                CREATE TABLE target_entries(
                    target_num INTEGER PRIMARY KEY,
                    entry_id TEXT NOT NULL UNIQUE
                );
                CREATE TABLE sentence_targets(
                    target_num INTEGER NOT NULL,
                    sentence_num INTEGER NOT NULL,
                    level_value INTEGER NOT NULL,
                    PRIMARY KEY(target_num, sentence_num)
                ) WITHOUT ROWID;
                CREATE INDEX ix_sentence_targets_sentence ON sentence_targets(sentence_num, target_num);
                """;
            command.ExecuteNonQuery();
        }

        using SqliteTransaction transaction = connection.BeginTransaction();
        InsertMetadata(connection, transaction, "schema_version", SchemaVersion.ToString());
        InsertMetadata(connection, transaction, "pack_id", pack.PackId);
        InsertMetadata(connection, transaction, "source_language", pack.SourceLanguage);
        InsertMetadata(connection, transaction, "target_language", pack.TargetLanguage);
        InsertMetadata(connection, transaction, "provenance", pack.Provenance);
        InsertMetadata(connection, transaction, "license", pack.License);

        Dictionary<string, int> targetNumbers = BuildTargetDictionary(connection, transaction, pack);

        using SqliteCommand sentenceCommand = connection.CreateCommand();
        sentenceCommand.Transaction = transaction;
        sentenceCommand.CommandText = """
            INSERT INTO sentences(
                sentence_num, stable_id, english, ukrainian, source, license_override,
                source_sentence_id, translation_sentence_id, difficulty_value,
                off_list_token_count, quality_flags, lemma_override)
            VALUES(
                $num, $stable, $en, $uk, $source, $license,
                $sourceId, $translationId, $difficulty,
                $offList, $flags, $lemmas);
            """;
        SqliteParameter sentenceNum = sentenceCommand.Parameters.Add("$num", SqliteType.Integer);
        SqliteParameter stableId = sentenceCommand.Parameters.Add("$stable", SqliteType.Text);
        SqliteParameter english = sentenceCommand.Parameters.Add("$en", SqliteType.Text);
        SqliteParameter ukrainian = sentenceCommand.Parameters.Add("$uk", SqliteType.Text);
        SqliteParameter source = sentenceCommand.Parameters.Add("$source", SqliteType.Text);
        SqliteParameter licenseOverride = sentenceCommand.Parameters.Add("$license", SqliteType.Text);
        SqliteParameter sourceSentenceId = sentenceCommand.Parameters.Add("$sourceId", SqliteType.Text);
        SqliteParameter translationSentenceId = sentenceCommand.Parameters.Add("$translationId", SqliteType.Text);
        SqliteParameter difficulty = sentenceCommand.Parameters.Add("$difficulty", SqliteType.Integer);
        SqliteParameter offList = sentenceCommand.Parameters.Add("$offList", SqliteType.Integer);
        SqliteParameter qualityFlags = sentenceCommand.Parameters.Add("$flags", SqliteType.Text);
        SqliteParameter lemmaOverride = sentenceCommand.Parameters.Add("$lemmas", SqliteType.Text);

        using SqliteCommand targetCommand = connection.CreateCommand();
        targetCommand.Transaction = transaction;
        targetCommand.CommandText = "INSERT INTO sentence_targets(target_num, sentence_num, level_value) VALUES ($target, $sentence, $level);";
        SqliteParameter targetNum = targetCommand.Parameters.Add("$target", SqliteType.Integer);
        SqliteParameter targetSentenceNum = targetCommand.Parameters.Add("$sentence", SqliteType.Integer);
        SqliteParameter levelValue = targetCommand.Parameters.Add("$level", SqliteType.Integer);

        for (int i = 0; i < pack.Sentences.Count; i++)
        {
            SentenceRecord sentence = pack.Sentences[i];
            long numericId = i + 1L;
            sentenceNum.Value = numericId;
            stableId.Value = sentence.Id;
            english.Value = sentence.English;
            ukrainian.Value = sentence.Ukrainian;
            source.Value = sentence.Source;
            licenseOverride.Value = string.Equals(sentence.License, pack.License, StringComparison.Ordinal) ? DBNull.Value : sentence.License;
            sourceSentenceId.Value = (object?)sentence.SourceSentenceId ?? DBNull.Value;
            translationSentenceId.Value = (object?)sentence.TranslationSentenceId ?? DBNull.Value;
            difficulty.Value = LevelToValue(sentence.DifficultyLevel);
            offList.Value = sentence.OffListTokenCount;
            qualityFlags.Value = sentence.QualityFlags.Count == 0 ? DBNull.Value : JsonSerializer.Serialize(sentence.QualityFlags, JsonOptions);
            lemmaOverride.Value = sentence.Lemmas.SequenceEqual(sentence.Tokens, StringComparer.Ordinal) ? DBNull.Value : JsonSerializer.Serialize(sentence.Lemmas, JsonOptions);
            sentenceCommand.ExecuteNonQuery();

            foreach (string target in sentence.TargetEntryIds.Distinct(StringComparer.OrdinalIgnoreCase))
            {
                targetNum.Value = targetNumbers[target];
                targetSentenceNum.Value = numericId;
                levelValue.Value = LevelToValue(sentence.EntryLevels.GetValueOrDefault(target, sentence.DifficultyLevel));
                targetCommand.ExecuteNonQuery();
            }
        }

        transaction.Commit();
        using SqliteCommand optimize = connection.CreateCommand();
        optimize.CommandText = "ANALYZE; PRAGMA optimize;";
        optimize.ExecuteNonQuery();
    }

    public static IReadOnlyList<SentenceRecord> LookupAllTargets(string databasePath, IReadOnlyCollection<string> targetEntryIds)
    {
        string[] requestedTargets = targetEntryIds
            .Where(value => !string.IsNullOrWhiteSpace(value))
            .Select(value => value.Trim().ToLowerInvariant())
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
        if (requestedTargets.Length == 0) return Array.Empty<SentenceRecord>();

        using var connection = Open(databasePath, readOnly: true);
        PackMetadata metadata = ValidateAndReadMetadata(connection);
        Dictionary<string, long> requestedNumbers = ResolveTargetNumbers(connection, requestedTargets);
        if (requestedNumbers.Count != requestedTargets.Length) return Array.Empty<SentenceRecord>();

        using SqliteCommand command = connection.CreateCommand();
        var placeholders = new List<string>(requestedNumbers.Count);
        int index = 0;
        foreach (long numericTarget in requestedNumbers.Values)
        {
            string name = "$t" + index++;
            placeholders.Add(name);
            command.Parameters.AddWithValue(name, numericTarget);
        }
        command.Parameters.AddWithValue("$required", requestedNumbers.Count);
        command.CommandText = $"""
            WITH matches AS (
                SELECT sentence_num
                FROM sentence_targets
                WHERE target_num IN ({string.Join(",", placeholders)})
                GROUP BY sentence_num
                HAVING COUNT(*) = $required
            )
            SELECT
                s.sentence_num, s.stable_id, s.english, s.ukrainian, s.source,
                s.license_override, s.source_sentence_id, s.translation_sentence_id,
                s.difficulty_value, s.off_list_token_count, s.quality_flags, s.lemma_override,
                te.entry_id, st.level_value
            FROM matches m
            JOIN sentences s ON s.sentence_num = m.sentence_num
            JOIN sentence_targets st ON st.sentence_num = s.sentence_num
            JOIN target_entries te ON te.target_num = st.target_num
            ORDER BY s.sentence_num, st.target_num;
            """;

        var result = new List<SentenceRecord>();
        SentenceBuilder? builder = null;
        using SqliteDataReader reader = command.ExecuteReader();
        while (reader.Read())
        {
            long numericSentence = reader.GetInt64(0);
            if (builder is null || builder.NumericId != numericSentence)
            {
                if (builder is not null) result.Add(builder.Build(metadata.License));
                builder = SentenceBuilder.FromRow(reader);
            }
            builder.AddTarget(reader.GetString(12), ValueToLevel(reader.GetInt32(13)));
        }
        if (builder is not null) result.Add(builder.Build(metadata.License));
        return result;
    }

    public static SentencePackSqliteMetrics Measure(string sourcePackPath, string databasePath, IReadOnlyCollection<string> targets)
    {
        GC.Collect(); GC.WaitForPendingFinalizers(); GC.Collect();
        long managedBefore = GC.GetTotalMemory(true);
        long workingBefore = Process.GetCurrentProcess().WorkingSet64;
        Stopwatch build = Stopwatch.StartNew();
        SentencePack pack = SentencePackIo.Read(sourcePackPath);
        Build(databasePath, pack);
        build.Stop();
        pack = null!;
        GC.Collect(); GC.WaitForPendingFinalizers(); GC.Collect();
        Stopwatch query = Stopwatch.StartNew();
        IReadOnlyList<SentenceRecord> results = LookupAllTargets(databasePath, targets);
        query.Stop();
        long managedAfter = GC.GetTotalMemory(true);
        long workingAfter = Process.GetCurrentProcess().WorkingSet64;
        return new SentencePackSqliteMetrics(new FileInfo(databasePath).Length, build.ElapsedMilliseconds, query.ElapsedMilliseconds, managedAfter - managedBefore, workingAfter - workingBefore, results.Count);
    }

    public static SentencePackSqliteMetrics MeasureQueryOnly(string databasePath, IReadOnlyCollection<string> targets)
    {
        GC.Collect(); GC.WaitForPendingFinalizers(); GC.Collect();
        long managedBefore = GC.GetTotalMemory(true);
        using Process process = Process.GetCurrentProcess();
        process.Refresh();
        long workingBefore = process.WorkingSet64;
        Stopwatch query = Stopwatch.StartNew();
        IReadOnlyList<SentenceRecord> results = LookupAllTargets(databasePath, targets);
        query.Stop();
        long managedAfter = GC.GetTotalMemory(true);
        process.Refresh();
        long workingAfter = process.WorkingSet64;
        GC.KeepAlive(results);
        return new SentencePackSqliteMetrics(new FileInfo(databasePath).Length, 0, query.ElapsedMilliseconds, managedAfter - managedBefore, workingAfter - workingBefore, results.Count);
    }

    private static Dictionary<string, int> BuildTargetDictionary(SqliteConnection connection, SqliteTransaction transaction, SentencePack pack)
    {
        string[] allTargets = pack.Sentences.SelectMany(sentence => sentence.TargetEntryIds).Distinct(StringComparer.OrdinalIgnoreCase).OrderBy(id => id, StringComparer.OrdinalIgnoreCase).ToArray();
        var result = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        using SqliteCommand command = connection.CreateCommand();
        command.Transaction = transaction;
        command.CommandText = "INSERT INTO target_entries(target_num, entry_id) VALUES ($num, $id);";
        SqliteParameter number = command.Parameters.Add("$num", SqliteType.Integer);
        SqliteParameter id = command.Parameters.Add("$id", SqliteType.Text);
        for (int i = 0; i < allTargets.Length; i++)
        {
            int numeric = i + 1;
            string entry = allTargets[i].ToLowerInvariant();
            result[entry] = numeric;
            number.Value = numeric;
            id.Value = entry;
            command.ExecuteNonQuery();
        }
        return result;
    }

    private static Dictionary<string, long> ResolveTargetNumbers(SqliteConnection connection, IReadOnlyList<string> targetEntryIds)
    {
        using SqliteCommand command = connection.CreateCommand();
        var placeholders = new List<string>(targetEntryIds.Count);
        for (int i = 0; i < targetEntryIds.Count; i++)
        {
            string name = "$id" + i;
            placeholders.Add(name);
            command.Parameters.AddWithValue(name, targetEntryIds[i]);
        }
        command.CommandText = $"SELECT entry_id, target_num FROM target_entries WHERE entry_id IN ({string.Join(",", placeholders)});";
        var result = new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase);
        using SqliteDataReader reader = command.ExecuteReader();
        while (reader.Read()) result[reader.GetString(0)] = reader.GetInt64(1);
        return result;
    }

    private static SqliteConnection Open(string databasePath, bool readOnly)
    {
        var builder = new SqliteConnectionStringBuilder { DataSource = Path.GetFullPath(databasePath), Mode = readOnly ? SqliteOpenMode.ReadOnly : SqliteOpenMode.ReadWriteCreate, Cache = SqliteCacheMode.Private };
        var connection = new SqliteConnection(builder.ToString());
        connection.Open();
        return connection;
    }

    private static void InsertMetadata(SqliteConnection connection, SqliteTransaction transaction, string key, string value)
    {
        using SqliteCommand command = connection.CreateCommand();
        command.Transaction = transaction;
        command.CommandText = "INSERT INTO metadata(key, value) VALUES ($key, $value);";
        command.Parameters.AddWithValue("$key", key);
        command.Parameters.AddWithValue("$value", value);
        command.ExecuteNonQuery();
    }

    private static PackMetadata ValidateAndReadMetadata(SqliteConnection connection)
    {
        using SqliteCommand command = connection.CreateCommand();
        command.CommandText = "SELECT key, value FROM metadata WHERE key IN ('schema_version','license');";
        var values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        using SqliteDataReader reader = command.ExecuteReader();
        while (reader.Read()) values[reader.GetString(0)] = reader.GetString(1);
        if (!int.TryParse(values.GetValueOrDefault("schema_version"), out int version) || version != SchemaVersion) throw new InvalidDataException("Unsupported or missing SQLite SentencePack schema version.");
        if (!values.TryGetValue("license", out string? license) || string.IsNullOrWhiteSpace(license)) throw new InvalidDataException("SQLite SentencePack is missing license metadata.");
        return new PackMetadata(license);
    }

    private static int LevelToValue(string? level) => (level ?? string.Empty).ToUpperInvariant() switch { "A1" => 1, "A2" => 2, "B1" => 3, "B2" => 4, "C1" => 5, "C2" => 6, _ => 7 };
    private static string ValueToLevel(int value) => value switch { 1 => "A1", 2 => "A2", 3 => "B1", 4 => "B2", 5 => "C1", 6 => "C2", _ => "CUSTOM" };
    private sealed record PackMetadata(string License);

    private sealed class SentenceBuilder
    {
        public long NumericId { get; }
        private readonly string _stableId, _english, _ukrainian, _source, _difficulty;
        private readonly string? _licenseOverride, _sourceSentenceId, _translationSentenceId;
        private readonly int _offList;
        private readonly List<string> _qualityFlags;
        private readonly List<string>? _lemmaOverride;
        private readonly List<string> _targetIds = new();
        private readonly Dictionary<string, string> _entryLevels = new(StringComparer.OrdinalIgnoreCase);

        private SentenceBuilder(long numericId, string stableId, string english, string ukrainian, string source, string? licenseOverride, string? sourceSentenceId, string? translationSentenceId, string difficulty, int offList, List<string> qualityFlags, List<string>? lemmaOverride)
        {
            NumericId = numericId; _stableId = stableId; _english = english; _ukrainian = ukrainian; _source = source; _licenseOverride = licenseOverride; _sourceSentenceId = sourceSentenceId; _translationSentenceId = translationSentenceId; _difficulty = difficulty; _offList = offList; _qualityFlags = qualityFlags; _lemmaOverride = lemmaOverride;
        }

        public static SentenceBuilder FromRow(SqliteDataReader reader)
        {
            string? flagsJson = reader.IsDBNull(10) ? null : reader.GetString(10);
            string? lemmasJson = reader.IsDBNull(11) ? null : reader.GetString(11);
            return new SentenceBuilder(reader.GetInt64(0), reader.GetString(1), reader.GetString(2), reader.GetString(3), reader.GetString(4), reader.IsDBNull(5) ? null : reader.GetString(5), reader.IsDBNull(6) ? null : reader.GetString(6), reader.IsDBNull(7) ? null : reader.GetString(7), ValueToLevel(reader.GetInt32(8)), reader.GetInt32(9), flagsJson is null ? new List<string>() : JsonSerializer.Deserialize<List<string>>(flagsJson, JsonOptions) ?? new List<string>(), lemmasJson is null ? null : JsonSerializer.Deserialize<List<string>>(lemmasJson, JsonOptions));
        }

        public void AddTarget(string entryId, string level) { _targetIds.Add(entryId); _entryLevels[entryId] = level; }

        public SentenceRecord Build(string packLicense)
        {
            List<string> tokens = SentenceTokenizer.Tokenize(_english).ToList();
            var sentence = new SentenceRecord { Id = _stableId, English = _english, Ukrainian = _ukrainian, Source = _source, License = _licenseOverride ?? packLicense, SourceSentenceId = _sourceSentenceId, TranslationSentenceId = _translationSentenceId, Tokens = tokens, Lemmas = _lemmaOverride ?? tokens.ToList(), TargetEntryIds = _targetIds, EntryLevels = _entryLevels, DifficultyLevel = _difficulty, OffListTokenCount = _offList, QualityFlags = _qualityFlags };
            sentence.Validate();
            return sentence;
        }
    }
}

internal static class SentencePackSqlitePrototypeSelfTest
{
    public static void Run()
    {
        string root = Path.Combine(Path.GetTempPath(), "WordDeck-sqlite-selftest-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var first = Create("s1", "I like apples.", "Я люблю яблука.", new[] { "e1", "e2" });
            var second = Create("s2", "We like books.", "Ми любимо книжки.", new[] { "e1", "e3" });
            var pack = new SentencePack { PackId = "sqlite-selftest", Provenance = "synthetic self-test", License = "test-only", Sentences = new List<SentenceRecord> { first, second } };
            string db = Path.Combine(root, "pack.sqlite");
            SentencePackSqlitePrototype.Build(db, pack);
            Require(File.Exists(db) && new FileInfo(db).Length > 0, "SQLite prototype database was not created.");
            IReadOnlyList<SentenceRecord> one = SentencePackSqlitePrototype.LookupAllTargets(db, new[] { "e1" });
            Require(one.Count == 2, "Single-target SQLite lookup returned the wrong count.");
            IReadOnlyList<SentenceRecord> two = SentencePackSqlitePrototype.LookupAllTargets(db, new[] { "e1", "e2" });
            Require(two.Count == 1 && two[0].Id == "s1", "Two-target SQLite intersection is incorrect.");
            Require(two[0].TargetEntryIds.Count == 2 && two[0].EntryLevels.Count == 2, "SQLite round-trip lost target metadata.");
            Require(SentencePackSqlitePrototype.LookupAllTargets(db, new[] { "missing" }).Count == 0, "Missing target lookup should be empty.");
            SentencePackSqliteMetrics measured = SentencePackSqlitePrototype.MeasureQueryOnly(db, new[] { "e1", "e2" });
            Require(measured.ResultCount == 1 && measured.BuildMilliseconds == 0, "Query-only SQLite measurement is incorrect.");
        }
        finally { try { Directory.Delete(root, true); } catch { } }
    }

    private static SentenceRecord Create(string id, string english, string ukrainian, IEnumerable<string> targets)
    {
        List<string> tokens = SentenceTokenizer.Tokenize(english).ToList();
        return new SentenceRecord { Id = id, English = english, Ukrainian = ukrainian, Source = "synthetic", License = "test-only", Tokens = tokens, Lemmas = tokens.ToList(), TargetEntryIds = targets.ToList(), EntryLevels = targets.ToDictionary(x => x, _ => "A1", StringComparer.OrdinalIgnoreCase), DifficultyLevel = "A1" };
    }

    private static void Require(bool condition, string message) { if (!condition) throw new InvalidDataException(message); }
}
