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
    /// Historical stable-tag participation keyed by dictionary entry IDs. This is useful
    /// for reproducible sentence-index/gap accounting, but it is NOT unique physical-form
    /// coverage and it is NOT resolved POS/sense coverage. True unique physical written-form
    /// coverage is emitted separately by ContextPhysicalLexicalCoverageEvidenceBuilder.
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
                "Synthetic/test-only stable-tag participation measurement. It cannot support production physical-form, POS/sense, corpus coverage or redistribution claims.",
            ContextCorpusKind.LocalUserText =>
                "Privacy-local stable-tag participation measurement. It is useful for local indexing/gap analysis only; unique physical-form and resolved stable-ID coverage require their separate evidence axes.",
            _ =>
                "Real-corpus stable-tag participation measurement keyed by dictionary IDs. Same-written-form Oxford IDs can share one physical occurrence, so these numbers are neither unique physical-form coverage nor resolved stable-ID/POS/sense coverage. Coverage numbers do not by themselves approve redistribution, licensing, provenance or a shipped SentencePack."
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
        ContextCoverageEvidence participation = AnalyzeNaturalCoverage(
            source,
            lexicon,
            scopeEntryIds,
            requiredTargetCount,
            options,
            fallbackCandidateLimit);
        ContextStableIdentityCoverageReport stable = ContextStableIdentityResolution.ResolveCoverage(
            participation.Coverage,
            lexicon,
            scopeEntryIds);
        string boundary = participation.Source.Kind switch
        {
            ContextCorpusKind.SyntheticFixture =>
                "Synthetic/test-only conservative stable-ID measurement. Physically participating homographic stable IDs remain unresolved; physically absent IDs remain coverage gaps. Synthetic data cannot support production coverage.",
            ContextCorpusKind.LocalUserText =>
                "Privacy-local conservative stable-ID measurement. Physically participating homographic stable IDs remain unresolved without explicit POS/sense evidence; absent forms remain local coverage gaps.",
            _ =>
                "Conservative real-corpus stable-ID measurement derived from stable-tag participation under the homograph fail-closed rule. Participating non-homographic dictionary IDs can count as resolved; participating same-written-form multi-ID entries remain unresolved unless a future POS/sense-aware source explicitly disambiguates them, while non-participating entries remain corpus gaps. True unique physical-form coverage remains a separate evidence document."
        };
        return new ContextStableIdentityCoverageEvidence(
            participation.Source,
            participation.Coverage,
            stable,
            participation.IsRealCorpusMeasurement,
            participation.IsPrivacyLocalMeasurement,
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
