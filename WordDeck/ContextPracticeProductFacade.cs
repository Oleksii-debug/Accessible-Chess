namespace WordDeck;

internal sealed record ContextProductUseOptions(bool AllowSyntheticFixtures = false);

internal sealed record ContextCoverageEvidence(
    ContextSourceDescriptor Source,
    ContextNaturalCoverageReport Coverage,
    bool IsRealCorpusMeasurement,
    bool IsPrivacyLocalMeasurement,
    string EvidenceBoundary);

internal sealed record ContextStableIdentityCoverageEvidence(
    ContextSourceDescriptor Source,
    ContextNaturalCoverageReport PhysicalFormCoverage,
    ContextStableIdentityCoverageReport StableIdentityCoverage,
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
        EnforceResolvedStableTargets(source, request, effective);
        return ContextPracticeService.Select(
            source,
            request with { AllowSyntheticFixtures = effective.AllowSyntheticFixtures });
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
        ArgumentNullException.ThrowIfNull(lexicon);

        ContextStableIdentityResolution.EnsureResolvedTargets(lexicon, new[] { anchorEntryId });
        IReadOnlyList<string> resolvedPool = ContextStableIdentityResolution.ResolvedStudyPool(lexicon, studyPoolEntryIds);
        if (resolvedPool.Count < desiredTargetCount)
            return Array.Empty<NaturalContextTargetSet>();

        return ContextNaturalTargetPlanner.Discover(
            source,
            lexicon,
            resolvedPool,
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
                "Synthetic/test-only physical-form context measurement. It cannot support a production corpus coverage or redistribution claim.",
            ContextCorpusKind.LocalUserText =>
                "Privacy-local physical-form user-text measurement. It is useful for local practice only and is not public corpus evidence.",
            _ =>
                "Real-corpus physical-written-form measurement. Ambiguous homograph stable IDs remain unresolved; these numbers are not stable-ID/POS/sense coverage. Coverage numbers do not by themselves approve redistribution, licensing, provenance or a shipped SentencePack."
        };

        return new ContextCoverageEvidence(descriptor, coverage, real, local, boundary);
    }

    public static ContextStableIdentityCoverageEvidence AnalyzeStableIdentityCoverage(
        IContextSentenceSource source,
        ContextTargetLexicon lexicon,
        IReadOnlyCollection<string> scopeEntryIds,
        int requiredTargetCount,
        ContextProductUseOptions? options = null,
        int fallbackCandidateLimit = 512)
    {
        ContextCoverageEvidence physical = AnalyzeNaturalCoverage(
            source,
            lexicon,
            scopeEntryIds,
            requiredTargetCount,
            options,
            fallbackCandidateLimit);
        ContextStableIdentityCoverageReport stable = ContextStableIdentityResolution.ResolveCoverage(
            physical.Coverage,
            lexicon,
            scopeEntryIds);
        string boundary = physical.Source.Kind switch
        {
            ContextCorpusKind.SyntheticFixture =>
                "Synthetic/test-only resolved stable-ID measurement. Homographic stable IDs are conservatively unresolved and synthetic data cannot support production coverage.",
            ContextCorpusKind.LocalUserText =>
                "Privacy-local resolved stable-ID measurement. Homographic stable IDs remain unresolved without explicit POS/sense evidence.",
            _ =>
                "Conservative real-corpus stable-ID measurement. Only physically covered, non-homographic dictionary IDs count as resolved; every same-written-form multi-ID entry stays unresolved unless a future POS/sense-aware source explicitly disambiguates it."
        };
        return new ContextStableIdentityCoverageEvidence(
            physical.Source,
            physical.Coverage,
            stable,
            physical.IsRealCorpusMeasurement,
            physical.IsPrivacyLocalMeasurement,
            boundary);
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

    private static void EnforceResolvedStableTargets(
        IContextSentenceSource source,
        ContextPracticeRequest request,
        ContextProductUseOptions options)
    {
        if (request.TargetLexicon is null)
        {
            if (source.Descriptor.Kind != ContextCorpusKind.SyntheticFixture || !options.AllowSyntheticFixtures)
            {
                throw new InvalidDataException(
                    "Product-facing Context Practice requires the dictionary lexical catalog even for one target so homographic stable IDs can fail closed instead of inheriting ambiguous surface-form evidence.");
            }
            return;
        }

        ContextStableIdentityResolution.EnsureResolvedTargets(request.TargetLexicon, request.RequiredTargetEntryIds);
    }
}
