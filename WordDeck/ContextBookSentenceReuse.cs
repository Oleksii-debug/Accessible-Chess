using System.Runtime.CompilerServices;

namespace WordDeck;

/// <summary>
/// Platform-neutral handoff contract for private local book/reading sentences.
/// DEV03 can map its BookSentenceRecord into this DTO after integration without
/// DEV02 taking ownership of book parsing or persistence.
/// </summary>
internal sealed record ContextBookSentenceInput(
    string SourceId,
    string BookId,
    string ChapterId,
    string SentenceId,
    string English,
    string? Ukrainian,
    long StartOffset,
    long EndOffset,
    IReadOnlyList<string> StableEntryIds,
    IReadOnlyDictionary<string, string> EntryLevels,
    string DifficultyLevel,
    int OffListTokenCount,
    IReadOnlyList<string>? GrammarSkillIds = null)
{
    public void Validate()
    {
        Require(SourceId, "Book context source id");
        Require(BookId, "Book context book id");
        Require(ChapterId, "Book context chapter id");
        Require(SentenceId, "Book context sentence id");
        Require(English, "Book context English sentence");
        if (English.IndexOfAny(new[] { '\r', '\n', '\t' }) >= 0)
            throw new InvalidDataException("Book context English sentence must be a single canonical line.");
        if (Ukrainian is not null)
        {
            Require(Ukrainian, "Book context Ukrainian sentence");
            if (Ukrainian.IndexOfAny(new[] { '\r', '\n', '\t' }) >= 0)
                throw new InvalidDataException("Book context Ukrainian sentence must be a single canonical line.");
        }
        if (StartOffset < 0 || EndOffset < StartOffset)
            throw new InvalidDataException("Book context sentence offsets are invalid.");

        string[] stableIds = ContextTargetIds.NormalizeStudyPool(StableEntryIds ?? Array.Empty<string>());
        if (stableIds.Length == 0)
            throw new InvalidDataException("Book context sentence must map at least one stable dictionary entry before it can enter Context Practice.");
        if (EntryLevels is null)
            throw new InvalidDataException("Book context sentence entry-level metadata is required.");
        foreach (string id in stableIds)
        {
            if (!EntryLevels.TryGetValue(id, out string? level) || !IsSupportedLevel(level))
                throw new InvalidDataException($"Book context sentence is missing a supported CEFR level for stable entry {id}.");
        }
        if (!IsSupportedLevel(DifficultyLevel))
            throw new InvalidDataException("Book context sentence difficulty must be A1-C1.");

        int tokenCount = SentenceTokenizer.Tokenize(English).Count;
        if (tokenCount == 0)
            throw new InvalidDataException("Book context English sentence contains no supported lexical tokens.");
        if (OffListTokenCount < 0 || OffListTokenCount > tokenCount)
            throw new InvalidDataException("Book context off-list token count is outside the sentence token boundary.");

        _ = NormalizeGrammarSkillIds(GrammarSkillIds ?? Array.Empty<string>());
    }

    public bool HasExplicitUkrainianPair => !string.IsNullOrWhiteSpace(Ukrainian);

    internal static string[] NormalizeGrammarSkillIds(IEnumerable<string> values)
    {
        ArgumentNullException.ThrowIfNull(values);
        var result = new List<string>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (string? raw in values)
        {
            string id = (raw ?? string.Empty).Trim().ToLowerInvariant();
            if (id.Length == 0)
                throw new InvalidDataException("Book context grammar skill id cannot be blank.");
            SentenceTokenizer.ValidateUnicode(id, "Book context grammar skill id");
            if (seen.Add(id)) result.Add(id);
        }
        return result.ToArray();
    }

    private static bool IsSupportedLevel(string? value) =>
        (value ?? string.Empty).Trim().ToUpperInvariant() is "A1" or "A2" or "B1" or "B2" or "C1";

    private static void Require(string? value, string description)
    {
        if (string.IsNullOrWhiteSpace(value) || !string.Equals(value, value.Trim(), StringComparison.Ordinal))
            throw new InvalidDataException($"{description} is required and must be canonical.");
        SentenceTokenizer.ValidateUnicode(value, description);
    }
}

