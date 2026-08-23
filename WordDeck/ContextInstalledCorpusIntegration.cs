using System.Runtime.CompilerServices;

namespace WordDeck;

internal sealed record ContextInstalledCorpusRuntime(
    IContextSentenceSource Source,
    ContextTargetLexicon TargetLexicon,
    ContextVocabularySnapshot Vocabulary,
    string PackId,
    string Provenance,
    string License,
    int SentenceCount,
    bool RedistributionApproved,
    string DistributionBoundary);

/// <summary>
/// Production runtime seam between the already-installed SentencePack subsystem and
/// Stage 11 Context Practice. This preserves exact source provenance from the active
/// SQLite/portable corpus instead of inventing provenance from PackId or license.
/// </summary>
internal static class ContextInstalledCorpusIntegration
{
    public static ContextInstalledCorpusRuntime Create(
        InstalledSentencePack installed,
        DictionaryPackage dictionary,
        AppState recallState,
        SpellingState spellingState)
    {
        ArgumentNullException.ThrowIfNull(installed);
        ArgumentNullException.ThrowIfNull(dictionary);
        ArgumentNullException.ThrowIfNull(recallState);
        ArgumentNullException.ThrowIfNull(spellingState);

        if (!string.Equals(installed.PackId, installed.Corpus.PackId, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Installed SentencePack identity does not match its active runtime corpus.");
        if (!string.Equals(installed.License, installed.Corpus.License, StringComparison.Ordinal))
            throw new InvalidDataException("Installed SentencePack license does not match its active runtime corpus.");
        if (installed.SentenceCount != installed.Corpus.SentenceCount || installed.SentenceCount <= 0)
            throw new InvalidDataException("Installed SentencePack sentence count does not match its active runtime corpus.");

        string provenance = ExactProvenance(installed);
        var descriptor = new ContextSourceDescriptor(
            installed.PackId,
            ContextCorpusKind.RealCorpus,
            provenance,
            installed.License,
            PrivacyLocalOnly: false);
        var source = new SentenceCorpusContextSource(installed.Corpus, descriptor);
        ContextTargetLexicon lexicon = CreateLexicon(dictionary);
        ContextVocabularySnapshot vocabulary = ContextVocabularySnapshotBuilder.Build(dictionary, recallState, spellingState);

        return new ContextInstalledCorpusRuntime(
            source,
            lexicon,
            vocabulary,
            installed.PackId,
            provenance,
            installed.License,
            installed.SentenceCount,
            RedistributionApproved: false,
            "Installed real corpus is available for local/offline learning. Runtime installation does not itself approve public redistribution or web publication; that remains a separate exact-artifact release gate.");
    }

    public static ContextTargetLexicon CreateLexicon(DictionaryPackage dictionary)
    {
        ArgumentNullException.ThrowIfNull(dictionary);
        if (dictionary.Entries is null || dictionary.Entries.Count == 0)
            throw new InvalidDataException("Context Practice requires a non-empty dictionary package.");

        var stableIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var pairs = new List<(string StableEntryId, string LexicalForm)>(dictionary.Entries.Count);
        foreach (DictionaryEntry entry in dictionary.Entries)
        {
            string id = ContextTargetIds.NormalizeSingle(entry.Id);
            if (!stableIds.Add(id))
                throw new InvalidDataException($"Dictionary contains duplicate stable entry id {id}.");
            if (string.IsNullOrWhiteSpace(entry.Source))
                throw new InvalidDataException($"Dictionary entry {id} has no physical English lexical form.");
            pairs.Add((id, entry.Source));
        }
        return new ContextTargetLexicon(dictionary.Id, pairs);
    }

    public static IReadOnlyList<string> BuildStudyUniverse(
        DictionaryPackage dictionary,
        AppState recallState,
        string scopeId,
        string? recallDeckId = null)
    {
        ArgumentNullException.ThrowIfNull(dictionary);
        ArgumentNullException.ThrowIfNull(recallState);
        if (!StudyScopeIds.Ordered.Contains(scopeId, StringComparer.OrdinalIgnoreCase))
            throw new ArgumentOutOfRangeException(nameof(scopeId), scopeId, "Unknown Context Practice study scope.");

        var scopeService = new RecallStudyScopeService(recallState, dictionary.Id, dictionary.Entries);
        IReadOnlyList<DictionaryEntry> eligible = scopeService.EligibleEntries(scopeId);
        IReadOnlyDictionary<string, string> assignments = scopeService.Assignments(scopeId);
        var hidden = new HashSet<string>(recallState.HiddenEntryIds ?? new HashSet<string>(), StringComparer.OrdinalIgnoreCase);

        if (!string.IsNullOrWhiteSpace(recallDeckId) &&
            !recallState.Decks.Any(deck => string.Equals(deck.Id, recallDeckId, StringComparison.OrdinalIgnoreCase)))
            throw new InvalidDataException("Requested Recall deck does not exist.");

        return eligible
            .Where(entry => !hidden.Contains(entry.Id))
            .Where(entry => string.IsNullOrWhiteSpace(recallDeckId) ||
                (assignments.TryGetValue(entry.Id, out string? deckId) &&
                 string.Equals(deckId, recallDeckId, StringComparison.OrdinalIgnoreCase)))
            .Select(entry => ContextTargetIds.NormalizeSingle(entry.Id))
            .ToArray();
    }

    private static string ExactProvenance(InstalledSentencePack installed)
    {
        string? provenance = installed.Corpus switch
        {
            SentencePackSqliteCorpus sqlite => sqlite.Provenance,
            SentencePack portable => portable.Provenance,
            _ => installed.PortablePack?.Provenance
        };
        if (string.IsNullOrWhiteSpace(provenance))
        {
            throw new InvalidDataException(
                "Installed SentencePack runtime does not expose exact provenance. Context Practice fails closed rather than manufacturing provenance from a pack id or license label.");
        }
        if (!string.Equals(provenance, provenance.Trim(), StringComparison.Ordinal))
            throw new InvalidDataException("Installed SentencePack provenance is not canonical.");
        SentenceTokenizer.ValidateUnicode(provenance, "Installed SentencePack provenance");
        return provenance;
    }
}

internal static class ContextInstalledCorpusIntegrationSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            ContextInstalledCorpusIntegrationSelfTest.Run();
    }
}

