namespace WordDeck;

internal sealed record ContextLexicalTarget(string EntryId, string LexicalKey, int Ordinal);

internal sealed class ContextTargetLexicon
{
    private readonly Dictionary<string, string> _lexicalKeyByEntryId;
    private readonly Dictionary<string, string[]> _entryIdsByLexicalKey;

    public string DictionaryId { get; }
    public int EntryCount => _lexicalKeyByEntryId.Count;

    public ContextTargetLexicon(DictionaryPackage dictionary)
    {
        ArgumentNullException.ThrowIfNull(dictionary);
        DictionaryId = dictionary.Id;
        _lexicalKeyByEntryId = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        var groups = new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase);

        foreach (DictionaryEntry entry in dictionary.Entries)
        {
            string id = ContextTargetIds.NormalizeSingle(entry.Id);
            string key = NormalizeLexicalKey(entry.Source);
            if (!_lexicalKeyByEntryId.TryAdd(id, key))
                throw new InvalidDataException($"Context lexical catalog contains duplicate stable ID {id}.");
            if (!groups.TryGetValue(key, out List<string>? ids))
            {
                ids = new List<string>();
                groups[key] = ids;
            }
            ids.Add(id);
        }

        _entryIdsByLexicalKey = groups.ToDictionary(
            pair => pair.Key,
            pair => pair.Value.Distinct(StringComparer.OrdinalIgnoreCase).OrderBy(id => id, StringComparer.Ordinal).ToArray(),
            StringComparer.OrdinalIgnoreCase);
    }

    internal ContextTargetLexicon(string dictionaryId, IEnumerable<(string EntryId, string Source)> entries)
    {
        DictionaryId = string.IsNullOrWhiteSpace(dictionaryId) ? "context-fixture" : dictionaryId.Trim();
        _lexicalKeyByEntryId = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        var groups = new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase);
        foreach ((string rawId, string source) in entries)
        {
            string id = ContextTargetIds.NormalizeSingle(rawId);
            string key = NormalizeLexicalKey(source);
            if (!_lexicalKeyByEntryId.TryAdd(id, key))
                throw new InvalidDataException($"Context lexical catalog contains duplicate stable ID {id}.");
            if (!groups.TryGetValue(key, out List<string>? ids))
            {
                ids = new List<string>();
                groups[key] = ids;
            }
            ids.Add(id);
        }
        _entryIdsByLexicalKey = groups.ToDictionary(
            pair => pair.Key,
            pair => pair.Value.Distinct(StringComparer.OrdinalIgnoreCase).OrderBy(id => id, StringComparer.Ordinal).ToArray(),
            StringComparer.OrdinalIgnoreCase);
    }

    public string LexicalKeyFor(string entryId)
    {
        string id = ContextTargetIds.NormalizeSingle(entryId);
        return _lexicalKeyByEntryId.TryGetValue(id, out string? key)
            ? key
            : throw new InvalidDataException($"Stable ID {id} is not present in context lexical catalog {DictionaryId}.");
    }

    public string LexicalKeyForOrStableId(string entryId)
    {
        string id = ContextTargetIds.NormalizeSingle(entryId);
        return _lexicalKeyByEntryId.TryGetValue(id, out string? key) ? key : "id:" + id;
    }

    public IReadOnlyList<string> StableIdsForLexicalKey(string lexicalKey) =>
        _entryIdsByLexicalKey.TryGetValue(lexicalKey, out string[]? ids) ? ids : Array.Empty<string>();

    public bool IsAmbiguousStableIdentity(string entryId) =>
        StableIdsForLexicalKey(LexicalKeyFor(entryId)).Count > 1;

    public void EnsureDistinctLexicalTargets(IEnumerable<string> targetEntryIds)
    {
        string[] ids = ContextTargetIds.NormalizeRequired(targetEntryIds);
        string[] keys = ids.Select(LexicalKeyFor).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        if (keys.Length != ids.Length)
            throw new InvalidDataException("Multi-target context requires physically distinct lexical forms. Different Oxford stable IDs for the same written form remain distinct progress identities but cannot be counted as multiple target words in one sentence.");
    }

    public IReadOnlyList<ContextLexicalTarget> DescribePool(IEnumerable<string> entryIds)
    {
        string[] ids = ContextTargetIds.NormalizeStudyPool(entryIds);
        return ids.Select((id, index) => new ContextLexicalTarget(id, LexicalKeyFor(id), index)).ToArray();
    }

    public IReadOnlyList<string> AmbiguousStableIds(IEnumerable<string> entryIds)
    {
        IReadOnlyList<ContextLexicalTarget> targets = DescribePool(entryIds);
        return targets
            .Where(target => StableIdsForLexicalKey(target.LexicalKey).Count > 1)
            .Select(target => target.EntryId)
            .ToArray();
    }

    private static string NormalizeLexicalKey(string source)
    {
        if (string.IsNullOrWhiteSpace(source))
            throw new InvalidDataException("Context lexical source form cannot be blank.");
        IReadOnlyList<string> tokens = SentenceTokenizer.Tokenize(source);
        if (tokens.Count == 0)
            throw new InvalidDataException("Context lexical source form does not contain a usable English token.");
        return string.Join(" ", tokens);
    }
}

