namespace WordDeck;

internal enum ContextStudyPoolPreset
{
    Thirty = 30,
    Hundred = 100,
    TwoHundred = 200,
    Full = 0
}

internal sealed record ContextStudyPoolSelection(
    ContextStudyPoolPreset Preset,
    IReadOnlyList<string> EntryIds,
    int AvailableEntryCount,
    bool FilledRequestedWindow,
    bool IsFullPool);

internal static class ContextStudyPoolBuilder
{
    public static ContextStudyPoolSelection Build(
        IEnumerable<string> orderedEntryIds,
        ContextStudyPoolPreset preset)
    {
        string[] normalized = ContextTargetIds.NormalizeStudyPool(orderedEntryIds);
        int requested = preset switch
        {
            ContextStudyPoolPreset.Thirty => 30,
            ContextStudyPoolPreset.Hundred => 100,
            ContextStudyPoolPreset.TwoHundred => 200,
            ContextStudyPoolPreset.Full => normalized.Length,
            _ => throw new ArgumentOutOfRangeException(nameof(preset))
        };

        string[] selected = preset == ContextStudyPoolPreset.Full
            ? normalized
            : normalized.Take(requested).ToArray();

        return new ContextStudyPoolSelection(
            preset,
            selected,
            normalized.Length,
            preset == ContextStudyPoolPreset.Full || selected.Length == requested,
            preset == ContextStudyPoolPreset.Full);
    }
}

internal sealed record ContextPracticeApplicationRequest(
    string AnchorEntryId,
    int DesiredTargetCount,
    ContextStudyPoolPreset PoolPreset = ContextStudyPoolPreset.Full,
    ContextLearnerVocabulary? Vocabulary = null,
    IReadOnlyCollection<string>? RecentSentenceIds = null,
    int MaxCards = 20,
    int CandidateLimit = 256,
    int MaxNaturalTargetSets = 40);

internal sealed record ContextPracticeCard(
    string SentenceId,
    string UkrainianPrompt,
    string EnglishAnswer,
    IReadOnlyList<string> TargetEntryIds,
    IReadOnlyList<string> TargetLexicalKeys,
    ContextDifficultyBreakdown Difficulty,
    string SourceId,
    ContextCorpusKind SourceKind,
    string Provenance,
    string License,
    bool PrivacyLocalOnly,
    LocalTextContextLocation? LocalTextLocation,
    IReadOnlyList<string> GrammarSkillIds,
    bool WasRecentlyUsed);

internal sealed record ContextPracticeApplicationResult(
    ContextStudyPoolSelection StudyPool,
    IReadOnlyList<ContextPracticeCard> Cards,
    IReadOnlyList<string> AmbiguousStableEntryIds,
    string SelectionExplanation);