internal static class ContextInstalledCorpusIntegrationSelfTest
{
    public static void Run()
    {
        TestInstalledRuntimePreservesProvenanceAndLexicalAmbiguity();
        TestStudyUniverseHonoursScopeDeckAndHiddenWords();
        TestMissingProvenanceFailsClosed();
        Console.WriteLine("Context installed-corpus integration self-test PASS: exact provenance, stable lexical forms, profile vocabulary and scope/deck/hidden boundaries verified.");
    }

    private static void TestInstalledRuntimePreservesProvenanceAndLexicalAmbiguity()
    {
        SentencePack pack = BuildPack();
        var installed = new InstalledSentencePack(
            "fixture.json",
            pack.PackId,
            pack.License,
            pack.SentenceCount,
            pack,
            PortablePack: pack);
        DictionaryPackage dictionary = BuildDictionary();
        AppState recall = BuildRecallState(dictionary);
        var spelling = new SpellingState();

        ContextInstalledCorpusRuntime runtime = ContextInstalledCorpusIntegration.Create(installed, dictionary, recall, spelling);
        Check(runtime.Provenance == pack.Provenance, "Runtime provenance was not preserved exactly.");
        Check(!runtime.RedistributionApproved && runtime.DistributionBoundary.Contains("does not itself approve", StringComparison.Ordinal),
            "Installed local corpus must not silently acquire redistribution approval.");
        Check(runtime.TargetLexicon.LexicalKeyFor("id-run-verb") == runtime.TargetLexicon.LexicalKeyFor("id-run-noun"),
            "Same-written-form stable IDs must share one physical lexical key.");
        Check(runtime.TargetLexicon.AmbiguousStableIds(dictionary.Entries.Select(entry => entry.Id)).Count == 2,
            "Physical lexical ambiguity ledger did not retain both distinct stable IDs.");
    }

