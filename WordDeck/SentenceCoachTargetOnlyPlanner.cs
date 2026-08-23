namespace WordDeck;

internal sealed record SentenceCoachTargetSetCandidate(
    IReadOnlyList<string> TargetEntryIds,
    string EvidenceSentenceId);

internal static class SentenceCoachTargetOnlyPlanner
{
    public static IReadOnlyList<DictionaryEntry> ResolvedScope(
        IEnumerable<DictionaryEntry> scopeEntries,
        ContextTargetLexicon lexicon) =>
        scopeEntries
            .Where(entry => !lexicon.IsAmbiguousStableIdentity(entry.Id))
            .ToArray();

    public static IReadOnlyList<SentenceCoachTargetSetCandidate> FindNaturalTargetSets(
        ISentenceCorpus corpus,
        DictionaryEntry anchor,
        IReadOnlyList<DictionaryEntry> resolvedScope,
        ContextTargetLexicon lexicon,
        int desiredTargetCount,
        int maxSets = 100)
    {
        ArgumentNullException.ThrowIfNull(corpus);
        ArgumentNullException.ThrowIfNull(anchor);
        ArgumentNullException.ThrowIfNull(resolvedScope);
        ArgumentNullException.ThrowIfNull(lexicon);
        if (desiredTargetCount is < 1 or > 3)
            throw new ArgumentOutOfRangeException(nameof(desiredTargetCount));
        if (maxSets is < 1 or > 500)
            throw new ArgumentOutOfRangeException(nameof(maxSets));
        if (lexicon.IsAmbiguousStableIdentity(anchor.Id))
            return Array.Empty<SentenceCoachTargetSetCandidate>();

        var scopeById = resolvedScope.ToDictionary(entry => entry.Id, StringComparer.OrdinalIgnoreCase);
        if (!scopeById.ContainsKey(anchor.Id))
            return Array.Empty<SentenceCoachTargetSetCandidate>();

        string anchorKey = lexicon.LexicalKeyFor(anchor.Id);
        var results = new List<SentenceCoachTargetSetCandidate>();
        var seen = new HashSet<string>(StringComparer.Ordinal);

        foreach (SentenceRecord sentence in corpus.LookupByEntryId(anchor.Id))
        {
            if (!OccursExactlyOnce(sentence.English, anchor.Source))
                continue;

            DictionaryEntry[] partners = sentence.TargetEntryIds
                .Where(id => !string.Equals(id, anchor.Id, StringComparison.OrdinalIgnoreCase))
                .Where(scopeById.ContainsKey)
                .Select(id => scopeById[id])
                .Where(entry => !lexicon.IsAmbiguousStableIdentity(entry.Id))
                .Where(entry => !string.Equals(lexicon.LexicalKeyFor(entry.Id), anchorKey, StringComparison.OrdinalIgnoreCase))
                .Where(entry => OccursExactlyOnce(sentence.English, entry.Source))
                .GroupBy(entry => lexicon.LexicalKeyFor(entry.Id), StringComparer.OrdinalIgnoreCase)
                .Select(group => group.OrderBy(entry => entry.Id, StringComparer.Ordinal).First())
                .OrderBy(entry => entry.Id, StringComparer.Ordinal)
                .ToArray();

            if (desiredTargetCount == 1)
            {
                Add(new[] { anchor.Id }, sentence.Id);
                continue;
            }

            if (desiredTargetCount == 2)
            {
                foreach (DictionaryEntry partner in partners)
                {
                    Add(new[] { anchor.Id, partner.Id }, sentence.Id);
                    if (results.Count >= maxSets) break;
                }
            }
            else
            {
                for (int i = 0; i < partners.Length && results.Count < maxSets; i++)
                    for (int j = i + 1; j < partners.Length && results.Count < maxSets; j++)
                        Add(new[] { anchor.Id, partners[i].Id, partners[j].Id }, sentence.Id);
            }

            if (results.Count >= maxSets)
                break;
        }

        return results;

        void Add(IReadOnlyList<string> ids, string sentenceId)
        {
            lexicon.EnsureDistinctLexicalTargets(ids);
            string key = string.Join("\u001f", ids.OrderBy(id => id, StringComparer.Ordinal));
            if (!seen.Add(key))
                return;
            results.Add(new SentenceCoachTargetSetCandidate(ids.ToArray(), sentenceId));
        }
    }

    public static bool HasNaturalTargetSet(
        ISentenceCorpus corpus,
        DictionaryEntry anchor,
        IReadOnlyList<DictionaryEntry> resolvedScope,
        ContextTargetLexicon lexicon,
        int desiredTargetCount) =>
        FindNaturalTargetSets(corpus, anchor, resolvedScope, lexicon, desiredTargetCount, maxSets: 1).Count > 0;

    private static bool OccursExactlyOnce(string sentenceEnglish, string physicalForm) =>
        ContextPhysicalTargetForm.BuildOccurrenceRegex(physicalForm).Matches(sentenceEnglish).Count == 1;
}
