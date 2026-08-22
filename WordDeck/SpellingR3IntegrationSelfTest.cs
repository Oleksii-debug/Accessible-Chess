using System.Runtime.CompilerServices;
using System.Text.Json;

namespace WordDeck;

internal static class SpellingR3IntegrationSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (!Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            return;
        SpellingR3IntegrationSelfTest.Run();
    }
}

internal static class SpellingR3IntegrationSelfTest
{
    public static void Run()
    {
        TestSelectionContractIsExplicitlyRandomSessionBased();
        TestCurrentCardPersistsAcrossRestartWithoutInventedShuffleState();
        TestCoachThresholdBoundariesAndHysteresis();
        TestCanonicalRecallFocusPolicyRemainsIntact();
        TestCombinedProfileRejectsIncompatibleCorpusBeforeMutation();
        Console.WriteLine("WordDeck R3 Spelling integration passed: explicit random-session next-card contract, current-card persistence, Coach threshold boundaries, canonical Recall focus policy and incompatible-profile fail-closed behavior verified.");
    }

    private static void TestSelectionContractIsExplicitlyRandomSessionBased()
    {
        string[] persistedPropertyNames = typeof(SpellingState).GetProperties()
            .Select(property => property.Name)
            .ToArray();
        Require(!persistedPropertyNames.Any(name => name.Contains("Shuffle", StringComparison.OrdinalIgnoreCase)),
            "Spelling unexpectedly acquired a persisted shuffle-bag contract. If product policy changes, update the explicit Stage-6 contract and migration tests together.");
        Require(persistedPropertyNames.Contains(nameof(SpellingState.CurrentEntryIdsByDictionaryScope), StringComparer.Ordinal),
            "Spelling no longer persists current cards per dictionary/scope.");
    }

