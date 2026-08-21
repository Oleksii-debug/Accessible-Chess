using System.Text.Json;

namespace WordDeck;

internal static class SpellingSelfTest
{
    public static void Run()
    {
        TestIndependentDeckState();
        TestScopeIndependentAssignmentsAndHiddenFilteringContract();
        TestDynamicSpellingDecksAndSafeTransfer();
        TestExactAnswerTechnicalNormalization();
        TestAdaptiveScheduler();
        TestSpellingPersistenceAndFailClosedRecovery();
        TestCombinedProfileRoundTripAndLegacyPreservation();
        TestSpellingShortcutRegistry();
    }

    private static void TestIndependentDeckState()
    {
        const string dictionaryId = "oxford-3000-en-uk";
        var recall = AppStateStore.Normalize(new AppState());
        var recallService = new DeckService(recall);
        Dictionary<string, string> recallMap = recallService.EnsureDictionaryAssignments(dictionaryId, new[] { "one", "two" });
        recallMap["one"] = DeckIds.Core(4);

        SpellingState spelling = SpellingStateStore.Normalize(new SpellingState());
        var spellingService = new SpellingDeckService(spelling);
        Dictionary<string, string> spellingMap = spellingService.EnsureAssignments(dictionaryId, StudyScopeIds.All, new[] { "one", "two" });
        spellingMap["one"] = SpellingDeckIds.Core(2);

        Require(recall.Decks.Count == 5 && spelling.Decks.Count == 5, "Recall and spelling must each own five independent core decks.");
        Require(recallMap["one"] == DeckIds.Core(4), "Creating spelling state changed a recall assignment.");
        Require(spellingMap["one"] == SpellingDeckIds.Core(2), "Spelling assignment was not independent from recall.");
        Require(recall.Decks.All(d => !d.Id.StartsWith("spelling-", StringComparison.OrdinalIgnoreCase)), "Spelling deck IDs leaked into recall state.");
    }

    private static void TestScopeIndependentAssignmentsAndHiddenFilteringContract()
    {
        const string dictionaryId = "dictionary-scope-test";
        SpellingState state = SpellingStateStore.Normalize(new SpellingState());
        var service = new SpellingDeckService(state);
        Dictionary<string, string> all = service.EnsureAssignments(dictionaryId, StudyScopeIds.All, new[] { "a1-word", "b2-word", "future-id" });
        Dictionary<string, string> a1 = service.EnsureAssignments(dictionaryId, StudyScopeIds.A1, new[] { "a1-word" });
        all["a1-word"] = SpellingDeckIds.Core(4);
        a1["a1-word"] = SpellingDeckIds.Core(2);

        Require(all["a1-word"] == SpellingDeckIds.Core(4) && a1["a1-word"] == SpellingDeckIds.Core(2),
            "Spelling scope deck assignments are not independent.");
        Require(!ReferenceEquals(all, a1), "All and A1 spelling scope maps unexpectedly share the same dictionary instance.");

        // Unknown stable IDs must remain inert/preserved rather than being silently
        // deleted merely because the current corpus view does not recognize them.
        all["unknown-future-entry"] = SpellingDeckIds.Core(3);
        service.EnsureAssignments(dictionaryId, StudyScopeIds.All, new[] { "a1-word", "b2-word" });
        Require(all.ContainsKey("unknown-future-entry"), "Spelling reconciliation silently discarded an unknown stable ID instead of preserving it for quarantine/migration.");

        var appState = AppStateStore.Normalize(new AppState());
        appState.HiddenEntryIds.Add("a1-word");
        Require(UserProgressService.IsHidden(appState, "a1-word"), "Shared hide overlay is unavailable to Spelling filtering.");
    }

