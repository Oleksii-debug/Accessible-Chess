namespace WordDeck;

internal enum ContextCorpusKind
{
    RealCorpus,
    LocalUserText,
    SyntheticFixture
}

internal sealed record ContextSourceDescriptor(
    string SourceId,
    ContextCorpusKind Kind,
    string Provenance,
    string License,
    bool PrivacyLocalOnly = false)
{
    public void Validate()
    {
        Require(SourceId, "Context source id");
        Require(Provenance, "Context source provenance");
        Require(License, "Context source license");
        if (Kind == ContextCorpusKind.LocalUserText && !PrivacyLocalOnly)
            throw new InvalidDataException("Local user text context sources must be privacy-local only.");
    }

    private static void Require(string? value, string description)
    {
        if (string.IsNullOrWhiteSpace(value) || !string.Equals(value, value.Trim(), StringComparison.Ordinal))
            throw new InvalidDataException($"{description} is required and must be canonical.");
        SentenceTokenizer.ValidateUnicode(value, description);
    }
}

internal sealed record LocalTextContextLocation(
    string SourceId,
    string BookId,
    string ChapterId,
    long StartOffset,
    long EndOffset,
    bool PrivacyLocalOnly = true)
{
    public void Validate()
    {
        Require(SourceId, "Local text source id");
        Require(BookId, "Local text book id");
        Require(ChapterId, "Local text chapter id");
        if (StartOffset < 0 || EndOffset < StartOffset)
            throw new InvalidDataException("Local text sentence offsets are invalid.");
        if (!PrivacyLocalOnly)
            throw new InvalidDataException("Imported book/text context is privacy-local by default and cannot be marked non-local here.");
    }

    private static void Require(string? value, string description)
    {
        if (string.IsNullOrWhiteSpace(value) || !string.Equals(value, value.Trim(), StringComparison.Ordinal))
            throw new InvalidDataException($"{description} is required and must be canonical.");
    }
}

