using Microsoft.Data.Sqlite;

namespace WordDeck;

internal sealed class SentencePackSqliteCorpus : ISentenceCorpus
{
    private const int SupportedSchemaVersion = 2;
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
