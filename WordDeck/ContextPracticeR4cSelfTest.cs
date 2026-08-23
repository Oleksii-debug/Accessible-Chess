using System.Diagnostics;
using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class ContextPracticeR4cSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            ContextPracticeR4cSelfTest.Run();
    }
}

internal static class ContextPracticeR4cSelfTest
{
    public static void Run()
    {
        DictionaryPackage dictionary = DictionaryLoader.LoadEmbeddedOxford();
        Check(dictionary.Entries.Count == 5446, "Stage-11 context preparation must use the exact 5446-entry Oxford universe.");
        Check(dictionary.Entries.Select(entry => entry.Id).Distinct(StringComparer.OrdinalIgnoreCase).Count() == 5446, "Oxford stable IDs must remain unique.");

        TestNaturalIntersections();
        TestLearnerVocabularyRanking();
        TestVocabularySnapshotBuilder(dictionary);
        TestStableIdPools(dictionary);
        TestSyntheticFailClosed();
        TestLocalTextAndGrammarMetadata();
        TestExact5446Coverage(dictionary);
        TestBoundedSqliteIntersections();

        Console.WriteLine("Context Practice R4c self-test PASS: stable-ID 1/2/3 target selection, real learner lexical state, exact 5446 gaps, SQLite stress, local-text and grammar metadata seams.");
    }

    private static void TestNaturalIntersections()
    {
        SentencePack pack = BuildSelectionPack();
        var source = FixtureSource(pack);

        Check(source.FindByTargets(new[] { "target-a" }, 20).Count == 3, "One-target lookup count is wrong.");
        Check(source.FindByTargets(new[] { "target-a", "target-b" }, 20).Select(x => x.Sentence.Id).SequenceEqual(new[] { "s-two", "s-three" }), "Two-target lookup must be a real intersection.");
        Check(source.FindByTargets(new[] { "target-a", "target-b", "target-c" }, 20).Single().Sentence.Id == "s-three", "Three-target lookup must be a natural co-occurrence.");
        Check(source.FindByTargets(new[] { "target-a", "target-b", "missing-target" }, 20).Count == 0, "Impossible combinations must never fabricate a sentence.");
        Check(source.FindByTargets(new[] { "bank-noun" }, 10).Single().Sentence.Id == "s-bank-noun", "Same-headword noun stable ID collapsed.");
        Check(source.FindByTargets(new[] { "bank-verb" }, 10).Single().Sentence.Id == "s-bank-verb", "Same-headword verb stable ID collapsed.");

        IReadOnlyList<ContextTargetSetCoverage> coverage = ContextCoverageAnalyzer.AnalyzeRequestedTargetSets(source, new IReadOnlyCollection<string>[]
        {
            new[] { "target-a" },
            new[] { "target-a", "target-b" },
            new[] { "target-a", "target-b", "target-c" },
            new[] { "target-a", "target-b", "missing-target" }
        });
        Check(coverage.Count == 4 && coverage[0].Covered && coverage[1].Covered && coverage[2].Covered && !coverage[3].Covered,
            "Requested target-set coverage must distinguish real intersections from gaps.");

        bool rejected = false;
        try { _ = source.FindByTargets(new[] { "a", "b", "c", "d" }, 10); }
        catch (InvalidDataException) { rejected = true; }
        Check(rejected, "More than three required context targets must fail closed in Stage-11 preparation.");
    }

    private static void TestLearnerVocabularyRanking()
    {
        SentencePack pack = BuildSelectionPack();
        var source = FixtureSource(pack);
        var vocabulary = new ContextLearnerVocabulary(knownEntryIds: new[] { "helper-known" });
        var request = new ContextPracticeRequest(new[] { "target-rank" }, Vocabulary: vocabulary, MaxResults: 10, CandidateLimit: 20, AllowSyntheticFixtures: true);
        IReadOnlyList<RankedContextSentence> ranked = ContextPracticeService.Select(source, request);

        Check(ranked.Count == 2, "Ranking fixture must expose two candidates.");
        Check(ranked[0].Candidate.Sentence.Id == "s-known-c1", "Actual known vocabulary must outrank coarse CEFR when the other sentence contains an unknown helper.");
        Check(ranked[0].Difficulty.UnknownHelperEntries == 0 && ranked[1].Difficulty.UnknownHelperEntries == 1, "Difficulty breakdown ignored learner lexical state.");
        Check(!string.IsNullOrWhiteSpace(ranked[0].Difficulty.Explanation), "Difficulty reason must be textual and deterministic.");
        for (int i = 0; i < 200; i++)
            Check(ContextPracticeService.Select(source, request).Select(x => x.Candidate.Sentence.Id).SequenceEqual(ranked.Select(x => x.Candidate.Sentence.Id)), "Identical context state changed deterministic ranking.");
    }

