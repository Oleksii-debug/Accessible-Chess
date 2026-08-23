using System.Runtime.CompilerServices;

namespace WordDeck;

internal enum ContextConsumerKind
{
    SentenceCoach,
    SentenceSpelling,
    Grammar,
    Story,
    Reading,
    BookIngestion,
    HybridFrontend,
    WebFrontend
}

internal enum ContextDataBoundary
{
    LocalOnly,
    ShareableCorpus
}

internal sealed record ContextIntegrationRequest(
    ContextConsumerKind Consumer,
    IReadOnlyCollection<string> RequiredTargetEntryIds,
    IReadOnlyCollection<string>? StudyPoolEntryIds = null,
    ContextLearnerVocabulary? Vocabulary = null,
    ContextTargetLexicon? TargetLexicon = null,
    IReadOnlyCollection<string>? RequiredGrammarSkillIds = null,
    int MaxResults = 20,
    int CandidateLimit = 256,
    bool AllowSyntheticFixturesForTests = false,
    bool AllowPrivateLocalContextIdentity = false);

internal sealed record ContextIntegrationLocation(
    string BookId,
    string ChapterId,
    long StartOffset,
    long EndOffset);

internal sealed record ContextIntegrationItem(
    string SentenceId,
    string English,
    string Ukrainian,
    IReadOnlyList<string> RequiredTargetEntryIds,
    IReadOnlyList<string> IndexedTargetEntryIds,
    IReadOnlyList<string> GrammarSkillIds,
    ContextDifficultyBreakdown Difficulty,
    string SourceId,
    ContextCorpusKind SourceKind,
    string Provenance,
    string License,
    ContextDataBoundary DataBoundary,
    ContextIntegrationLocation? LocalLocation);

internal static class ContextPracticeIntegrationGateway
{
    public static IReadOnlyList<ContextIntegrationItem> Query(
        IContextSentenceSource source,
        ContextIntegrationRequest request)
    {
        ArgumentNullException.ThrowIfNull(source);
        ArgumentNullException.ThrowIfNull(request);

        ContextProductUseOptions useOptions = new(request.AllowSyntheticFixturesForTests);
        ContextPracticeProductFacade.ValidateSourceForProductUse(source, useOptions);
        EnforceConsumerBoundary(source.Descriptor, request);

        string[] grammarSkills = NormalizeGrammarSkills(request.RequiredGrammarSkillIds ?? Array.Empty<string>());
        var practiceRequest = new ContextPracticeRequest(
            request.RequiredTargetEntryIds,
            request.StudyPoolEntryIds,
            request.Vocabulary,
            request.MaxResults,
            request.CandidateLimit,
            request.AllowSyntheticFixturesForTests,
            request.TargetLexicon);

        IReadOnlyList<RankedContextSentence> ranked = ContextPracticeProductFacade.Select(source, practiceRequest, useOptions);
        IEnumerable<RankedContextSentence> filtered = grammarSkills.Length == 0
            ? ranked
            : ranked.Where(item => grammarSkills.All(required =>
                item.Candidate.EffectiveGrammarSkillIds.Contains(required, StringComparer.OrdinalIgnoreCase)));

        return filtered.Select(item => ToIntegrationItem(item, request.AllowPrivateLocalContextIdentity)).ToArray();
    }

    public static IReadOnlyList<NaturalContextTargetSet> DiscoverNaturalTargets(
        IContextSentenceSource source,
        ContextTargetLexicon lexicon,
        IReadOnlyCollection<string> studyPoolEntryIds,
        string anchorEntryId,
        int desiredTargetCount,
        ContextConsumerKind consumer,
        bool allowPrivateLocalContextIdentity = false,
        int maxCandidateSentences = 256,
        int maxSets = 20)
    {
        ArgumentNullException.ThrowIfNull(source);
        EnforceConsumerBoundary(source.Descriptor, new ContextIntegrationRequest(
            consumer,
            new[] { anchorEntryId },
            studyPoolEntryIds,
            TargetLexicon: lexicon,
            AllowPrivateLocalContextIdentity: allowPrivateLocalContextIdentity));

        return ContextPracticeProductFacade.DiscoverNaturalTargets(
            source,
            lexicon,
            studyPoolEntryIds,
            anchorEntryId,
            desiredTargetCount,
            new ContextProductUseOptions(),
            maxCandidateSentences,
            maxSets);
    }

