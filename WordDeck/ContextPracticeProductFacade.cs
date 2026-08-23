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
    ContextNaturalCoverageReport StableTagParticipation,
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

        // A surface-form corpus cannot choose which noun/verb/sense stable ID owns a
        // homographic occurrence. Keep those identities out of canonical target sets
        // until an explicit POS/sense-aware source proves the mapping.
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

    /// <summary>
    /// Natural coverage for a scope whose stable IDs are already one-to-one with
    /// physical written forms. Ambiguous homograph IDs are rejected here rather than
    /// being counted twice. Use AnalyzeStableIdentityCoverage when the requested scope
    /// intentionally includes unresolved stable IDs.
    /// </summary>
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
        ArgumentNullException.ThrowIfNull(lexicon);
        ArgumentNullException.ThrowIfNull(scopeEntryIds);

        IReadOnlyList<string> unresolved = ContextStableIdentityResolution.UnresolvedStableIds(lexicon, scopeEntryIds);
        if (unresolved.Count > 0)
        {
            throw new InvalidDataException(
                "Natural physical-form coverage requires a stable-ID scope with one-to-one lexical forms. " +
                "The requested scope contains unresolved homographic IDs: " + string.Join(", ", unresolved) +
                ". Use conservative stable-identity coverage to report those IDs without double-counting their written forms.");
        }

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
                "Synthetic/test-only natural coverage over a resolved one-form-per-stable-ID scope. It cannot support a production corpus coverage or redistribution claim.",
            ContextCorpusKind.LocalUserText =>
                "Privacy-local natural coverage over a resolved one-form-per-stable-ID scope. It is useful for local practice only and is not public corpus evidence.",
            _ =>
                "Real-corpus natural coverage over a resolved one-form-per-stable-ID scope. Homographic stable IDs were excluded before this measurement. Full unique physical-form and conservative stable-ID corpus evidence are separate release artifacts, and coverage does not approve redistribution."
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
        ContextProductUseOptions effective = options ?? new ContextProductUseOptions();
        ValidateSourceForProductUse(source, effective);
        ArgumentNullException.ThrowIfNull(lexicon);
        ArgumentNullException.ThrowIfNull(scopeEntryIds);

        ContextNaturalCoverageReport stableTagParticipation = ContextNaturalCoverageAnalyzer.Analyze(
            source,
            lexicon,
            scopeEntryIds,
            requiredTargetCount,
            fallbackCandidateLimit);
        ContextStableIdentityCoverageReport stable = ContextStableIdentityResolution.ResolveCoverage(
            stableTagParticipation,
            lexicon,
            scopeEntryIds);

        ContextSourceDescriptor descriptor = source.Descriptor;
        bool real = descriptor.Kind == ContextCorpusKind.RealCorpus;
        bool local = descriptor.Kind == ContextCorpusKind.LocalUserText || descriptor.PrivacyLocalOnly;
        string boundary = descriptor.Kind switch
        {
            ContextCorpusKind.SyntheticFixture =>
                "Synthetic/test-only conservative stable-ID measurement. Surface-form stable-tag participation is retained only as source evidence; homographic stable IDs are unresolved and synthetic data cannot support production coverage.",
            ContextCorpusKind.LocalUserText =>
                "Privacy-local conservative stable-ID measurement. Surface-form stable-tag participation is not POS/sense evidence; homographic stable IDs remain unresolved without explicit disambiguation.",
            _ =>
                "Conservative real-corpus stable-ID measurement. Surface-form stable-tag participation is source evidence only. Only covered non-homographic IDs count as resolved; every same-written-form multi-ID entry stays unresolved unless a future POS/sense-aware source explicitly disambiguates it."
        };
        return new ContextStableIdentityCoverageEvidence(
            descriptor,
            stableTagParticipation,
            stable,
            real,
            local,
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
