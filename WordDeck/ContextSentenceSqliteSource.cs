using Microsoft.Data.Sqlite;

namespace WordDeck;

internal sealed class ContextSentenceSqliteSource :
    IContextSentenceSource,
    IContextCoverageSource,
    IContextTargetCountCoverageSource,
    IContextNaturalCoverageSource
{
    private const int ScopeChunkSize = 400;
    private const int NaturalScopeChunkSize = 140;
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

    public IReadOnlySet<string> GetCoveredOneTargetIds(IReadOnlyCollection<string> candidateEntryIds) =>
        GetCoveredTargetIds(candidateEntryIds, 1);

    // Stable-ID participation depth retained for backward-compatible R4c evidence.
    // This answers "does this exact stable ID co-occur with N distinct stable IDs?".
    public IReadOnlySet<string> GetCoveredTargetIds(IReadOnlyCollection<string> candidateEntryIds, int requiredTargetCount)
    {
        if (requiredTargetCount is < 1 or > 3)
            throw new ArgumentOutOfRangeException(nameof(requiredTargetCount));

        string[] requested = ContextTargetIds.NormalizeStudyPool(candidateEntryIds);
        if (requested.Length == 0)
            return new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if (requiredTargetCount == 1)
            return _corpus.GetCoveredScopeEntryIds(requested, requireSameScopePartner: false);
        if (requiredTargetCount == 2)
            return _corpus.GetCoveredScopeEntryIds(requested, requireSameScopePartner: true);

        using SqliteConnection connection = OpenReadOnly();
        CreateRequestedScope(connection, requested);
        try
        {
            using SqliteCommand query = connection.CreateCommand();
            query.CommandText = """
                SELECT te.entry_id
                FROM requested_scope rs
                JOIN target_entries te ON te.target_num = rs.target_num
                WHERE EXISTS (
                    SELECT 1
                    FROM sentence_targets st1
                    JOIN sentence_targets st2
                      ON st2.sentence_num = st1.sentence_num
                     AND st2.target_num <> st1.target_num
                    JOIN sentence_targets st3
                      ON st3.sentence_num = st1.sentence_num
                     AND st3.target_num <> st1.target_num
                     AND st3.target_num <> st2.target_num
                    JOIN requested_scope rs2 ON rs2.target_num = st2.target_num
                    JOIN requested_scope rs3 ON rs3.target_num = st3.target_num
                    WHERE st1.target_num = rs.target_num
                    LIMIT 1
                );
                """;
            var result = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            using SqliteDataReader reader = query.ExecuteReader();
            while (reader.Read()) result.Add(reader.GetString(0));
            return result;
        }
        finally
        {
            DropRequestedScope(connection);
        }
    }

    // Product-safe coverage: different Oxford stable IDs with the same written
    // lexical form remain distinct progress identities but count as ONE target word.
    public IReadOnlySet<string> GetCoveredNaturalTargetIds(IReadOnlyList<ContextLexicalTarget> scope, int requiredTargetCount)
    {
        ArgumentNullException.ThrowIfNull(scope);
        if (requiredTargetCount is < 1 or > 3)
            throw new ArgumentOutOfRangeException(nameof(requiredTargetCount));
        if (scope.Count == 0)
            return new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if (scope.Select(target => target.EntryId).Distinct(StringComparer.OrdinalIgnoreCase).Count() != scope.Count)
            throw new InvalidDataException("Natural coverage scope contains duplicate stable IDs.");
        if (scope.Any(target => string.IsNullOrWhiteSpace(target.EntryId) || string.IsNullOrWhiteSpace(target.LexicalKey)))
            throw new InvalidDataException("Natural coverage scope contains a blank stable ID or lexical key.");

        if (requiredTargetCount == 1)
            return GetCoveredOneTargetIds(scope.Select(target => target.EntryId).ToArray());

        using SqliteConnection connection = OpenReadOnly();
        CreateNaturalRequestedScope(connection, scope);
        try
        {
            using SqliteCommand query = connection.CreateCommand();
            query.Parameters.AddWithValue("$required", requiredTargetCount);
            query.CommandText = """
                SELECT requested.entry_id
                FROM temp.requested_natural_scope requested
                WHERE EXISTS (
                    SELECT 1
                    FROM sentence_targets anchor
                    JOIN sentence_targets peer ON peer.sentence_num = anchor.sentence_num
                    JOIN temp.requested_natural_scope peer_requested ON peer_requested.target_num = peer.target_num
                    WHERE anchor.target_num = requested.target_num
                    GROUP BY anchor.sentence_num
                    HAVING COUNT(DISTINCT peer_requested.lexical_key) >= $required
                    LIMIT 1
                )
                ORDER BY requested.ordinal;
                """;
            var result = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            using SqliteDataReader reader = query.ExecuteReader();
            while (reader.Read()) result.Add(reader.GetString(0));
            return result;
        }
        finally
        {
            DropNaturalRequestedScope(connection);
        }
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
        while (reader.Read()) details.Add(reader.GetString(3));
        return details;
    }

    internal IReadOnlyList<string> ExplainNaturalCoveragePlan(
        IReadOnlyList<ContextLexicalTarget> scope,
        int requiredTargetCount)
    {
        if (requiredTargetCount is < 2 or > 3)
            throw new ArgumentOutOfRangeException(nameof(requiredTargetCount));
        if (scope.Count == 0)
            return Array.Empty<string>();

        using SqliteConnection connection = OpenReadOnly();
        CreateNaturalRequestedScope(connection, scope);
        try
        {
            using SqliteCommand command = connection.CreateCommand();
            command.Parameters.AddWithValue("$required", requiredTargetCount);
            command.CommandText = """
                EXPLAIN QUERY PLAN
                SELECT requested.entry_id
                FROM temp.requested_natural_scope requested
                WHERE EXISTS (
                    SELECT 1
                    FROM sentence_targets anchor
                    JOIN sentence_targets peer ON peer.sentence_num = anchor.sentence_num
                    JOIN temp.requested_natural_scope peer_requested ON peer_requested.target_num = peer.target_num
                    WHERE anchor.target_num = requested.target_num
                    GROUP BY anchor.sentence_num
                    HAVING COUNT(DISTINCT peer_requested.lexical_key) >= $required
                    LIMIT 1
                );
                """;
            var details = new List<string>();
            using SqliteDataReader reader = command.ExecuteReader();
            while (reader.Read()) details.Add(reader.GetString(3));
            return details;
        }
        finally
        {
            DropNaturalRequestedScope(connection);
        }
    }

    private static void CreateRequestedScope(SqliteConnection connection, IReadOnlyList<string> requested)
    {
        using (SqliteCommand create = connection.CreateCommand())
        {
            create.CommandText = "DROP TABLE IF EXISTS temp.requested_scope; CREATE TEMP TABLE requested_scope(target_num INTEGER PRIMARY KEY) WITHOUT ROWID;";
            create.ExecuteNonQuery();
        }

        for (int offset = 0; offset < requested.Count; offset += ScopeChunkSize)
        {
            string[] chunk = requested.Skip(offset).Take(ScopeChunkSize).ToArray();
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
    }

    private static void DropRequestedScope(SqliteConnection connection)
    {
        using SqliteCommand drop = connection.CreateCommand();
        drop.CommandText = "DROP TABLE IF EXISTS temp.requested_scope;";
        drop.ExecuteNonQuery();
    }

    private static void CreateNaturalRequestedScope(SqliteConnection connection, IReadOnlyList<ContextLexicalTarget> scope)
    {
        using (SqliteCommand create = connection.CreateCommand())
        {
            create.CommandText = """
                DROP TABLE IF EXISTS temp.requested_natural_scope;
                CREATE TEMP TABLE requested_natural_scope(
                    target_num INTEGER PRIMARY KEY,
                    entry_id TEXT NOT NULL UNIQUE,
                    lexical_key TEXT NOT NULL,
                    ordinal INTEGER NOT NULL
                ) WITHOUT ROWID;
                """;
            create.ExecuteNonQuery();
        }

        for (int offset = 0; offset < scope.Count; offset += NaturalScopeChunkSize)
        {
            ContextLexicalTarget[] chunk = scope.Skip(offset).Take(NaturalScopeChunkSize).ToArray();
            using SqliteCommand insert = connection.CreateCommand();
            var rows = new List<string>(chunk.Length);
            for (int i = 0; i < chunk.Length; i++)
            {
                string idName = "$id" + i;
                string lexicalName = "$lex" + i;
                string ordinalName = "$ord" + i;
                rows.Add($"({idName},{lexicalName},{ordinalName})");
                insert.Parameters.AddWithValue(idName, ContextTargetIds.NormalizeSingle(chunk[i].EntryId));
                insert.Parameters.AddWithValue(lexicalName, chunk[i].LexicalKey);
                insert.Parameters.AddWithValue(ordinalName, chunk[i].Ordinal);
            }
            insert.CommandText = $"""
                WITH requested(entry_id, lexical_key, ordinal) AS (
                    VALUES {string.Join(",", rows)}
                )
                INSERT OR IGNORE INTO temp.requested_natural_scope(target_num, entry_id, lexical_key, ordinal)
                SELECT te.target_num, requested.entry_id, requested.lexical_key, requested.ordinal
                FROM requested
                JOIN target_entries te ON te.entry_id = requested.entry_id;
                """;
            insert.ExecuteNonQuery();
        }
    }

    private static void DropNaturalRequestedScope(SqliteConnection connection)
    {
        using SqliteCommand drop = connection.CreateCommand();
        drop.CommandText = "DROP TABLE IF EXISTS temp.requested_natural_scope;";
        drop.ExecuteNonQuery();
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