internal sealed record NaturalContextTargetSet(
    IReadOnlyList<string> TargetEntryIds,
    string EvidenceSentenceId,
    IReadOnlyList<string> AmbiguousStableEntryIds);

internal static class ContextNaturalTargetPlanner
{
    public const int MaxPlannerCandidateSentences = 512;
    public const int MaxPlannedSets = 100;

    public static IReadOnlyList<NaturalContextTargetSet> Discover(
        IContextSentenceSource source,
        ContextTargetLexicon lexicon,
        IReadOnlyCollection<string> studyPoolEntryIds,
        string anchorEntryId,
        int desiredTargetCount,
        int maxCandidateSentences = 256,
        int maxSets = 20)
    {
        ArgumentNullException.ThrowIfNull(source);
        ArgumentNullException.ThrowIfNull(lexicon);
        if (desiredTargetCount is < 1 or > 3)
            throw new ArgumentOutOfRangeException(nameof(desiredTargetCount), "Natural context planning supports one, two, or three target words.");
        if (maxCandidateSentences is < 1 or > MaxPlannerCandidateSentences)
            throw new ArgumentOutOfRangeException(nameof(maxCandidateSentences));
        if (maxSets is < 1 or > MaxPlannedSets)
            throw new ArgumentOutOfRangeException(nameof(maxSets));

        IReadOnlyList<ContextLexicalTarget> pool = lexicon.DescribePool(studyPoolEntryIds);
        if (pool.Count == 0)
            throw new InvalidDataException("Natural context planning requires a non-empty stable-ID study pool.");
        string anchor = ContextTargetIds.NormalizeSingle(anchorEntryId);
        ContextLexicalTarget anchorTarget = pool.FirstOrDefault(target => string.Equals(target.EntryId, anchor, StringComparison.OrdinalIgnoreCase))
            ?? throw new InvalidDataException("Natural context anchor must belong to the active study list/deck.");

        var poolById = pool.ToDictionary(target => target.EntryId, target => target, StringComparer.OrdinalIgnoreCase);
        IReadOnlyList<ContextSentenceEnvelope> candidates = source.FindByTargets(new[] { anchor }, maxCandidateSentences);
        var result = new List<NaturalContextTargetSet>();
        var seenSets = new HashSet<string>(StringComparer.Ordinal);

        foreach (ContextSentenceEnvelope envelope in candidates)
        {
            envelope.Validate();
            string[] sentencePoolIds = envelope.Sentence.TargetEntryIds
                .Select(ContextTargetIds.NormalizeSingle)
                .Where(poolById.ContainsKey)
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToArray();
            if (!sentencePoolIds.Contains(anchor, StringComparer.OrdinalIgnoreCase))
                continue;

            var byLexicalKey = sentencePoolIds
                .Select(id => poolById[id])
                .GroupBy(target => target.LexicalKey, StringComparer.OrdinalIgnoreCase)
                .ToDictionary(group => group.Key, group => group.OrderBy(target => target.Ordinal).ToArray(), StringComparer.OrdinalIgnoreCase);
            if (byLexicalKey.Count < desiredTargetCount)
                continue;

            var selected = new List<string> { anchor };
            foreach (ContextLexicalTarget groupRepresentative in byLexicalKey
                         .Where(pair => !pair.Key.Equals(anchorTarget.LexicalKey, StringComparison.OrdinalIgnoreCase))
                         .Select(pair => pair.Value[0])
                         .OrderBy(target => target.Ordinal))
            {
                selected.Add(groupRepresentative.EntryId);
                if (selected.Count == desiredTargetCount)
                    break;
            }
            if (selected.Count != desiredTargetCount)
                continue;

            lexicon.EnsureDistinctLexicalTargets(selected);
            string canonicalSetKey = string.Join("\u001f", selected.OrderBy(id => id, StringComparer.Ordinal));
            if (!seenSets.Add(canonicalSetKey))
                continue;

            string[] ambiguous = byLexicalKey
                .Where(pair => pair.Value.Length > 1)
                .SelectMany(pair => pair.Value.Select(target => target.EntryId))
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .OrderBy(id => id, StringComparer.Ordinal)
                .ToArray();
            result.Add(new NaturalContextTargetSet(selected.ToArray(), envelope.Sentence.Id, ambiguous));
            if (result.Count >= maxSets)
                break;
        }

        return result;
    }
}