    private static void TestDynamicSpellingDecksAndSafeTransfer()
    {
        const string dictionaryId = "dictionary-test";
        SpellingState state = SpellingStateStore.Normalize(new SpellingState());
        var service = new SpellingDeckService(state);
        DeckDefinition custom = service.Create("Hard words");
        Require(!custom.IsCore && custom.Id.StartsWith("spelling-user-", StringComparison.OrdinalIgnoreCase), "User spelling deck did not receive a stable spelling ID.");
        service.Rename(custom.Id, "Needs review");
        Require(service.Find(custom.Id)?.Name == "Needs review", "Spelling deck rename lost its stable ID.");

        Dictionary<string, string> all = service.EnsureAssignments(dictionaryId, StudyScopeIds.All, new[] { "a", "b" });
        Dictionary<string, string> b1 = service.EnsureAssignments(dictionaryId, StudyScopeIds.B1, new[] { "a" });
        all["a"] = custom.Id;
        b1["a"] = custom.Id;
        Require(service.CountEverywhere(custom.Id) == 2, "Cross-scope spelling deck count did not include both saved assignments.");

        bool unsafeDeleteRejected = false;
        try { service.DeleteUserDeck(custom.Id, null); } catch (InvalidOperationException) { unsafeDeleteRejected = true; }
        Require(unsafeDeleteRejected, "Non-empty spelling deck deletion was allowed without safe transfer.");
        service.DeleteUserDeck(custom.Id, SpellingDeckIds.Core(3));
        Require(service.Find(custom.Id) is null, "User spelling deck was not deleted after safe transfer.");
        Require(all["a"] == SpellingDeckIds.Core(3) && b1["a"] == SpellingDeckIds.Core(3),
            "Spelling word assignments were not transferred safely across every scope during deck deletion.");

        bool coreDeleteRejected = false;
        try { service.DeleteUserDeck(SpellingDeckIds.Core(1), SpellingDeckIds.Core(2)); } catch (InvalidOperationException) { coreDeleteRejected = true; }
        Require(coreDeleteRejected, "A permanent spelling core deck was deletable.");
    }

    private static void TestExactAnswerTechnicalNormalization()
    {
        Require(SpellingAnswerComparer.IsCorrect("  co-operate  ", "co-operate"), "Outer whitespace normalization failed.");
        Require(SpellingAnswerComparer.IsCorrect("O’Neill", "O'Neill"), "Deterministic apostrophe normalization failed.");
        Require(SpellingAnswerComparer.IsCorrect("well‑being", "well-being"), "Deterministic hyphen normalization failed.");
        Require(SpellingAnswerComparer.IsCorrect("cafe\u0301", "café"), "Canonical Unicode normalization failed.");
        Require(!SpellingAnswerComparer.IsCorrect("Co-operate", "co-operate"), "Spelling comparison incorrectly ignored English letter case.");
        Require(!SpellingAnswerComparer.IsCorrect("cooperate", "co-operate"), "Spelling comparison incorrectly ignored required punctuation.");
        Require(!SpellingAnswerComparer.IsCorrect("credit  card", "credit card"), "Spelling comparison incorrectly collapsed an internal extra space.");
    }

    private static void TestAdaptiveScheduler()
    {
        var scheduler = new ConservativeSpellingScheduler();
        var stats = new SpellingEntryStats
        {
            CompletedReviews = 3,
            FirstTrySuccesses = 3,
            CurrentStreak = 3,
            RecentOutcomes = new List<bool> { true, true, true }
        };
        SpellingScheduleDecision promote = scheduler.Decide(SpellingDeckIds.Core(2), stats, firstTryCorrect: true, usedHint: false);
        Require(promote.TargetDeckId == SpellingDeckIds.Core(3), "Statistically clean spelling history did not move one core spelling deck later.");
        Require(promote.Explanation.Contains("lifetime", StringComparison.OrdinalIgnoreCase) && promote.Explanation.Contains("recent", StringComparison.OrdinalIgnoreCase),
            "Adaptive promotion did not explain its statistical evidence.");

        SpellingScheduleDecision repeat = scheduler.Decide(SpellingDeckIds.Core(2), stats, firstTryCorrect: true, usedHint: false);
        Require(promote == repeat, "Adaptive scheduler is not deterministic for identical state and review input.");

        SpellingScheduleDecision demote = scheduler.Decide(SpellingDeckIds.Core(4), stats, firstTryCorrect: false, usedHint: false);
        Require(demote.TargetDeckId == SpellingDeckIds.Core(3), "A failed first try did not move one core deck earlier.");

        SpellingScheduleDecision hinted = scheduler.Decide(SpellingDeckIds.Core(3), stats, firstTryCorrect: false, usedHint: true);
        Require(hinted.TargetDeckId == SpellingDeckIds.Core(2), "Hint use was not treated conservatively by the spelling coach.");

        SpellingScheduleDecision earliestHold = scheduler.Decide(SpellingDeckIds.Core(1), stats, firstTryCorrect: false, usedHint: true);
        Require(earliestHold.TargetDeckId is null && earliestHold.Explanation.Contains("earliest", StringComparison.OrdinalIgnoreCase),
            "Coach did not explain why a difficult word was held in the earliest core deck.");

        SpellingScheduleDecision userDeck = scheduler.Decide("spelling-user-test", stats, firstTryCorrect: false, usedHint: true);
        Require(userDeck.TargetDeckId is null, "Adaptive coach attempted to redistribute a user-created spelling deck.");

        stats.CompletedReviews = 4;
        stats.FirstTrySuccesses = 2;
        stats.CurrentStreak = 2;
        stats.RecentOutcomes = new List<bool> { true, false, true, false };
        SpellingScheduleDecision statisticalHold = scheduler.Decide(SpellingDeckIds.Core(2), stats, firstTryCorrect: true, usedHint: false);
        Require(statisticalHold.TargetDeckId is null, "Adaptive coach promoted a word below deterministic statistical thresholds.");
        Require(statisticalHold.Explanation.Contains("75%", StringComparison.Ordinal), "Adaptive hold did not expose the stable promotion threshold.");
    }

