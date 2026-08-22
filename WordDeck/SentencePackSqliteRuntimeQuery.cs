using Microsoft.Data.Sqlite;
using System.Text.Json;

namespace WordDeck;

internal static class SentencePackSqliteRuntimeQuery
{
    public const int DefaultCandidateLimit = 4096;
    private static readonly JsonSerializerOptions JsonOptions = new() { PropertyNameCaseInsensitive = true };

    public static IReadOnlyList<SentenceRecord> LookupAllTargets(
        string databasePath,
        IReadOnlyCollection<string> targetEntryIds,
        int maxResults = DefaultCandidateLimit)
    {
        if (maxResults is < 1 or > DefaultCandidateLimit)
            throw new ArgumentOutOfRangeException(nameof(maxResults), $"SQLite SentencePack runtime queries support 1..{DefaultCandidateLimit} candidates.");

        string[] requestedTargets = targetEntryIds
            .Where(value => !string.IsNullOrWhiteSpace(value))
            .Select(value => value.Trim().ToLowerInvariant())
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
        if (requestedTargets.Length == 0)
            return Array.Empty<SentenceRecord>();
        if (requestedTargets.Length > 3)
            throw new ArgumentOutOfRangeException(nameof(targetEntryIds), "Sentence Coach runtime queries support at most three target entries.");

        using var connection = OpenReadOnly(databasePath);
        string packLicense = RequireMetadata(connection, "license");
        Dictionary<string, long> requestedNumbers = ResolveTargetNumbers(connection, requestedTargets);
        if (requestedNumbers.Count != requestedTargets.Length)
            return Array.Empty<SentenceRecord>();

        using SqliteCommand command = connection.CreateCommand();
        var placeholders = new List<string>(requestedNumbers.Count);
        int index = 0;
        foreach (long numericTarget in requestedNumbers.Values.OrderBy(value => value))
        {
            string name = "$t" + index++;
            placeholders.Add(name);
            command.Parameters.AddWithValue(name, numericTarget);
        }
        command.Parameters.AddWithValue("$required", requestedNumbers.Count);
        command.Parameters.AddWithValue("$limit", maxResults);
        command.CommandText = $"""
            WITH matches AS (
                SELECT sentence_num
                FROM sentence_targets
                WHERE target_num IN ({string.Join(",", placeholders)})
                GROUP BY sentence_num
                HAVING COUNT(*) = $required
                ORDER BY sentence_num
                LIMIT $limit
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
                if (builder is not null) result.Add(builder.Build(packLicense));
                builder = SentenceBuilder.FromRow(reader);
            }
            builder.AddTarget(reader.GetString(12), ValueToLevel(reader.GetInt32(13)));
        }
        if (builder is not null) result.Add(builder.Build(packLicense));
        return result;
    }

    internal static IReadOnlyList<string> ExplainRepresentativePlan(string databasePath, string targetEntryId)
    {
        string target = (targetEntryId ?? string.Empty).Trim().ToLowerInvariant();
        if (target.Length == 0)
            throw new ArgumentException("Target entry ID is required.", nameof(targetEntryId));

        using var connection = OpenReadOnly(databasePath);
        using SqliteCommand resolve = connection.CreateCommand();
        resolve.CommandText = "SELECT target_num FROM target_entries WHERE entry_id = $id;";
        resolve.Parameters.AddWithValue("$id", target);
        object? scalar = resolve.ExecuteScalar();
        if (scalar is null || scalar is DBNull)
            return Array.Empty<string>();

        using SqliteCommand explain = connection.CreateCommand();
        explain.CommandText = "EXPLAIN QUERY PLAN SELECT sentence_num FROM sentence_targets WHERE target_num = $target ORDER BY sentence_num LIMIT 32;";
        explain.Parameters.AddWithValue("$target", Convert.ToInt64(scalar));
        var details = new List<string>();
        using SqliteDataReader reader = explain.ExecuteReader();
        while (reader.Read()) details.Add(reader.GetString(3));
        return details;
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

    private static SqliteConnection OpenReadOnly(string databasePath)
    {
        var builder = new SqliteConnectionStringBuilder
        {
            DataSource = Path.GetFullPath(databasePath),
            Mode = SqliteOpenMode.ReadOnly,
            Cache = SqliteCacheMode.Private,
            Pooling = false
        };
        var connection = new SqliteConnection(builder.ToString());
        connection.Open();
        return connection;
    }

    private static string RequireMetadata(SqliteConnection connection, string key)
    {
        using SqliteCommand command = connection.CreateCommand();
        command.CommandText = "SELECT value FROM metadata WHERE key = $key;";
        command.Parameters.AddWithValue("$key", key);
        string? value = command.ExecuteScalar() as string;
        if (string.IsNullOrWhiteSpace(value))
            throw new InvalidDataException($"SQLite SentencePack is missing {key} metadata.");
        return value;
    }

    private static string ValueToLevel(int value) => value switch
    {
        1 => "A1",
        2 => "A2",
        3 => "B1",
        4 => "B2",
        5 => "C1",
        _ => throw new InvalidDataException($"SQLite SentencePack contains unsupported CEFR level value {value}.")
    };

    private sealed class SentenceBuilder
    {
        public long NumericId { get; }
        private readonly string _stableId;
        private readonly string _english;
        private readonly string _ukrainian;
        private readonly string _source;
        private readonly string _difficulty;
        private readonly string? _licenseOverride;
        private readonly string? _sourceSentenceId;
        private readonly string? _translationSentenceId;
        private readonly int _offList;
        private readonly List<string> _qualityFlags;
        private readonly List<string>? _lemmaOverride;
        private readonly List<string> _targetIds = new();
        private readonly Dictionary<string, string> _entryLevels = new(StringComparer.OrdinalIgnoreCase);

        private SentenceBuilder(long numericId, string stableId, string english, string ukrainian, string source,
            string? licenseOverride, string? sourceSentenceId, string? translationSentenceId, string difficulty,
            int offList, List<string> qualityFlags, List<string>? lemmaOverride)
        {
            NumericId = numericId;
            _stableId = stableId;
            _english = english;
            _ukrainian = ukrainian;
            _source = source;
            _licenseOverride = licenseOverride;
            _sourceSentenceId = sourceSentenceId;
            _translationSentenceId = translationSentenceId;
            _difficulty = difficulty;
            _offList = offList;
            _qualityFlags = qualityFlags;
            _lemmaOverride = lemmaOverride;
        }

        public static SentenceBuilder FromRow(SqliteDataReader reader)
        {
            string? flagsJson = reader.IsDBNull(10) ? null : reader.GetString(10);
            string? lemmasJson = reader.IsDBNull(11) ? null : reader.GetString(11);
            return new SentenceBuilder(
                reader.GetInt64(0), reader.GetString(1), reader.GetString(2), reader.GetString(3), reader.GetString(4),
                reader.IsDBNull(5) ? null : reader.GetString(5), reader.IsDBNull(6) ? null : reader.GetString(6),
                reader.IsDBNull(7) ? null : reader.GetString(7), ValueToLevel(reader.GetInt32(8)), reader.GetInt32(9),
                flagsJson is null ? new List<string>() : JsonSerializer.Deserialize<List<string>>(flagsJson, JsonOptions) ?? new List<string>(),
                lemmasJson is null ? null : JsonSerializer.Deserialize<List<string>>(lemmasJson, JsonOptions));
        }

        public void AddTarget(string entryId, string level)
        {
            _targetIds.Add(entryId);
            _entryLevels[entryId] = level;
        }

        public SentenceRecord Build(string packLicense)
        {
            List<string> tokens = SentenceTokenizer.Tokenize(_english).ToList();
            var sentence = new SentenceRecord
            {
                Id = _stableId,
                English = _english,
                Ukrainian = _ukrainian,
                Source = _source,
                License = _licenseOverride ?? packLicense,
                SourceSentenceId = _sourceSentenceId,
                TranslationSentenceId = _translationSentenceId,
                Tokens = tokens,
                Lemmas = _lemmaOverride ?? tokens.ToList(),
                TargetEntryIds = _targetIds,
                EntryLevels = _entryLevels,
                DifficultyLevel = _difficulty,
                OffListTokenCount = _offList,
                QualityFlags = _qualityFlags
            };
            sentence.Validate();
            return sentence;
        }
    }
}
