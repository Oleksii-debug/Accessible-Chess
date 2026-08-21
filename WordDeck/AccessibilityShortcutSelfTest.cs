namespace WordDeck;

internal static class AccessibilityShortcutSelfTest
{
    public static void Run()
    {
        TestHumanReadableFormatting();
        TestUnsafeBindingsFailClosed();
        TestRecallAndTrainingDispatchIsolation();
        TestCrossModuleDefaultsAreConflictFree();
    }

    private static void TestHumanReadableFormatting()
    {
        Require(ShortcutFormatter.Format(Keys.None) == "Unassigned", "Unassigned shortcut text changed.");
        Require(ShortcutFormatter.Format(Keys.Control | Keys.Shift | Keys.Delete) == "Ctrl+Shift+Delete", "Delete shortcut formatting is not human-readable.");
        Require(ShortcutFormatter.Format(Keys.Control | Keys.PageDown) == "Ctrl+Page Down", "Page Down shortcut formatting is not human-readable.");
        Require(ShortcutFormatter.Format(Keys.Alt | Keys.OemQuestion) == "Alt+/", "OEM punctuation leaked into user-facing shortcut text.");
        Require(!ShortcutFormatter.Format(Keys.Control | Keys.Left).Contains("Oem", StringComparison.OrdinalIgnoreCase), "WinForms enum text leaked into shortcut formatting.");
    }

    private static void TestUnsafeBindingsFailClosed()
    {
        var state = AppStateStore.Normalize(new AppState());
        var manager = new ShortcutManager(state);

        Require(!manager.TrySet(ActionIds.SaveProgress, Keys.A, out _), "Printable unmodified key was accepted as a global shortcut.");
        Require(!manager.TrySet(ActionIds.SaveProgress, Keys.Control | Keys.C, out _), "Standard Ctrl+C editing chord was accepted as a global shortcut.");
        Require(!manager.TrySet(ActionIds.SaveProgress, Keys.Control | Keys.Right, out _), "Recall compatibility Ctrl+Right was accepted for reassignment.");
        Require(!manager.TrySet(ActionIds.SaveProgress, Keys.Alt | Keys.Space, out _), "Windows Alt+Space system-menu chord was accepted.");
        Require(!manager.TrySet(ActionIds.SaveProgress, Keys.LWin, out _), "Windows logo key was accepted as a shortcut.");
        Require(!manager.TrySet(ActionIds.SaveProgress, Keys.Left, out _), "Unmodified Left navigation key was accepted.");
        Require(!manager.TrySet(ActionIds.SaveProgress, Keys.Right, out _), "Unmodified Right navigation key was accepted.");
        Require(manager.Get(ActionIds.NextWord) == Keys.Down, "Recall Down default was accidentally rejected by safety filtering.");
        Require(manager.Get(ActionIds.PreviousWord) == Keys.Up, "Recall Up default was accidentally rejected by safety filtering.");
    }

    private static void TestRecallAndTrainingDispatchIsolation()
    {
        var state = AppStateStore.Normalize(new AppState());
        var recallManager = new ShortcutManager(state);
        SpellingState spelling = SpellingStateStore.Normalize(new SpellingState());

        recallManager.RefreshDeckDefinitions(spelling.Decks);
        Require(recallManager.Definitions.Any(def => def.Id == ActionIds.OpenSpelling), "Recall help/settings registry did not learn Spelling actions after refresh.");
        Require(recallManager.Definitions.Any(def => def.Id == ActionIds.OpenSentenceCoach), "Recall help/settings registry did not learn Sentence actions after refresh.");
        Require(recallManager.FindAction(Keys.Down) == ActionIds.NextWord, "Recall dispatch lost Down after training definitions were refreshed.");
        Require(recallManager.FindAction(Keys.Control | Keys.Shift | Keys.H) is null, "Recall context dispatched a Spelling-only action.");
        Require(recallManager.FindAction(Keys.Control | Keys.Alt | Keys.H) is null, "Recall context dispatched a Sentence-only action.");

        var trainingManager = new ShortcutManager(state, spelling.Decks);
        Require(trainingManager.FindAction(Keys.Control | Keys.Shift | Keys.H) == ActionIds.SpellingShowAnswer, "Training context did not dispatch Spelling show-answer.");
        Require(trainingManager.FindAction(Keys.Control | Keys.Alt | Keys.H) == ActionIds.SentenceShowAnswer, "Training context did not dispatch Sentence show-answer.");
        Require(trainingManager.Get(ActionIds.SpellingDeleteDeck) == (Keys.Control | Keys.Shift | Keys.Delete), "Spelling delete shortcut changed from Ctrl+Shift+Delete.");
    }

    private static void TestCrossModuleDefaultsAreConflictFree()
    {
        var state = AppStateStore.Normalize(new AppState());
        SpellingState spelling = SpellingStateStore.Normalize(new SpellingState());
        var manager = new ShortcutManager(state, spelling.Decks);
        ShortcutDefinition[] assigned = manager.Definitions.Where(def => def.DefaultKeys != Keys.None).ToArray();
        Require(assigned.Select(def => def.DefaultKeys).Distinct().Count() == assigned.Length,
            "Recall, Spelling and Sentence default shortcuts contain a conflict.");

        string a1 = ActionIds.SwitchStudyScope(StudyScopeIds.A1);
        Require(manager.TrySet(a1, Keys.Control | Keys.Alt | Keys.F8, out string? error), $"Safe scope rebind failed: {error}");
        Require(manager.FindAction(Keys.Control | Keys.Alt | Keys.F8) == a1, "Safe scope rebind did not become active immediately.");
        manager.Clear(a1);
        Require(manager.Get(a1) == Keys.None && ShortcutFormatter.Format(manager.Get(a1)) == "Unassigned", "Cleared scope shortcut is not reported honestly.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException("Accessibility/shortcut self-test failed: " + message);
    }
}
