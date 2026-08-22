using System.Diagnostics;
using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class ContextPracticeR4cSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (!Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            return;
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

        TestNaturalOneTwoThreeTargetIntersections();
        TestLearnerVocabularyDominatesCefr();
        TestStableIdPools(dictionary);
        TestSyntheticFailClosed();
        TestLocalTextAndGrammarMetadataSeams();
        TestExact5446CoverageAccounting(dictionary);
        TestBoundedSqliteIntersectionsAndStress();

        Console.WriteLine("Context Practice R4c self-test PASS: stable-ID 1/2/3 target selection, lexical difficulty, exact 5446 gaps, SQLite stress, local-text and grammar metadata seams.");
    }

    private static void TestNaturalOneTwoThreeTargetIntersections()
    {
        SentencePack pack = BuildSelectionPack();
        var source = new SentenceCorpusContextSource(
            pack,
            new ContextSourceDescriptor(pack.PackId, ContextCorpusKind.SyntheticFixture, pack.Provenance, pack.License));

        IReadOnlyList<ContextSentenceEnvelope> one = source.FindByTargets(new[] { "target-a" }, 20);
        IReadOnlyList<ContextSentenceEnvelope> two = source.FindByTargets(new[] { "target-a", "target-b" }, 20);
        IReadOnlyList<ContextSentenceEnvelope> three = source.FindByTargets(new[] { "target-a", "target-b", "target-c" }, 20);
        IReadOnlyList<ContextSentenceEnvelope> impossible = source.FindByTargets(new[] { "target-a", "target-b", "missing-target" }, 20);

        Check(one.Count == 3, "One-target context lookup must return every real matching fixture sentence.");
        Check(two.Select(item => item.Sentence.Id).SequenceEqual(new[] { "s-two", "s-three" }), "Two-target lookup must be a real intersection.");
        Check(three.Count == 1 && three[0].Sentence.Id == "s-three", "Three-target lookup must return only a naturally co-occurring sentence.");
        Check(impossible.Count == 0, "An impossible target combination must not fabricate or concatenate a sentence.");

        IReadOnlyList<ContextTargetSetCoverage> setCoverage = ContextCoverageAnalyzer.AnalyzeRequestedTargetSets(
            source,
            new IReadOnlyCollection<string>[]
            {
                new[] { "target-a" },
                new[] { "target-a", "target-b" },
                new[] { "target-a", "target-b", "target-c" },
                new[] { "target-a", "target-b", "missing-target" }
            });
        Check(setCoverage.Count == 4 && setCoverage[0].Covered && setCoverage[1].Covered && setCoverage[2].Covered && !setCoverage[3].Covered,
            "Requested 1/2/3-target coverage must report exact real availability and explicit gaps.");

        IReadOnlyList<ContextSentenceEnvelope> noun = source.FindByTargets(new[] { "bank-noun" }, 10);
        IReadOnlyList<ContextSentenceEnvelope> verb = source.FindByTargets(new[] { "bank-verb" }, 10);
        Check(noun.Count == 1 && noun[0].Sentence.Id == "s-bank-noun", "Same-headword noun stable ID must remain distinct.");
        Check(verb.Count == 1 && verb[0].Sentence.Id == "s-bank-verb", "Same-headword verb stable ID must remain distinct.");

        bool fourRejected = false;
        try { _ = source.FindByTargets(new[] { "a", "b", "c", "d" }, 10); }
        catch (InvalidDataException) { fourRejected = true; }
        Check(fourRejected, "Context target sets larger than three must fail closed during Stage-11 preparation.");
    }

    private static void TestLearnerVocabularyDominatesCefr()
    {
        SentencePack pack = BuildSelectionPack();
        var source = new SentenceCorpusContextSource(
            pack,
            new ContextSourceDescriptor(pack.PackId, ContextCorpusKind.SyntheticFixture, pack.Provenance, pack.License));
        var vocabulary = new ContextLearnerVocabulary(knownEntryIds: new[] { "helper-known" });
        var request = new ContextPracticeRequest(
            new[] { "target-rank" },
            Vocabulary: vocabulary,
            MaxResults: 10,
            CandidateLimit: 20,
            AllowSyntheticFixtures: true);

        IReadOnlyList<RankedContextSentence> ranked = ContextPracticeService.Select(source, request);
        Check(ranked.Count == 2, "Ranking fixture must expose both target sentences.");
        Check(ranked[0].Candidate.Sentence.Id == "s-known-c1", "Known-vocabulary context must outrank an A1 sentence containing an unknown helper word.");
        Check(ranked[0].Difficulty.UnknownHelperEntries == 0 && ranked[1].Difficulty.UnknownHelperEntries == 1,
            "Difficulty breakdown must be derived from learner lexical state, not CEFR alone.");
        Check(!string.IsNullOrWhiteSpace(ranked[0].Difficulty.Explanation), "Context ranking must expose a short deterministic explanation.");

        for (int i = 0; i < 200; i++)
        {
            IReadOnlyList<RankedContextSentence> repeat = ContextPracticeService.Select(source, request);
            Check(repeat.Select(item => item.Candidate.Sentence.Id).SequenceEqual(ranked.Select(item => item.Candidate.Sentence.Id)),
                "Identical context state must produce deterministic ranking.");
        }
    }

    private static void TestStableIdPools(DictionaryPackage dictionary)
    {
        string[] ids30 = ContextTargetIds.NormalizeStudyPool(dictionary.Entries.Take(30).Select(entry => entry.Id));
        string[] ids100 = ContextTargetIds.NormalizeStudyPool(dictionary.Entries.Take(100).Select(entry => entry.Id));
        string[] ids200 = ContextTargetIds.NormalizeStudyPool(dictionary.Entries.Take(200).Select(entry => entry.Id));
        Check(ids30.Length == 30 && ids100.Length == 100 && ids200.Length == 200, "30/100/200-word user list/deck inputs must preserve exact stable IDs.");

        string firstId = dictionary.Entries[0].Id;
        SentencePack poolPack = BuildPack(
            "context-pool-fixture",
            MakeSentence("s-pool", "alpha beta", new[] { firstId }, "A1"));
        var source = new SentenceCorpusContextSource(
            poolPack,
            new ContextSourceDescriptor(poolPack.PackId, ContextCorpusKind.SyntheticFixture, poolPack.Provenance, poolPack.License));
        IReadOnlyList<RankedContextSentence> result = ContextPracticeService.Select(source, new ContextPracticeRequest(
            new[] { firstId },
            ids200,
            new ContextLearnerVocabulary(ids200),
            MaxResults: 5,
            CandidateLimit: 10,
            AllowSyntheticFixtures: true));
        Check(result.Count == 1, "A target from a user-supplied stable-ID pool must remain selectable.");

        bool outsidePoolRejected = false;
        try
        {
            _ = ContextPracticeService.Select(source, new ContextPracticeRequest(
                new[] { "not-in-pool" }, ids200, MaxResults: 1, CandidateLimit: 1, AllowSyntheticFixtures: true));
        }
        catch (InvalidDataException) { outsidePoolRejected = true; }
        Check(outsidePoolRejected, "A required target outside the supplied study list/deck must fail closed.");
    }

    private static void TestSyntheticFailClosed()
    {
        SentencePack pack = BuildSelectionPack();
        var source = new SentenceCorpusContextSource(
            pack,
            new ContextSourceDescriptor(pack.PackId, ContextCorpusKind.SyntheticFixture, pack.Provenance, pack.License));
        var defaultRequest = new ContextPracticeRequest(new[] { "target-a" }, MaxResults: 5, CandidateLimit: 10);
        Check(ContextPracticeService.Select(source, defaultRequest).Count == 0,
            "Synthetic/test context must be excluded from product selection unless explicitly enabled for tests.");

        var explicitFixtureRequest = defaultRequest with { AllowSyntheticFixtures = true };
        Check(ContextPracticeService.Select(source, explicitFixtureRequest).Count > 0,
            "Explicit test mode may use a labeled synthetic fixture.");
    }

    private static void TestLocalTextAndGrammarMetadataSeams()
    {
        var localDescriptor = new ContextSourceDescriptor(
            "local-book-1",
            ContextCorpusKind.LocalUserText,
            "local-user-import",
            "user-private-local",
            PrivacyLocalOnly: true);
        var location = new LocalTextContextLocation("local-source-1", "book-1", "chapter-03", 120, 174, PrivacyLocalOnly: true);
        var envelope = new ContextSentenceEnvelope(
            MakeSentence("local-sentence-1", "alpha beta gamma", new[] { "target-local" }, "B1", flags: new[] { "grammar:present-perfect" }),
            localDescriptor,
            location,
            ContextGrammarMetadata.ExtractFromQualityFlags(new[] { "grammar:present-perfect", "long-sentence" }));
        envelope.Validate();
        Check(envelope.LocalTextLocation?.ChapterId == "chapter-03" && envelope.LocalTextLocation.StartOffset == 120 && envelope.LocalTextLocation.EndOffset == 174,
            "Stage-12 seam must preserve source/book/chapter sentence offsets.");
        Check(envelope.Source.PrivacyLocalOnly, "Local imported text must default to privacy-local handling.");
        Check(envelope.EffectiveGrammarSkillIds.SequenceEqual(new[] { "present-perfect" }),
            "Grammar readiness is metadata-only: grammar skill IDs may pass through without implementing Grammar Coach.");

        bool nonLocalRejected = false;
        try
        {
            new ContextSourceDescriptor("bad-local", ContextCorpusKind.LocalUserText, "local", "private", PrivacyLocalOnly: false).Validate();
        }
        catch (InvalidDataException) { nonLocalRejected = true; }
        Check(nonLocalRejected, "A local book/text source cannot silently opt out of privacy-local handling.");
    }

    private static void TestExact5446CoverageAccounting(DictionaryPackage dictionary)
    {
        string[] universe = dictionary.Entries.Select(entry => entry.Id).ToArray();
        var source = new CoverageOnlySource(universe.Take(5000));
        ContextCoverageReport report = ContextCoverageAnalyzer.AnalyzeOneTargetUniverse(source, universe);
        Check(report.RequestedEntryCount == 5446, "Coverage accounting must use all 5446 current Oxford stable IDs.");
        Check(report.CoveredEntryCount == 5000 && report.UncoveredEntryCount == 446, "Coverage accounting must expose exact covered and uncovered counts.");
        Check(report.CoveredEntryIds.Count + report.UncoveredEntryIds.Count == 5446, "Coverage lists must exactly partition all 5446 stable IDs.");
        Check(report.UncoveredEntryIds.SequenceEqual(universe.Skip(5000).Select(ContextTargetIds.NormalizeSingle)), "Uncovered stable IDs must be explicit and deterministic.");
    }

    private static void TestBoundedSqliteIntersectionsAndStress()
    {
        string root = Path.Combine(Path.GetTempPath(), "WordDeck контекст R4c " + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        string databasePath = Path.Combine(root, "речення stage 11.sqlite");
        try
        {
            SentencePack pack = BuildSqliteStressPack();
            SentencePackSqlitePrototype.Build(databasePath, pack);
            var source = new ContextSentenceSqliteSource(databasePath, ContextCorpusKind.SyntheticFixture);

            IReadOnlyList<ContextSentenceEnvelope> triple = source.FindByTargets(new[] { "ctx-a", "ctx-b", "ctx-c" }, 16);
            Check(triple.Count > 0 && triple.Count <= 16, "SQLite three-target intersection must be real and bounded.");
            Check(triple.All(item => ContainsAll(item.Sentence, new[] { "ctx-a", "ctx-b", "ctx-c" })), "SQLite intersection must never return a sentence missing a requested stable ID.");

            IReadOnlyList<string> plan = source.ExplainIntersectionPlan(new[] { "ctx-a", "ctx-b", "ctx-c" }, 16);
            string joinedPlan = string.Join(" | ", plan);
            Check(plan.Count > 0 && joinedPlan.Contains("sentence_targets", StringComparison.OrdinalIgnoreCase), "SQLite intersection query plan must touch the indexed sentence_targets relation.");
            Check(joinedPlan.Contains("PRIMARY KEY", StringComparison.OrdinalIgnoreCase) || joinedPlan.Contains("INDEX", StringComparison.OrdinalIgnoreCase),
                "SQLite intersection query plan must use an index/primary-key search rather than an unbounded full-table design.");

            ContextCoverageReport coverage = ContextCoverageAnalyzer.AnalyzeOneTargetUniverse(source, new[] { "ctx-a", "ctx-b", "ctx-c", "ctx-missing" });
            Check(coverage.CoveredEntryCount == 3 && coverage.UncoveredEntryIds.SequenceEqual(new[] { "ctx-missing" }),
                "SQLite coverage path must report explicit one-target gaps.");

            Stopwatch stopwatch = Stopwatch.StartNew();
            long checksum = 0;
            for (int i = 0; i < 1000; i++)
            {
                string[] targets = i % 3 switch
                {
                    0 => new[] { "ctx-a" },
                    1 => new[] { "ctx-a", "ctx-b" },
                    _ => new[] { "ctx-a", "ctx-b", "ctx-c" }
                };
                IReadOnlyList<ContextSentenceEnvelope> found = source.FindByTargets(targets, 8);
                Check(found.Count <= 8, "Every Stage-11 SQLite lookup must honor its explicit candidate bound.");
                Check(found.All(item => ContainsAll(item.Sentence, targets)), "Repeated SQLite lookup returned a non-intersection candidate.");
                checksum += found.Count;
            }
            stopwatch.Stop();
            Check(checksum > 0, "SQLite stress must execute real matching queries.");
            Check(stopwatch.Elapsed < TimeSpan.FromSeconds(30), "1000 bounded SQLite context lookups exceeded the generous 30-second regression budget.");
            Console.WriteLine($"Context R4c SQLite stress: 1000 bounded 1/2/3-target queries in {stopwatch.ElapsedMilliseconds} ms; checksum={checksum}; plan={joinedPlan}");
        }
        finally
        {
            try { Directory.Delete(root, recursive: true); } catch { }
        }
    }

    private static SentencePack BuildSelectionPack() => BuildPack(
        "context-selection-fixture",
        MakeSentence("s-single", "alpha beta", new[] { "target-a" }, "A1"),
        MakeSentence("s-two", "alpha beta gamma", new[] { "target-a", "target-b" }, "A2"),
        MakeSentence("s-three", "alpha beta gamma delta", new[] { "target-a", "target-b", "target-c" }, "B1"),
        MakeSentence("s-bank-noun", "the bank closed", new[] { "bank-noun" }, "A2"),
        MakeSentence("s-bank-verb", "planes bank sharply", new[] { "bank-verb" }, "B1"),
        MakeSentence("s-known-c1", "alpha known context", new[] { "target-rank", "helper-known" }, "C1"),
        MakeSentence("s-unknown-a1", "alpha unknown context", new[] { "target-rank", "helper-unknown" }, "A1"),
        MakeSentence("s-grammar", "they have finished", new[] { "target-grammar" }, "B1", flags: new[] { "grammar:present-perfect" }));

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
            string[] flags = i % 10 == 0 ? new[] { "grammar:conditionals" } : Array.Empty<string>();
            sentences.Add(MakeSentence($"sqlite-{i:D4}", "alpha beta gamma delta", targets, levels[i % levels.Length], offList: i % 7 == 0 ? 1 : 0, flags: flags));
        }
        return BuildPack("context-sqlite-fixture", sentences.ToArray());
    }

    private static SentencePack BuildPack(string packId, params SentenceRecord[] sentences)
    {
        var pack = new SentencePack
        {
            PackId = packId,
            Provenance = "synthetic-self-test-only",
            License = "CC0-1.0",
            Sentences = sentences.ToList()
        };
        pack.Validate();
        return pack;
    }

    private static SentenceRecord MakeSentence(
        string id,
        string english,
        IEnumerable<string> targets,
        string difficulty,
        int offList = 0,
        IEnumerable<string>? flags = null)
    {
        List<string> targetList = targets.Select(ContextTargetIds.NormalizeSingle).Distinct(StringComparer.OrdinalIgnoreCase).ToList();
        List<string> tokens = SentenceTokenizer.Tokenize(english).ToList();
        var levels = targetList.ToDictionary(target => target, _ => difficulty, StringComparer.OrdinalIgnoreCase);
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
            EntryLevels = levels,
            DifficultyLevel = difficulty,
            OffListTokenCount = offList,
            QualityFlags = flags?.ToList() ?? new List<string>()
        };
    }

    private static bool ContainsAll(SentenceRecord sentence, IEnumerable<string> targets)
    {
        var sentenceIds = new HashSet<string>(sentence.TargetEntryIds, StringComparer.OrdinalIgnoreCase);
        return targets.All(sentenceIds.Contains);
    }

    private static void Check(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException("Context Practice R4c self-test failed: " + message);
    }

    private sealed class CoverageOnlySource : IContextSentenceSource, IContextCoverageSource
    {
        private readonly HashSet<string> _covered;
        public ContextSourceDescriptor Descriptor { get; } = new(
            "coverage-self-test",
            ContextCorpusKind.SyntheticFixture,
            "synthetic-self-test-only",
            "CC0-1.0");

        public CoverageOnlySource(IEnumerable<string> covered) =>
            _covered = new HashSet<string>(covered.Select(ContextTargetIds.NormalizeSingle), StringComparer.OrdinalIgnoreCase);

        public IReadOnlyList<ContextSentenceEnvelope> FindByTargets(IReadOnlyCollection<string> targetEntryIds, int maxCandidates) =>
            Array.Empty<ContextSentenceEnvelope>();

        public IReadOnlySet<string> GetCoveredOneTargetIds(IReadOnlyCollection<string> candidateEntryIds)
        {
            var result = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (string id in candidateEntryIds.Select(ContextTargetIds.NormalizeSingle))
                if (_covered.Contains(id)) result.Add(id);
            return result;
        }
    }
}
