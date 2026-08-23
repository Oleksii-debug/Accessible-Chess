using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class ContextPracticeRuntimeSessionSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            ContextPracticeRuntimeSessionSelfTest.Run();
    }
}

internal static class ContextPracticeRuntimeSessionSelfTest
{
    public static void Run()
    {
        TestInstalledPortableMetadataBoundary();
        TestRuntimeUsesLearnerVocabularyAndThirtyWordPool();
        TestRuntimeThreeTargetSelectionAndGapTruth();
        Console.WriteLine("Context Practice runtime-session self-test PASS: installed metadata, learner-vocabulary ranking, 30-word pool, natural three-target selection and truthful gaps verified.");
    }

    private static void TestInstalledPortableMetadataBoundary()
    {
        SentencePack pack = BuildPack(
            "runtime-source-fixture",
            MakeSentence("source-sentence", "alpha beta", "альфа бета", new[] { "e001", "e002" }));
        var installed = new InstalledSentencePack(
            "unused-test-path.json",
            pack.PackId,
            pack.License,
            pack.SentenceCount,
            pack,
            SqlitePath: null,
            PortablePack: pack);

        IContextSentenceSource source = InstalledContextSourceFactory.Create(installed, ContextCorpusKind.SyntheticFixture);
        Check(source.Descriptor.Kind == ContextCorpusKind.SyntheticFixture, "Installed source factory lost explicit synthetic test kind.");
        Check(source.Descriptor.Provenance == pack.Provenance && source.Descriptor.License == pack.License,
            "Installed source factory must preserve exact SentencePack provenance/license metadata.");

        bool localRejected = false;
        try { _ = InstalledContextSourceFactory.Create(installed, ContextCorpusKind.LocalUserText); }
        catch (InvalidDataException) { localRejected = true; }
        Check(localRejected, "A public installed SentencePack must not be silently reclassified as privacy-local book/text data.");
    }

    private static void TestRuntimeUsesLearnerVocabularyAndThirtyWordPool()
    {
        DictionaryPackage dictionary = BuildDictionary(35);
        SentencePack pack = BuildPack(
            "runtime-ranking-fixture",
            MakeSentence("easy-known-helper", "word1 word2 word4", "слово1 слово2 слово4", new[] { "e001", "e002", "e004" }),
            MakeSentence("hard-unknown-helper", "word1 word2 word35", "слово1 слово2 слово35", new[] { "e001", "e002", "e035" }));
        var source = new SentenceCorpusContextSource(
            pack,
            new ContextSourceDescriptor(pack.PackId, ContextCorpusKind.SyntheticFixture, pack.Provenance, pack.License));

        var appState = new AppState();
        var spelling = new SpellingState
        {
            StatsByDictionary = new Dictionary<string, Dictionary<string, SpellingEntryStats>>(StringComparer.OrdinalIgnoreCase)
            {
                [dictionary.Id] = new Dictionary<string, SpellingEntryStats>(StringComparer.OrdinalIgnoreCase)
                {
                    ["e004"] = new SpellingEntryStats
                    {
                        CompletedReviews = 4,
                        FirstTrySuccesses = 4,
                        CurrentStreak = 4,
                        RecentOutcomes = new List<bool> { true, true, true, true }
                    }
                }
            }
        };

        var runtime = new ContextPracticeRuntimeSession(
            dictionary,
            appState,
            spelling,
            source,
            new ContextProductUseOptions(AllowSyntheticFixtures: true));
        ContextRuntimeResult result = runtime.SelectNext(new ContextRuntimeRequest(
            dictionary.Entries.Select(entry => entry.Id).ToArray(),
            ContextStudyPoolPreset.Thirty,
            TargetCount: 2,
            CandidateLimit: 32,
            MaxCardsPerAnchor: 8));

        Check(result.StudyPool.EntryIds.Count == 30 && result.StudyPool.FilledRequestedWindow,
            "Runtime did not enforce the exact 30-word active study pool.");
        Check(result.VocabularySnapshot.Vocabulary.IsKnown("e004"),
            "Runtime did not consume the learner's real Spelling evidence through ContextVocabularySnapshotBuilder.");
        Check(result.Card is not null, "Runtime failed to select an available natural two-target sentence.");
        Check(result.Card!.SentenceId == "easy-known-helper",
            "Learner-known helper vocabulary must outrank an otherwise-equivalent sentence with an unknown helper word.");
        Check(result.Card.Difficulty.UnknownHelperEntries == 0,
            "Chosen learner-aware sentence should not count the strongly-known helper as unknown.");
        Check(result.Coverage.Coverage.RequiredTargetCount == 2 && result.Coverage.Coverage.CoveredEntryCount >= 2,
            "Runtime did not expose natural two-target coverage for its exact selected pool.");
    }

