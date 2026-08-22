using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class ProductEngineR4SelfTest
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (!Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            return;
        Run();
    }

    internal static void Run()
    {
        TestPlatformNeutralLearningServices();
        TestFutureOptionalPortsStayOfflineByDefault();
        TestImageMetadataDoesNotLeakAnswers();
        TestAccessibleThemeContract();
        TestSentencePackTransactionalCompatibilityContract();
        Console.WriteLine("WordDeck R4 product-engine self-test passed: platform-neutral learning services, offline optional ports, image metadata safety, theme accessibility and SentencePack transaction compatibility validated.");
    }

    private static void TestPlatformNeutralLearningServices()
    {
        var spelling = new SpellingLearningApplicationService();
        SpellingCheckResult accepted = spelling.Check(new SpellingCheckRequest("student’s", "student's"));
        Require(accepted.Accepted, "Platform-neutral Spelling service lost technical apostrophe normalization.");
        Require(!spelling.Check(new SpellingCheckRequest("Student", "student")).Accepted,
            "Platform-neutral Spelling service accidentally made case insignificant.");

        var stats = new SpellingEntryStats
        {
            CompletedReviews = 4,
            FirstTrySuccesses = 4,
            CurrentStreak = 4,
            RecentOutcomes = new List<bool> { true, true, true, true }
        };
        CoachDecisionDto promote = spelling.EvaluateCoach(SpellingDeckIds.Core(2), stats, firstTryCorrect: true, usedHint: false);
        Require(promote.TargetDeckId == SpellingDeckIds.Core(3), "Platform-neutral Adaptive Coach did not preserve one-deck deterministic promotion.");
        CoachDecisionDto assisted = spelling.EvaluateCoach(SpellingDeckIds.Core(2), stats, firstTryCorrect: false, usedHint: true);
        Require(assisted.TargetDeckId == SpellingDeckIds.Core(1), "Platform-neutral Adaptive Coach did not preserve assisted one-deck demotion.");

        var sentence = new SentenceLearningApplicationService();
        SentenceAnswerResult sentenceResult = sentence.Check(new SentenceCheckRequest(
            "Very very well-known student's skills improve",
            "skills improve very student’s very well known"));
        Require(sentenceResult.Accepted && sentenceResult.WordOrderIgnored,
            "Platform-neutral Sentence service changed the exact normalized multiset contract.");
    }

    private static void TestFutureOptionalPortsStayOfflineByDefault()
    {
        ProductOptionalPorts ports = ProductOptionalPorts.Offline;
        Require(ports.Accounts.GetCurrentAsync().GetAwaiter().GetResult() is null,
            "Offline account adapter unexpectedly created an identity or network dependency.");
        Require(ports.Releases.GetLatestAsync().GetAwaiter().GetResult() is null,
            "Offline release adapter unexpectedly created a network dependency.");
        Require(ports.Images.GetForEntryAsync("oxford-3000-en-uk", "entry-1").GetAwaiter().GetResult() is null,
            "Offline image adapter unexpectedly returned remote content.");

        var telemetry = new ProductTelemetryEvent(
            PseudonymousInstallationId: "install-4a828b4f",
            SessionId: "session-a1",
            AppVersion: "0.2-candidate",
            StudyMode: "Spelling",
            EventName: "review-completed",
            DurationMilliseconds: 1200,
            AggregateCount: 1);
        ports.Telemetry.TrackAsync(telemetry).GetAwaiter().GetResult();

        bool rejected = false;
        try
        {
            ports.Telemetry.TrackAsync(telemetry with { PseudonymousInstallationId = "" }).GetAwaiter().GetResult();
        }
        catch (InvalidDataException) { rejected = true; }
        Require(rejected, "Telemetry contract accepted a blank pseudonymous installation id.");
    }

    private static void TestImageMetadataDoesNotLeakAnswers()
    {
        var safe = new WordImageMetadata(
            AssetId: "image-apple-001",
            Source: "future-provider:test-fixture",
            License: "test-only",
            Provenance: "Synthetic R4 image metadata fixture",
            AltText: "A round fruit on a table",
            HintText: "A common fruit",
            RevealPolicy: ImageRevealPolicy.HintOnly);
        safe.ValidateForEntry("apple");

        bool rejected = false;
        try
        {
            (safe with { AltText = "A red apple on a table" }).ValidateForEntry("apple");
        }
        catch (InvalidDataException) { rejected = true; }
        Require(rejected, "Pre-answer image metadata was allowed to reveal the English answer.");

        (safe with { AltText = "A red apple on a table", RevealPolicy = ImageRevealPolicy.AfterAnswer }).ValidateForEntry("apple");
    }

    private static void TestAccessibleThemeContract()
    {
        ProductThemeTokens.AccessibleDefault.Validate();
        bool rejected = false;
        try
        {
            (ProductThemeTokens.AccessibleDefault with { FocusOutlineThickness = 0 }).Validate();
        }
        catch (InvalidDataException) { rejected = true; }
        Require(rejected, "Theme contract accepted an invisible focus outline.");
    }

    private static void TestSentencePackTransactionalCompatibilityContract()
    {
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck R4 product tx Київ {Guid.NewGuid():N}");
        try
        {
            Directory.CreateDirectory(root);
            string baselineSource = Path.Combine(root, "baseline.json.gz");
            SentencePackIo.WriteGZip(baselineSource, BuildPack("product-r4-pack", "old-sentence", "old"));
            _ = new SentencePackStore(root).Import(baselineSource);

            string replacementSource = Path.Combine(root, "replacement.json.gz");
            SentencePackIo.WriteGZip(replacementSource, BuildPack("product-r4-pack", "new-sentence", "new"));

            string[] compatibilityCheckpoints =
            {
                "before-sqlite-build",
                "before-candidate-validation",
                "old-installation-backed-up",
                "portable-installed",
                "sqlite-installed",
                "before-manifest-commit"
            };

            foreach (string checkpoint in compatibilityCheckpoints)
            {
                bool injected = false;
                try
                {
                    _ = new SentencePackStore(root, reached =>
                    {
                        if (!string.Equals(reached, checkpoint, StringComparison.Ordinal)) return;
                        injected = true;
                        throw new IOException("Synthetic R4 interruption at " + checkpoint);
                    }).Import(replacementSource);
                }
                catch (IOException) { }

                Require(injected, $"SentencePack lifecycle no longer exposes compatibility checkpoint {checkpoint}.");
                InstalledSentencePack? current = new SentencePackStore(root).Find("product-r4-pack");
                Require(current is not null && current.Corpus.LookupByEntryId("target-old").Single().Id == "old-sentence",
                    $"SentencePack failure at {checkpoint} changed the last-known-good active generation.");
            }

            InstalledSentencePack committed = new SentencePackStore(root).Import(replacementSource);
            Require(committed.Corpus.LookupByEntryId("target-new").Single().Id == "new-sentence",
                "SentencePack valid replacement did not commit after the compatibility failure matrix.");
            new SentencePackStore(root).VerifyIntegrity("product-r4-pack");
        }
        finally
        {
            Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
            try { if (Directory.Exists(root)) Directory.Delete(root, true); } catch { }
        }
    }

    private static SentencePack BuildPack(string packId, string sentenceId, string suffix)
    {
        string english = $"we practice {suffix}";
        List<string> tokens = SentenceTokenizer.Tokenize(english).ToList();
        string target = "target-" + suffix;
        var pack = new SentencePack
        {
            PackId = packId,
            Provenance = "Synthetic R4 product-engine transaction fixture",
            License = "CC0-1.0",
            Sentences = new List<SentenceRecord>
            {
                new()
                {
                    Id = sentenceId,
                    English = english,
                    Ukrainian = "Ми тренуємося",
                    Source = "Synthetic R4 product-engine transaction fixture",
                    License = "CC0-1.0",
                    Tokens = tokens,
                    Lemmas = tokens.ToList(),
                    TargetEntryIds = new List<string> { target },
                    EntryLevels = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase) { [target] = "A1" },
                    DifficultyLevel = "A1"
                }
            }
        };
        pack.Validate();
        return pack;
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }
}