internal static class ContextPracticeApplicationService
{
    public static ContextPracticeApplicationResult BuildCards(
        IContextSentenceSource source,
        ContextTargetLexicon lexicon,
        IEnumerable<string> orderedStudyPoolEntryIds,
        ContextPracticeApplicationRequest request,
        ContextProductUseOptions? productOptions = null)
    {
        ArgumentNullException.ThrowIfNull(source);
        ArgumentNullException.ThrowIfNull(lexicon);
        ArgumentNullException.ThrowIfNull(orderedStudyPoolEntryIds);
        ArgumentNullException.ThrowIfNull(request);

        if (request.DesiredTargetCount is < 1 or > 3)
            throw new ArgumentOutOfRangeException(nameof(request.DesiredTargetCount));
        if (request.MaxCards is < 1 or > ContextPracticeService.MaxResults)
            throw new ArgumentOutOfRangeException(nameof(request.MaxCards));
        if (request.CandidateLimit < request.MaxCards || request.CandidateLimit > ContextPracticeService.MaxCandidateLimit)
            throw new ArgumentOutOfRangeException(nameof(request.CandidateLimit));
        if (request.MaxNaturalTargetSets is < 1 or > ContextNaturalTargetPlanner.MaxPlannedSets)
            throw new ArgumentOutOfRangeException(nameof(request.MaxNaturalTargetSets));

        ContextProductUseOptions effectiveOptions = productOptions ?? new ContextProductUseOptions();
        ContextPracticeProductFacade.ValidateSourceForProductUse(source, effectiveOptions);

        ContextStudyPoolSelection pool = ContextStudyPoolBuilder.Build(orderedStudyPoolEntryIds, request.PoolPreset);
        if (pool.EntryIds.Count == 0)
            throw new InvalidDataException("Context practice requires a non-empty active study pool.");

        string anchor = ContextTargetIds.NormalizeSingle(request.AnchorEntryId);
        if (!pool.EntryIds.Contains(anchor, StringComparer.OrdinalIgnoreCase))
            throw new InvalidDataException("Context practice anchor must belong to the selected 30/100/200/full study pool.");

        IReadOnlyList<NaturalContextTargetSet> targetSets;
        if (request.DesiredTargetCount == 1)
        {
            string lexicalKey = lexicon.LexicalKeyFor(anchor);
            string[] ambiguous = lexicon.StableIdsForLexicalKey(lexicalKey)
                .Where(id => pool.EntryIds.Contains(id, StringComparer.OrdinalIgnoreCase))
                .Where(id => !string.Equals(id, anchor, StringComparison.OrdinalIgnoreCase))
                .OrderBy(id => id, StringComparer.Ordinal)
                .ToArray();
            targetSets = new[] { new NaturalContextTargetSet(new[] { anchor }, string.Empty, ambiguous) };
        }
        else
        {
            targetSets = ContextPracticeProductFacade.DiscoverNaturalTargets(
                source,
                lexicon,
                pool.EntryIds,
                anchor,
                request.DesiredTargetCount,
                effectiveOptions,
                request.CandidateLimit,
                request.MaxNaturalTargetSets);
        }

        var recent = new HashSet<string>(request.RecentSentenceIds ?? Array.Empty<string>(), StringComparer.OrdinalIgnoreCase);
        var cardsBySentenceId = new Dictionary<string, ContextPracticeCard>(StringComparer.OrdinalIgnoreCase);
        foreach (NaturalContextTargetSet targetSet in targetSets)
        {
            int perSetResultLimit = Math.Min(request.MaxCards, request.CandidateLimit);
            IReadOnlyList<RankedContextSentence> ranked = ContextPracticeProductFacade.Select(
                source,
                new ContextPracticeRequest(
                    targetSet.TargetEntryIds,
                    pool.EntryIds,
                    request.Vocabulary,
                    MaxResults: perSetResultLimit,
                    CandidateLimit: request.CandidateLimit,
                    AllowSyntheticFixtures: effectiveOptions.AllowSyntheticFixtures,
                    TargetLexicon: lexicon),
                effectiveOptions);

            foreach (RankedContextSentence item in ranked)
            {
                ContextSentenceEnvelope envelope = item.Candidate;
                string[] targetIds = item.RequiredTargetEntryIds
                    .Select(ContextTargetIds.NormalizeSingle)
                    .ToArray();
                string[] lexicalKeys = targetIds.Select(lexicon.LexicalKeyFor).ToArray();
                bool wasRecent = recent.Contains(envelope.Sentence.Id);
                var card = new ContextPracticeCard(
                    envelope.Sentence.Id,
                    envelope.Sentence.Ukrainian,
                    envelope.Sentence.English,
                    targetIds,
                    lexicalKeys,
                    item.Difficulty,
                    envelope.Source.SourceId,
                    envelope.Source.Kind,
                    envelope.Source.Provenance,
                    envelope.Source.License,
                    envelope.Source.PrivacyLocalOnly,
                    envelope.LocalTextLocation,
                    envelope.EffectiveGrammarSkillIds,
                    wasRecent);

                if (!cardsBySentenceId.TryGetValue(card.SentenceId, out ContextPracticeCard? existing) ||
                    Compare(card, existing) < 0)
                {
                    cardsBySentenceId[card.SentenceId] = card;
                }
            }
        }

        ContextPracticeCard[] cards = cardsBySentenceId.Values
            .OrderBy(card => card.WasRecentlyUsed)
            .ThenBy(card => card.Difficulty.Score)
            .ThenBy(card => card.SentenceId, StringComparer.Ordinal)
            .Take(request.MaxCards)
            .ToArray();

        string[] ambiguousStableIds = lexicon.AmbiguousStableIds(pool.EntryIds)
            .OrderBy(id => id, StringComparer.Ordinal)
            .ToArray();
        string explanation = targetSets.Count == 0
            ? $"No natural {request.DesiredTargetCount}-target sentence set was found for the anchor in the selected study pool. No sentence was fabricated."
            : $"Selected from {targetSets.Count} natural target set(s) in the {PoolName(pool)} pool; learner-known vocabulary drives difficulty before CEFR, and recently used sentences are deprioritized.";

        return new ContextPracticeApplicationResult(pool, cards, ambiguousStableIds, explanation);
    }

    public static SentenceAnswerResult EvaluateSentenceSpelling(ContextPracticeCard card, string typedEnglish)
    {
        ArgumentNullException.ThrowIfNull(card);
        return SentenceAnswerEvaluator.Evaluate(card.EnglishAnswer, typedEnglish ?? string.Empty);
    }

    public static ContextCoverageEvidence MeasurePoolCoverage(
        IContextSentenceSource source,
        ContextTargetLexicon lexicon,
        IEnumerable<string> orderedStudyPoolEntryIds,
        ContextStudyPoolPreset preset,
        int requiredTargetCount,
        ContextProductUseOptions? productOptions = null)
    {
        ContextStudyPoolSelection pool = ContextStudyPoolBuilder.Build(orderedStudyPoolEntryIds, preset);
        if (pool.EntryIds.Count == 0)
            throw new InvalidDataException("Context coverage requires a non-empty study pool.");
        return ContextPracticeProductFacade.AnalyzeNaturalCoverage(
            source,
            lexicon,
            pool.EntryIds,
            requiredTargetCount,
            productOptions);
    }

    private static int Compare(ContextPracticeCard left, ContextPracticeCard right)
    {
        int recent = left.WasRecentlyUsed.CompareTo(right.WasRecentlyUsed);
        if (recent != 0) return recent;
        int score = left.Difficulty.Score.CompareTo(right.Difficulty.Score);
        if (score != 0) return score;
        return StringComparer.Ordinal.Compare(left.SentenceId, right.SentenceId);
    }

    private static string PoolName(ContextStudyPoolSelection pool) => pool.Preset switch
    {
        ContextStudyPoolPreset.Thirty => "30-word",
        ContextStudyPoolPreset.Hundred => "100-word",
        ContextStudyPoolPreset.TwoHundred => "200-word",
        ContextStudyPoolPreset.Full => "full",
        _ => "study"
    };
}