internal sealed record ContextBookReuseDecision(
    string SentenceId,
    bool ReadingContextEligible,
    bool ActiveSentencePracticeEligible,
    bool GrammarContextEligible,
    string Reason);

internal static class ContextBookSentenceReusePolicy
{
    public static ContextBookReuseDecision Evaluate(ContextBookSentenceInput input)
    {
        ArgumentNullException.ThrowIfNull(input);
        input.Validate();
        if (!input.HasExplicitUkrainianPair)
        {
            return new ContextBookReuseDecision(
                input.SentenceId,
                ReadingContextEligible: true,
                ActiveSentencePracticeEligible: false,
                GrammarContextEligible: false,
                "Private book sentence has English context and stable lexical mapping, but no explicit Ukrainian counterpart. Reading/context reuse is allowed; Sentence/Grammar active production must fail closed instead of inventing a translation.");
        }

        return new ContextBookReuseDecision(
            input.SentenceId,
            ReadingContextEligible: true,
            ActiveSentencePracticeEligible: true,
            GrammarContextEligible: true,
            "Private book sentence has an explicit EN-UA pair and may be adapted into local-only Context/Sentence/Grammar practice while retaining book/chapter/offset identity.");
    }
}

/// <summary>
/// Creates an IContextSentenceSource only from explicit EN-UA private book pairs.
/// Raw English-only book text never receives a placeholder or generated Ukrainian
/// translation here. The resulting source remains LocalUserText/PrivacyLocalOnly.
/// </summary>
internal static class ContextBookSentenceSourceFactory
{
    public const string LocalUserTextLicense = "LOCAL-USER-TEXT";

