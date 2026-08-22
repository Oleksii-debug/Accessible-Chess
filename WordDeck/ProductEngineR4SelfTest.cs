using System.Runtime.CompilerServices;
using System.Text.Json;

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
        TestUnifiedProfileApplicationBoundary();
        TestFutureOptionalPortsStayOfflineByDefault();
        TestImageMetadataDoesNotLeakAnswers();
        TestAccessibleThemeContract();
        TestSentencePackInstallTrustBoundary();
        Console.WriteLine("WordDeck R4 product-engine self-test passed: platform-neutral learning/profile services, offline optional ports, image/theme safety and bounded SentencePack installation validated.");
    }

    private static void TestPlatformNeutralLearningServices()
    {
        var spelling = new SpellingLearningApplicationService();
        Require(spelling.Check(new SpellingCheckRequest("student’s", "student's")).Accepted,
            "Platform-neutral Spelling service lost technical apostrophe normalization.");
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
        Require(promote.TargetDeckId == SpellingDeckIds.Core(3),
            "Platform-neutral Adaptive Coach did not preserve one-deck deterministic promotion.");
        CoachDecisionDto assisted = spelling.EvaluateCoach(SpellingDeckIds.Core(2), stats, firstTryCorrect: false, usedHint: true);
        Require(assisted.TargetDeckId == SpellingDeckIds.Core(1),
            "Platform-neutral Adaptive Coach did not preserve assisted one-deck demotion.");

        var sentence = new SentenceLearningApplicationService();
        SentenceAnswerResult sentenceResult = sentence.Check(new SentenceCheckRequest(
            "Very very well-known student's skills improve",
            "skills improve very student’s very well known"));
        Require(sentenceResult.Accepted && sentenceResult.WordOrderIgnored,
            "Platform-neutral Sentence service changed the exact normalized multiset contract.");
    }

    private static void TestUnifiedProfileApplicationBoundary()
    {
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck R4 profile app Київ {Guid.NewGuid():N}");
        try
        {
            Directory.CreateDirectory(root);
            const string dictionaryId = "oxford-3000-en-uk";
            var appStore = new AppStateStore(root);
            AppState state = AppStateStore.Normalize(new AppState { ActiveDictionaryId = dictionaryId });
            appStore.Save(state);

            var application = new UnifiedProfileApplicationService(new UnifiedProfileService(appStore, root));
            string profilePath = Path.Combine(root, "profile-r4.json");
            application.Export(new UnifiedProfileExportRequest(state, profilePath));
            Require(File.Exists(profilePath), "Platform-neutral profile use case did not create an export.");

            using JsonDocument profile = JsonDocument.Parse(File.ReadAllText(profilePath));
            Require(profile.RootElement.GetProperty(nameof(WordDeckUnifiedProfile.ProfileSchemaVersion)).GetInt32() == UnifiedProfileService.CurrentProfileSchemaVersion,
                "Platform-neutral profile use case did not preserve unified profile schema identity.");
        }
        finally
        {
            try { if (Directory.Exists(root)) Directory.Delete(root, true); } catch { }
        }
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

    private static void TestSentencePackInstallTrustBoundary()
    {
        SentencePack valid = BuildPack("product-r4-pack", "short provenance");
        SentencePackLicenseValidator.ValidateForInstallation(valid);

        SentencePack tooLarge = BuildPack(
            "product-r4-too-large",
            new string('x', SentencePackStructuralLimits.MaxProvenanceChars + 1));
        bool rejected = false;
        try { SentencePackLicenseValidator.ValidateForInstallation(tooLarge); }
        catch (InvalidDataException) { rejected = true; }
        Require(rejected, "SentencePack installation accepted an object graph beyond the structural provenance bound.");
    }

    private static SentencePack BuildPack(string packId, string provenance)
    {
        const string english = "we practice words";
        List<string> tokens = SentenceTokenizer.Tokenize(english).ToList();
        var pack = new SentencePack
        {
            PackId = packId,
            Provenance = provenance,
            License = "CC0-1.0",
            Sentences = new List<SentenceRecord>
            {
                new()
                {
                    Id = "sentence-1",
                    English = english,
                    Ukrainian = "Ми тренуємо слова",
                    Source = "Synthetic R4 product-engine fixture",
                    License = "CC0-1.0",
                    Tokens = tokens,
                    Lemmas = tokens.ToList(),
                    TargetEntryIds = new List<string> { "target-words" },
                    EntryLevels = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase) { ["target-words"] = "A1" },
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
