namespace WordDeck;

internal sealed record MorphologyGrammarTargetPlan(
    string GrammarSkillId,
    string AnchorEntryId,
    IReadOnlyList<MorphologyIntegrationTarget> RelatedVocabularyTargets,
    IReadOnlyList<string> ExcludedAmbiguousStableIds);

/// <summary>
/// Cross-mode bridge for Grammar. Grammar owns its skill graph and exercise state;
/// Morphology contributes only exact source-backed lexical targets. The caller must
/// choose a Grammar skill reference explicitly; this bridge never infers a grammar
/// skill from a suffix, prefix, POS label or written word form.
/// </summary>
internal sealed class MorphologyGrammarBridge
{
    private readonly MorphologyContextTargetPlanner _planner;

    public MorphologyGrammarBridge(MorphologyOverlay overlay, DictionaryPackage dictionary)
    {
        ArgumentNullException.ThrowIfNull(overlay);
        ArgumentNullException.ThrowIfNull(dictionary);
        _planner = new MorphologyContextTargetPlanner(overlay, dictionary);
    }

    public MorphologyGrammarTargetPlan Plan(
        string anchorEntryId,
        string grammarSkillReference,
        IReadOnlySet<string>? allowedEntryIds = null,
        IReadOnlySet<string>? allowedLevels = null,
        int maxRelatedTargets = 16,
        IReadOnlySet<string>? resolvedAmbiguousEntryIds = null)
    {
        string skillId = GrammarSkillReferenceResolver.Resolve(grammarSkillReference);
        MorphologyContextTargetPlan morphology = _planner.Plan(
            anchorEntryId,
            allowedEntryIds,
            allowedLevels,
            maxRelatedTargets,
            resolvedAmbiguousEntryIds);

        return new MorphologyGrammarTargetPlan(
            skillId,
            morphology.AnchorEntryId,
            morphology.SafeRelatedTargets,
            morphology.ExcludedAmbiguousStableIds);
    }
}