    private static void TestRuntimeThreeTargetSelectionAndGapTruth()
    {
        DictionaryPackage dictionary = BuildDictionary(8);
        SentencePack pack = BuildPack(
            "runtime-three-fixture",
            MakeSentence("triple", "word1 word2 word3", "слово1 слово2 слово3", new[] { "e001", "e002", "e003" }),
            MakeSentence("single", "word8", "слово8", new[] { "e008" }));
        var source = new SentenceCorpusContextSource(
            pack,
            new ContextSourceDescriptor(pack.PackId, ContextCorpusKind.SyntheticFixture, pack.Provenance, pack.License));
        var runtime = new ContextPracticeRuntimeSession(
            dictionary,
            new AppState(),
            new SpellingState(),
            source,
            new ContextProductUseOptions(AllowSyntheticFixtures: true));

        ContextRuntimeResult triple = runtime.SelectNext(new ContextRuntimeRequest(
            new[] { "e001", "e002", "e003" },
            ContextStudyPoolPreset.Full,
            TargetCount: 3,
            CandidateLimit: 24,
            MaxCardsPerAnchor: 6));
        Check(triple.Card is not null && triple.Card.TargetEntryIds.Count == 3,
            "Runtime did not deliver a real natural three-target card when the corpus contained one.");
        Check(triple.Card!.TargetLexicalKeys.Distinct(StringComparer.OrdinalIgnoreCase).Count() == 3,
            "Runtime three-target exercise must represent three physical lexical forms, not merely three stable IDs.");

        ContextRuntimeResult gap = runtime.SelectNext(new ContextRuntimeRequest(
            new[] { "e008" },
            ContextStudyPoolPreset.Full,
            TargetCount: 2,
            CandidateLimit: 24,
            MaxCardsPerAnchor: 6));
        Check(gap.Card is null && gap.Coverage.Coverage.CoveredEntryCount == 0,
            "A one-word-only corpus gap must not turn into a fabricated two-target exercise.");
        Check(gap.Explanation.Contains("No sentence was fabricated", StringComparison.Ordinal),
            "Runtime gap result must state the no-fabrication boundary explicitly.");
    }

    private static DictionaryPackage BuildDictionary(int count)
    {
        var entries = Enumerable.Range(1, count)
            .Select(i => new DictionaryEntry($"e{i:000}", "A2", $"word{i}", $"слово{i}"))
            .ToArray();
        return new DictionaryPackage
        {
            Id = "runtime-dictionary",
            Name = "Runtime test dictionary",
            SourceLanguage = "en",
            TargetLanguage = "uk",
            Entries = entries
        };
    }

    private static SentencePack BuildPack(string packId, params SentenceRecord[] sentences)
    {
        var pack = new SentencePack
        {
            PackId = packId,
            Provenance = "synthetic-runtime-self-test-only",
            License = "TEST-ONLY",
            Sentences = sentences.ToList()
        };
        pack.Validate();
        return pack;
    }

    private static SentenceRecord MakeSentence(string id, string english, string ukrainian, IReadOnlyList<string> targetIds)
    {
        List<string> tokens = SentenceTokenizer.Tokenize(english).ToList();
        return new SentenceRecord
        {
            Id = id,
            English = english,
            Ukrainian = ukrainian,
            Source = "synthetic-runtime-self-test-only",
            License = "TEST-ONLY",
            Tokens = tokens,
            Lemmas = tokens.ToList(),
            TargetEntryIds = targetIds.ToList(),
            EntryLevels = targetIds.ToDictionary(target => target, _ => "A2", StringComparer.OrdinalIgnoreCase),
            DifficultyLevel = "A2",
            OffListTokenCount = 0
        };
    }

    private static void Check(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
}
