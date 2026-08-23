using System.Diagnostics;
using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class ContextPracticeR4cDeepSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            ContextPracticeR4cDeepSelfTest.Run();
    }
}

internal static class ContextPracticeR4cDeepSelfTest
{
    public static void Run()
    {
        DictionaryPackage dictionary = DictionaryLoader.LoadEmbeddedOxford();
        var lexicon = new ContextTargetLexicon(dictionary);
        Require(lexicon.EntryCount == 5446, "Lexical catalog did not preserve all 5,446 stable Oxford IDs.");

        (DictionaryEntry homographA, DictionaryEntry homographB) = FindHomographPair(dictionary, lexicon);
        DictionaryEntry[] unique = FindUniqueLexicalEntries(dictionary, lexicon, 220);

        TestSameWrittenFormCannotBecomeMultipleTargets(dictionary, lexicon, homographA, homographB, unique);
        TestNaturalPlannerFor30_100_200Lists(dictionary, lexicon, homographA, homographB, unique);
        TestLexicalAwareDifficulty(dictionary, lexicon, homographA, homographB, unique);
        TestFullNaturalCoverageAndSqlitePlan(dictionary, lexicon, homographA, homographB, unique);

        Console.WriteLine("Context Practice R4c deep self-test PASS: same-written-form stable IDs cannot inflate 2/3-word exercises, natural 30/100/200 list planning works, lexical difficulty is conservative, and exact 5,446 one/two/three-target gaps are explicit.");
    }

    private static void TestSameWrittenFormCannotBecomeMultipleTargets(
        DictionaryPackage dictionary,
        ContextTargetLexicon lexicon,
        DictionaryEntry homographA,
        DictionaryEntry homographB,
        IReadOnlyList<DictionaryEntry> unique)
    {
        Require(string.Equals(lexicon.LexicalKeyFor(homographA.Id), lexicon.LexicalKeyFor(homographB.Id), StringComparison.OrdinalIgnoreCase),
            "Homograph fixture does not share one written lexical form.");
        Require(!string.Equals(homographA.Id, homographB.Id, StringComparison.OrdinalIgnoreCase),
            "Homograph fixture collapsed stable identities.");

        SentencePack pack = BuildPack(
            "r4c-homograph-product-safety",
            MakeSentence("homograph-plus-partner", new[] { homographA, homographB, unique[0] }, "B1"));
        var source = FixtureSource(pack);

        bool rejectedArtificialPair = false;
        try
        {
            _ = ContextPracticeService.Select(source, new ContextPracticeRequest(
                new[] { homographA.Id, homographB.Id },
                Vocabulary: new ContextLearnerVocabulary(),
                MaxResults: 5,
                CandidateLimit: 10,
                AllowSyntheticFixtures: true,
                TargetLexicon: lexicon));
        }
        catch (InvalidDataException) { rejectedArtificialPair = true; }
        Require(rejectedArtificialPair,
            "Product context selection counted two stable IDs for one written form as two target words.");

        IReadOnlyList<RankedContextSentence> validPair = ContextPracticeService.Select(source, new ContextPracticeRequest(
            new[] { homographA.Id, unique[0].Id },
            Vocabulary: new ContextLearnerVocabulary(),
            MaxResults: 5,
            CandidateLimit: 10,
            AllowSyntheticFixtures: true,
            TargetLexicon: lexicon));
        Require(validPair.Count == 1 && validPair[0].Candidate.Sentence.Id == "homograph-plus-partner",
            "A real two-lexeme sentence was rejected while protecting stable-ID homographs.");
    }

