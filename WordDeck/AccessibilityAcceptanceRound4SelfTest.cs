using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class AccessibilityAcceptanceRound4SelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            AccessibilityAcceptanceRound4SelfTest.Run();
    }
}

internal static class AccessibilityAcceptanceRound4SelfTest
{
    public static void Run()
    {
        TestShortcutContextIsolation();
        TestTrainingRegistrySynchronization();
        TestPersistedDynamicSpellingBindingSafety();
        TestUnsafeAndNativeKeysFailClosed();
        TestRecallArrowSurfaceContract();
        TestSelectorNavigationContract();
        Console.WriteLine("WordDeck R4 accessibility acceptance passed: shortcut context isolation, synchronized F1/settings registry, persisted dynamic Spelling binding preservation, cross-mode conflict rejection, unsafe/native keys, Recall arrow surface and selector navigation contracts verified.");
    }

    private static void TestShortcutContextIsolation()
    {
        AppState app = AppStateStore.Normalize(new AppState());
        SpellingState spelling = SpellingStateStore.Normalize(new SpellingState());

        var spellingManager = new ShortcutManager(app, spelling.Decks, ShortcutDispatchContext.Spelling);
        AssertEqual(ActionIds.SpellingShowAnswer, spellingManager.FindAction(Keys.Control | Keys.Shift | Keys.H), "Spelling shortcut must dispatch in Spelling context.");
        AssertNull(spellingManager.FindAction(Keys.Control | Keys.T), "Recall shortcut must not be swallowed in Spelling context.");
        AssertNull(spellingManager.FindAction(Keys.Control | Keys.Alt | Keys.H), "Sentence shortcut must not be swallowed in Spelling context.");

        var sentenceManager = new ShortcutManager(app, spelling.Decks, ShortcutDispatchContext.Sentence);
        AssertEqual(ActionIds.SentenceShowAnswer, sentenceManager.FindAction(Keys.Control | Keys.Alt | Keys.H), "Sentence shortcut must dispatch in Sentence context.");
        AssertNull(sentenceManager.FindAction(Keys.Control | Keys.T), "Recall shortcut must not be swallowed in Sentence context.");
        AssertNull(sentenceManager.FindAction(Keys.Control | Keys.Shift | Keys.H), "Spelling shortcut must not be swallowed in Sentence context.");

        var recallManager = new ShortcutManager(app, spelling.Decks, ShortcutDispatchContext.Recall);
        AssertEqual(ActionIds.RevealTranslation, recallManager.FindAction(Keys.Control | Keys.T), "Recall shortcut must dispatch in Recall context.");
        AssertNull(recallManager.FindAction(Keys.Control | Keys.Shift | Keys.H), "Spelling shortcut must not be swallowed in Recall context.");
        AssertNull(recallManager.FindAction(Keys.Control | Keys.Shift | Keys.S), "Spelling entry-point accelerator must fall through to the WinForms menu in Recall context.");
        AssertNull(recallManager.FindAction(Keys.Control | Keys.Shift | Keys.E), "Sentence entry-point accelerator must fall through to the WinForms menu in Recall context.");
    }

