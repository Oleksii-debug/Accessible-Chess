namespace WordDeck;

internal static class SpellingSelfTest
{
    public static void Run()
    {
        TestIndependentDeckState();
        TestDynamicSpellingDecksAndSafeTransfer();
        TestAdaptiveScheduler();
        TestSpellingPersistence();
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
        Dictionary<string, string> spellingMap = spellingService.EnsureAssignments(dictionaryId, new[] { "one", "two" });
        spellingMap["one"] = SpellingDeckIds.Core(2);

        Require(recall.Decks.Count == 5 && spelling.Decks.Count == 5, "Recall and spelling must each own five independent core decks.");
        Require(recallMap["one"] == DeckIds.Core(4), "Creating spelling state changed a recall assignment.");
        Require(spellingMap["one"] == SpellingDeckIds.Core(2), "Spelling assignment was not independent from recall.");
        Require(recall.Decks.All(d => !d.Id.StartsWith("spelling-", StringComparison.OrdinalIgnoreCase)), "Spelling deck IDs leaked into recall state.");
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

        Dictionary<string, string> map = service.EnsureAssignments(dictionaryId, new[] { "a", "b" });
        map["a"] = custom.Id;
        bool unsafeDeleteRejected = false;
        try { service.DeleteUserDeck(custom.Id, null); } catch (InvalidOperationException) { unsafeDeleteRejected = true; }
        Require(unsafeDeleteRejected, "Non-empty spelling deck deletion was allowed without safe transfer.");
        service.DeleteUserDeck(custom.Id, SpellingDeckIds.Core(3));
        Require(service.Find(custom.Id) is null, "User spelling deck was not deleted after safe transfer.");
        Require(map["a"] == SpellingDeckIds.Core(3), "Spelling word was lost instead of transferred during deck deletion.");

        bool coreDeleteRejected = false;
        try { service.DeleteUserDeck(SpellingDeckIds.Core(1), SpellingDeckIds.Core(2)); } catch (InvalidOperationException) { coreDeleteRejected = true; }
        Require(coreDeleteRejected, "A permanent spelling core deck was deletable.");
    }

    private static void TestAdaptiveScheduler()
    {
        var scheduler = new ConservativeSpellingScheduler();
        var stats = new SpellingEntryStats { CurrentStreak = 3 };
        SpellingScheduleDecision promote = scheduler.Decide(SpellingDeckIds.Core(2), stats, firstTryCorrect: true, usedHint: false);
        Require(promote.TargetDeckId == SpellingDeckIds.Core(3), "Three clean first-try reviews did not move one core spelling deck later.");

        SpellingScheduleDecision demote = scheduler.Decide(SpellingDeckIds.Core(4), stats, firstTryCorrect: false, usedHint: false);
        Require(demote.TargetDeckId == SpellingDeckIds.Core(3), "A wrong spelling did not move one core deck earlier.");

        SpellingScheduleDecision hinted = scheduler.Decide(SpellingDeckIds.Core(3), stats, firstTryCorrect: true, usedHint: true);
        Require(hinted.TargetDeckId == SpellingDeckIds.Core(2), "Hint use was not treated conservatively by the spelling coach.");

        SpellingScheduleDecision userDeck = scheduler.Decide("spelling-user-test", stats, firstTryCorrect: false, usedHint: true);
        Require(userDeck.TargetDeckId is null, "Adaptive coach attempted to redistribute a user-created spelling deck.");

        stats.CurrentStreak = 2;
        SpellingScheduleDecision hold = scheduler.Decide(SpellingDeckIds.Core(2), stats, firstTryCorrect: true, usedHint: false);
        Require(hold.TargetDeckId is null, "Adaptive coach moved a word before the conservative clean-streak threshold.");
    }

    private static void TestSpellingPersistence()
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
            state.CoachEnabled = false;
            state.CurrentEntryIdByDictionary["d"] = "entry-1";
            state.DeckIdsByDictionary["d"] = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase) { ["entry-1"] = custom.Id };
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
                    RecentOutcomes = new List<bool> { false, true },
                    LastReviewedUtc = DateTimeOffset.UtcNow
                }
            };
            store.Save(state);

            SpellingState loaded = new SpellingStateStore(root).Load();
            Require(loaded.ActiveDeckId == custom.Id, "Active spelling deck did not survive restart.");
            Require(!loaded.CoachEnabled, "Adaptive spelling coach setting did not survive restart.");
            Require(loaded.CurrentEntryIdByDictionary["d"] == "entry-1", "Current spelling card did not survive restart.");
            Require(loaded.DeckIdsByDictionary["d"]["entry-1"] == custom.Id, "Spelling deck assignment did not survive restart.");
            SpellingEntryStats stats = loaded.StatsByDictionary["d"]["entry-1"];
            Require(stats.CompletedReviews == 4 && stats.FirstTrySuccesses == 2 && stats.WrongAttempts == 3 && stats.HintUses == 1 && stats.ShowAnswerUses == 1,
                "Spelling review statistics did not survive restart.");
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
        Require(ShortcutFormatter.Format(Keys.Control | Keys.OemQuestion) == "Ctrl+/" &&
                ShortcutFormatter.Format(Keys.Shift | Keys.Back) == "Shift+Backspace",
            "Human-readable shortcut formatter leaked a technical Windows key name.");

        Keys importedConflict = Keys.Control | Keys.Alt | Keys.F10;
        app.Shortcuts[ActionIds.SpellingShowAnswer] = importedConflict.ToString();
        app.Shortcuts[ActionIds.SpellingRepeatPrompt] = importedConflict.ToString();
        Require(manager.Get(ActionIds.SpellingShowAnswer) == Keys.None && manager.Get(ActionIds.SpellingRepeatPrompt) == Keys.None &&
                manager.FindAction(importedConflict) is null,
            "Ambiguous shortcut bindings imported from a profile did not fail closed.");

        Keys replacement = Keys.Control | Keys.Alt | Keys.Shift | Keys.F11;
        Require(manager.TrySet(ActionIds.SpellingShowAnswer, replacement, out string? error), $"Spelling shortcut could not be rebound: {error}");
        Require(manager.Get(ActionIds.SpellingShowAnswer) == replacement && manager.FindAction(replacement) == ActionIds.SpellingShowAnswer,
            "Rebound spelling shortcut did not dispatch through the shared shortcut manager.");
        Require(!manager.TrySet(ActionIds.SpellingRepeatPrompt, replacement, out string? conflict) && !string.IsNullOrWhiteSpace(conflict),
            "Conflict checking did not reject a duplicate spelling shortcut.");

        var service = new SpellingDeckService(spelling);
        DeckDefinition custom = service.Create("Shortcut deck");
        manager.RefreshDeckDefinitions(spelling.Decks);
        Require(manager.Definitions.Any(d => d.Id == ActionIds.SpellingSwitchDeck(custom.Id)), "User-created spelling deck did not gain a stable switch action.");
        Require(manager.Get(ActionIds.SpellingSwitchDeck(custom.Id)) == Keys.None, "User-created spelling deck switch shortcut should start unassigned.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }
}