    private static void TestCurrentCardPersistsAcrossRestartWithoutInventedShuffleState()
    {
        string root = Path.Combine(Path.GetTempPath(), "WordDeck-r3-spelling-current-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var store = new SpellingStateStore(root);
            SpellingState state = SpellingStateStore.Normalize(new SpellingState());
            var decks = new SpellingDeckService(state);
            Dictionary<string, string> a1 = decks.EnsureAssignments("dictionary", StudyScopeIds.A1, new[] { "entry-a", "entry-b" });
            a1["entry-a"] = SpellingDeckIds.Core(3);
            state.ActiveScopeIdByDictionary["dictionary"] = StudyScopeIds.A1;
            state.ActiveDeckId = SpellingDeckIds.Core(3);
            state.CurrentEntryIdsByDictionaryScope["dictionary"] = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                [StudyScopeIds.A1] = "entry-a"
            };
            store.Save(state);

            SpellingState loaded = store.Load();
            Require(loaded.ActiveScopeIdByDictionary["dictionary"] == StudyScopeIds.A1, "Spelling active scope did not survive restart.");
            Require(loaded.ActiveDeckId == SpellingDeckIds.Core(3), "Spelling active deck did not survive restart.");
            Require(loaded.CurrentEntryIdsByDictionaryScope["dictionary"][StudyScopeIds.A1] == "entry-a", "Spelling current card did not survive restart.");
            string json = JsonSerializer.Serialize(loaded);
            Require(!json.Contains("shuffle", StringComparison.OrdinalIgnoreCase), "Spelling state serialized an undocumented shuffle-sequence contract.");
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    private static void TestCoachThresholdBoundariesAndHysteresis()
    {
        var coach = new ConservativeSpellingScheduler();
        var below = new SpellingEntryStats
        {
            CompletedReviews = 3,
            FirstTrySuccesses = 2,
            CurrentStreak = 3,
            RecentOutcomes = new List<bool> { true, true, false }
        };
        SpellingScheduleDecision hold = coach.Decide(SpellingDeckIds.Core(3), below, firstTryCorrect: true, usedHint: false);
        Require(hold.TargetDeckId is null, "Coach promoted below the lifetime/recent clean-rate thresholds.");

        var ready = new SpellingEntryStats
        {
            CompletedReviews = 4,
            FirstTrySuccesses = 4,
            CurrentStreak = 4,
            RecentOutcomes = new List<bool> { true, true, true, true }
        };
        SpellingScheduleDecision promote1 = coach.Decide(SpellingDeckIds.Core(3), ready, firstTryCorrect: true, usedHint: false);
        SpellingScheduleDecision promote2 = coach.Decide(SpellingDeckIds.Core(3), ready, firstTryCorrect: true, usedHint: false);
        Require(promote1 == promote2, "Identical Coach state produced different decisions.");
        Require(promote1.TargetDeckId == SpellingDeckIds.Core(4), "Coach did not promote one core deck after crossing all thresholds.");

        SpellingScheduleDecision assisted = coach.Decide(SpellingDeckIds.Core(4), ready, firstTryCorrect: true, usedHint: true);
        Require(assisted.TargetDeckId == SpellingDeckIds.Core(3), "Hint-assisted review did not conservatively move one core deck earlier.");
        SpellingScheduleDecision userDeck = coach.Decide("spelling-user-test", ready, firstTryCorrect: true, usedHint: false);
        Require(userDeck.TargetDeckId is null, "Coach attempted to redistribute a user-created spelling deck.");
    }

    private static void TestCanonicalRecallFocusPolicyRemainsIntact()
    {
        Require(RecallKeyboardFocusPolicy.IsFastCardArrow(Keys.Down, englishWordSurfaceFocused: true),
            "Canonical English-word Down-arrow fast Recall behavior was lost.");
        Require(!RecallKeyboardFocusPolicy.IsFastCardArrow(Keys.Down, englishWordSurfaceFocused: false),
            "Unfocused/translation Down-arrow was incorrectly treated as fast Recall navigation.");
        Require(!RecallKeyboardFocusPolicy.IsFastCardArrow(Keys.Control | Keys.Down, englishWordSurfaceFocused: true),
            "Modified arrow was incorrectly treated as native fast Recall navigation.");
        Require(!RecallKeyboardFocusPolicy.ShouldFocusCardAfterSelectorChange(selectorContainsFocus: true),
            "Canonical selector focus-retention policy regressed.");
    }

    private static void TestCombinedProfileRejectsIncompatibleCorpusBeforeMutation()
    {
        string root = Path.Combine(Path.GetTempPath(), "WordDeck-r3-profile-mismatch-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            var appStore = new AppStateStore(root);
            var spellingStore = new SpellingStateStore(root);
            AppState app = AppStateStore.Normalize(new AppState { ActiveDictionaryId = "dictionary" });
            SpellingState spelling = SpellingStateStore.Normalize(new SpellingState());
            var spellingDecks = new SpellingDeckService(spelling);
            Dictionary<string, string> map = spellingDecks.EnsureAssignments("dictionary", StudyScopeIds.All, new[] { "entry" });
            map["entry"] = SpellingDeckIds.Core(4);
            appStore.Save(app);
            spellingStore.Save(spelling);

            var profile = new WordDeckCombinedProfile
            {
                ProfileSchemaVersion = SpellingProfileService.CurrentProfileSchemaVersion,
                StateSchemaVersion = AppStateStore.CurrentSchemaVersion,
                SpellingSchemaVersion = SpellingStateStore.CurrentSchemaVersion,
                SourceAppVersion = AppStateStore.SourceAppVersion,
                CorpusIdentity = "not-the-worddeck-corpus",
                ExportedAtUtc = DateTimeOffset.UtcNow,
                State = AppStateStore.Normalize(new AppState { ActiveDictionaryId = "dictionary" }),
                SpellingState = SpellingStateStore.Clone(spelling)
            };
            string path = Path.Combine(root, "bad-profile.json");
            File.WriteAllText(path, JsonSerializer.Serialize(profile));

            bool rejected = false;
            try
            {
                new SpellingProfileService(appStore, spellingStore).Import(path, app, spelling, new[] { "entry" }, new[] { "dictionary" });
            }
            catch (InvalidDataException)
            {
                rejected = true;
            }
            Require(rejected, "R3 combined profile accepted an incompatible corpus.");
            Require(map["entry"] == SpellingDeckIds.Core(4), "Rejected incompatible profile mutated live Spelling assignment state.");
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
}