    private static void TestStudyUniverseHonoursScopeDeckAndHiddenWords()
    {
        DictionaryPackage dictionary = BuildDictionary();
        AppState recall = BuildRecallState(dictionary);
        var service = new RecallStudyScopeService(recall, dictionary.Id, dictionary.Entries);
        service.Move(StudyScopeIds.B2, "id-practice", DeckIds.Core(2));
        recall.HiddenEntryIds.Add("id-run-verb");

        IReadOnlyList<string> b2 = ContextInstalledCorpusIntegration.BuildStudyUniverse(dictionary, recall, StudyScopeIds.B2);
        Check(b2.SequenceEqual(new[] { "id-practice", "id-run-verb" }, StringComparer.OrdinalIgnoreCase) == false,
            "Hidden B2 entry unexpectedly remained in study universe.");
        Check(b2.SequenceEqual(new[] { "id-practice" }, StringComparer.OrdinalIgnoreCase),
            "B2 study universe must exclude hidden words and preserve dictionary order.");

        IReadOnlyList<string> deck2 = ContextInstalledCorpusIntegration.BuildStudyUniverse(dictionary, recall, StudyScopeIds.B2, DeckIds.Core(2));
        Check(deck2.SequenceEqual(new[] { "id-practice" }, StringComparer.OrdinalIgnoreCase),
            "Recall-deck filtered Context Practice universe is wrong.");
    }

    private static void TestMissingProvenanceFailsClosed()
    {
        SentencePack pack = BuildPack();
        var opaque = new OpaqueCorpus(pack);
        var installed = new InstalledSentencePack("opaque.bin", pack.PackId, pack.License, pack.SentenceCount, opaque);
        bool blocked = false;
        try
        {
            _ = ContextInstalledCorpusIntegration.Create(installed, BuildDictionary(), BuildRecallState(BuildDictionary()), new SpellingState());
        }
        catch (InvalidDataException ex)
        {
            blocked = ex.Message.Contains("does not expose exact provenance", StringComparison.OrdinalIgnoreCase);
        }
        Check(blocked, "Unknown installed corpus implementation must fail closed when exact provenance cannot be recovered.");
    }

    private static SentencePack BuildPack()
    {
        string english = "Run and practice daily";
        IReadOnlyList<string> tokens = SentenceTokenizer.Tokenize(english);
        var sentence = new SentenceRecord
        {
            Id = "integration-s1",
            English = english,
            Ukrainian = "Біжи та практикуйся щодня",
            Source = "integration-source-record",
            License = "TEST-LICENSE",
            Tokens = tokens.ToList(),
            Lemmas = tokens.ToList(),
            TargetEntryIds = new List<string> { "id-run-verb", "id-practice" },
            EntryLevels = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                ["id-run-verb"] = "B2",
                ["id-practice"] = "B2"
            },
            DifficultyLevel = "B2",
            OffListTokenCount = 2
        };
        var pack = new SentencePack
        {
            PackId = "installed-integration-fixture",
            Provenance = "integration-fixture-provenance",
            License = "TEST-LICENSE",
            Sentences = new List<SentenceRecord> { sentence }
        };
        pack.Validate();
        return pack;
    }

    private static DictionaryPackage BuildDictionary() => new()
    {
        Id = "dictionary-fixture",
        Name = "Dictionary fixture",
        SourceLanguage = "en",
        TargetLanguage = "uk",
        Entries = new List<DictionaryEntry>
        {
            new("id-run-noun", "B1", "run", "пробіжка"),
            new("id-practice", "B2", "practice", "практикуватися"),
            new("id-run-verb", "B2", "run", "бігти"),
            new("id-daily", "A1", "daily", "щодня")
        }
    };

    private static AppState BuildRecallState(DictionaryPackage dictionary)
    {
        var state = new AppState
        {
            Decks = Enumerable.Range(1, 5)
                .Select(i => new DeckDefinition { Id = DeckIds.Core(i), Name = "Deck " + i, IsCore = true, Order = i })
                .ToList(),
            HiddenEntryIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase),
            StudyHistoryByEntryId = new Dictionary<string, WordStudyHistory>(StringComparer.OrdinalIgnoreCase)
        };
        _ = new RecallStudyScopeService(state, dictionary.Id, dictionary.Entries);
        return state;
    }

    private sealed class OpaqueCorpus : ISentenceCorpus
    {
        private readonly SentencePack _pack;
        public OpaqueCorpus(SentencePack pack) => _pack = pack;
        public string PackId => _pack.PackId;
        public string License => _pack.License;
        public int SentenceCount => _pack.SentenceCount;
        public IReadOnlyList<SentenceRecord> LookupByEntryId(string entryId) => _pack.LookupByEntryId(entryId);
        public IReadOnlyList<SentenceRecord> LookupAllTargets(IReadOnlyCollection<string> targetEntryIds) => _pack.LookupAllTargets(targetEntryIds);
    }

    private static void Check(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
}