    public static IContextSentenceSource CreateForActivePractice(
        string sourceId,
        string provenance,
        IEnumerable<ContextBookSentenceInput> inputs)
    {
        if (string.IsNullOrWhiteSpace(sourceId) || !string.Equals(sourceId, sourceId.Trim(), StringComparison.Ordinal))
            throw new InvalidDataException("Private book context source id is required and must be canonical.");
        if (string.IsNullOrWhiteSpace(provenance) || !string.Equals(provenance, provenance.Trim(), StringComparison.Ordinal))
            throw new InvalidDataException("Private book context provenance is required and must be canonical.");
        ArgumentNullException.ThrowIfNull(inputs);

        ContextBookSentenceInput[] all = inputs.ToArray();
        if (all.Length == 0)
            throw new InvalidDataException("Private book context source requires at least one sentence input.");
        foreach (ContextBookSentenceInput input in all)
        {
            input.Validate();
            if (!string.Equals(input.SourceId, sourceId, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Private book context input source id does not match the requested source.");
        }

        ContextBookSentenceInput[] paired = all.Where(input => input.HasExplicitUkrainianPair).ToArray();
        if (paired.Length == 0)
            throw new InvalidDataException("No explicit EN-UA book sentence pairs are available for active Sentence/Grammar practice. English-only book text remains Reading/context material; no translation was fabricated.");

        var descriptor = new ContextSourceDescriptor(
            sourceId,
            ContextCorpusKind.LocalUserText,
            provenance,
            LocalUserTextLicense,
            PrivacyLocalOnly: true);
        return new LocalBookSentenceContextSource(descriptor, paired);
    }

    private sealed class LocalBookSentenceContextSource : IContextSentenceSource, IContextCoverageSource
    {
        private readonly ContextSentenceEnvelope[] _sentences;
        public ContextSourceDescriptor Descriptor { get; }

        public LocalBookSentenceContextSource(ContextSourceDescriptor descriptor, IEnumerable<ContextBookSentenceInput> inputs)
        {
            Descriptor = descriptor;
            Descriptor.Validate();
            _sentences = inputs.Select(ToEnvelope).ToArray();
            if (_sentences.Select(item => item.Sentence.Id).Distinct(StringComparer.OrdinalIgnoreCase).Count() != _sentences.Length)
                throw new InvalidDataException("Private book context source contains duplicate stable sentence ids.");
        }

        public IReadOnlyList<ContextSentenceEnvelope> FindByTargets(IReadOnlyCollection<string> targetEntryIds, int maxCandidates)
        {
            if (maxCandidates is < 1 or > SentencePackSqliteRuntimeQuery.DefaultCandidateLimit)
                throw new ArgumentOutOfRangeException(nameof(maxCandidates));
            string[] required = ContextTargetIds.NormalizeRequired(targetEntryIds);
            return _sentences
                .Where(item => required.All(id => item.Sentence.TargetEntryIds.Contains(id, StringComparer.OrdinalIgnoreCase)))
                .OrderBy(item => item.LocalTextLocation!.BookId, StringComparer.Ordinal)
                .ThenBy(item => item.LocalTextLocation!.ChapterId, StringComparer.Ordinal)
                .ThenBy(item => item.LocalTextLocation!.StartOffset)
                .ThenBy(item => item.Sentence.Id, StringComparer.Ordinal)
                .Take(maxCandidates)
                .ToArray();
        }

        public IReadOnlySet<string> GetCoveredOneTargetIds(IReadOnlyCollection<string> candidateEntryIds)
        {
            string[] candidates = ContextTargetIds.NormalizeStudyPool(candidateEntryIds);
            var indexed = new HashSet<string>(
                _sentences.SelectMany(item => item.Sentence.TargetEntryIds),
                StringComparer.OrdinalIgnoreCase);
            return new HashSet<string>(candidates.Where(indexed.Contains), StringComparer.OrdinalIgnoreCase);
        }

        private ContextSentenceEnvelope ToEnvelope(ContextBookSentenceInput input)
        {
            string[] tokens = SentenceTokenizer.Tokenize(input.English).ToArray();
            string[] stableIds = ContextTargetIds.NormalizeStudyPool(input.StableEntryIds);
            var levels = stableIds.ToDictionary(
                id => id,
                id => input.EntryLevels[id].Trim().ToUpperInvariant(),
                StringComparer.OrdinalIgnoreCase);
            string[] grammarIds = ContextBookSentenceInput.NormalizeGrammarSkillIds(input.GrammarSkillIds ?? Array.Empty<string>());
            var record = new SentenceRecord
            {
                Id = input.SentenceId,
                English = input.English,
                Ukrainian = input.Ukrainian!,
                Source = Descriptor.Provenance,
                License = Descriptor.License,
                Tokens = tokens.ToList(),
                // Book reuse is exact-lexical-form based at this boundary. Do not
                // claim NLP lemmatization that DEV03 did not perform.
                Lemmas = tokens.ToList(),
                TargetEntryIds = stableIds.ToList(),
                EntryLevels = levels,
                DifficultyLevel = input.DifficultyLevel.Trim().ToUpperInvariant(),
                OffListTokenCount = input.OffListTokenCount,
                QualityFlags = grammarIds.Select(id => "grammar:" + id)
                    .Append("local-book-exact-lexical-form")
                    .ToList()
            };
            record.Validate();
            var location = new LocalTextContextLocation(
                Descriptor.SourceId,
                input.BookId,
                input.ChapterId,
                input.StartOffset,
                input.EndOffset,
                PrivacyLocalOnly: true);
            return new ContextSentenceEnvelope(record, Descriptor, location, grammarIds);
        }
    }
}

internal static class ContextBookSentenceReuseSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            ContextBookSentenceReuseSelfTest.Run();
    }
}