    private static void TestVocabularySnapshotBuilder(DictionaryPackage dictionary)
    {
        string knownId = dictionary.Entries[0].Id;
        string recallLearningId = dictionary.Entries[1].Id;
        string spellingLearningId = dictionary.Entries[2].Id;
        string hiddenOnlyId = dictionary.Entries[3].Id;
        const string unknownId = "not-in-current-oxford-corpus";

        var recall = new AppState();
        recall.StudyHistoryByEntryId[recallLearningId] = new WordStudyHistory { SeenCount = 5, TranslationRevealCount = 1 };
        recall.HiddenEntryIds.Add(hiddenOnlyId);
        recall.StudyHistoryByEntryId[unknownId] = new WordStudyHistory { SeenCount = 99 };

        var spelling = new SpellingState();
        spelling.StatsByDictionary[dictionary.Id] = new Dictionary<string, SpellingEntryStats>(StringComparer.OrdinalIgnoreCase)
        {
            [knownId] = new()
            {
                CompletedReviews = 4,
                FirstTrySuccesses = 3,
                CurrentStreak = 3,
                RecentOutcomes = new List<bool> { true, true, true, true }
            },
            [spellingLearningId] = new()
            {
                CompletedReviews = 4,
                FirstTrySuccesses = 2,
                WrongAttempts = 2,
                CurrentStreak = 1,
                RecentOutcomes = new List<bool> { false, true, false, true }
            },
            [unknownId] = new()
            {
                CompletedReviews = 100,
                FirstTrySuccesses = 100,
                CurrentStreak = 100,
                RecentOutcomes = new List<bool> { true, true, true, true, true }
            }
        };

        ContextVocabularySnapshot snapshot = ContextVocabularySnapshotBuilder.Build(dictionary, recall, spelling);
        Check(snapshot.Vocabulary.IsKnown(knownId), "Strong real Spelling evidence must classify the stable ID as known.");
        Check(snapshot.Vocabulary.IsLearning(recallLearningId), "Recall history must contribute a learning signal without pretending the word is mastered.");
        Check(snapshot.Vocabulary.IsLearning(spellingLearningId), "Weak Spelling evidence must remain learning, not known.");
        Check(!snapshot.Vocabulary.IsKnown(hiddenOnlyId) && !snapshot.Vocabulary.IsLearning(hiddenOnlyId), "Hiding alone must never be treated as mastery evidence.");
        Check(snapshot.KnownCount == 1 && snapshot.LearningCount == 2, "Vocabulary snapshot counts are not deterministic.");
        Check(snapshot.IgnoredUnknownEntryIds == 1, "Unknown profile IDs must be ignored and counted instead of entering mastery.");
        Check(ContextVocabularySnapshotBuilder.IsStrongSpellingEvidence(new SpellingEntryStats
        {
            CompletedReviews = 3,
            FirstTrySuccesses = 3,
            CurrentStreak = 3,
            RecentOutcomes = new List<bool> { true, true, true }
        }), "Minimum strong Spelling threshold should pass when recent clean evidence is also strong.");
        Check(!ContextVocabularySnapshotBuilder.IsStrongSpellingEvidence(new SpellingEntryStats
        {
            CompletedReviews = 3,
            FirstTrySuccesses = 2,
            CurrentStreak = 3,
            RecentOutcomes = new List<bool> { true, true, true }
        }), "Below-75-percent lifetime first-try success must not be known.");
        Check(!ContextVocabularySnapshotBuilder.IsStrongSpellingEvidence(new SpellingEntryStats
        {
            CompletedReviews = 5,
            FirstTrySuccesses = 5,
            CurrentStreak = 5,
            RecentOutcomes = new List<bool> { true, true, true, false, false }
        }), "Below-80-percent recent clean rate must not be known even with perfect lifetime evidence.");
        Check(ContextVocabularySnapshotBuilder.IsStrongSpellingEvidence(new SpellingEntryStats
        {
            CompletedReviews = 5,
            FirstTrySuccesses = 5,
            CurrentStreak = 5,
            RecentOutcomes = new List<bool> { true, true, true, true, false }
        }), "Exactly-80-percent recent clean rate should satisfy the current Spelling Coach threshold.");
    }

