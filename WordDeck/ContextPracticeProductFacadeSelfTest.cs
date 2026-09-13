using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class ContextPracticeProductFacadeSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            ContextPracticeProductFacadeSelfTest.Run();
    }
}

internal static class ContextPracticeProductFacadeSelfTest
{
    public static void Run()
    {
        var lexicon = new ContextTargetLexicon(
            "context-product-facade-fixture",
            new[]
            {
                ("target-a", "alpha"),
                ("target-b", "beta"),
                ("target-c", "gamma")
            });

        var homographLexicon = new ContextTargetLexicon(
            "context-global-homograph-fixture",
            new[]
            {
                ("run-n", "run"),
                ("run-v", "run"),
                ("walk-v", "walk")
            });
        IReadOnlyList<string> narrowScopeAmbiguous = homographLexicon.AmbiguousStableIds(new[] { "run-n", "walk-v" });
        Require(narrowScopeAmbiguous.Count == 1 && narrowScopeAmbiguous[0] == "run-n",
            "Narrow study-scope ambiguity accounting forgot a globally homographic sibling stable ID outside the active scope.");

        SentencePack pack = BuildPack();
        var synthetic = new SentenceCorpusContextSource(
            pack,
            new ContextSourceDescriptor(
                pack.PackId,
                ContextCorpusKind.SyntheticFixture,
                pack.Provenance,
                pack.License));

        ExpectSyntheticRejected(() => ContextPracticeProductFacade.Select(
            synthetic,
            new ContextPracticeRequest(
                new[] { "target-a" },
                TargetLexicon: lexicon)));
        ExpectSyntheticRejected(() => ContextPracticeProductFacade.DiscoverNaturalTargets(
            synthetic,
            lexicon,
            new[] { "target-a", "target-b", "target-c" },
            "target-a",
            desiredTargetCount: 2));
        ExpectSyntheticRejected(() => ContextPracticeProductFacade.AnalyzeNaturalCoverage(
            synthetic,
            lexicon,
            new[] { "target-a", "target-b", "target-c" },
            requiredTargetCount: 2));

        var testOptions = new ContextProductUseOptions(AllowSyntheticFixtures: true);
        IReadOnlyList<RankedContextSentence> selected = ContextPracticeProductFacade.Select(
            synthetic,
            new ContextPracticeRequest(
                new[] { "target-a" },
                TargetLexicon: lexicon),
            testOptions);
        Require(selected.Count == 1 && selected[0].Candidate.Sentence.Id == "product-facade-sentence",
            "Explicit test-only synthetic selection did not reach the existing context selector.");

        IReadOnlyList<NaturalContextTargetSet> planned = ContextPracticeProductFacade.DiscoverNaturalTargets(
            synthetic,
            lexicon,
            new[] { "target-a", "target-b", "target-c" },
            "target-a",
            desiredTargetCount: 3,
            options: testOptions,
            maxCandidateSentences: 8,
            maxSets: 4);
        Require(planned.Count == 1 && planned[0].TargetEntryIds.Count == 3,
            "Explicit test-only synthetic target planning failed.");

        ContextCoverageEvidence syntheticEvidence = ContextPracticeProductFacade.AnalyzeNaturalCoverage(
            synthetic,
            lexicon,
            new[] { "target-a", "target-b", "target-c" },
            requiredTargetCount: 3,
            options: testOptions,
            fallbackCandidateLimit: 8);
        Require(!syntheticEvidence.IsRealCorpusMeasurement &&
                syntheticEvidence.EvidenceBoundary.Contains("test-only", StringComparison.OrdinalIgnoreCase),
            "Synthetic coverage evidence was not clearly labeled non-production.");

        var realClassified = new SentenceCorpusContextSource(
            pack,
            new ContextSourceDescriptor(
                pack.PackId,
                ContextCorpusKind.RealCorpus,
                "real-corpus-classification-self-test-only",
                pack.License));
        ContextCoverageEvidence realEvidence = ContextPracticeProductFacade.AnalyzeNaturalCoverage(
            realClassified,
            lexicon,
            new[] { "target-a", "target-b", "target-c" },
            requiredTargetCount: 3,
            fallbackCandidateLimit: 8);
        Require(realEvidence.IsRealCorpusMeasurement &&
                realEvidence.EvidenceBoundary.Contains("do not by themselves approve redistribution", StringComparison.OrdinalIgnoreCase),
            "Real-corpus coverage boundary over-claimed release or licensing approval.");

        var localDescriptor = new ContextSourceDescriptor(
            "local-context-source",
            ContextCorpusKind.LocalUserText,
            "local-user-text-self-test",
            "user-private-local",
            PrivacyLocalOnly: true);
        localDescriptor.Validate();
        Require(localDescriptor.PrivacyLocalOnly,
            "Privacy-local source contract regressed while adding product-facing context policy.");

        Console.WriteLine("Context Practice product facade self-test PASS: synthetic fixtures fail closed by default, test-only opt-in is explicit, global homograph ambiguity survives narrow scopes, and coverage evidence remains provenance/release bounded.");
    }

    private static void ExpectSyntheticRejected(Action action)
    {
        bool rejected = false;
        try { action(); }
        catch (InvalidDataException ex) when (ex.Message.Contains("Synthetic context fixtures", StringComparison.OrdinalIgnoreCase))
        {
            rejected = true;
        }
        Require(rejected, "Product-facing context API accepted a synthetic fixture without explicit test-only opt-in.");
    }

    private static SentencePack BuildPack()
    {
        var sentence = new SentenceRecord
        {
            Id = "product-facade-sentence",
            English = "Alpha beta gamma.",
            Ukrainian = "Альфа бета гамма.",
            Source = "WordDeck synthetic product-facade self-test",
            License = "CC0-1.0",
            Tokens = SentenceTokenizer.Tokenize("Alpha beta gamma.").ToList(),
            Lemmas = SentenceTokenizer.Tokenize("Alpha beta gamma.").ToList(),
            TargetEntryIds = new List<string> { "target-a", "target-b", "target-c" },
            EntryLevels = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                ["target-a"] = "A1",
                ["target-b"] = "A1",
                ["target-c"] = "A1"
            },
            DifficultyLevel = "A1",
            OffListTokenCount = 0
        };
        var pack = new SentencePack
        {
            PackId = "context-product-facade-fixture",
            Provenance = "Synthetic product-facade self-test; never production release data",
            License = "CC0-1.0",
            Sentences = new List<SentenceRecord> { sentence }
        };
        pack.Validate();
        return pack;
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException("Context Practice product facade self-test failed: " + message);
    }
}