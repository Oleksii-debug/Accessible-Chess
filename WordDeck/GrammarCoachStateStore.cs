using Microsoft.Data.Sqlite;

namespace WordDeck;

internal sealed record GrammarAttemptRecord(
    long AttemptId,
    string ExerciseId,
    string SkillId,
    bool Correct,
    GrammarErrorKind ErrorKind,
    string SubmittedAnswer,
    string ExpectedAnswer,
    DateTimeOffset AttemptedUtc);

internal sealed class GrammarCoachStateStore
{
    private const int CurrentSchemaVersion = 1;
    private readonly string _databasePath;

    public GrammarCoachStateStore(string databasePath)
    {
        if (string.IsNullOrWhiteSpace(databasePath))
            throw new ArgumentException("Grammar profile database path is required.", nameof(databasePath));
        _databasePath = Path.GetFullPath(databasePath);
    }

    public void Initialize()
    {
        string? directory = Path.GetDirectoryName(_databasePath);
        if (!string.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);

        using SqliteConnection connection = Open();
        using SqliteCommand bootstrap = connection.CreateCommand();
        bootstrap.CommandText = "CREATE TABLE IF NOT EXISTS grammar_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);";
        bootstrap.ExecuteNonQuery();

        int version = ReadSchemaVersion(connection);
        if (version > CurrentSchemaVersion)
            throw new InvalidDataException($"Grammar profile schema {version} is newer than supported schema {CurrentSchemaVersion}; data was not modified.");
        if (version < CurrentSchemaVersion)
        {
            if (File.Exists(_databasePath) && new FileInfo(_databasePath).Length > 0)
                CreateBackup("before-migration");
            Migrate(connection, version);
        }
    }