    private static void TestNaturalPlannerFor30_100_200Lists(
        DictionaryPackage dictionary,
        ContextTargetLexicon lexicon,
        DictionaryEntry homographA,
        DictionaryEntry homographB,
        IReadOnlyList<DictionaryEntry> unique)
    {
        SentencePack pack = BuildPack(
            "r4c-natural-list-planner",
            MakeSentence("natural-pair", new[] { homographA, homographB, unique[0] }, "A2"),
            MakeSentence("natural-triple", new[] { homographA, homographB, unique[0], unique[1] }, "B1"));
        var source = FixtureSource(pack);

        foreach (int size in new[] { 30, 100, 200 })
        {
            string[] pool = BuildPool(size, homographA.Id, homographB.Id, unique);
            IReadOnlyList<NaturalContextTargetSet> pairs = ContextNaturalTargetPlanner.Discover(
                source,
                lexicon,
                pool,
                homographA.Id,
                desiredTargetCount: 2,
                maxCandidateSentences: 32,
                maxSets: 10);
            Require(pairs.Count > 0 && pairs.All(set => set.TargetEntryIds.Count == 2),
                $"Natural two-target planning failed for a {size}-word stable-ID study list.");
            Require(pairs.All(set => set.TargetEntryIds.Select(lexicon.LexicalKeyFor).Distinct(StringComparer.OrdinalIgnoreCase).Count() == 2),
                $"Natural planner inflated a same-written-form stable ID in the {size}-word list.");
            Require(pairs.Any(set => set.AmbiguousStableEntryIds.Contains(homographA.Id, StringComparer.OrdinalIgnoreCase) &&
                                     set.AmbiguousStableEntryIds.Contains(homographB.Id, StringComparer.OrdinalIgnoreCase)),
                $"Natural planner hid same-written-form stable-ID ambiguity for the {size}-word list.");

            IReadOnlyList<NaturalContextTargetSet> triples = ContextNaturalTargetPlanner.Discover(
                source,
                lexicon,
                pool,
                homographA.Id,
                desiredTargetCount: 3,
                maxCandidateSentences: 32,
                maxSets: 10);
            Require(triples.Count > 0 && triples.All(set => set.TargetEntryIds.Count == 3),
                $"Natural three-target planning failed for a {size}-word stable-ID study list.");
            Require(triples.All(set => set.TargetEntryIds.Select(lexicon.LexicalKeyFor).Distinct(StringComparer.OrdinalIgnoreCase).Count() == 3),
                $"Natural three-target planner counted stable-ID homographs as separate physical words in the {size}-word list.");
        }

        SentencePack impossiblePack = BuildPack(
            "r4c-impossible-homograph-triple",
            MakeSentence("only-two-physical-words", new[] { homographA, homographB, unique[0] }, "A2"));
        IReadOnlyList<NaturalContextTargetSet> impossible = ContextNaturalTargetPlanner.Discover(
            FixtureSource(impossiblePack),
            lexicon,
            BuildPool(30, homographA.Id, homographB.Id, unique),
            homographA.Id,
            desiredTargetCount: 3,
            maxCandidateSentences: 16,
            maxSets: 5);
        Require(impossible.Count == 0,
            "Natural planner fabricated a three-target exercise from two physical lexical forms.");
    }

    private static void TestLexicalAwareDifficulty(
        DictionaryPackage dictionary,
        ContextTargetLexicon lexicon,
        DictionaryEntry homographA,
        DictionaryEntry homographB,
        IReadOnlyList<DictionaryEntry> unique)
    {
        DictionaryEntry target = unique[2];
        SentencePack pack = BuildPack(
            "r4c-lexical-difficulty",
            MakeSentence("ambiguous-helper", new[] { target, homographA, homographB }, "A1"));
        var source = FixtureSource(pack);

        IReadOnlyList<RankedContextSentence> ranked = ContextPracticeService.Select(source, new ContextPracticeRequest(
            new[] { target.Id },
            Vocabulary: new ContextLearnerVocabulary(),
            MaxResults: 5,
            CandidateLimit: 10,
            AllowSyntheticFixtures: true,
            TargetLexicon: lexicon));
        Require(ranked.Count == 1 && ranked[0].Difficulty.UnknownHelperEntries == 1,
            "Difficulty counted two stable senses of one written helper as two unknown helper words.");

        var mixedEvidence = new ContextLearnerVocabulary(knownEntryIds: new[] { homographA.Id });
        IReadOnlyList<RankedContextSentence> mixed = ContextPracticeService.Select(source, new ContextPracticeRequest(
            new[] { target.Id },
            Vocabulary: mixedEvidence,
            MaxResults: 5,
            CandidateLimit: 10,
            AllowSyntheticFixtures: true,
            TargetLexicon: lexicon));
        Require(mixed.Count == 1 && mixed[0].Difficulty.KnownHelperEntries == 0 && mixed[0].Difficulty.LearningHelperEntries == 1,
            "Ambiguous helper with only one known stable sense was over-claimed as fully known.");
    }

