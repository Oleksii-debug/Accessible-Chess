using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class ContextPracticeApplicationSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            ContextPracticeApplicationSelfTest.Run();
    }
}

internal static class ContextPracticeApplicationSelfTest
{
    public static void Run()
    {
        TestStudyPoolPresets();
        TestSyntheticBoundaryAndNaturalCards();
        TestRecentSentenceDeprioritization();
        TestSentenceSpellingEvaluation();
        TestSameWrittenFormCannotBecomeTwoTargets();
        TestNoNaturalPairDoesNotFabricate();
        Console.WriteLine("Context Practice application self-test PASS: 30/100/200/full pools, natural cards, recent-history ranking, Sentence Spelling, homograph safety and no-fabrication behavior verified.");
    }

    private static void TestStudyPoolPresets()
    {
        string[] ids = Enumerable.Range(1, 250).Select(i => $"entry-{i:000}").ToArray();
        ContextStudyPoolSelection thirty = ContextStudyPoolBuilder.Build(ids, ContextStudyPoolPreset.Thirty);
        ContextStudyPoolSelection hundred = ContextStudyPoolBuilder.Build(ids, ContextStudyPoolPreset.Hundred);
        ContextStudyPoolSelection twoHundred = ContextStudyPoolBuilder.Build(ids, ContextStudyPoolPreset.TwoHundred);
        ContextStudyPoolSelection full = ContextStudyPoolBuilder.Build(ids, ContextStudyPoolPreset.Full);

        Check(thirty.EntryIds.Count == 30 && thirty.FilledRequestedWindow, "30-word study pool preset is wrong.");
        Check(hundred.EntryIds.Count == 100 && hundred.FilledRequestedWindow, "100-word study pool preset is wrong.");
        Check(twoHundred.EntryIds.Count == 200 && twoHundred.FilledRequestedWindow, "200-word study pool preset is wrong.");
        Check(full.EntryIds.Count == 250 && full.IsFullPool && full.FilledRequestedWindow, "Full study pool preset is wrong.");
        Check(thirty.EntryIds.SequenceEqual(ids.Take(30)), "Study pool selection must preserve caller order deterministically.");

        ContextStudyPoolSelection shortPool = ContextStudyPoolBuilder.Build(ids.Take(12), ContextStudyPoolPreset.Thirty);
        Check(shortPool.EntryIds.Count == 12 && !shortPool.FilledRequestedWindow, "A short source pool must remain bounded instead of inventing entries.");
    }

    private static void TestSyntheticBoundaryAndNaturalCards()
    {
        SentencePack pack = BuildPack(
            "application-synthetic",
            MakeSentence("s-pair", "Practice daily", "Практикуйся щодня", new[] { "target-a", "target-b" }, "grammar:present-simple"),
            MakeSentence("s-triple", "Practice daily together", "Практикуйтеся щодня разом", new[] { "target-a", "target-b", "target-c" }, "grammar:present-simple"));
        var source = FixtureSource(pack);
        var lexicon = new ContextTargetLexicon("application", new[]
        {
            ("target-a", "practice"),
            ("target-b", "daily"),
            ("target-c", "together")
        });
        var request = new ContextPracticeApplicationRequest("target-a", 3, ContextStudyPoolPreset.Full, MaxCards: 10, CandidateLimit: 20);

        bool blocked = false;
        try
        {
            _ = ContextPracticeApplicationService.BuildCards(source, lexicon, new[] { "target-a", "target-b", "target-c" }, request);
        }
        catch (InvalidDataException)
        {
            blocked = true;
        }
        Check(blocked, "Synthetic SentencePack fixtures must fail closed for product-facing Context Practice by default.");

        ContextPracticeApplicationResult result = ContextPracticeApplicationService.BuildCards(
            source,
            lexicon,
            new[] { "target-a", "target-b", "target-c" },
            request,
            new ContextProductUseOptions(AllowSyntheticFixtures: true));
        Check(result.Cards.Count == 1 && result.Cards[0].SentenceId == "s-triple", "Natural three-target application card selection failed.");
        Check(result.Cards[0].TargetEntryIds.Count == 3 && result.Cards[0].TargetLexicalKeys.Distinct(StringComparer.OrdinalIgnoreCase).Count() == 3,
            "Application card lost stable target IDs or physical lexical-form identity.");
        Check(result.Cards[0].GrammarSkillIds.Contains("present-simple", StringComparer.OrdinalIgnoreCase), "Grammar metadata was not carried into the reusable application card.");
        Check(result.Cards[0].SourceKind == ContextCorpusKind.SyntheticFixture && result.Cards[0].Provenance == pack.Provenance && result.Cards[0].License == pack.License,
            "Application card lost source/provenance/license metadata.");
    }

    private static void TestRecentSentenceDeprioritization()
    {
        SentencePack pack = BuildPack(
            "application-recent",
            MakeSentence("s-a-recent", "Practice daily", "Практикуйся щодня", new[] { "target-a", "target-b" }),
            MakeSentence("s-z-fresh", "Practice daily", "Практикуйся щодня", new[] { "target-a", "target-b" }));
        var source = FixtureSource(pack);
        var lexicon = new ContextTargetLexicon("application", new[] { ("target-a", "practice"), ("target-b", "daily") });
        var request = new ContextPracticeApplicationRequest(
            "target-a",
            2,
            ContextStudyPoolPreset.Full,
            RecentSentenceIds: new[] { "s-a-recent" },
            MaxCards: 10,
            CandidateLimit: 20);

        ContextPracticeApplicationResult result = ContextPracticeApplicationService.BuildCards(
            source,
            lexicon,
            new[] { "target-a", "target-b" },
            request,
            new ContextProductUseOptions(AllowSyntheticFixtures: true));
        Check(result.Cards.Count == 2, "Recent-history fixture must produce both natural cards.");
        Check(result.Cards[0].SentenceId == "s-z-fresh" && !result.Cards[0].WasRecentlyUsed,
            "A fresh equally-difficult sentence must outrank a recently used sentence.");
        Check(result.Cards[1].SentenceId == "s-a-recent" && result.Cards[1].WasRecentlyUsed,
            "Recent sentence identity was not preserved for deterministic recycling.");
    }

