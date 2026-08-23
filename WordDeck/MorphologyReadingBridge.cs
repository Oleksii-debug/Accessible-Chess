namespace WordDeck;

internal sealed record MorphologyReadingSuggestion(
    string AnchorEntryId,
    string AnchorForm,
    IReadOnlyList<MorphologyIntegrationTarget> RelatedTargets);

internal sealed record MorphologyReadingProjection(
    IReadOnlyList<MorphologyReadingSuggestion> Suggestions,
    IReadOnlyList<string> ExcludedAmbiguousStableIds);

/// <summary>
/// Reading-facing projection that depends only on exact stable IDs already mapped
/// by the book/reading owner. It does not depend on BookReading persistence types,
/// source text, offsets or upload behavior and therefore cannot take ownership of
/// private book state.
/// </summary>
internal sealed class MorphologyReadingBridge
{
    private readonly MorphologyContextTargetPlanner _planner;
    private readonly IReadOnlyDictionary<string, DictionaryEntry> _entries;

    public MorphologyReadingBridge(MorphologyOverlay overlay, DictionaryPackage dictionary)
    {
        ArgumentNullException.ThrowIfNull(overlay);
        ArgumentNullException.ThrowIfNull(dictionary);
        _planner = new MorphologyContextTargetPlanner(overlay, dictionary);
        _entries = dictionary.Entries.ToDictionary(entry => entry.Id, StringComparer.OrdinalIgnoreCase);
    }

    public MorphologyReadingProjection ProjectSentence(
        IReadOnlyCollection<string> sentenceStableEntryIds,
        IReadOnlySet<string>? studyPoolEntryIds = null,
        IReadOnlySet<string>? allowedLevels = null,
        int maxAnchors = 12,
        int maxRelatedTargetsPerAnchor = 8,
        IReadOnlySet<string>? resolvedAmbiguousEntryIds = null)
    {
        ArgumentNullException.ThrowIfNull(sentenceStableEntryIds);
        if (maxAnchors is < 1 or > 128) throw new ArgumentOutOfRangeException(nameof(maxAnchors));
        if (maxRelatedTargetsPerAnchor is < 1 or > 64) throw new ArgumentOutOfRangeException(nameof(maxRelatedTargetsPerAnchor));

        string[] sentenceIds = sentenceStableEntryIds
            .Select(id => string.IsNullOrWhiteSpace(id) ? string.Empty : id.Trim())
            .Where(id => id.Length > 0)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();

        var suggestions = new List<MorphologyReadingSuggestion>();
        var excluded = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (string anchor in sentenceIds)
        {
            if (!_entries.TryGetValue(anchor, out DictionaryEntry? entry))
                throw new InvalidDataException($"Reading supplied unknown morphology stable ID '{anchor}'.");
            if (_planner.IsUnresolvedAmbiguity(anchor, resolvedAmbiguousEntryIds))
            {
                excluded.Add(anchor);
                continue;
            }

            HashSet<string>? plannerPool = null;
            if (studyPoolEntryIds is not null)
            {
                plannerPool = new HashSet<string>(studyPoolEntryIds, StringComparer.OrdinalIgnoreCase) { anchor };
            }

            MorphologyContextTargetPlan plan = _planner.Plan(
                anchor,
                plannerPool,
                allowedLevels,
                maxRelatedTargetsPerAnchor,
                resolvedAmbiguousEntryIds);
            foreach (string ambiguous in plan.ExcludedAmbiguousStableIds)
                excluded.Add(ambiguous);

            MorphologyIntegrationTarget[] related = plan.SafeRelatedTargets
                .Where(target => studyPoolEntryIds is null || studyPoolEntryIds.Contains(target.EntryId))
                .Take(maxRelatedTargetsPerAnchor)
                .ToArray();
            if (related.Length == 0) continue;

            suggestions.Add(new MorphologyReadingSuggestion(anchor, entry.Source, related));
            if (suggestions.Count >= maxAnchors) break;
        }

        return new MorphologyReadingProjection(
            suggestions,
            excluded.OrderBy(id => id, StringComparer.OrdinalIgnoreCase).ToArray());
    }
}
