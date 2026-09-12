namespace WordDeck;

/// <summary>
/// Thin production bridge from validated morphology relations into the canonical
/// Stage-11 Context/Sentence engine. The bridge screens physical-form ambiguity
/// before any morphology-related stable ID is offered as a corpus target.
/// </summary>
internal sealed class MorphologyContextBridge
{
    private readonly MorphologyContextTargetPlanner _planner;
    private readonly ContextTargetLexicon _lexicon;

    public MorphologyContextBridge(MorphologyOverlay overlay, DictionaryPackage dictionary)
    {
        ArgumentNullException.ThrowIfNull(overlay);
        ArgumentNullException.ThrowIfNull(dictionary);
        _planner = new MorphologyContextTargetPlanner(overlay, dictionary);
        _lexicon = new ContextTargetLexicon(dictionary);
    }

    public IReadOnlyList<RankedContextSentence> SelectAnchorSentences(
        IContextSentenceSource source,
        string anchorEntryId,
        IReadOnlyCollection<string> studyPoolEntryIds,
        ContextLearnerVocabulary? vocabulary = null,
        ContextProductUseOptions? options = null,
        int maxResults = 20,
        int candidateLimit = 256,
        IReadOnlySet<string>? resolvedAmbiguousEntryIds = null)
    {
        HashSet<string> allowed = NormalizePool(studyPoolEntryIds);
        MorphologyContextTargetPlan plan = _planner.Plan(
            anchorEntryId,
            allowed,
            maxRelatedTargets: 32,
            resolvedAmbiguousEntryIds: resolvedAmbiguousEntryIds);
        return ContextPracticeProductFacade.Select(
            source,
            new ContextPracticeRequest(
                new[] { plan.AnchorEntryId },
                plan.PhysicalTargetPoolEntryIds,
                vocabulary,
                maxResults,
                candidateLimit,
                false,
                _lexicon),
            options);
    }

    public IReadOnlyList<NaturalContextTargetSet> DiscoverRelatedTargetSets(
        IContextSentenceSource source,
        string anchorEntryId,
        IReadOnlyCollection<string> studyPoolEntryIds,
        int desiredTargetCount,
        ContextProductUseOptions? options = null,
        int maxCandidateSentences = 256,
        int maxSets = 20,
        IReadOnlySet<string>? resolvedAmbiguousEntryIds = null)
    {
        if (desiredTargetCount is < 2 or > 3)
            throw new ArgumentOutOfRangeException(nameof(desiredTargetCount), "Morphology-related natural target discovery supports two or three physical target forms; use SelectAnchorSentences for one target.");

        HashSet<string> allowed = NormalizePool(studyPoolEntryIds);
        MorphologyContextTargetPlan plan = _planner.Plan(
            anchorEntryId,
            allowed,
            maxRelatedTargets: 32,
            resolvedAmbiguousEntryIds: resolvedAmbiguousEntryIds);
        if (plan.PhysicalTargetPoolEntryIds.Count < desiredTargetCount)
            return Array.Empty<NaturalContextTargetSet>();

        return ContextPracticeProductFacade.DiscoverNaturalTargets(
            source,
            _lexicon,
            plan.PhysicalTargetPoolEntryIds,
            plan.AnchorEntryId,
            desiredTargetCount,
            options,
            maxCandidateSentences,
            maxSets);
    }

    public IReadOnlyList<RankedContextSentence> SelectRelatedTargetSet(
        IContextSentenceSource source,
        string anchorEntryId,
        IReadOnlyCollection<string> studyPoolEntryIds,
        IReadOnlyCollection<string> requiredTargetEntryIds,
        ContextLearnerVocabulary? vocabulary = null,
        ContextProductUseOptions? options = null,
        int maxResults = 20,
        int candidateLimit = 256,
        IReadOnlySet<string>? resolvedAmbiguousEntryIds = null)
    {
        if (requiredTargetEntryIds is null || requiredTargetEntryIds.Count is < 1 or > 3)
            throw new ArgumentOutOfRangeException(nameof(requiredTargetEntryIds));

        HashSet<string> allowed = NormalizePool(studyPoolEntryIds);
        MorphologyContextTargetPlan plan = _planner.Plan(
            anchorEntryId,
            allowed,
            maxRelatedTargets: 32,
            resolvedAmbiguousEntryIds: resolvedAmbiguousEntryIds);
        var morphologyPool = new HashSet<string>(plan.PhysicalTargetPoolEntryIds, StringComparer.OrdinalIgnoreCase);
        string[] required = requiredTargetEntryIds
            .Select(id => string.IsNullOrWhiteSpace(id) ? string.Empty : id.Trim())
            .Where(id => id.Length > 0)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
        if (required.Length != requiredTargetEntryIds.Count)
            throw new InvalidDataException("Morphology Context target set contains blank or duplicate stable IDs.");
        if (!required.Contains(plan.AnchorEntryId, StringComparer.OrdinalIgnoreCase))
            throw new InvalidDataException("Morphology Context target set must include the morphology anchor stable ID.");
        if (required.Any(id => !morphologyPool.Contains(id)))
            throw new InvalidDataException("Morphology Context target set contains an entry that is not an ambiguity-safe source-backed family target.");
        _lexicon.EnsureDistinctLexicalTargets(required);

        return ContextPracticeProductFacade.Select(
            source,
            new ContextPracticeRequest(
                required,
                plan.PhysicalTargetPoolEntryIds,
                vocabulary,
                maxResults,
                candidateLimit,
                false,
                _lexicon),
            options);
    }

    private static HashSet<string> NormalizePool(IReadOnlyCollection<string> studyPoolEntryIds)
    {
        ArgumentNullException.ThrowIfNull(studyPoolEntryIds);
        var result = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (string raw in studyPoolEntryIds)
        {
            if (string.IsNullOrWhiteSpace(raw)) continue;
            result.Add(raw.Trim());
        }
        if (result.Count == 0)
            throw new InvalidDataException("Morphology Context integration requires a non-empty active study pool.");
        return result;
    }
}