    private static void TestStableIdPools(DictionaryPackage dictionary)
    {
        Check(ContextTargetIds.NormalizeStudyPool(dictionary.Entries.Take(30).Select(e => e.Id)).Length == 30, "30-word stable-ID pool failed.");
        Check(ContextTargetIds.NormalizeStudyPool(dictionary.Entries.Take(100).Select(e => e.Id)).Length == 100, "100-word stable-ID pool failed.");
        string[] pool200 = ContextTargetIds.NormalizeStudyPool(dictionary.Entries.Take(200).Select(e => e.Id));
        Check(pool200.Length == 200, "200-word stable-ID pool failed.");

        string firstId = dictionary.Entries[0].Id;
        SentencePack pack = BuildPack("context-pool-fixture", MakeSentence("s-pool", "alpha beta", new[] { firstId }, "A1"));
        IReadOnlyList<RankedContextSentence> selected = ContextPracticeService.Select(FixtureSource(pack), new ContextPracticeRequest(
            new[] { firstId }, pool200, new ContextLearnerVocabulary(pool200), MaxResults: 5, CandidateLimit: 10, AllowSyntheticFixtures: true));
        Check(selected.Count == 1, "A target inside the explicit study pool was not selectable.");

        bool rejected = false;
        try { _ = ContextPracticeService.Select(FixtureSource(pack), new ContextPracticeRequest(new[] { "outside-pool" }, pool200, MaxResults: 1, CandidateLimit: 1, AllowSyntheticFixtures: true)); }
        catch (InvalidDataException) { rejected = true; }
        Check(rejected, "Required target outside the supplied list/deck must fail closed.");
    }

    private static void TestSyntheticFailClosed()
    {
        SentencePack pack = BuildSelectionPack();
        var source = FixtureSource(pack);
        var request = new ContextPracticeRequest(new[] { "target-a" }, MaxResults: 5, CandidateLimit: 10);
        Check(ContextPracticeService.Select(source, request).Count == 0, "Synthetic context leaked into normal product selection.");
        Check(ContextPracticeService.Select(source, request with { AllowSyntheticFixtures = true }).Count > 0, "Explicit self-test mode should permit a labeled fixture.");
    }

    private static void TestLocalTextAndGrammarMetadata()
    {
        var source = new ContextSourceDescriptor("local-book-1", ContextCorpusKind.LocalUserText, "local-user-import", "user-private-local", PrivacyLocalOnly: true);
        var location = new LocalTextContextLocation("local-book-1", "book-1", "chapter-03", 120, 174, PrivacyLocalOnly: true);
        var sentence = MakeSentence("local-sentence-1", "alpha beta gamma", new[] { "target-local" }, "B1", flags: new[] { "grammar:present-perfect" });
        var envelope = new ContextSentenceEnvelope(
            sentence,
            source,
            location,
            ContextGrammarMetadata.ExtractFromQualityFlags(new[] { "grammar:present-perfect", "long-sentence" }));
        envelope.Validate();
        Check(envelope.LocalTextLocation?.ChapterId == "chapter-03" && envelope.LocalTextLocation.StartOffset == 120 && envelope.LocalTextLocation.EndOffset == 174, "Local book/chapter offsets were not preserved.");
        Check(envelope.Source.PrivacyLocalOnly, "Imported local text must remain privacy-local by default.");
        Check(envelope.EffectiveGrammarSkillIds.SequenceEqual(new[] { "present-perfect" }), "Grammar readiness must remain metadata-only and stable.");

        bool privacyRejected = false;
        try { new ContextSourceDescriptor("bad-local", ContextCorpusKind.LocalUserText, "local", "private", PrivacyLocalOnly: false).Validate(); }
        catch (InvalidDataException) { privacyRejected = true; }
        Check(privacyRejected, "Local user text cannot silently opt out of privacy-local handling.");

        bool identityMismatchRejected = false;
        try
        {
            new ContextSentenceEnvelope(
                sentence,
                source,
                location with { SourceId = "different-local-source" },
                Array.Empty<string>()).Validate();
        }
        catch (InvalidDataException) { identityMismatchRejected = true; }
        Check(identityMismatchRejected, "Local book/text location cannot point to a different source identity.");
    }