internal sealed record ContextSentenceEnvelope(
    SentenceRecord Sentence,
    ContextSourceDescriptor Source,
    LocalTextContextLocation? LocalTextLocation = null,
    IReadOnlyList<string>? GrammarSkillIds = null)
{
    public IReadOnlyList<string> EffectiveGrammarSkillIds => GrammarSkillIds ?? Array.Empty<string>();

    public void Validate()
    {
        Sentence.Validate();
        Source.Validate();
        LocalTextLocation?.Validate();
        if (LocalTextLocation is not null && Source.Kind != ContextCorpusKind.LocalUserText)
            throw new InvalidDataException("Book/chapter offsets may only be attached to a local user-text context source.");
        if (LocalTextLocation is not null && !string.Equals(LocalTextLocation.SourceId, Source.SourceId, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Local book/text location source identity does not match its context source descriptor.");
        if (EffectiveGrammarSkillIds.Any(string.IsNullOrWhiteSpace))
            throw new InvalidDataException("Context grammar-skill metadata contains a blank skill id.");
    }
}

internal interface IContextSentenceSource
{
    ContextSourceDescriptor Descriptor { get; }
    IReadOnlyList<ContextSentenceEnvelope> FindByTargets(IReadOnlyCollection<string> targetEntryIds, int maxCandidates);
}

internal interface IContextCoverageSource
{
    IReadOnlySet<string> GetCoveredOneTargetIds(IReadOnlyCollection<string> candidateEntryIds);
}

internal sealed class SentenceCorpusContextSource : IContextSentenceSource
{
    private const int MaxCandidates = SentencePackSqliteRuntimeQuery.DefaultCandidateLimit;
    private readonly ISentenceCorpus _corpus;

    public ContextSourceDescriptor Descriptor { get; }

    public SentenceCorpusContextSource(ISentenceCorpus corpus, ContextSourceDescriptor descriptor)
    {
        _corpus = corpus ?? throw new ArgumentNullException(nameof(corpus));
        Descriptor = descriptor ?? throw new ArgumentNullException(nameof(descriptor));
        Descriptor.Validate();
        if (!string.Equals(_corpus.PackId, Descriptor.SourceId, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Context source descriptor id does not match the SentencePack id.");
        if (!string.Equals(_corpus.License, Descriptor.License, StringComparison.Ordinal))
            throw new InvalidDataException("Context source descriptor license does not match the SentencePack license.");
    }

    public IReadOnlyList<ContextSentenceEnvelope> FindByTargets(IReadOnlyCollection<string> targetEntryIds, int maxCandidates)
    {
        if (maxCandidates is < 1 or > MaxCandidates)
            throw new ArgumentOutOfRangeException(nameof(maxCandidates));
        string[] required = ContextTargetIds.NormalizeRequired(targetEntryIds);
        return _corpus.LookupAllTargets(required)
            .Take(maxCandidates)
            .Select(sentence => new ContextSentenceEnvelope(
                sentence,
                Descriptor,
                null,
                ContextGrammarMetadata.ExtractFromQualityFlags(sentence.QualityFlags)))
            .ToArray();
    }
}

internal sealed class ContextLearnerVocabulary
{
    private readonly HashSet<string> _known;
    private readonly HashSet<string> _learning;

    public IReadOnlySet<string> KnownEntryIds => _known;
    public IReadOnlySet<string> LearningEntryIds => _learning;

    public ContextLearnerVocabulary(IEnumerable<string>? knownEntryIds = null, IEnumerable<string>? learningEntryIds = null)
    {
        _known = new HashSet<string>(ContextTargetIds.NormalizeStudyPool(knownEntryIds ?? Array.Empty<string>()), StringComparer.OrdinalIgnoreCase);
        _learning = new HashSet<string>(ContextTargetIds.NormalizeStudyPool(learningEntryIds ?? Array.Empty<string>()), StringComparer.OrdinalIgnoreCase);
        _learning.ExceptWith(_known);
    }

    public bool IsKnown(string entryId) => _known.Contains(ContextTargetIds.NormalizeSingle(entryId));
    public bool IsLearning(string entryId) => _learning.Contains(ContextTargetIds.NormalizeSingle(entryId));
}

internal sealed record ContextPracticeRequest(
    IReadOnlyCollection<string> RequiredTargetEntryIds,
    IReadOnlyCollection<string>? StudyPoolEntryIds = null,
    ContextLearnerVocabulary? Vocabulary = null,
    int MaxResults = 20,
    int CandidateLimit = 256,
    bool AllowSyntheticFixtures = false,
    ContextTargetLexicon? TargetLexicon = null);

internal sealed record ContextDifficultyBreakdown(
    int KnownHelperEntries,
    int LearningHelperEntries,
    int UnknownHelperEntries,
    int OffListTokens,
    int CefrRank,
    int TokenCount,
    long Score,
    string Explanation);

internal sealed record RankedContextSentence(
    ContextSentenceEnvelope Candidate,
    IReadOnlyList<string> RequiredTargetEntryIds,
    ContextDifficultyBreakdown Difficulty);

internal static class ContextPracticeService
{
    public const int MaxResults = 100;
    public const int MaxCandidateLimit = SentencePackSqliteRuntimeQuery.DefaultCandidateLimit;

    public static IReadOnlyList<RankedContextSentence> Select(IContextSentenceSource source, ContextPracticeRequest request)
    {
        ArgumentNullException.ThrowIfNull(source);
        ArgumentNullException.ThrowIfNull(request);
        source.Descriptor.Validate();

        if (request.MaxResults is < 1 or > MaxResults)
            throw new ArgumentOutOfRangeException(nameof(request.MaxResults));
        if (request.CandidateLimit < request.MaxResults || request.CandidateLimit > MaxCandidateLimit)
            throw new ArgumentOutOfRangeException(nameof(request.CandidateLimit), "Candidate limit must be at least MaxResults and remain bounded by the SentencePack runtime limit.");

        string[] required = ContextTargetIds.NormalizeRequired(request.RequiredTargetEntryIds);
        if (required.Length > 1)
        {
            if (request.TargetLexicon is null)
                throw new InvalidDataException("Multi-target context selection requires the Oxford lexical catalog so same-written-form stable IDs cannot be miscounted as multiple physical target words.");
            request.TargetLexicon.EnsureDistinctLexicalTargets(required);
        }

        string[] pool = ContextTargetIds.NormalizeStudyPool(request.StudyPoolEntryIds ?? Array.Empty<string>());
        if (pool.Length > 0)
        {
            var poolSet = new HashSet<string>(pool, StringComparer.OrdinalIgnoreCase);
            if (required.Any(id => !poolSet.Contains(id)))
                throw new InvalidDataException("Every required context target must belong to the supplied study list/deck.");
        }

        if (source.Descriptor.Kind == ContextCorpusKind.SyntheticFixture && !request.AllowSyntheticFixtures)
            return Array.Empty<RankedContextSentence>();

        ContextLearnerVocabulary vocabulary = request.Vocabulary ?? new ContextLearnerVocabulary();
        IReadOnlyList<ContextSentenceEnvelope> raw = source.FindByTargets(required, request.CandidateLimit);
        var ranked = new List<RankedContextSentence>(Math.Min(raw.Count, request.MaxResults));
        foreach (ContextSentenceEnvelope candidate in raw)
        {
            candidate.Validate();
            var candidateTargets = new HashSet<string>(candidate.Sentence.TargetEntryIds.Select(ContextTargetIds.NormalizeSingle), StringComparer.OrdinalIgnoreCase);
            if (required.Any(id => !candidateTargets.Contains(id)))
                throw new InvalidDataException($"Context source returned sentence {candidate.Sentence.Id} without every requested stable target id.");

            ContextDifficultyBreakdown difficulty = Score(candidate.Sentence, required, vocabulary, request.TargetLexicon);
            ranked.Add(new RankedContextSentence(candidate, required, difficulty));
        }

        return ranked
            .OrderBy(item => item.Difficulty.Score)
            .ThenBy(item => item.Difficulty.OffListTokens)
            .ThenBy(item => item.Difficulty.UnknownHelperEntries)
            .ThenBy(item => item.Difficulty.LearningHelperEntries)
            .ThenBy(item => item.Candidate.Sentence.Id, StringComparer.Ordinal)
            .Take(request.MaxResults)
            .ToArray();
    }

    internal static ContextDifficultyBreakdown Score(
        SentenceRecord sentence,
        IReadOnlyCollection<string> requiredTargetEntryIds,
        ContextLearnerVocabulary vocabulary,
        ContextTargetLexicon? targetLexicon = null)
    {
        string[] required = ContextTargetIds.NormalizeRequired(requiredTargetEntryIds);
        var requiredStableSet = new HashSet<string>(required, StringComparer.OrdinalIgnoreCase);
        var requiredLexicalSet = targetLexicon is null
            ? new HashSet<string>(required, StringComparer.OrdinalIgnoreCase)
            : new HashSet<string>(required.Select(targetLexicon.LexicalKeyFor), StringComparer.OrdinalIgnoreCase);

        var helperGroups = sentence.TargetEntryIds
            .Select(ContextTargetIds.NormalizeSingle)
            .Where(id => !requiredStableSet.Contains(id))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Select(id => new { Id = id, LexicalKey = targetLexicon?.LexicalKeyForOrStableId(id) ?? id })
            .Where(item => !requiredLexicalSet.Contains(item.LexicalKey))
            .GroupBy(item => item.LexicalKey, StringComparer.OrdinalIgnoreCase)
            .ToArray();

        int known = 0;
        int learning = 0;
        int unknown = 0;
        foreach (var group in helperGroups)
        {
            string[] ids = group.Select(item => item.Id).ToArray();
            if (ids.All(vocabulary.IsKnown))
                known++;
            else if (ids.Any(id => vocabulary.IsKnown(id) || vocabulary.IsLearning(id)))
                learning++;
            else
                unknown++;
        }

        int offList = sentence.OffListTokenCount;
        int cefr = CefrRank(sentence.DifficultyLevel);
        int tokenCount = sentence.Length;

        // Actual learner lexical state intentionally dominates coarse CEFR metadata.
        // Same-written-form stable IDs are one helper lexical group for difficulty,
        // while their stable identities remain separate in learner progress.
        long score = checked((long)offList * 1000L + (long)unknown * 200L + (long)learning * 60L + (long)cefr * 10L + Math.Min(tokenCount, 99));
        string explanation = $"known helper lexical groups={known}; learning helper lexical groups={learning}; unknown helper lexical groups={unknown}; off-list tokens={offList}; CEFR={sentence.DifficultyLevel}; tokens={tokenCount}";
        return new ContextDifficultyBreakdown(known, learning, unknown, offList, cefr, tokenCount, score, explanation);
    }

    private static int CefrRank(string? level) => (level ?? string.Empty).Trim().ToUpperInvariant() switch
    {
        "A1" => 1,
        "A2" => 2,
        "B1" => 3,
        "B2" => 4,
        "C1" => 5,
        _ => 6
    };
}

internal sealed record ContextCoverageReport(
    int RequestedEntryCount,
    int CoveredEntryCount,
    int UncoveredEntryCount,
    IReadOnlyList<string> CoveredEntryIds,
    IReadOnlyList<string> UncoveredEntryIds)
{
    public double CoveragePercent => RequestedEntryCount == 0 ? 100.0 : CoveredEntryCount * 100.0 / RequestedEntryCount;
}

internal sealed record ContextTargetSetCoverage(
    IReadOnlyList<string> TargetEntryIds,
    bool Covered,
    int MatchingSentenceCount);

internal static class ContextCoverageAnalyzer
{
    public static ContextCoverageReport AnalyzeOneTargetUniverse(IContextSentenceSource source, IReadOnlyCollection<string> entryIds)
    {
        ArgumentNullException.ThrowIfNull(source);
        string[] requested = ContextTargetIds.NormalizeStudyPool(entryIds);
        IReadOnlySet<string> coveredSet;
        if (source is IContextCoverageSource optimized)
        {
            coveredSet = optimized.GetCoveredOneTargetIds(requested);
        }
        else
        {
            var covered = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (string id in requested)
            {
                if (source.FindByTargets(new[] { id }, 1).Count > 0)
                    covered.Add(id);
            }
            coveredSet = covered;
        }

        string[] coveredOrdered = requested.Where(coveredSet.Contains).ToArray();
        string[] uncovered = requested.Where(id => !coveredSet.Contains(id)).ToArray();
        if (coveredOrdered.Length + uncovered.Length != requested.Length)
            throw new InvalidOperationException("Context coverage accounting did not partition the requested stable-id universe.");
        return new ContextCoverageReport(requested.Length, coveredOrdered.Length, uncovered.Length, coveredOrdered, uncovered);
    }

    public static IReadOnlyList<ContextTargetSetCoverage> AnalyzeRequestedTargetSets(
        IContextSentenceSource source,
        IEnumerable<IReadOnlyCollection<string>> requestedTargetSets,
        int countLimitPerSet = 128)
    {
        ArgumentNullException.ThrowIfNull(source);
        if (countLimitPerSet is < 1 or > SentencePackSqliteRuntimeQuery.DefaultCandidateLimit)
            throw new ArgumentOutOfRangeException(nameof(countLimitPerSet));

        var result = new List<ContextTargetSetCoverage>();
        foreach (IReadOnlyCollection<string> set in requestedTargetSets)
        {
            string[] normalized = ContextTargetIds.NormalizeRequired(set);
            int count = source.FindByTargets(normalized, countLimitPerSet).Count;
            result.Add(new ContextTargetSetCoverage(normalized, count > 0, count));
        }
        return result;
    }
}

internal static class ContextTargetIds
{
    public const int MaxOxfordTargetPool = 5446;

    public static string NormalizeSingle(string? value)
    {
        string id = (value ?? string.Empty).Trim().ToLowerInvariant();
        if (id.Length == 0)
            throw new InvalidDataException("Context target stable id cannot be blank.");
        SentenceTokenizer.ValidateUnicode(id, "Context target stable id");
        return id;
    }

    public static string[] NormalizeRequired(IEnumerable<string> values)
    {
        string[] result = Normalize(values, maxCount: 3);
        if (result.Length is < 1 or > 3)
            throw new InvalidDataException("Context practice requires one, two, or three distinct stable target ids.");
        return result;
    }

    public static string[] NormalizeStudyPool(IEnumerable<string> values) => Normalize(values, MaxOxfordTargetPool);

    private static string[] Normalize(IEnumerable<string> values, int maxCount)
    {
        ArgumentNullException.ThrowIfNull(values);
        var result = new List<string>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (string raw in values)
        {
            string id = NormalizeSingle(raw);
            if (!seen.Add(id))
                continue;
            result.Add(id);
            if (result.Count > maxCount)
                throw new InvalidDataException($"Context target list exceeds the supported bound of {maxCount} stable ids.");
        }
        return result.ToArray();
    }
}

internal static class ContextGrammarMetadata
{
    private const string Prefix = "grammar:";

    public static IReadOnlyList<string> ExtractFromQualityFlags(IEnumerable<string> qualityFlags) =>
        qualityFlags
            .Where(flag => flag.StartsWith(Prefix, StringComparison.OrdinalIgnoreCase) && flag.Length > Prefix.Length)
            .Select(flag => flag[Prefix.Length..].Trim().ToLowerInvariant())
            .Where(id => id.Length > 0)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(id => id, StringComparer.Ordinal)
            .ToArray();
}