    private static void TestFullNaturalCoverageAndSqlitePlan(
        DictionaryPackage dictionary,
        ContextTargetLexicon lexicon,
        DictionaryEntry homographA,
        DictionaryEntry homographB,
        IReadOnlyList<DictionaryEntry> unique)
    {
        string root = Path.Combine(Path.GetTempPath(), "WordDeck R4c natural coverage Київ " + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        string databasePath = Path.Combine(root, "natural coverage 5446.sqlite");
        try
        {
            SentencePack pack = BuildPack(
                "r4c-natural-full-coverage",
                MakeSentence("coverage-one", new[] { unique[0] }, "A1"),
                MakeSentence("coverage-two", new[] { unique[1], unique[2] }, "A2"),
                MakeSentence("coverage-three", new[] { unique[3], unique[4], unique[5] }, "B1"),
                MakeSentence("coverage-homograph", new[] { homographA, homographB, unique[6] }, "B2"));
            SentencePackSqlitePrototype.Build(databasePath, pack);
            Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();

            var source = new ContextSentenceSqliteSource(databasePath, ContextCorpusKind.SyntheticFixture);
            string[] universe = dictionary.Entries.Select(entry => entry.Id).ToArray();

            var watch = Stopwatch.StartNew();
            ContextNaturalCoverageReport one = ContextNaturalCoverageAnalyzer.Analyze(source, lexicon, universe, 1);
            ContextNaturalCoverageReport two = ContextNaturalCoverageAnalyzer.Analyze(source, lexicon, universe, 2);
            ContextNaturalCoverageReport three = ContextNaturalCoverageAnalyzer.Analyze(source, lexicon, universe, 3);
            watch.Stop();

            foreach (ContextNaturalCoverageReport report in new[] { one, two, three })
            {
                Require(report.ScopeEntryCount == 5446,
                    $"Natural {report.RequiredTargetCount}-target coverage used {report.ScopeEntryCount} instead of 5,446 Oxford stable IDs.");
                Require(report.CoveredEntryCount + report.UncoveredEntryCount == 5446,
                    $"Natural {report.RequiredTargetCount}-target coverage does not partition all 5,446 stable IDs.");
                Require(report.UncoveredEntryIds.Count == report.UncoveredEntryCount &&
                        report.UncoveredEntryIds.Distinct(StringComparer.OrdinalIgnoreCase).Count() == report.UncoveredEntryCount,
                    $"Natural {report.RequiredTargetCount}-target gap list is not exact/deduplicated.");
                Require(report.AmbiguousStableEntryIds.Contains(homographA.Id, StringComparer.OrdinalIgnoreCase) &&
                        report.AmbiguousStableEntryIds.Contains(homographB.Id, StringComparer.OrdinalIgnoreCase),
                    "Full natural coverage did not surface same-written-form stable-ID ambiguity.");
            }

            Require(one.CoveredEntryCount == 9 && one.UncoveredEntryCount == 5437,
                $"One-target natural coverage expected 9/5446 fixture IDs, got {one.CoveredEntryCount}/{one.ScopeEntryCount}.");
            Require(two.CoveredEntryCount == 8 && two.UncoveredEntryCount == 5438,
                $"Two-target natural coverage expected 8/5446 fixture IDs, got {two.CoveredEntryCount}/{two.ScopeEntryCount}.");
            Require(three.CoveredEntryCount == 3 && three.UncoveredEntryCount == 5443,
                $"Three-target natural coverage expected 3/5446 fixture IDs, got {three.CoveredEntryCount}/{three.ScopeEntryCount}.");
            Require(!three.CoveredEntryIds.Contains(homographA.Id, StringComparer.OrdinalIgnoreCase) &&
                    !three.CoveredEntryIds.Contains(homographB.Id, StringComparer.OrdinalIgnoreCase) &&
                    !three.CoveredEntryIds.Contains(unique[6].Id, StringComparer.OrdinalIgnoreCase),
                "Three-target coverage was inflated by two stable IDs for one physical written word.");

            IReadOnlyList<ContextLexicalTarget> planScope = lexicon.DescribePool(
                BuildPool(30, homographA.Id, homographB.Id, unique));
            string plan = string.Join(" | ", source.ExplainNaturalCoveragePlan(planScope, 3));
            Require(plan.Contains("sentence_targets", StringComparison.OrdinalIgnoreCase),
                "Natural coverage SQLite plan does not traverse sentence_targets.");
            Require(plan.Contains("INDEX", StringComparison.OrdinalIgnoreCase) ||
                    plan.Contains("PRIMARY KEY", StringComparison.OrdinalIgnoreCase) ||
                    plan.Contains("SEARCH", StringComparison.OrdinalIgnoreCase),
                "Natural coverage SQLite plan does not expose indexed/search access.");

            Require(watch.Elapsed < TimeSpan.FromSeconds(30),
                "Three exact 5,446-entry natural coverage passes exceeded the generous 30-second regression budget on the tiny fixture.");
            Console.WriteLine($"Context R4c exact 5446 natural coverage: one={one.CoveredEntryCount}, two={two.CoveredEntryCount}, three={three.CoveredEntryCount}, elapsed={watch.ElapsedMilliseconds} ms; plan={plan}");
        }
        finally
        {
            Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
            try { Directory.Delete(root, recursive: true); } catch { }
        }
    }

    private static string[] BuildPool(
        int size,
        string homographA,
        string homographB,
        IReadOnlyList<DictionaryEntry> unique)
    {
        if (size < 4 || unique.Count < size)
            throw new ArgumentOutOfRangeException(nameof(size));
        var ids = new List<string> { homographA, homographB };
        foreach (DictionaryEntry entry in unique)
        {
            if (ids.Count >= size) break;
            if (!ids.Contains(entry.Id, StringComparer.OrdinalIgnoreCase))
                ids.Add(entry.Id);
        }
        Require(ids.Count == size, $"Could not build deterministic {size}-entry context pool.");
        return ids.ToArray();
    }

    private static (DictionaryEntry A, DictionaryEntry B) FindHomographPair(
        DictionaryPackage dictionary,
        ContextTargetLexicon lexicon)
    {
        IGrouping<string, DictionaryEntry>? group = dictionary.Entries
            .GroupBy(entry => lexicon.LexicalKeyFor(entry.Id), StringComparer.OrdinalIgnoreCase)
            .FirstOrDefault(items => items.Select(entry => entry.Id).Distinct(StringComparer.OrdinalIgnoreCase).Count() >= 2);
        if (group is null)
            throw new InvalidOperationException("R4c deep test expected at least one same-written-form Oxford stable-ID group.");
        DictionaryEntry[] entries = group.Take(2).ToArray();
        return (entries[0], entries[1]);
    }

    private static DictionaryEntry[] FindUniqueLexicalEntries(
        DictionaryPackage dictionary,
        ContextTargetLexicon lexicon,
        int count)
    {
        var keyCounts = dictionary.Entries
            .GroupBy(entry => lexicon.LexicalKeyFor(entry.Id), StringComparer.OrdinalIgnoreCase)
            .ToDictionary(group => group.Key, group => group.Count(), StringComparer.OrdinalIgnoreCase);
        DictionaryEntry[] result = dictionary.Entries
            .Where(entry => keyCounts[lexicon.LexicalKeyFor(entry.Id)] == 1)
            .Take(count)
            .ToArray();
        Require(result.Length == count, $"Could not find {count} unique lexical entries for R4c deep tests.");
        return result;
    }

    private static SentenceCorpusContextSource FixtureSource(SentencePack pack) => new(
        pack,
        new ContextSourceDescriptor(pack.PackId, ContextCorpusKind.SyntheticFixture, pack.Provenance, pack.License));

    private static SentencePack BuildPack(string packId, params SentenceRecord[] sentences)
    {
        var pack = new SentencePack
        {
            PackId = packId,
            Provenance = "Synthetic R4c deep context fixture; never production release data",
            License = "CC0-1.0",
            Sentences = sentences.ToList()
        };
        pack.Validate();
        return pack;
    }

    private static SentenceRecord MakeSentence(string id, IReadOnlyList<DictionaryEntry> targets, string difficulty)
    {
        string english = "Context sentence for lexical safety testing.";
        List<string> tokens = SentenceTokenizer.Tokenize(english).ToList();
        string[] ids = targets.Select(entry => entry.Id).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        return new SentenceRecord
        {
            Id = id,
            English = english,
            Ukrainian = "Тестове контекстне речення.",
            Source = "WordDeck synthetic R4c deep context fixture",
            License = "CC0-1.0",
            Tokens = tokens,
            Lemmas = tokens.ToList(),
            TargetEntryIds = ids.ToList(),
            EntryLevels = targets
                .GroupBy(entry => entry.Id, StringComparer.OrdinalIgnoreCase)
                .ToDictionary(group => group.Key, group => group.First().Level, StringComparer.OrdinalIgnoreCase),
            DifficultyLevel = difficulty,
            OffListTokenCount = 0
        };
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException("Context Practice R4c deep self-test failed: " + message);
    }
}
