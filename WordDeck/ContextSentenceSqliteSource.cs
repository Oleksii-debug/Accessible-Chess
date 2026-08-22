using Microsoft.Data.Sqlite;

namespace WordDeck;

internal sealed class ContextSentenceSqliteSource : IContextSentenceSource, IContextCoverageSource
{
    private readonly string _databasePath;
    private readonly SentencePackSqliteCorpus _corpus;

    public ContextSourceDescriptor Descriptor { get; }

    public ContextSentenceSqliteSource(string databasePath, ContextCorpusKind kind = ContextCorpusKind.RealCorpus)
    {
        if (string.IsNullOrWhiteSpace(databasePath))
            throw new ArgumentException("SQLite context database path is required.", nameof(databasePath));
        _databasePath = Path.GetFullPath(databasePath);
        _corpus = new SentencePackSqliteCorpus(_databasePath);
        Descriptor = new ContextSourceDescriptor(
            _corpus.PackId,
            kind,
            _corpus.Provenance,
            _corpus.License,
            PrivacyLocalOnly: kind == ContextCorpusKind.LocalUserText);
        Descriptor.Validate();
    }

    public IReadOnlyList<ContextSentenceEnvelope> FindByTargets(IReadOnlyCollection<string> targetEntryIds, int maxCandidates)
    {
        string[] required = ContextTargetIds.NormalizeRequired(targetEntryIds);
        IReadOnlyList<SentenceRecord> records = SentencePackSqliteRuntimeQuery.LookupAllTargets(_databasePath, required, maxCandidates);
        return records.Select(sentence => new ContextSentenceEnvelope(
            sentence,
            Descriptor,
            null,
            ContextGrammarMetadata.ExtractFromQualityFlags(sentence.QualityFlags))).ToArray();
    }

    public IReadOnlySet<string> GetCoveredOneTargetIds(IReadOnlyCollection<string> candidateEntryIds)
    {
        string[] requested = ContextTargetIds.NormalizeStudyPool(candidateEntryIds);
        return _corpus.GetCoveredScopeEntryIds(requested, requireSameScopePartner: false);
    }

    internal IReadOnlyList<string> ExplainIntersectionPlan(IReadOnlyCollection<string> targetEntryIds, int maxCandidates = 32)
    {
        string[] required = ContextTargetIds.NormalizeRequired(targetEntryIds);
        if (maxCandidates is < 1 or > SentencePackSqliteRuntimeQuery.DefaultCandidateLimit)
            throw new ArgumentOutOfRangeException(nameof(maxCandidates));

        using SqliteConnection connection = OpenReadOnly();
        Dictionary<string, long> targets = ResolveTargetNumbers(connection, required);
        if (targets.Count != required.Length)
            return Array.Empty<string>();

        using SqliteCommand command = connection.CreateCommand();
        var placeholders = new List<string>(targets.Count);
        int index = 0;
        foreach (long numericTarget in targets.Values.OrderBy(value => value))
        {
            string name = "$t" + index++;
            placeholders.Add(name);
            command.Parameters.AddWithValue(name, numericTarget);
        }
        command.Parameters.AddWithValue("$required", targets.Count);
        command.Parameters.AddWithValue("$limit", maxCandidates);
        command.CommandText = $"""
            EXPLAIN QUERY PLAN
            WITH matches AS (
                SELECT sentence_num
                FROM sentence_targets
                WHERE target_num IN ({string.Join(",", placeholders)})
                GROUP BY sentence_num
                HAVING COUNT(*) = $required
                ORDER BY sentence_num
                LIMIT $limit
            )
            SELECT s.sentence_num
            FROM matches m
            JOIN sentences s ON s.sentence_num = m.sentence_num
            ORDER BY s.sentence_num;
            """;

        var details = new List<string>();
        using SqliteDataReader reader = command.ExecuteReader();
        while (reader.Read())
            details.Add(reader.GetString(3));
        return details;
    }

    private Dictionary<string, long> ResolveTargetNumbers(SqliteConnection connection, IReadOnlyList<string> targetEntryIds)
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
        while (reader.Read())
            result[reader.GetString(0)] = reader.GetInt64(1);
        return result;
    }

    private SqliteConnection OpenReadOnly()
    {
        var builder = new SqliteConnectionStringBuilder
        {
            DataSource = _databasePath,
            Mode = SqliteOpenMode.ReadOnly,
            Cache = SqliteCacheMode.Private,
            Pooling = false
        };
        var connection = new SqliteConnection(builder.ToString());
        connection.Open();
        return connection;
    }
}
