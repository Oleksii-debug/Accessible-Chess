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
    private const int SchemaVersion = 1;
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
                CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE sentences(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE targets(entry_id TEXT NOT NULL, sentence_id TEXT NOT NULL, PRIMARY KEY(entry_id, sentence_id));
                CREATE INDEX ix_targets_sentence ON targets(sentence_id);
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

        using SqliteCommand sentenceCommand = connection.CreateCommand();
        sentenceCommand.Transaction = transaction;
        sentenceCommand.CommandText = "INSERT INTO sentences(id, payload) VALUES ($id, $payload);";
        SqliteParameter sentenceId = sentenceCommand.Parameters.Add("$id", SqliteType.Text);
        SqliteParameter payload = sentenceCommand.Parameters.Add("$payload", SqliteType.Text);

        using SqliteCommand targetCommand = connection.CreateCommand();
        targetCommand.Transaction = transaction;
        targetCommand.CommandText = "INSERT OR IGNORE INTO targets(entry_id, sentence_id) VALUES ($entry, $sentence);";
        SqliteParameter entryId = targetCommand.Parameters.Add("$entry", SqliteType.Text);
        SqliteParameter targetSentenceId = targetCommand.Parameters.Add("$sentence", SqliteType.Text);

        foreach (SentenceRecord sentence in pack.Sentences)
        {
            sentenceId.Value = sentence.Id;
            payload.Value = JsonSerializer.Serialize(sentence, JsonOptions);
            sentenceCommand.ExecuteNonQuery();

            foreach (string target in sentence.TargetEntryIds.Distinct(StringComparer.OrdinalIgnoreCase))
            {
                entryId.Value = target.ToLowerInvariant();
                targetSentenceId.Value = sentence.Id;
                targetCommand.ExecuteNonQuery();
            }
        }

        transaction.Commit();
        using SqliteCommand optimize = connection.CreateCommand();
        optimize.CommandText = "PRAGMA optimize;";
        optimize.ExecuteNonQuery();
    }

    public static IReadOnlyList<SentenceRecord> LookupAllTargets(string databasePath, IReadOnlyCollection<string> targetEntryIds)
    {
        string[] targets = targetEntryIds
            .Where(value => !string.IsNullOrWhiteSpace(value))
            .Select(value => value.Trim().ToLowerInvariant())
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
        if (targets.Length == 0) return Array.Empty<SentenceRecord>();

        using var connection = Open(databasePath, readOnly: true);
        ValidateMetadata(connection);
        using SqliteCommand command = connection.CreateCommand();
        var placeholders = new List<string>(targets.Length);
        for (int i = 0; i < targets.Length; i++)
        {
            string name = "$t" + i;
            placeholders.Add(name);
            command.Parameters.AddWithValue(name, targets[i]);
        }
        command.Parameters.AddWithValue("$required", targets.Length);
        command.CommandText = $"""
            SELECT s.payload
            FROM sentences s
            JOIN (
                SELECT sentence_id
                FROM targets
                WHERE entry_id IN ({string.Join(",", placeholders)})
                GROUP BY sentence_id
                HAVING COUNT(DISTINCT entry_id) = $required
            ) m ON m.sentence_id = s.id
            ORDER BY s.id;
            """;

        var result = new List<SentenceRecord>();
        using SqliteDataReader reader = command.ExecuteReader();
        while (reader.Read())
        {
            SentenceRecord sentence = JsonSerializer.Deserialize<SentenceRecord>(reader.GetString(0), JsonOptions)
                ?? throw new InvalidDataException("SQLite SentencePack contains an empty sentence payload.");
            sentence.Validate();
            result.Add(sentence);
        }
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
        return new SentencePackSqliteMetrics(
            new FileInfo(databasePath).Length,
            build.ElapsedMilliseconds,
            query.ElapsedMilliseconds,
            managedAfter - managedBefore,
            workingAfter - workingBefore,
            results.Count);
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
        return new SentencePackSqliteMetrics(
            new FileInfo(databasePath).Length,
            0,
            query.ElapsedMilliseconds,
            managedAfter - managedBefore,
            workingAfter - workingBefore,
            results.Count);
    }

    private static SqliteConnection Open(string databasePath, bool readOnly)
    {
        var builder = new SqliteConnectionStringBuilder
        {
            DataSource = Path.GetFullPath(databasePath),
            Mode = readOnly ? SqliteOpenMode.ReadOnly : SqliteOpenMode.ReadWriteCreate,
            Cache = SqliteCacheMode.Private
        };
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

    private static void ValidateMetadata(SqliteConnection connection)
    {
        using SqliteCommand command = connection.CreateCommand();
        command.CommandText = "SELECT value FROM metadata WHERE key='schema_version';";
        object? value = command.ExecuteScalar();
        if (value is null || !int.TryParse(Convert.ToString(value), out int version) || version != SchemaVersion)
            throw new InvalidDataException("Unsupported or missing SQLite SentencePack schema version.");
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
            var pack = new SentencePack
            {
                PackId = "sqlite-selftest",
                Provenance = "synthetic self-test",
                License = "test-only",
                Sentences = new List<SentenceRecord> { first, second }
            };
            string db = Path.Combine(root, "pack.sqlite");
            SentencePackSqlitePrototype.Build(db, pack);
            Require(File.Exists(db) && new FileInfo(db).Length > 0, "SQLite prototype database was not created.");
            IReadOnlyList<SentenceRecord> one = SentencePackSqlitePrototype.LookupAllTargets(db, new[] { "e1" });
            Require(one.Count == 2, "Single-target SQLite lookup returned the wrong count.");
            IReadOnlyList<SentenceRecord> two = SentencePackSqlitePrototype.LookupAllTargets(db, new[] { "e1", "e2" });
            Require(two.Count == 1 && two[0].Id == "s1", "Two-target SQLite intersection is incorrect.");
            Require(SentencePackSqlitePrototype.LookupAllTargets(db, new[] { "missing" }).Count == 0, "Missing target lookup should be empty.");
            SentencePackSqliteMetrics measured = SentencePackSqlitePrototype.MeasureQueryOnly(db, new[] { "e1", "e2" });
            Require(measured.ResultCount == 1 && measured.BuildMilliseconds == 0, "Query-only SQLite measurement is incorrect.");
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    private static SentenceRecord Create(string id, string english, string ukrainian, IEnumerable<string> targets)
    {
        List<string> tokens = SentenceTokenizer.Tokenize(english).ToList();
        return new SentenceRecord
        {
            Id = id,
            English = english,
            Ukrainian = ukrainian,
            Source = "synthetic",
            License = "test-only",
            Tokens = tokens,
            Lemmas = tokens.ToList(),
            TargetEntryIds = targets.ToList(),
            EntryLevels = targets.ToDictionary(x => x, _ => "A1", StringComparer.OrdinalIgnoreCase),
            DifficultyLevel = "A1"
        };
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }
}