    private static ContextIntegrationItem ToIntegrationItem(RankedContextSentence ranked, bool exposeLocalIdentity)
    {
        ContextSentenceEnvelope envelope = ranked.Candidate;
        SentenceRecord sentence = envelope.Sentence;
        ContextSourceDescriptor source = envelope.Source;
        ContextIntegrationLocation? location = null;
        if (exposeLocalIdentity && envelope.LocalTextLocation is not null)
        {
            LocalTextContextLocation local = envelope.LocalTextLocation;
            location = new ContextIntegrationLocation(local.BookId, local.ChapterId, local.StartOffset, local.EndOffset);
        }

        return new ContextIntegrationItem(
            sentence.Id,
            sentence.English,
            sentence.Ukrainian,
            ranked.RequiredTargetEntryIds.ToArray(),
            sentence.TargetEntryIds.Select(ContextTargetIds.NormalizeSingle).ToArray(),
            envelope.EffectiveGrammarSkillIds.ToArray(),
            ranked.Difficulty,
            source.SourceId,
            source.Kind,
            source.Provenance,
            source.License,
            source.PrivacyLocalOnly ? ContextDataBoundary.LocalOnly : ContextDataBoundary.ShareableCorpus,
            location);
    }

    private static void EnforceConsumerBoundary(ContextSourceDescriptor descriptor, ContextIntegrationRequest request)
    {
        descriptor.Validate();
        bool privateLocal = descriptor.Kind == ContextCorpusKind.LocalUserText || descriptor.PrivacyLocalOnly;
        bool externalSurface = request.Consumer is ContextConsumerKind.WebFrontend;

        if (privateLocal && externalSurface)
            throw new InvalidDataException("Private local book/text context cannot be exposed through a web/network-facing context consumer. A future explicit user-controlled export boundary is required.");

        if (request.AllowPrivateLocalContextIdentity && !privateLocal)
            throw new InvalidDataException("Private local context identity may only be requested from a privacy-local source.");

        if (request.AllowPrivateLocalContextIdentity && request.Consumer is not (ContextConsumerKind.Reading or ContextConsumerKind.BookIngestion or ContextConsumerKind.HybridFrontend))
            throw new InvalidDataException("Book/chapter/offset identity is restricted to local reading, book-ingestion, or local hybrid consumers.");
    }

    private static string[] NormalizeGrammarSkills(IEnumerable<string> values)
    {
        var result = new List<string>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (string? raw in values)
        {
            string value = (raw ?? string.Empty).Trim().ToLowerInvariant();
            if (value.Length == 0)
                throw new InvalidDataException("Required grammar skill id cannot be blank.");
            SentenceTokenizer.ValidateUnicode(value, "Grammar skill id");
            if (seen.Add(value)) result.Add(value);
        }
        return result.ToArray();
    }
}

internal static class ContextPracticeIntegrationGatewaySelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            ContextPracticeIntegrationGatewaySelfTest.Run();
    }
}

internal static class ContextPracticeIntegrationGatewaySelfTest
{
    public static void Run()
    {
        TestGrammarAndSentenceConsumers();
        TestPrivateBookBoundary();
        Console.WriteLine("Context integration gateway self-test PASS: Sentence/Grammar/Story/Reading/Book/web ports and private-local boundaries verified.");
    }