internal interface IContextNaturalCoverageSource
{
    IReadOnlySet<string> GetCoveredNaturalTargetIds(IReadOnlyList<ContextLexicalTarget> scope, int requiredTargetCount);
}

internal sealed record ContextNaturalCoverageReport(
    int RequiredTargetCount,
    int ScopeEntryCount,
    int CoveredEntryCount,
    int UncoveredEntryCount,
    IReadOnlyList<string> CoveredEntryIds,
    IReadOnlyList<string> UncoveredEntryIds,
    IReadOnlyList<string> AmbiguousStableEntryIds)
{
    public double CoveragePercent => ScopeEntryCount == 0 ? 100.0 : CoveredEntryCount * 100.0 / ScopeEntryCount;
}

internal static class ContextNaturalCoverageAnalyzer
{
    public static ContextNaturalCoverageReport Analyze(
        IContextSentenceSource source,
        ContextTargetLexicon lexicon,
        IReadOnlyCollection<string> scopeEntryIds,
        int requiredTargetCount,
        int fallbackCandidateLimit = 512)
    {
        ArgumentNullException.ThrowIfNull(source);
        ArgumentNullException.ThrowIfNull(lexicon);
        if (requiredTargetCount is < 1 or > 3)
            throw new ArgumentOutOfRangeException(nameof(requiredTargetCount));
        if (fallbackCandidateLimit is < 1 or > SentencePackSqliteRuntimeQuery.DefaultCandidateLimit)
            throw new ArgumentOutOfRangeException(nameof(fallbackCandidateLimit));

        IReadOnlyList<ContextLexicalTarget> scope = lexicon.DescribePool(scopeEntryIds);
        IReadOnlySet<string> coveredSet;
        if (source is IContextNaturalCoverageSource optimized)
        {
            coveredSet = optimized.GetCoveredNaturalTargetIds(scope, requiredTargetCount);
        }
        else if (requiredTargetCount == 1 && source is IContextCoverageSource oneTargetOptimized)
        {
            coveredSet = oneTargetOptimized.GetCoveredOneTargetIds(scope.Select(target => target.EntryId).ToArray());
        }
        else
        {
            var scopeById = scope.ToDictionary(target => target.EntryId, target => target, StringComparer.OrdinalIgnoreCase);
            var covered = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (ContextLexicalTarget anchor in scope)
            {
                IReadOnlyList<ContextSentenceEnvelope> candidates = source.FindByTargets(new[] { anchor.EntryId }, fallbackCandidateLimit);
                bool found = candidates.Any(envelope => envelope.Sentence.TargetEntryIds
                    .Select(ContextTargetIds.NormalizeSingle)
                    .Where(scopeById.ContainsKey)
                    .Select(id => scopeById[id].LexicalKey)
                    .Distinct(StringComparer.OrdinalIgnoreCase)
                    .Count() >= requiredTargetCount);
                if (found)
                    covered.Add(anchor.EntryId);
            }
            coveredSet = covered;
        }

        string[] orderedIds = scope.Select(target => target.EntryId).ToArray();
        string[] coveredOrdered = orderedIds.Where(coveredSet.Contains).ToArray();
        string[] uncovered = orderedIds.Where(id => !coveredSet.Contains(id)).ToArray();
        if (coveredOrdered.Length + uncovered.Length != orderedIds.Length)
            throw new InvalidOperationException("Natural context coverage did not partition the complete requested stable-ID universe.");

        string[] ambiguous = lexicon.AmbiguousStableIds(orderedIds).ToArray();
        return new ContextNaturalCoverageReport(
            requiredTargetCount,
            orderedIds.Length,
            coveredOrdered.Length,
            uncovered.Length,
            coveredOrdered,
            uncovered,
            ambiguous);
    }
}