    public string CreateBackup(string reason)
    {
        string safeReason = string.Concat((reason ?? "backup").Where(ch => char.IsLetterOrDigit(ch) || ch is '-' or '_'));
        if (safeReason.Length == 0) safeReason = "backup";
        string backupPath = _databasePath + $".{DateTimeOffset.UtcNow:yyyyMMddHHmmssfff}.{safeReason}.backup.sqlite";
        string? directory = Path.GetDirectoryName(backupPath);
        if (!string.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);

        using SqliteConnection source = Open();
        using var destination = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = backupPath, Mode = SqliteOpenMode.ReadWriteCreate }.ToString());
        destination.Open();
        source.BackupDatabase(destination);
        return backupPath;
    }

    public IReadOnlyDictionary<string, GrammarSkillMastery> LoadMastery()
    {
        Initialize();
        using SqliteConnection connection = Open();
        using SqliteCommand command = connection.CreateCommand();
        command.CommandText = "SELECT skill_id,attempts,correct_count,mastery,updated_utc FROM grammar_mastery ORDER BY skill_id";
        using SqliteDataReader reader = command.ExecuteReader();
        var result = new Dictionary<string, GrammarSkillMastery>(StringComparer.OrdinalIgnoreCase);
        while (reader.Read())
        {
            string id = reader.GetString(0);
            result[id] = new GrammarSkillMastery(id, reader.GetInt32(1), reader.GetInt32(2), reader.GetDouble(3), DateTimeOffset.Parse(reader.GetString(4)));
        }
        return result;
    }

    public GrammarSkillMastery RecordAttempt(GrammarExercise exercise, GrammarEvaluation evaluation, string? submittedAnswer)
    {
        ArgumentNullException.ThrowIfNull(exercise);
        ArgumentNullException.ThrowIfNull(evaluation);
        exercise.Validate();
        Initialize();

        using SqliteConnection connection = Open();
        using SqliteTransaction transaction = connection.BeginTransaction();
        try
        {
            GrammarSkillMastery current = LoadMastery(connection, transaction, exercise.SkillId) ?? GrammarSkillMastery.Empty(exercise.SkillId);
            GrammarSkillMastery next = GrammarMasteryEngine.Apply(current, evaluation);
            using (SqliteCommand upsert = connection.CreateCommand())
            {
                upsert.Transaction = transaction;
                upsert.CommandText = """
                    INSERT INTO grammar_mastery(skill_id,attempts,correct_count,mastery,updated_utc)
                    VALUES($skill,$attempts,$correct,$mastery,$updated)
                    ON CONFLICT(skill_id) DO UPDATE SET
                      attempts=excluded.attempts,
                      correct_count=excluded.correct_count,
                      mastery=excluded.mastery,
                      updated_utc=excluded.updated_utc;
                    """;
                upsert.Parameters.AddWithValue("$skill", next.SkillId);
                upsert.Parameters.AddWithValue("$attempts", next.Attempts);
                upsert.Parameters.AddWithValue("$correct", next.Correct);
                upsert.Parameters.AddWithValue("$mastery", next.Mastery);
                upsert.Parameters.AddWithValue("$updated", next.UpdatedUtc.ToString("O"));
                upsert.ExecuteNonQuery();
            }

            using (SqliteCommand attempt = connection.CreateCommand())
            {
                attempt.Transaction = transaction;
                attempt.CommandText = """
                    INSERT INTO grammar_attempt(exercise_id,skill_id,correct,error_kind,submitted_answer,expected_answer,attempted_utc)
                    VALUES($exercise,$skill,$correct,$error,$submitted,$expected,$utc);
                    """;
                attempt.Parameters.AddWithValue("$exercise", exercise.ExerciseId);
                attempt.Parameters.AddWithValue("$skill", exercise.SkillId);
                attempt.Parameters.AddWithValue("$correct", evaluation.Correct ? 1 : 0);
                attempt.Parameters.AddWithValue("$error", (int)evaluation.ErrorKind);
                attempt.Parameters.AddWithValue("$submitted", submittedAnswer ?? string.Empty);
                attempt.Parameters.AddWithValue("$expected", evaluation.ExpectedAnswer);
                attempt.Parameters.AddWithValue("$utc", next.UpdatedUtc.ToString("O"));
                attempt.ExecuteNonQuery();
            }
            transaction.Commit();
            return next;
        }
        catch
        {
            transaction.Rollback();
            throw;
        }
    }

    public IReadOnlyList<GrammarAttemptRecord> LoadRecentAttempts(int limit = 100)
    {
        if (limit is < 1 or > 10000) throw new ArgumentOutOfRangeException(nameof(limit));
        Initialize();
        using SqliteConnection connection = Open();
        using SqliteCommand command = connection.CreateCommand();
        command.CommandText = """
            SELECT attempt_id,exercise_id,skill_id,correct,error_kind,submitted_answer,expected_answer,attempted_utc
            FROM grammar_attempt ORDER BY attempt_id DESC LIMIT $limit;
            """;
        command.Parameters.AddWithValue("$limit", limit);
        using SqliteDataReader reader = command.ExecuteReader();
        var result = new List<GrammarAttemptRecord>();
        while (reader.Read())
            result.Add(new GrammarAttemptRecord(reader.GetInt64(0), reader.GetString(1), reader.GetString(2), reader.GetInt32(3) != 0,
                (GrammarErrorKind)reader.GetInt32(4), reader.GetString(5), reader.GetString(6), DateTimeOffset.Parse(reader.GetString(7))));
        return result;
    }

    public void ImportMasterySnapshot(IEnumerable<GrammarSkillMastery> snapshot)
    {
        ArgumentNullException.ThrowIfNull(snapshot);
        GrammarSkillMastery[] rows = snapshot.ToArray();
        foreach (GrammarSkillMastery row in rows)
        {
            if (!GrammarSkillCatalog.ById.ContainsKey(row.SkillId)) throw new InvalidDataException("Grammar snapshot contains unknown skill id " + row.SkillId);
            if (row.Attempts < 0 || row.Correct < 0 || row.Correct > row.Attempts || row.Mastery is < 0 or > 1)
                throw new InvalidDataException("Grammar snapshot contains invalid mastery counters.");
        }
        Initialize();
        CreateBackup("before-import");
        using SqliteConnection connection = Open();
        using SqliteTransaction transaction = connection.BeginTransaction();
        try
        {
            foreach (GrammarSkillMastery row in rows)
            {
                using SqliteCommand command = connection.CreateCommand();
                command.Transaction = transaction;
                command.CommandText = """
                    INSERT INTO grammar_mastery(skill_id,attempts,correct_count,mastery,updated_utc)
                    VALUES($skill,$attempts,$correct,$mastery,$updated)
                    ON CONFLICT(skill_id) DO UPDATE SET attempts=excluded.attempts,correct_count=excluded.correct_count,mastery=excluded.mastery,updated_utc=excluded.updated_utc;
                    """;
                command.Parameters.AddWithValue("$skill", row.SkillId);
                command.Parameters.AddWithValue("$attempts", row.Attempts);
                command.Parameters.AddWithValue("$correct", row.Correct);
                command.Parameters.AddWithValue("$mastery", row.Mastery);
                command.Parameters.AddWithValue("$updated", row.UpdatedUtc.ToString("O"));
                command.ExecuteNonQuery();
            }
            transaction.Commit();
        }
        catch
        {
            transaction.Rollback();
            throw;
        }
    }

    private static GrammarSkillMastery? LoadMastery(SqliteConnection connection, SqliteTransaction transaction, string skillId)
    {
        using SqliteCommand command = connection.CreateCommand();
        command.Transaction = transaction;
        command.CommandText = "SELECT attempts,correct_count,mastery,updated_utc FROM grammar_mastery WHERE skill_id=$skill";
        command.Parameters.AddWithValue("$skill", skillId);
        using SqliteDataReader reader = command.ExecuteReader();
        if (!reader.Read()) return null;
        return new GrammarSkillMastery(skillId, reader.GetInt32(0), reader.GetInt32(1), reader.GetDouble(2), DateTimeOffset.Parse(reader.GetString(3)));
    }

    private void Migrate(SqliteConnection connection, int fromVersion)
    {
        using SqliteTransaction transaction = connection.BeginTransaction();
        try
        {
            if (fromVersion == 0)
            {
                using SqliteCommand command = connection.CreateCommand();
                command.Transaction = transaction;
                command.CommandText = """
                    CREATE TABLE IF NOT EXISTS grammar_mastery(
                        skill_id TEXT PRIMARY KEY,
                        attempts INTEGER NOT NULL CHECK(attempts >= 0),
                        correct_count INTEGER NOT NULL CHECK(correct_count >= 0 AND correct_count <= attempts),
                        mastery REAL NOT NULL CHECK(mastery >= 0 AND mastery <= 1),
                        updated_utc TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS grammar_attempt(
                        attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        exercise_id TEXT NOT NULL,
                        skill_id TEXT NOT NULL,
                        correct INTEGER NOT NULL CHECK(correct IN (0,1)),
                        error_kind INTEGER NOT NULL,
                        submitted_answer TEXT NOT NULL,
                        expected_answer TEXT NOT NULL,
                        attempted_utc TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS ix_grammar_attempt_skill_time ON grammar_attempt(skill_id,attempt_id DESC);
                    INSERT INTO grammar_metadata(key,value) VALUES('schema_version','1')
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value;
                    """;
                command.ExecuteNonQuery();
                fromVersion = 1;
            }
            if (fromVersion != CurrentSchemaVersion) throw new InvalidDataException("No grammar profile migration path is available.");
            transaction.Commit();
        }
        catch
        {
            transaction.Rollback();
            throw;
        }
    }

    private static int ReadSchemaVersion(SqliteConnection connection)
    {
        using SqliteCommand command = connection.CreateCommand();
        command.CommandText = "SELECT value FROM grammar_metadata WHERE key='schema_version'";
        object? value = command.ExecuteScalar();
        return value is null ? 0 : int.Parse(Convert.ToString(value)!, System.Globalization.CultureInfo.InvariantCulture);
    }

    private SqliteConnection Open()
    {
        var builder = new SqliteConnectionStringBuilder { DataSource = _databasePath, Mode = SqliteOpenMode.ReadWriteCreate, Cache = SqliteCacheMode.Shared };
        var connection = new SqliteConnection(builder.ToString());
        connection.Open();
        using SqliteCommand pragma = connection.CreateCommand();
        pragma.CommandText = "PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000; PRAGMA journal_mode=WAL;";
        pragma.ExecuteNonQuery();
        return connection;
    }
}