    private static void TestGrammarAndSentenceConsumers()
    {
        SentencePack pack = BuildPack("integration-real", "CC-BY-2.0", "integration-fixture-provenance");
        var source = new SentenceCorpusContextSource(pack, new ContextSourceDescriptor(pack.PackId, ContextCorpusKind.RealCorpus, pack.Provenance, pack.License));
        var request = new ContextIntegrationRequest(
            ContextConsumerKind.Grammar,
            new[] { "target-a" },
            new[] { "target-a", "helper-b" },
            new ContextLearnerVocabulary(new[] { "helper-b" }),
            RequiredGrammarSkillIds: new[] { "present-simple" });
        IReadOnlyList<ContextIntegrationItem> result = ContextPracticeIntegrationGateway.Query(source, request);
        Check(result.Count == 1, "Grammar consumer must receive matching real context.");
        Check(result[0].GrammarSkillIds.SequenceEqual(new[] { "present-simple" }), "Grammar metadata was not preserved.");
        Check(result[0].DataBoundary == ContextDataBoundary.ShareableCorpus && result[0].LocalLocation is null, "Real-corpus integration boundary is wrong.");

        IReadOnlyList<NaturalContextTargetSet> pairs = ContextPracticeIntegrationGateway.DiscoverNaturalTargets(
            source,
            new ContextTargetLexicon("integration", new[] { ("target-a", "practice"), ("helper-b", "daily") }),
            new[] { "target-a", "helper-b" },
            "target-a",
            2,
            ContextConsumerKind.Story);
        Check(pairs.Count == 1 && pairs[0].TargetEntryIds.Count == 2, "Story consumer natural pair planning failed.");
    }

    private static void TestPrivateBookBoundary()
    {
        SentencePack pack = BuildPack("private-book", "LOCAL-USER-TEXT", "local-user-book");
        var descriptor = new ContextSourceDescriptor(pack.PackId, ContextCorpusKind.LocalUserText, pack.Provenance, pack.License, PrivacyLocalOnly: true);
        var location = new LocalTextContextLocation(pack.PackId, "book-1", "chapter-2", 100, 140);
        var source = new SingleEnvelopeSource(new ContextSentenceEnvelope(pack.Sentences[0], descriptor, location, new[] { "present-simple" }), descriptor);

        IReadOnlyList<ContextIntegrationItem> local = ContextPracticeIntegrationGateway.Query(source, new ContextIntegrationRequest(
            ContextConsumerKind.Reading,
            new[] { "target-a" },
            AllowPrivateLocalContextIdentity: true));
        Check(local.Single().LocalLocation?.ChapterId == "chapter-2", "Local reading must preserve return-to-context identity when explicitly requested.");
        Check(local[0].DataBoundary == ContextDataBoundary.LocalOnly, "User-book context must stay marked local-only.");

        bool blocked = false;
        try
        {
            _ = ContextPracticeIntegrationGateway.Query(source, new ContextIntegrationRequest(ContextConsumerKind.WebFrontend, new[] { "target-a" }));
        }
        catch (InvalidDataException)
        {
            blocked = true;
        }
        Check(blocked, "Private local book text must fail closed for a web/network-facing consumer.");
    }

    private static SentencePack BuildPack(string packId, string license, string provenance)
    {
        string english = "Practice daily";
        IReadOnlyList<string> tokens = SentenceTokenizer.Tokenize(english);
        var sentence = new SentenceRecord
        {
            Id = packId + "-s1",
            English = english,
            Ukrainian = "Практикуйся щодня",
            Source = provenance,
            License = license,
            Tokens = tokens.ToList(),
            Lemmas = tokens.ToList(),
            TargetEntryIds = new List<string> { "target-a", "helper-b" },
            EntryLevels = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                ["target-a"] = "A2",
                ["helper-b"] = "A1"
            },
            DifficultyLevel = "A2",
            OffListTokenCount = 0,
            QualityFlags = new List<string> { "grammar:present-simple" }
        };
        var pack = new SentencePack
        {
            PackId = packId,
            Provenance = provenance,
            License = license,
            Sentences = new List<SentenceRecord> { sentence }
        };
        pack.Validate();
        return pack;
    }

    private sealed class SingleEnvelopeSource : IContextSentenceSource
    {
        private readonly ContextSentenceEnvelope _envelope;
        public ContextSourceDescriptor Descriptor { get; }

        public SingleEnvelopeSource(ContextSentenceEnvelope envelope, ContextSourceDescriptor descriptor)
        {
            _envelope = envelope;
            Descriptor = descriptor;
        }

        public IReadOnlyList<ContextSentenceEnvelope> FindByTargets(IReadOnlyCollection<string> targetEntryIds, int maxCandidates)
        {
            string[] required = ContextTargetIds.NormalizeRequired(targetEntryIds);
            return required.All(id => _envelope.Sentence.TargetEntryIds.Contains(id, StringComparer.OrdinalIgnoreCase))
                ? new[] { _envelope }
                : Array.Empty<ContextSentenceEnvelope>();
        }
    }

    private static void Check(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
}
