namespace WordDeck;

[Flags]
internal enum ContextIntegrationCapabilities
{
    None = 0,
    ReadingContext = 1 << 0,
    GrammarExample = 1 << 1,
    StoryContext = 1 << 2,
    SentenceCoach = 1 << 3,
    SentenceTargetSpelling = 1 << 4,
    UkrainianTranslation = 1 << 5,
    GrammarMetadata = 1 << 6,
    LocalReadingPosition = 1 << 7
}

internal sealed record ContextLearningSentenceReference(
    string SentenceId,
    string English,
    string? Ukrainian,
    IReadOnlyList<string> TargetEntryIds,
    IReadOnlyList<string> GrammarSkillIds,
    ContextSourceDescriptor Source,
    LocalTextContextLocation? LocalTextLocation,
    ContextIntegrationCapabilities Capabilities,
    long? DifficultyScore = null,
    string? DifficultyExplanation = null)
{
    public void Validate()
    {
        RequireCanonical(SentenceId, "Context integration sentence id");
        RequireCanonical(English, "Context integration English text");
        if (Ukrainian is not null)
            RequireCanonical(Ukrainian, "Context integration Ukrainian text");
        Source.Validate();
        LocalTextContextLocation? location = LocalTextLocation;
        location?.Validate();

        string[] ids = ContextTargetIds.NormalizeStudyPool(TargetEntryIds);
        if (ids.Length == 0)
            throw new InvalidDataException("Context integration sentence must preserve at least one stable target ID.");
        if (ids.Length != TargetEntryIds.Count)
            throw new InvalidDataException("Context integration target IDs must be canonical and distinct.");

        if (GrammarSkillIds.Any(string.IsNullOrWhiteSpace))
            throw new InvalidDataException("Context integration grammar metadata contains a blank skill ID.");
        if (GrammarSkillIds.Distinct(StringComparer.OrdinalIgnoreCase).Count() != GrammarSkillIds.Count)
            throw new InvalidDataException("Context integration grammar metadata contains duplicate skill IDs.");

        if (location is not null && Source.Kind != ContextCorpusKind.LocalUserText)
            throw new InvalidDataException("Only private local user text may carry book/chapter reading offsets through the context integration port.");
        if (location is not null && !Capabilities.HasFlag(ContextIntegrationCapabilities.LocalReadingPosition))
            throw new InvalidDataException("Context integration record with local offsets must declare LocalReadingPosition capability.");
        if (Capabilities.HasFlag(ContextIntegrationCapabilities.LocalReadingPosition) && location is null)
            throw new InvalidDataException("LocalReadingPosition capability requires a local reading location.");
        if (Capabilities.HasFlag(ContextIntegrationCapabilities.UkrainianTranslation) != (Ukrainian is not null))
            throw new InvalidDataException("Context integration UkrainianTranslation capability does not match the actual payload.");
        if (Capabilities.HasFlag(ContextIntegrationCapabilities.SentenceTargetSpelling) && Ukrainian is null)
            throw new InvalidDataException("Sentence target spelling requires a real Ukrainian prompt and cannot be enabled for English-only book text.");
        if (Capabilities.HasFlag(ContextIntegrationCapabilities.GrammarMetadata) != (GrammarSkillIds.Count > 0))
            throw new InvalidDataException("Context integration GrammarMetadata capability does not match the actual grammar skill list.");
    }

    public bool Supports(ContextIntegrationCapabilities capability) =>
        (Capabilities & capability) == capability;

    private static void RequireCanonical(string? value, string description)
    {
        if (string.IsNullOrWhiteSpace(value) || !string.Equals(value, value.Trim(), StringComparison.Ordinal))
            throw new InvalidDataException($"{description} is required and must be canonical.");
        SentenceTokenizer.ValidateUnicode(value, description);
    }
}