    private static void TestExact5446Coverage(DictionaryPackage dictionary)
    {
        string[] universe = dictionary.Entries.Select(e => e.Id).ToArray();
        var source = new CoverageOnlySource(universe.Take(5000));
        ContextCoverageReport report = ContextCoverageAnalyzer.AnalyzeOneTargetUniverse(source, universe);
        Check(report.RequestedEntryCount == 5446 && report.CoveredEntryCount == 5000 && report.UncoveredEntryCount == 446, "Exact 5446 coverage accounting failed.");
        Check(report.CoveredEntryIds.Count + report.UncoveredEntryIds.Count == 5446, "Covered and uncovered stable IDs must partition the universe.");
        Check(report.UncoveredEntryIds.SequenceEqual(universe.Skip(5000).Select(ContextTargetIds.NormalizeSingle)), "Gap IDs must be explicit and deterministic.");
    }

    private static void TestBoundedSqliteIntersections()
    {
        string root = Path.Combine(Path.GetTempPath(), "WordDeck контекст R4c " + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        string databasePath = Path.Combine(root, "речення stage 11.sqlite");
        try
        {
            SentencePackSqlitePrototype.Build(databasePath, BuildSqliteStressPack());
            var source = new ContextSentenceSqliteSource(databasePath, ContextCorpusKind.SyntheticFixture);
            IReadOnlyList<ContextSentenceEnvelope> triple = source.FindByTargets(new[] { "ctx-a", "ctx-b", "ctx-c" }, 16);
            Check(triple.Count > 0 && triple.Count <= 16 && triple.All(x => ContainsAll(x.Sentence, new[] { "ctx-a", "ctx-b", "ctx-c" })), "SQLite three-target intersection is not bounded/exact.");

            string plan = string.Join(" | ", source.ExplainIntersectionPlan(new[] { "ctx-a", "ctx-b", "ctx-c" }, 16));
            Check(plan.Contains("sentence_targets", StringComparison.OrdinalIgnoreCase), "SQLite plan did not use sentence_targets.");
            Check(plan.Contains("PRIMARY KEY", StringComparison.OrdinalIgnoreCase) || plan.Contains("INDEX", StringComparison.OrdinalIgnoreCase), "SQLite plan does not expose indexed/primary-key access.");

            ContextCoverageReport coverage = ContextCoverageAnalyzer.AnalyzeOneTargetUniverse(source, new[] { "ctx-a", "ctx-b", "ctx-c", "ctx-missing" });
            Check(coverage.CoveredEntryCount == 3 && coverage.UncoveredEntryIds.SequenceEqual(new[] { "ctx-missing" }), "SQLite one-target gap accounting failed.");

            Stopwatch sw = Stopwatch.StartNew();
            long checksum = 0;
            for (int i = 0; i < 1000; i++)
            {
                string[] targets = (i % 3) switch
                {
                    0 => new[] { "ctx-a" },
                    1 => new[] { "ctx-a", "ctx-b" },
                    _ => new[] { "ctx-a", "ctx-b", "ctx-c" }
                };
                IReadOnlyList<ContextSentenceEnvelope> found = source.FindByTargets(targets, 8);
                Check(found.Count <= 8 && found.All(x => ContainsAll(x.Sentence, targets)), "Repeated SQLite lookup violated its intersection/bound contract.");
                checksum += found.Count;
            }
            sw.Stop();
            Check(checksum > 0, "SQLite stress performed no useful matching work.");
            Check(sw.Elapsed < TimeSpan.FromSeconds(30), "1000 bounded SQLite lookups exceeded the generous 30-second regression budget.");
            Console.WriteLine($"Context R4c SQLite stress: 1000 bounded 1/2/3-target queries in {sw.ElapsedMilliseconds} ms; checksum={checksum}; plan={plan}");
        }
        finally
        {
            try { Directory.Delete(root, recursive: true); } catch { }
        }
    }

    private static SentenceCorpusContextSource FixtureSource(SentencePack pack) => new(
        pack,
        new ContextSourceDescriptor(pack.PackId, ContextCorpusKind.SyntheticFixture, pack.Provenance, pack.License));

    private static SentencePack BuildSelectionPack() => BuildPack(
        "context-selection-fixture",
        MakeSentence("s-single", "alpha beta", new[] { "target-a" }, "A1"),
        MakeSentence("s-two", "alpha beta gamma", new[] { "target-a", "target-b" }, "A2"),
        MakeSentence("s-three", "alpha beta gamma delta", new[] { "target-a", "target-b", "target-c" }, "B1"),
        MakeSentence("s-bank-noun", "the bank closed", new[] { "bank-noun" }, "A2"),
        MakeSentence("s-bank-verb", "planes bank sharply", new[] { "bank-verb" }, "B1"),
        MakeSentence("s-known-c1", "alpha known context", new[] { "target-rank", "helper-known" }, "C1"),
        MakeSentence("s-unknown-a1", "alpha unknown context", new[] { "target-rank", "helper-unknown" }, "A1"));

    private static SentencePack BuildSqliteStressPack()
    {
        var sentences = new List<SentenceRecord>();
        string[] levels = { "A1", "A2", "B1", "B2", "C1" };
        for (int i = 1; i <= 360; i++)
        {
            var targets = new List<string> { "ctx-a" };
            if (i % 2 == 0) targets.Add("ctx-b");
            if (i % 3 == 0) targets.Add("ctx-c");
            targets.Add(i % 2 == 0 ? "ctx-helper-known" : "ctx-helper-unknown");
            sentences.Add(MakeSentence($"sqlite-{i:D4}", "alpha beta gamma delta", targets, levels[i % levels.Length], offList: i % 7 == 0 ? 1 : 0));
        }
        return BuildPack("context-sqlite-fixture", sentences.ToArray());
    }

    private static SentencePack BuildPack(string packId, params SentenceRecord[] sentences)
    {
        var pack = new SentencePack { PackId = packId, Provenance = "synthetic-self-test-only", License = "CC0-1.0", Sentences = sentences.ToList() };
        pack.Validate();
        return pack;
    }

    private static SentenceRecord MakeSentence(string id, string english, IEnumerable<string> targets, string difficulty, int offList = 0, IEnumerable<string>? flags = null)
    {
        List<string> targetList = targets.Select(ContextTargetIds.NormalizeSingle).Distinct(StringComparer.OrdinalIgnoreCase).ToList();
        List<string> tokens = SentenceTokenizer.Tokenize(english).ToList();
        return new SentenceRecord
        {
            Id = id,
            English = english,
            Ukrainian = "Тестове українське речення.",
            Source = "WordDeck synthetic context self-test",
            License = "CC0-1.0",
            Tokens = tokens,
            Lemmas = tokens.ToList(),
            TargetEntryIds = targetList,
            EntryLevels = targetList.ToDictionary(target => target, _ => difficulty, StringComparer.OrdinalIgnoreCase),
            DifficultyLevel = difficulty,
            OffListTokenCount = offList,
            QualityFlags = flags?.ToList() ?? new List<string>()
        };
    }

    private static bool ContainsAll(SentenceRecord sentence, IEnumerable<string> targets)
    {
        var ids = new HashSet<string>(sentence.TargetEntryIds, StringComparer.OrdinalIgnoreCase);
        return targets.All(ids.Contains);
    }

    private static void Check(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException("Context Practice R4c self-test failed: " + message);
    }

    private sealed class CoverageOnlySource : IContextSentenceSource, IContextCoverageSource
    {
        private readonly HashSet<string> _covered;
        public ContextSourceDescriptor Descriptor { get; } = new("coverage-self-test", ContextCorpusKind.SyntheticFixture, "synthetic-self-test-only", "CC0-1.0");
        public CoverageOnlySource(IEnumerable<string> covered) => _covered = new HashSet<string>(covered.Select(ContextTargetIds.NormalizeSingle), StringComparer.OrdinalIgnoreCase);
        public IReadOnlyList<ContextSentenceEnvelope> FindByTargets(IReadOnlyCollection<string> targetEntryIds, int maxCandidates) => Array.Empty<ContextSentenceEnvelope>();
        public IReadOnlySet<string> GetCoveredOneTargetIds(IReadOnlyCollection<string> candidateEntryIds) =>
            new HashSet<string>(candidateEntryIds.Select(ContextTargetIds.NormalizeSingle).Where(_covered.Contains), StringComparer.OrdinalIgnoreCase);
    }
}