    private static void TestSentenceSpellingEvaluation()
    {
        var card = new ContextPracticeCard(
            "spelling-card",
            "Я дуже добре вчуся",
            "I study very well",
            new[] { "study" },
            new[] { "study" },
            new ContextDifficultyBreakdown(0, 0, 0, 0, 1, 4, 14, "fixture"),
            "fixture",
            ContextCorpusKind.SyntheticFixture,
            "test-only",
            "TEST-ONLY",
            false,
            null,
            Array.Empty<string>(),
            false);

        SentenceAnswerResult reordered = ContextPracticeApplicationService.EvaluateSentenceSpelling(card, "well very study I");
        Check(reordered.Accepted && reordered.WordOrderIgnored, "Sentence Spelling must preserve existing exact-token multiset semantics with arbitrary word order.");

        SentenceAnswerResult missing = ContextPracticeApplicationService.EvaluateSentenceSpelling(card, "I study very");
        Check(!missing.Accepted && missing.Missing.Contains("well", StringComparer.Ordinal), "Sentence Spelling failed to report a missing required form.");

        SentenceAnswerResult duplicate = ContextPracticeApplicationService.EvaluateSentenceSpelling(card, "I study very well well");
        Check(!duplicate.Accepted && duplicate.Extra.Contains("well", StringComparer.Ordinal), "Sentence Spelling failed to reject an extra duplicated form.");
    }

    private static void TestSameWrittenFormCannotBecomeTwoTargets()
    {
        SentencePack pack = BuildPack(
            "application-homograph",
            MakeSentence("s-bank", "Bank safely", "Користуйся банком безпечно", new[] { "bank-noun", "bank-verb" }));
        var source = FixtureSource(pack);
        var lexicon = new ContextTargetLexicon("application", new[]
        {
            ("bank-noun", "bank"),
            ("bank-verb", "bank")
        });

        bool blocked = false;
        try
        {
            _ = ContextPracticeApplicationService.BuildCards(
                source,
                lexicon,
                new[] { "bank-noun", "bank-verb" },
                new ContextPracticeApplicationRequest("bank-noun", 2, ContextStudyPoolPreset.Full, MaxCards: 10, CandidateLimit: 20),
                new ContextProductUseOptions(AllowSyntheticFixtures: true));
        }
        catch (InvalidDataException ex)
        {
            blocked = ex.Message.Contains("unresolved", StringComparison.OrdinalIgnoreCase) &&
                      ex.Message.Contains("bank-noun", StringComparison.OrdinalIgnoreCase);
        }
        Check(blocked,
            "Two Oxford stable IDs for the same written form must fail closed until explicit POS/sense evidence resolves the stable identity.");
    }

    private static void TestNoNaturalPairDoesNotFabricate()
    {
        SentencePack pack = BuildPack(
            "application-gap",
            MakeSentence("s-a", "Practice now", "Практикуйся зараз", new[] { "target-a" }),
            MakeSentence("s-b", "Read daily", "Читай щодня", new[] { "target-b" }));
        var source = FixtureSource(pack);
        var lexicon = new ContextTargetLexicon("application", new[] { ("target-a", "practice"), ("target-b", "read") });

        ContextPracticeApplicationResult result = ContextPracticeApplicationService.BuildCards(
            source,
            lexicon,
            new[] { "target-a", "target-b" },
            new ContextPracticeApplicationRequest("target-a", 2, ContextStudyPoolPreset.Full, MaxCards: 10, CandidateLimit: 20),
            new ContextProductUseOptions(AllowSyntheticFixtures: true));
        Check(result.Cards.Count == 0, "Missing natural pair coverage must stay an explicit gap; Context Practice must not fabricate a sentence.");
        Check(result.SelectionExplanation.Contains("No natural 2-target", StringComparison.Ordinal), "No-natural-pair result must expose an explicit deterministic gap explanation.");
    }

    private static SentenceCorpusContextSource FixtureSource(SentencePack pack) =>
        new(pack, new ContextSourceDescriptor(pack.PackId, ContextCorpusKind.SyntheticFixture, pack.Provenance, pack.License));

    private static SentencePack BuildPack(string packId, params SentenceRecord[] sentences)
    {
        var pack = new SentencePack
        {
            PackId = packId,
            Provenance = "synthetic-test-fixture-only",
            License = "TEST-ONLY",
            Sentences = sentences.ToList()
        };
        pack.Validate();
        return pack;
    }

    private static SentenceRecord MakeSentence(
        string id,
        string english,
        string ukrainian,
        IReadOnlyList<string> targetIds,
        params string[] qualityFlags)
    {
        IReadOnlyList<string> tokens = SentenceTokenizer.Tokenize(english);
        return new SentenceRecord
        {
            Id = id,
            English = english,
            Ukrainian = ukrainian,
            Source = "synthetic-test-fixture-only",
            License = "TEST-ONLY",
            Tokens = tokens.ToList(),
            Lemmas = tokens.ToList(),
            TargetEntryIds = targetIds.ToList(),
            EntryLevels = targetIds.ToDictionary(id => id, _ => "A2", StringComparer.OrdinalIgnoreCase),
            DifficultyLevel = "A2",
            OffListTokenCount = 0,
            QualityFlags = qualityFlags.ToList()
        };
    }

    private static void Check(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
}