internal static class ContextIntegrationAdapter
{
    public static ContextLearningSentenceReference FromRanked(RankedContextSentence ranked)
    {
        ArgumentNullException.ThrowIfNull(ranked);
        ranked.Candidate.Validate();

        ContextIntegrationCapabilities capabilities =
            ContextIntegrationCapabilities.ReadingContext |
            ContextIntegrationCapabilities.GrammarExample |
            ContextIntegrationCapabilities.StoryContext |
            ContextIntegrationCapabilities.SentenceCoach |
            ContextIntegrationCapabilities.SentenceTargetSpelling |
            ContextIntegrationCapabilities.UkrainianTranslation;

        if (ranked.Candidate.EffectiveGrammarSkillIds.Count > 0)
            capabilities |= ContextIntegrationCapabilities.GrammarMetadata;
        if (ranked.Candidate.LocalTextLocation is not null)
            capabilities |= ContextIntegrationCapabilities.LocalReadingPosition;

        var reference = new ContextLearningSentenceReference(
            ranked.Candidate.Sentence.Id,
            ranked.Candidate.Sentence.English,
            ranked.Candidate.Sentence.Ukrainian,
            ranked.Candidate.Sentence.TargetEntryIds
                .Select(ContextTargetIds.NormalizeSingle)
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToArray(),
            ranked.Candidate.EffectiveGrammarSkillIds
                .Select(id => id.Trim().ToLowerInvariant())
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToArray(),
            ranked.Candidate.Source,
            ranked.Candidate.LocalTextLocation,
            capabilities,
            ranked.Difficulty.Score,
            ranked.Difficulty.Explanation);
        reference.Validate();
        return reference;
    }

    public static ContextLearningSentenceReference FromPrivateLocalReading(
        string sentenceId,
        string english,
        IReadOnlyCollection<string> stableEntryIds,
        string sourceId,
        string provenance,
        string licenseOrRightsBasis,
        string bookId,
        string chapterId,
        long startOffset,
        long endOffset,
        string? ukrainian = null,
        IReadOnlyCollection<string>? grammarSkillIds = null)
    {
        var source = new ContextSourceDescriptor(
            sourceId,
            ContextCorpusKind.LocalUserText,
            provenance,
            licenseOrRightsBasis,
            PrivacyLocalOnly: true);
        var location = new LocalTextContextLocation(
            sourceId,
            bookId,
            chapterId,
            startOffset,
            endOffset,
            PrivacyLocalOnly: true);

        string[] grammar = (grammarSkillIds ?? Array.Empty<string>())
            .Select(id => (id ?? string.Empty).Trim().ToLowerInvariant())
            .Where(id => id.Length > 0)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();

        ContextIntegrationCapabilities capabilities =
            ContextIntegrationCapabilities.ReadingContext |
            ContextIntegrationCapabilities.GrammarExample |
            ContextIntegrationCapabilities.StoryContext |
            ContextIntegrationCapabilities.LocalReadingPosition;
        if (ukrainian is not null)
        {
            capabilities |= ContextIntegrationCapabilities.UkrainianTranslation |
                            ContextIntegrationCapabilities.SentenceCoach |
                            ContextIntegrationCapabilities.SentenceTargetSpelling;
        }
        if (grammar.Length > 0)
            capabilities |= ContextIntegrationCapabilities.GrammarMetadata;

        var reference = new ContextLearningSentenceReference(
            sentenceId,
            english,
            ukrainian,
            ContextTargetIds.NormalizeStudyPool(stableEntryIds),
            grammar,
            source,
            location,
            capabilities);
        reference.Validate();
        return reference;
    }
}

internal interface IContextLearningQueryPort
{
    IReadOnlyList<ContextLearningSentenceReference> Search(ContextPracticeRequest request);
}

internal sealed class ContextLearningQueryPort : IContextLearningQueryPort
{
    private readonly IContextSentenceSource _source;

    public ContextLearningQueryPort(IContextSentenceSource source)
    {
        _source = source ?? throw new ArgumentNullException(nameof(source));
        _source.Descriptor.Validate();
    }

    public IReadOnlyList<ContextLearningSentenceReference> Search(ContextPracticeRequest request) =>
        ContextPracticeService.Select(_source, request)
            .Select(ContextIntegrationAdapter.FromRanked)
            .ToArray();
}