    private static void TestSpellingPersistenceAndFailClosedRecovery()
    {
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck-spelling-self-test-{Guid.NewGuid():N}");
        try
        {
            var store = new SpellingStateStore(root);
            SpellingState state = store.Load();
            var service = new SpellingDeckService(state);
            service.Rename(SpellingDeckIds.Core(1), "Spelling inbox");
            DeckDefinition custom = service.Create("Persistent spelling");
            state.ActiveDeckId = custom.Id;
            state.ActiveScopeIdByDictionary["d"] = StudyScopeIds.B2;
            state.CoachEnabled = false;
            state.CurrentEntryIdsByDictionaryScope["d"] = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                [StudyScopeIds.All] = "entry-1",
                [StudyScopeIds.B2] = "entry-2"
            };
            Dictionary<string, string> all = service.EnsureAssignments("d", StudyScopeIds.All, new[] { "entry-1", "entry-2" });
            Dictionary<string, string> b2 = service.EnsureAssignments("d", StudyScopeIds.B2, new[] { "entry-2" });
            all["entry-1"] = custom.Id;
            b2["entry-2"] = SpellingDeckIds.Core(4);
            state.StatsByDictionary["d"] = new Dictionary<string, SpellingEntryStats>(StringComparer.OrdinalIgnoreCase)
            {
                ["entry-1"] = new SpellingEntryStats
                {
                    CompletedReviews = 4,
                    FirstTrySuccesses = 2,
                    WrongAttempts = 3,
                    HintUses = 1,
                    ShowAnswerUses = 1,
                    CurrentStreak = 1,
                    RecentOutcomes = new List<bool> { false, true, false, true },
                    LastReviewedUtc = DateTimeOffset.UtcNow
                }
            };
            store.Save(state);

            SpellingState loaded = new SpellingStateStore(root).Load();
            Require(loaded.SchemaVersion == SpellingStateStore.CurrentSchemaVersion, "Spelling state schema version was not persisted.");
            Require(loaded.ActiveDeckId == custom.Id, "Active spelling deck did not survive restart.");
            Require(loaded.ActiveScopeIdByDictionary["d"] == StudyScopeIds.B2, "Active spelling scope did not survive restart.");
            Require(!loaded.CoachEnabled, "Adaptive spelling coach setting did not survive restart.");
            Require(loaded.CurrentEntryIdsByDictionaryScope["d"][StudyScopeIds.B2] == "entry-2", "Scope-specific current spelling card did not survive restart.");
            Require(loaded.DeckIdsByDictionaryScope["d"][StudyScopeIds.All]["entry-1"] == custom.Id, "All-scope spelling assignment did not survive restart.");
            Require(loaded.DeckIdsByDictionaryScope["d"][StudyScopeIds.B2]["entry-2"] == SpellingDeckIds.Core(4), "B2 spelling assignment did not survive restart.");
            SpellingEntryStats restoredStats = loaded.StatsByDictionary["d"]["entry-1"];
            Require(restoredStats.CompletedReviews == 4 && restoredStats.FirstTrySuccesses == 2 && restoredStats.WrongAttempts == 3 && restoredStats.HintUses == 1 && restoredStats.ShowAnswerUses == 1,
                "Spelling review statistics did not survive restart.");

            // A corrupted primary must fall back to a verified previous backup.
            store.Save(loaded);
            File.WriteAllText(Path.Combine(root, "spelling-state.json"), "{ definitely broken json");
            SpellingState recovered = new SpellingStateStore(root).Load();
            Require(recovered.Decks.Count >= 5, "Spelling recovery backup was not used after primary corruption.");

            File.WriteAllText(Path.Combine(root, "spelling-state.backup.json"), "broken too");
            bool corruptRejected = false;
            try { _ = new SpellingStateStore(root).Load(); } catch (InvalidDataException) { corruptRejected = true; }
            Require(corruptRejected, "Spelling state silently reset after both primary and backup became unreadable.");
        }
        finally
        {
            try { if (Directory.Exists(root)) Directory.Delete(root, true); } catch { }
        }
    }

    private static void TestCombinedProfileRoundTripAndLegacyPreservation()
    {
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck-spelling-profile-self-test-{Guid.NewGuid():N}");
        try
        {
            Directory.CreateDirectory(root);
            var appStore = new AppStateStore(root);
            var spellingStore = new SpellingStateStore(root);
            var service = new SpellingProfileService(appStore, spellingStore);
            AppState app = AppStateStore.Normalize(new AppState { ActiveDictionaryId = "d" });
            app.HiddenEntryIds.Add("entry-1");
            appStore.Save(app);

            SpellingState spelling = SpellingStateStore.Normalize(new SpellingState());
            var decks = new SpellingDeckService(spelling);
            DeckDefinition custom = decks.Create("Transfer me");
            Dictionary<string, string> a1 = decks.EnsureAssignments("d", StudyScopeIds.A1, new[] { "entry-1" });
            a1["entry-1"] = custom.Id;
            spelling.ActiveScopeIdByDictionary["d"] = StudyScopeIds.A1;
            spelling.StatsByDictionary["d"] = new Dictionary<string, SpellingEntryStats>(StringComparer.OrdinalIgnoreCase)
            {
                ["entry-1"] = new SpellingEntryStats { CompletedReviews = 5, FirstTrySuccesses = 4, CurrentStreak = 2, RecentOutcomes = new List<bool> { true, true, false, true, true } }
            };
            spellingStore.Save(spelling);

            string combinedPath = Path.Combine(root, "profile-v2.json");
            service.Export(app, spelling, combinedPath);

            app.HiddenEntryIds.Clear();
            a1["entry-1"] = SpellingDeckIds.Core(1);
            spelling.StatsByDictionary.Clear();
            appStore.Save(app);
            spellingStore.Save(spelling);

            CombinedProfileImportResult imported = service.Import(combinedPath, app, spelling, new[] { "entry-1" }, new[] { "d" });
            Require(imported.SpellingImported && !imported.LegacyProfile, "Combined profile did not report Spelling restoration.");
            Require(app.HiddenEntryIds.Contains("entry-1"), "Recall overlay did not round-trip through combined profile.");
            Require(spelling.DeckIdsByDictionaryScope["d"][StudyScopeIds.A1]["entry-1"] == custom.Id, "Spelling scope assignment did not round-trip through combined profile.");
            Require(spelling.StatsByDictionary["d"]["entry-1"].CompletedReviews == 5, "Spelling statistics did not round-trip through combined profile.");
            Require(File.Exists(imported.RecallBackupPath) && imported.SpellingBackupPath is not null && File.Exists(imported.SpellingBackupPath),
                "Combined profile import did not create both pre-import recovery artifacts.");

            string legacyPath = Path.Combine(root, "profile-v1.json");
            appStore.ExportProfile(app, legacyPath);
            spelling.DeckIdsByDictionaryScope["d"][StudyScopeIds.A1]["entry-1"] = SpellingDeckIds.Core(5);
            spellingStore.Save(spelling);
            CombinedProfileImportResult legacy = service.Import(legacyPath, app, spelling, new[] { "entry-1" }, new[] { "d" });
            Require(legacy.LegacyProfile && !legacy.SpellingImported, "Legacy V0.1 profile was not recognized as Recall-only.");
            Require(spelling.DeckIdsByDictionaryScope["d"][StudyScopeIds.A1]["entry-1"] == SpellingDeckIds.Core(5),
                "Importing a legacy V0.1 profile erased current Spelling progress.");

            string invalidPath = Path.Combine(root, "profile-invalid.json");
            File.WriteAllText(invalidPath, JsonSerializer.Serialize(new { ProfileSchemaVersion = 999 }));
            string beforeDeck = spelling.DeckIdsByDictionaryScope["d"][StudyScopeIds.A1]["entry-1"];
            bool invalidRejected = false;
            try { service.Import(invalidPath, app, spelling, new[] { "entry-1" }, new[] { "d" }); } catch (InvalidDataException) { invalidRejected = true; }
            Require(invalidRejected && spelling.DeckIdsByDictionaryScope["d"][StudyScopeIds.A1]["entry-1"] == beforeDeck,
                "Invalid profile changed Spelling state instead of failing closed.");
        }
        finally
        {
            try { if (Directory.Exists(root)) Directory.Delete(root, true); } catch { }
        }
    }

    private static void TestSpellingShortcutRegistry()
    {
        AppState app = AppStateStore.Normalize(new AppState());
        SpellingState spelling = SpellingStateStore.Normalize(new SpellingState());
        var manager = new ShortcutManager(app, spelling.Decks);
        Require(manager.Definitions.Any(d => d.Id == ActionIds.OpenSpelling), "Open Spelling is missing from the configurable shortcut registry.");
        Require(manager.Definitions.Any(d => d.Id == ActionIds.SpellingShowAnswer), "Show spelling answer is missing from the configurable shortcut registry.");
        Require(manager.Definitions.Any(d => d.Id == ActionIds.SpellingSwitchDeck(SpellingDeckIds.Core(5))), "Core spelling deck switch shortcut is missing.");
        Require(manager.Definitions.Any(d => d.Id == ActionIds.SpellingMoveToDeck(SpellingDeckIds.Core(5))), "Core spelling move shortcut is missing.");
        Require(manager.Get(ActionIds.SpellingDeleteDeck) == (Keys.Control | Keys.Shift | Keys.Delete),
            "Spelling deck deletion default must be capturable by WordDeck and must not use Windows Ctrl+Alt+Delete.");
        Require(!manager.TrySet(ActionIds.SpellingDeleteDeck, Keys.Control | Keys.Alt | Keys.Delete, out string? secureAttentionError) &&
                !string.IsNullOrWhiteSpace(secureAttentionError),
            "Windows Ctrl+Alt+Delete secure-attention sequence was incorrectly accepted as a WordDeck shortcut.");

        Keys replacement = Keys.Control | Keys.Alt | Keys.Shift | Keys.F11;
        Require(manager.TrySet(ActionIds.SpellingShowAnswer, replacement, out string? error), $"Spelling shortcut could not be rebound: {error}");
        Require(manager.Get(ActionIds.SpellingShowAnswer) == replacement && manager.FindAction(replacement) == ActionIds.SpellingShowAnswer,
            "Rebound spelling shortcut did not dispatch through the shared shortcut manager.");
        Require(!manager.TrySet(ActionIds.SpellingRepeatPrompt, replacement, out string? conflict) && !string.IsNullOrWhiteSpace(conflict),
            "Conflict checking did not reject a duplicate spelling shortcut.");

        var deckService = new SpellingDeckService(spelling);
        DeckDefinition custom = deckService.Create("Shortcut deck");
        manager.RefreshDeckDefinitions(spelling.Decks);
        Require(manager.Definitions.Any(d => d.Id == ActionIds.SpellingSwitchDeck(custom.Id)), "User-created spelling deck did not gain a stable switch action.");
        Require(manager.Get(ActionIds.SpellingSwitchDeck(custom.Id)) == Keys.None, "User-created spelling deck switch shortcut should start unassigned.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }
}
