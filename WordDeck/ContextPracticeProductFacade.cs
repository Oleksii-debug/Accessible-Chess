namespace WordDeck;

internal sealed record ContextProductUseOptions(bool AllowSyntheticFixtures = false);

internal sealed record ContextCoverageEvidence(
    ContextSourceDescriptor Source,
    ContextNaturalCoverageReport Coverage,
    bool IsRealCorpusMeasurement,
    bool IsPrivacyLocalMeasurement,
    string EvidenceBoundary);

internal static class ContextPracticeProductFacade
{
    public static IReadOnlyList<RankedContextSentence> Select(
        IContextSentenceSource source,
        ContextPracticeRequest request,
        ContextProductUseOptions? options = null)
    {
        ArgumentNullException.ThrowIfNull(request);
        ContextProductUseOptions effective = options ?? new ContextProductUseOptions();
        ValidateSourceForProductUse(source, effective);
        ContextPracticeRequest effectiveRequest = request with { AllowSyntheticFixtures = effective.AllowSyntheticFixtures };

        // Real/local surface-form corpora cannot prove one Oxford POS/sense merely because
        // the written form occurred. Product-facing stable-ID practice therefore fails
        // closed for homographs until the source carries explicit disambiguating evidence.
        // Synthetic fixtures may opt out so ambiguity mechanics can still be tested.
        if (source.Descriptor.Kind != ContextCorpusKind.SyntheticFixture)
        {
            if (effectiveRequest.TargetLexicon is null)
                throw new InvalidDataException(
                    "Product-facing context selection requires the Oxford lexical catalog so stable-ID/POS/sense ambiguity can be checked fail-closed.");
            ContextStableIdentityResolution.EnsureResolvedTargets(
                effectiveRequest.TargetLexicon,
                effectiveRequest.RequiredTargetEntryIds);
        }

        return ContextPracticeService.Select(source, effectiveRequest);
    }

    public static IReadOnlyList<NaturalContextTargetSet> DiscoverNaturalTargets(
        IContextSentenceSource source,
        ContextTargetLexicon lexicon,
        IReadOnlyCollection<string> studyPoolEntryIds,
        string anchorEntryId,
        int desiredTargetCount,
        ContextProductUseOptions? options = null,
        int maxCandidateSentences = 256,
        int maxSets = 20)
    {
        ContextProductUseOptions effective = options ?? new ContextProductUseOptions();
        ValidateSourceForProductUse(source, effective);

        IReadOnlyCollection<string> safePool = studyPoolEntryIds;
        if (source.Descriptor.Kind != ContextCorpusKind.SyntheticFixture)
        {
            ContextStableIdentityResolution.EnsureResolvedTargets(lexicon, new[] { anchorEntryId });
            safePool = ContextStableIdentityResolution.ResolvedStudyPool(lexicon, studyPoolEntryIds);
        }

        return ContextNaturalTargetPlanner.Discover(
            source,
            lexicon,
            safePool,
            anchorEntryId,
            desiredTargetCount,
            maxCandidateSentences,
            maxSets);
    }

    public static ContextCoverageEvidence AnalyzeNaturalCoverage(
        IContextSentenceSource source,
        ContextTargetLexicon lexicon,
        IReadOnlyCollection<string> scopeEntryIds,
        int requiredTargetCount,
        ContextProductUseOptions? options = null,
        int fallbackCandidateLimit = 512)
    {
        ContextProductUseOptions effective = options ?? new ContextProductUseOptions();
        ValidateSourceForProductUse(source, effective);
        ContextNaturalCoverageReport coverage = ContextNaturalCoverageAnalyzer.Analyze(
            source,
            lexicon,
            scopeEntryIds,
            requiredTargetCount,
            fallbackCandidateLimit);

        ContextSourceDescriptor descriptor = source.Descriptor;
        bool real = descriptor.Kind == ContextCorpusKind.RealCorpus;
        bool local = descriptor.Kind == ContextCorpusKind.LocalUserText || descriptor.PrivacyLocalOnly;
        string boundary = descriptor.Kind switch
        {
            ContextCorpusKind.SyntheticFixture =>
                "Synthetic/test-only context measurement. It cannot support a production corpus coverage or redistribution claim.",
            ContextCorpusKind.LocalUserText =>
                "Privacy-local user-text measurement. It is useful for local practice only and is not public corpus evidence.",
            _ =>
                "Real-corpus surface-form measurement. Written-form occurrence/co-occurrence is not by itself POS/sense-resolved stable-ID evidence. Coverage numbers do not approve redistribution, licensing, provenance or a shipped SentencePack."
        };

        return new ContextCoverageEvidence(descriptor, coverage, real, local, boundary);
    }

    internal static void ValidateSourceForProductUse(
        IContextSentenceSource source,
        ContextProductUseOptions options)
    {
        ArgumentNullException.ThrowIfNull(source);
        ArgumentNullException.ThrowIfNull(options);
        source.Descriptor.Validate();
        if (source.Descriptor.Kind == ContextCorpusKind.SyntheticFixture && !options.AllowSyntheticFixtures)
            throw new InvalidDataException(
                "Synthetic context fixtures are test-only by default. Product-facing selection, target planning and coverage require an explicit AllowSyntheticFixtures test opt-in.");
    }
}