internal static class ContextBookSentenceReuseSelfTest
{
    public static void Run()
    {
        TestEnglishOnlyBookSentenceStaysReadingOnly();
        TestExplicitPairCreatesPrivateLocalPracticeSource();
        Console.WriteLine("Context book-sentence reuse self-test PASS: English-only Reading reuse, explicit EN-UA active-practice boundary, local identity and no-network policy verified.");
    }

    private static void TestEnglishOnlyBookSentenceStaysReadingOnly()
    {
        ContextBookSentenceInput raw = MakeInput(ukrainian: null);
        ContextBookReuseDecision decision = ContextBookSentenceReusePolicy.Evaluate(raw);
        Check(decision.ReadingContextEligible, "English-only private book sentence should remain available to Reading/context.");
        Check(!decision.ActiveSentencePracticeEligible && !decision.GrammarContextEligible,
            "English-only private book sentence must not enter EN-UA active production.");

        bool blocked = false;
        try
        {
            _ = ContextBookSentenceSourceFactory.CreateForActivePractice(raw.SourceId, "private-local-book-test", new[] { raw });
        }
        catch (InvalidDataException ex)
        {
            blocked = ex.Message.Contains("no translation was fabricated", StringComparison.OrdinalIgnoreCase);
        }
        Check(blocked, "Active-practice bridge must fail closed when a private book sentence has no explicit Ukrainian pair.");
    }

    private static void TestExplicitPairCreatesPrivateLocalPracticeSource()
    {
        ContextBookSentenceInput paired = MakeInput("Я практикуюся щодня.");
        IContextSentenceSource source = ContextBookSentenceSourceFactory.CreateForActivePractice(
            paired.SourceId,
            "private-local-book-test",
            new[] { paired });

        var lexicon = new ContextTargetLexicon("book-reuse-test", new[]
        {
            ("entry-practice", "practice"),
            ("entry-daily", "daily")
        });
        IReadOnlyList<ContextIntegrationItem> items = ContextPracticeIntegrationGateway.Query(
            source,
            new ContextIntegrationRequest(
                ContextConsumerKind.Reading,
                new[] { "entry-practice" },
                new[] { "entry-practice", "entry-daily" },
                TargetLexicon: lexicon,
                RequiredGrammarSkillIds: new[] { "present.simple.core" },
                AllowPrivateLocalContextIdentity: true));

        Check(items.Count == 1, "Explicit EN-UA private book pair should be queryable through the context gateway.");
        Check(items[0].DataBoundary == ContextDataBoundary.LocalOnly && !items[0].RedistributionApproved,
            "Private book reuse must remain local-only and non-redistributable.");
        Check(items[0].LocalLocation?.BookId == paired.BookId && items[0].LocalLocation?.ChapterId == paired.ChapterId,
            "Private book reuse lost return-to-context identity.");
        Check(items[0].GrammarSkillIds.Contains("present.simple.core", StringComparer.OrdinalIgnoreCase),
            "Private book reuse lost grammar-skill metadata.");

        bool webBlocked = false;
        try
        {
            _ = ContextPracticeIntegrationGateway.Query(source, new ContextIntegrationRequest(
                ContextConsumerKind.WebFrontend,
                new[] { "entry-practice" }));
        }
        catch (InvalidDataException)
        {
            webBlocked = true;
        }
        Check(webBlocked, "Private local book sentence must never cross into the web/network context consumer by default.");
    }

    private static ContextBookSentenceInput MakeInput(string? ukrainian)
    {
        return new ContextBookSentenceInput(
            "private-book-source",
            "book-123",
            "book-123:chapter:00001",
            "book-123:chapter:00001:sentence:000001",
            "I practice daily.",
            ukrainian,
            100,
            117,
            new[] { "entry-practice", "entry-daily" },
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                ["entry-practice"] = "A2",
                ["entry-daily"] = "A1"
            },
            "A2",
            1,
            new[] { "present.simple.core" });
    }

    private static void Check(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
}