    private static void TestTrainingRegistrySynchronization()
    {
        AppState app = AppStateStore.Normalize(new AppState());
        SpellingState spelling = SpellingStateStore.Normalize(new SpellingState());

        // The main Recall dispatcher must preserve its own critical commands before
        // training topology is loaded. Training/F1/settings truth is then expanded
        // explicitly from the live Spelling deck context.
        var mainRegistry = new ShortcutManager(app);
        AssertEqual(ActionIds.ShortcutSettings, mainRegistry.FindAction(Keys.Control | Keys.K), "Ctrl+K must work before training definitions are synchronized.");
        AssertEqual(ActionIds.Help, mainRegistry.FindAction(Keys.F1), "F1 must work before training definitions are synchronized.");

        mainRegistry.RefreshDeckDefinitions(spelling.Decks);
        AssertTrue(mainRegistry.Definitions.Any(def => def.Id == ActionIds.OpenSpelling), "Synchronized Main/F1 registry omitted Open Spelling.");
        AssertTrue(mainRegistry.Definitions.Any(def => def.Id == ActionIds.OpenSentenceCoach), "Synchronized Main/F1 registry omitted Open Sentence Spelling.");
        string spellingCore1 = ActionIds.SpellingSwitchDeck(SpellingDeckIds.Core(1));
        AssertTrue(mainRegistry.Definitions.Any(def => def.Id == spellingCore1), "Synchronized Main/F1 registry omitted live Spelling deck actions.");
        AssertEqual(ActionIds.ShortcutSettings, mainRegistry.FindAction(Keys.Control | Keys.K), "Ctrl+K became unavailable after training definitions were synchronized.");
        AssertEqual(ActionIds.Help, mainRegistry.FindAction(Keys.F1), "F1 became unavailable after training definitions were synchronized.");
        AssertNull(mainRegistry.FindAction(Keys.Control | Keys.Shift | Keys.S), "Recall dispatcher swallowed the synchronized Open Spelling accelerator.");
        AssertNull(mainRegistry.FindAction(Keys.Control | Keys.Shift | Keys.E), "Recall dispatcher swallowed the synchronized Open Sentence accelerator.");

        AssertFalse(mainRegistry.TrySet(ActionIds.SpellingShowAnswer, Keys.Control | Keys.K, out string? ctrlKConflict) || string.IsNullOrWhiteSpace(ctrlKConflict),
            "Training shortcut settings allowed a Spelling action to steal Ctrl+K from shortcut settings.");
        AssertFalse(mainRegistry.TrySet(ActionIds.SentenceShowAnswer, Keys.F1, out string? f1Conflict) || string.IsNullOrWhiteSpace(f1Conflict),
            "Training shortcut settings allowed a Sentence action to steal F1 from help.");
    }

    private static void TestPersistedDynamicSpellingBindingSafety()
    {
        AppState app = AppStateStore.Normalize(new AppState());
        SpellingState spelling = SpellingStateStore.Normalize(new SpellingState());
        var recallOnly = new ShortcutManager(app);

        string spellingDeckId = spelling.Decks.First().Id;
        string dynamicAction = ActionIds.SpellingSwitchDeck(spellingDeckId);
        Keys dynamicKey = Keys.Control | Keys.Shift | Keys.F8;
        app.Shortcuts[dynamicAction] = dynamicKey.ToString();

        recallOnly.RefreshDeckDefinitions();
        AssertTrue(app.Shortcuts.ContainsKey(dynamicAction),
            "Recall-only shortcut refresh deleted a dynamic Spelling binding without Spelling deck context.");
        AssertFalse(recallOnly.TrySet(ActionIds.SaveProgress, dynamicKey, out string? crossModeConflict) || string.IsNullOrWhiteSpace(crossModeConflict),
            "Recall settings accepted a key already owned by a persisted dynamic Spelling action.");

        app.Shortcuts[ActionIds.SaveProgress] = dynamicKey.ToString();
        AssertTrue(recallOnly.Get(ActionIds.SaveProgress) == Keys.None,
            "Ambiguous persisted cross-mode shortcut did not fail closed.");
        app.Shortcuts[ActionIds.SaveProgress] = (Keys.Control | Keys.S).ToString();

        var full = new ShortcutManager(app, spelling.Decks, ShortcutDispatchContext.All);
        AssertTrue(full.Definitions.Any(def => def.Id == dynamicAction),
            "Full shortcut registry omitted a valid dynamic Spelling deck action.");
        AssertEqual(dynamicAction, full.FindAction(dynamicKey),
            "Valid dynamic Spelling binding did not survive into the full registry.");

        string orphan = ActionIds.SpellingSwitchDeck("definitely-missing-r4c-deck");
        app.Shortcuts[orphan] = (Keys.Control | Keys.Shift | Keys.F9).ToString();
        full.RefreshDeckDefinitions(spelling.Decks);
        AssertFalse(app.Shortcuts.ContainsKey(orphan),
            "Full Spelling-context refresh failed to remove a proven orphaned dynamic Spelling binding.");
    }

