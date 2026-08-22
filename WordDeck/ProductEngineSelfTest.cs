using System.Diagnostics;
using System.Reflection;
using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class ProductEngineSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            ProductEngineSelfTest.Run();
    }
}

internal static class ProductEngineSelfTest
{
    public static void Run()
    {
        TestPlatformNeutralContractSurface();
        TestSpellingApplicationSemantics();
        TestCoachApplicationSemantics();
        TestSentenceApplicationSemantics();
        TestOptionalImageAndThemeContracts();
        TestSentencePackReleaseDescriptor();
        TestOfflineOptionalPorts();
        TestCompleteCorpusDtoProjection();
        TestBoundedApplicationStress();
        Console.WriteLine("WordDeck R4b Product Engine passed: platform-neutral DTO/use-case boundary, blank-submit safety contract, deterministic Coach, Sentence multiset evaluation, image/theme/release metadata safety, offline optional ports, 5446 stable-ID projection and bounded stress verified.");
    }

    private static void TestPlatformNeutralContractSurface()
    {
        Type[] contractTypes =
        {
            typeof(LearningCardDto),
            typeof(SpellingCheckRequest),
            typeof(SpellingCheckResult),
            typeof(CoachHistoryDto),
            typeof(CoachDecisionDto),
            typeof(SentenceCheckRequest),
            typeof(SentenceCheckResultDto),
            typeof(ISpellingLearningUseCases),
            typeof(ISentenceLearningUseCases),
            typeof(IProfileTransferPort),
            typeof(IAccountIdentityPort),
            typeof(ITelemetryPort),
            typeof(IReleaseMetadataPort),
            typeof(IWordImageProvider)
        };

        foreach (Type type in contractTypes)
        {
            Require(!ReferencesWindowsForms(type), $"Product contract {type.Name} directly references Windows Forms.");
            foreach (PropertyInfo property in type.GetProperties(BindingFlags.Public | BindingFlags.Instance))
                Require(!ReferencesWindowsForms(property.PropertyType), $"Product contract {type.Name}.{property.Name} leaks Windows Forms type {property.PropertyType}.");
            foreach (MethodInfo method in type.GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.DeclaredOnly))
            {
                Require(!ReferencesWindowsForms(method.ReturnType), $"Product use-case {type.Name}.{method.Name} return type leaks Windows Forms.");
                foreach (ParameterInfo parameter in method.GetParameters())
                    Require(!ReferencesWindowsForms(parameter.ParameterType), $"Product use-case {type.Name}.{method.Name} parameter {parameter.Name} leaks Windows Forms.");
            }
        }
    }

    private static bool ReferencesWindowsForms(Type type)
    {
        if ((type.FullName ?? string.Empty).StartsWith("System.Windows.Forms.", StringComparison.Ordinal))
            return true;
        if (type.IsArray)
            return ReferencesWindowsForms(type.GetElementType()!);
        if (type.IsGenericType)
            return type.GetGenericArguments().Any(ReferencesWindowsForms);
        return false;
    }

    private static void TestSpellingApplicationSemantics()
    {
        var service = new SpellingLearningApplicationService();

        SpellingCheckResult blank = service.Check(new SpellingCheckRequest("   ", "word"));
        Require(blank.EmptySubmission && !blank.Accepted, "Blank Spelling submit was not classified as a non-learning submission.");
        Require(blank.Feedback.Contains("must not count", StringComparison.OrdinalIgnoreCase), "Blank Spelling feedback does not explain its statistics-safe behavior.");

        Require(service.Check(new SpellingCheckRequest(" café ", "café")).Accepted, "Outer trim/NFC exact match failed through application service.");
        Require(service.Check(new SpellingCheckRequest("don’t", "don't")).Accepted, "Supported apostrophe normalization failed through application service.");
        Require(service.Check(new SpellingCheckRequest("state‑of‑the‑art", "state-of-the-art")).Accepted, "Supported hyphen normalization failed through application service.");
        Require(!service.Check(new SpellingCheckRequest("Word", "word")).Accepted, "Application layer incorrectly made Spelling case-insensitive.");
        Require(!service.Check(new SpellingCheckRequest("two  words", "two words")).Accepted, "Application layer incorrectly collapsed significant internal spacing.");
        Require(!service.Check(new SpellingCheckRequest("word!", "word")).Accepted, "Application layer incorrectly ignored punctuation.");
    }

    private static void TestCoachApplicationSemantics()
    {
        var service = new SpellingLearningApplicationService();
        var strong = new CoachHistoryDto(
            CompletedReviews: 4,
            FirstTrySuccesses: 4,
            WrongAttempts: 0,
            HintUses: 0,
            ShowAnswerUses: 0,
            CurrentStreak: 4,
            RecentOutcomes: new[] { true, true, true, true });

        CoachDecisionDto first = service.EvaluateCoach(SpellingDeckIds.Core(2), strong, firstTryCorrect: true, usedHint: false);
        Require(first.TargetDeckId == SpellingDeckIds.Core(3), "Strong deterministic Coach history did not promote exactly one core deck.");
        for (int i = 0; i < 500; i++)
        {
            CoachDecisionDto repeat = service.EvaluateCoach(SpellingDeckIds.Core(2), strong, true, false);
            Require(repeat == first, "Identical Coach application input produced a different decision.");
        }

        var assisted = strong with { WrongAttempts = 1, CurrentStreak = 0, HintUses = 1, RecentOutcomes = new[] { true, true, true, false } };
        CoachDecisionDto demotion = service.EvaluateCoach(SpellingDeckIds.Core(3), assisted, firstTryCorrect: false, usedHint: true);
        Require(demotion.TargetDeckId == SpellingDeckIds.Core(2), "Assisted/wrong Coach path did not move exactly one core deck earlier.");

        CoachDecisionDto userDeck = service.EvaluateCoach("spelling-user-test", strong, true, false);
        Require(userDeck.TargetDeckId is null && userDeck.Explanation.Contains("user-created", StringComparison.OrdinalIgnoreCase), "Coach application service attempted automatic movement in a custom deck.");

        ExpectInvalid(() => service.EvaluateCoach(SpellingDeckIds.Core(1), strong with { FirstTrySuccesses = 9 }, true, false), "invalid Coach statistics");
        ExpectInvalid(() => service.EvaluateCoach(SpellingDeckIds.Core(1), strong with { RecentOutcomes = Enumerable.Repeat(true, 11).ToArray() }, true, false), "oversized Coach recent history");
    }

    private static void TestSentenceApplicationSemantics()
    {
        var service = new SentenceLearningApplicationService();

        SentenceCheckResultDto blank = service.Check(new SentenceCheckRequest("I really really care", "   "));
        Require(!blank.Accepted && blank.Feedback.Contains("must not count", StringComparison.OrdinalIgnoreCase), "Blank Sentence submit is not statistics-safe at the application boundary.");

        SentenceCheckResultDto reordered = service.Check(new SentenceCheckRequest("I really really care", "care really I really"));
        Require(reordered.Accepted && reordered.WordOrderIgnored, "Sentence application layer lost approved multiset/word-order semantics.");

        SentenceCheckResultDto missingDuplicate = service.Check(new SentenceCheckRequest("I really really care", "I really care"));
        Require(!missingDuplicate.Accepted && missingDuplicate.Missing.Count == 1 && missingDuplicate.Missing[0] == "really", "Sentence duplicate-token requirement was not preserved individually.");

        SentenceCheckResultDto wrongForm = service.Check(new SentenceCheckRequest("she walks home", "she walk home"));
        Require(!wrongForm.Accepted && wrongForm.Missing.Contains("walks") && wrongForm.Extra.Contains("walk"), "Sentence application layer accepted a wrong word form semantically.");
    }

    private static void TestOptionalImageAndThemeContracts()
    {
        var safe = new WordImageMetadata(
            "asset-1",
            "local://images/asset-1.webp",
            "CC0-1.0",
            "curated local clue set",
            "A small animal sitting beside a window.",
            "Think of a common household pet.",
            ImageRevealPolicy.HintOnly);
        safe.ValidateForEntry("cat");

        var leaking = safe with { AltText = "A cat sitting beside a window." };
        ExpectInvalid(() => leaking.ValidateForEntry("cat"), "pre-answer image answer disclosure");

        var afterAnswer = leaking with { RevealPolicy = ImageRevealPolicy.AfterAnswer };
        afterAnswer.ValidateForEntry("cat");

        ProductThemeTokens.AccessibleDefault.Validate();
        ExpectInvalid(() => (ProductThemeTokens.AccessibleDefault with { FocusOutlineThickness = 0 }).Validate(), "invisible focus token");
        ExpectInvalid(() => (ProductThemeTokens.AccessibleDefault with { HighContrastCompatible = false }).Validate(), "high-contrast-incompatible theme");
    }

    private static void TestSentencePackReleaseDescriptor()
    {
        var real = new SentencePackProductDescriptor(
            "tatoeba-en-uk-verified",
            "Tatoeba EN-UA export with retained sentence identifiers and attribution manifest",
            "CC BY 2.0 FR",
            1000,
            "sha256:source",
            "sha256:sqlite",
            IsSynthetic: false);
        real.ValidateForRelease();

        ExpectInvalid(() => (real with { IsSynthetic = true }).ValidateForRelease(), "synthetic release corpus");
        ExpectInvalid(() => (real with { SourceIdentity = " " }).ValidateForRelease(), "missing source identity");
        ExpectInvalid(() => (real with { SentenceCount = 0 }).ValidateForRelease(), "empty release corpus");
    }

    private static void TestOfflineOptionalPorts()
    {
        ProductOptionalPorts ports = ProductOptionalPorts.Offline;
        Require(ports.Accounts.GetCurrentAsync().AsTask().GetAwaiter().GetResult() is null, "Offline account port unexpectedly produced a live identity.");
        Require(ports.Releases.GetLatestAsync().AsTask().GetAwaiter().GetResult() is null, "Offline release port unexpectedly contacted/returned a live source.");
        Require(ports.Images.GetForEntryAsync("oxford-3000-en-uk", "entry-1").AsTask().GetAwaiter().GetResult() is null, "Offline image port unexpectedly produced a network-backed image.");

        var evt = new ProductTelemetryEvent("install-opaque-1", "session-opaque-1", "0.2", "Spelling", "review-completed", 1200, 1);
        ports.Telemetry.TrackAsync(evt).AsTask().GetAwaiter().GetResult();
        ExpectInvalid(() => ports.Telemetry.TrackAsync(evt with { EventName = "bad\nname" }).AsTask().GetAwaiter().GetResult(), "telemetry control separator");

        using var cancelled = new CancellationTokenSource();
        cancelled.Cancel();
        bool cancellationObserved = false;
        try { ports.Accounts.GetCurrentAsync(cancelled.Token).AsTask().GetAwaiter().GetResult(); }
        catch (OperationCanceledException) { cancellationObserved = true; }
        Require(cancellationObserved, "Offline optional port ignored cancellation.");
    }

    private static void TestCompleteCorpusDtoProjection()
    {
        DictionaryPackage package = DictionaryLoader.LoadEmbeddedOxford();
        Require(package.Entries.Count == 5446, $"Product DTO projection expected 5446 canonical entries, got {package.Entries.Count}.");
        var ids = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (DictionaryEntry entry in package.Entries)
        {
            Require(ids.Add(entry.Id), $"Product DTO projection found duplicate stable id {entry.Id}.");
            var dto = new LearningCardDto(package.Id, entry.Id, StudyScopeIds.All, SpellingDeckIds.Core(1), entry.Source, entry.Target, false);
            Require(dto.EntryId == entry.Id && dto.English == entry.Source && dto.Ukrainian == entry.Target, "Product DTO projection changed lexical identity/content.");
        }
    }

    private static void TestBoundedApplicationStress()
    {
        var spelling = new SpellingLearningApplicationService();
        var coachHistory = new CoachHistoryDto(10, 9, 1, 1, 0, 5, new[] { true, true, true, true, false, true, true, true, true, true });
        var sentence = new SentenceLearningApplicationService();
        var stopwatch = Stopwatch.StartNew();
        for (int i = 0; i < 10_000; i++)
        {
            Require(spelling.Check(new SpellingCheckRequest("don’t", "don't")).Accepted, "Spelling application stress became nondeterministic.");
            CoachDecisionDto decision = spelling.EvaluateCoach(SpellingDeckIds.Core(3), coachHistory, true, false);
            Require(decision.TargetDeckId == SpellingDeckIds.Core(4), "Coach application stress changed a deterministic threshold result.");
            Require(sentence.Check(new SentenceCheckRequest("we learn words", "words we learn")).Accepted, "Sentence application stress became nondeterministic.");
        }
        stopwatch.Stop();
        Console.WriteLine($"R4b Product Engine stress: 10,000 Spelling+Coach+Sentence application cycles completed in {stopwatch.ElapsedMilliseconds} ms.");
    }

    private static void ExpectInvalid(Action action, string description)
    {
        bool rejected = false;
        try { action(); }
        catch (InvalidDataException) { rejected = true; }
        Require(rejected, $"Product Engine did not reject {description}.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
}