internal sealed record GrammarPlanningCandidate(GrammarExercise Exercise, double PriorityScore, string Reason);

internal static class GrammarPracticePlanner
{
    public static IReadOnlyList<GrammarPlanningCandidate> Plan(
        IEnumerable<GrammarExercise> exercises,
        IReadOnlyDictionary<string, GrammarSkillMastery> mastery,
        IReadOnlySet<string>? weakVocabularyEntryIds,
        int maxItems = 30)
    {
        ArgumentNullException.ThrowIfNull(exercises);
        ArgumentNullException.ThrowIfNull(mastery);
        if (maxItems is < 1 or > 200) throw new ArgumentOutOfRangeException(nameof(maxItems));
        weakVocabularyEntryIds ??= new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var available = new HashSet<string>(GrammarMasteryEngine.AvailableSkills(mastery), StringComparer.OrdinalIgnoreCase);
        foreach (GrammarSkill root in GrammarSkillCatalog.All.Where(x => x.PrerequisiteSkillIds.Count == 0)) available.Add(root.SkillId);

        return exercises
            .Where(e => available.Contains(e.SkillId))
            .Select(e =>
            {
                e.Validate();
                double current = mastery.TryGetValue(e.SkillId, out GrammarSkillMastery? state) ? state.Mastery : 0;
                int weakOverlap = e.TargetStableEntryIds.Count(id => weakVocabularyEntryIds.Contains(id));
                double score = (1.0 - current) * 1000.0 + weakOverlap * 150.0;
                string reason = $"skill mastery={current:0.000}; weak vocabulary overlap={weakOverlap}";
                return new GrammarPlanningCandidate(e, score, reason);
            })
            .OrderByDescending(x => x.PriorityScore)
            .ThenBy(x => x.Exercise.SkillId, StringComparer.Ordinal)
            .ThenBy(x => x.Exercise.ExerciseId, StringComparer.Ordinal)
            .Take(maxItems)
            .ToArray();
    }
}

internal sealed record GrammarSentenceEvidence(
    string SourceId,
    string Provenance,
    string License,
    string EnglishSentence,
    IReadOnlyList<string> GrammarSkillIds,
    IReadOnlyList<string> StableEntryIds,
    bool PrivateLocalOnly = false)
{
    public void Validate()
    {
        if (string.IsNullOrWhiteSpace(SourceId) || string.IsNullOrWhiteSpace(Provenance) || string.IsNullOrWhiteSpace(License) || string.IsNullOrWhiteSpace(EnglishSentence))
            throw new InvalidDataException("Grammar sentence evidence must carry source, provenance, license and sentence text.");
        if (GrammarSkillIds.Any(id => !GrammarSkillCatalog.ById.ContainsKey(id)))
            throw new InvalidDataException("Grammar sentence evidence references an unknown grammar skill.");
    }
}