    private static void TestUnsafeAndNativeKeysFailClosed()
    {
        AppState app = AppStateStore.Normalize(new AppState());
        SpellingState spelling = SpellingStateStore.Normalize(new SpellingState());
        var manager = new ShortcutManager(app, spelling.Decks, ShortcutDispatchContext.All);

        AssertFalse(manager.TrySet(ActionIds.SpellingDeleteDeck, Keys.Control | Keys.Alt | Keys.Delete, out _), "Ctrl+Alt+Delete must remain reserved for Windows.");
        AssertFalse(manager.TrySet(ActionIds.SpellingShowAnswer, Keys.Alt | Keys.F4, out _), "Alt+F4 must remain the standard Windows close command.");
        AssertFalse(manager.TrySet(ActionIds.SentenceShowAnswer, Keys.Up, out _), "Unmodified Up must not become a training shortcut.");
        AssertFalse(manager.TrySet(ActionIds.SentenceShowAnswer, Keys.Left, out _), "Unmodified Left must remain native text/control navigation.");
    }

    private static void TestRecallArrowSurfaceContract()
    {
        AssertTrue(RecallKeyboardFocusPolicy.IsFastCardArrow(Keys.Down, englishWordSurfaceFocused: true), "Down must navigate Recall only on the English-word surface.");
        AssertTrue(RecallKeyboardFocusPolicy.IsFastCardArrow(Keys.Up, englishWordSurfaceFocused: true), "Up must navigate Recall only on the English-word surface.");
        AssertFalse(RecallKeyboardFocusPolicy.IsFastCardArrow(Keys.Down, englishWordSurfaceFocused: false), "Down must remain native outside the English-word surface.");
        AssertFalse(RecallKeyboardFocusPolicy.IsFastCardArrow(Keys.Control | Keys.Down, englishWordSurfaceFocused: true), "Modified arrows are not the fast Recall-arrow contract.");
        AssertFalse(RecallKeyboardFocusPolicy.ShouldFocusCardAfterSelectorChange(selectorContainsFocus: true), "A focused selector must retain focus after changing selection.");
        AssertTrue(RecallKeyboardFocusPolicy.ShouldFocusCardAfterSelectorChange(selectorContainsFocus: false), "Programmatic selector changes may return focus to the card.");
    }

    private static void TestSelectorNavigationContract()
    {
        AssertTrue(KeyboardSelectorFocusGuard.IsNativeSelectionNavigation(Keys.Up), "Selector Up must be recognized as native selection navigation.");
        AssertTrue(KeyboardSelectorFocusGuard.IsNativeSelectionNavigation(Keys.Down), "Selector Down must be recognized as native selection navigation.");
        AssertTrue(KeyboardSelectorFocusGuard.IsNativeSelectionNavigation(Keys.Home), "Selector Home must be recognized as native selection navigation.");
        AssertFalse(KeyboardSelectorFocusGuard.IsNativeSelectionNavigation(Keys.Control | Keys.Down), "Modified Down must not be mistaken for native selector navigation.");
        AssertFalse(KeyboardSelectorFocusGuard.IsNativeSelectionNavigation(Keys.Tab), "Tab is focus traversal, not selector selection navigation.");
    }

    private static void AssertTrue(bool value, string message)
    {
        if (!value) throw new InvalidOperationException("Accessibility R4 self-test: " + message);
    }

    private static void AssertFalse(bool value, string message) => AssertTrue(!value, message);

    private static void AssertNull(object? value, string message)
    {
        if (value is not null) throw new InvalidOperationException("Accessibility R4 self-test: " + message);
    }

    private static void AssertEqual(string expected, string? actual, string message)
    {
        if (!string.Equals(expected, actual, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException($"Accessibility R4 self-test: {message} Expected {expected}, got {actual ?? "<null>"}.");
    }
}
