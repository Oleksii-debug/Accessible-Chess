using Microsoft.Data.Sqlite;

namespace WordDeck;

internal sealed class SentencePackSqliteCorpus : ISentenceCorpus
{
    private const int SupportedSchemaVersion = 2;
    private const int ScopeChunkSize = 400;
    private readonly string _databasePath;

    public string PackId { get; }
    public string License { get; }
    public int SentenceCount { get; }

    public SentencePackSqliteCorpus(string databasePath)
    {
        if (string.IsNullOrWhiteSpace(databasePath))
            throw new ArgumentException("SQLite SentencePack path is required.", nameof(databasePath));

        _databasePath = Path.GetFullPath(databasePath);
        if (!File.Exists(_databasePath))
            throw new FileNotFoundException("SQLite SentencePack was not found.", _databasePath);

        using var connection = OpenReadOnly(_databasePath);
        Dictionary<string, string> metadata = ReadMetadata(connection);
        if (!int.TryParse(metadata.GetValueOrDefault("schema_version"), out int schemaVersion) || schemaVersion != SupportedSchemaVersion)
            throw new InvalidDataException("Unsupported SQLite SentencePack schema version.");

        PackId = Require(metadata, "pack_id");
        License = Require(metadata, "license");
        string sourceLanguage = Require(metadata, "source_language");
        string targetLanguage = Require(metadata, "target_language");
        if (!sourceLanguage.Equals("en", StringComparison.OrdinalIgnoreCase) || !targetLanguage.Equals("uk", StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("This Sentence Coach build currently requires an EN-UA SQLite corpus.");

        using SqliteCommand count = connection.CreateCommand();
        count.CommandText = "SELECT COUNT(*) FROM sentences;";
        SentenceCount = checked(Convert.ToInt32(count.ExecuteScalar()));
        if (SentenceCount <= 0)
            throw new InvalidDataException("SQLite SentencePack contains no sentences.");
    }

    public IReadOnlyList<SentenceRecord> LookupByEntryId(string entryId) =>
        SentencePackSqlitePrototype.LookupAllTargets(_databasePath, new[] { entryId });

    public IReadOnlyList<SentenceRecord> LookupAllTargets(IReadOnlyCollection<string> targetEntryIds) =>
        SentencePackSqlitePrototype.LookupAllTargets(_databasePath, targetEntryIds);

    public HashSet<string> GetCoveredScopeEntryIds(IReadOnlyCollection<string> scopeEntryIds, bool requireSameScopePartner)
    {
        string[] scope = scopeEntryIds
            .Where(id => !string.IsNullOrWhiteSpace(id))
            .Select(id => id.Trim().ToLowerInvariant())
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
        var result = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if (scope.Length == 0)
            return result;

        using var connection = OpenReadOnly(_databasePath);
        using (SqliteCommand create = connection.CreateCommand())
        {
            create.CommandText = "CREATE TEMP TABLE requested_scope(target_num INTEGER PRIMARY KEY) WITHOUT ROWID;";
            create.ExecuteNonQuery();
        }

        for (int offset = 0; offset < scope.Length; offset += ScopeChunkSize)
        {
            string[] chunk = scope.Skip(offset).Take(ScopeChunkSize).ToArray();
            using SqliteCommand insert = connection.CreateCommand();
            var placeholders = new List<string>(chunk.Length);
            for (int i = 0; i < chunk.Length; i++)
            {
                string name = "$id" + i;
                placeholders.Add(name);
                insert.Parameters.AddWithValue(name, chunk[i]);
            }
            insert.CommandText = $"INSERT OR IGNORE INTO requested_scope(target_num) SELECT target_num FROM target_entries WHERE entry_id IN ({string.Join(",", placeholders)});";
            insert.ExecuteNonQuery();
        }

        using SqliteCommand query = connection.CreateCommand();
        query.CommandText = requireSameScopePartner
            ? """
                SELECT te.entry_id
                FROM requested_scope rs
                JOIN target_entries te ON te.target_num = rs.target_num
                WHERE EXISTS (
                    SELECT 1
                    FROM sentence_targets st1
                    JOIN sentence_targets st2
                      ON st2.sentence_num = st1.sentence_num
                     AND st2.target_num <> st1.target_num
                    JOIN requested_scope rs2 ON rs2.target_num = st2.target_num
                    WHERE st1.target_num = rs.target_num
                    LIMIT 1
                );
                """
            : """
                SELECT te.entry_id
                FROM requested_scope rs
                JOIN target_entries te ON te.target_num = rs.target_num
                WHERE EXISTS (
                    SELECT 1
                    FROM sentence_targets st
                    WHERE st.target_num = rs.target_num
                    LIMIT 1
                );
                """;

        using SqliteDataReader reader = query.ExecuteReader();
        while (reader.Read())
            result.Add(reader.GetString(0));
        return result;
    }

    private static SqliteConnection OpenReadOnly(string path)
    {
        var builder = new SqliteConnectionStringBuilder
        {
            DataSource = path,
            Mode = SqliteOpenMode.ReadOnly,
            Cache = SqliteCacheMode.Private
        };
        var connection = new SqliteConnection(builder.ToString());
        connection.Open();
        return connection;
    }

    private static Dictionary<string, string> ReadMetadata(SqliteConnection connection)
    {
        using SqliteCommand command = connection.CreateCommand();
        command.CommandText = "SELECT key, value FROM metadata;";
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        using SqliteDataReader reader = command.ExecuteReader();
        while (reader.Read())
            result[reader.GetString(0)] = reader.GetString(1);
        return result;
    }

    private static string Require(IReadOnlyDictionary<string, string> metadata, string key)
    {
        if (!metadata.TryGetValue(key, out string? value) || string.IsNullOrWhiteSpace(value))
            throw new InvalidDataException($"SQLite SentencePack is missing {key} metadata.");
        return value;
    }
}
