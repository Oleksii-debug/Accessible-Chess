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
        Console.WriteLine("WordDeck R4 accessibility acceptance passed: shortcut context isolation, global fixed-action F1/settings registry, protected unknown Spelling binding preservation without live-key poisoning, live cross-mode conflict rejection, unsafe/native keys, Recall arrow surface and selector navigation contracts verified.");
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

        // Fixed cross-mode actions are global truth for F1/settings/conflict checks
        // even before dynamic Spelling deck topology is available. Dispatch remains
        // context-scoped, so the Recall form still does not consume training keys.
        var mainRegistry = new ShortcutManager(app);
        AssertEqual(ActionIds.ShortcutSettings, mainRegistry.FindAction(Keys.Control | Keys.K), "Ctrl+K must work before training definitions are synchronized.");
        AssertEqual(ActionIds.Help, mainRegistry.FindAction(Keys.F1), "F1 must work before training definitions are synchronized.");
        AssertTrue(mainRegistry.Definitions.Any(def => def.Id == ActionIds.OpenSpelling),
            "Global F1/settings registry omitted fixed Open Spelling before dynamic deck synchronization.");
        AssertTrue(mainRegistry.Definitions.Any(def => def.Id == ActionIds.OpenSentenceCoach),
            "Global F1/settings registry omitted fixed Open Sentence Spelling before dynamic deck synchronization.");
        AssertNull(mainRegistry.FindAction(Keys.Control | Keys.Shift | Keys.S),
            "Recall dispatcher swallowed the fixed Open Spelling accelerator before dynamic deck synchronization.");
        AssertNull(mainRegistry.FindAction(Keys.Control | Keys.Shift | Keys.E),
            "Recall dispatcher swallowed the fixed Open Sentence accelerator before dynamic deck synchronization.");

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
            "Training shortcut settings allowed a live Spelling action to steal Ctrl+K from shortcut settings.");
        AssertFalse(mainRegistry.TrySet(ActionIds.SentenceShowAnswer, Keys.F1, out string? f1Conflict) || string.IsNullOrWhiteSpace(f1Conflict),
            "Training shortcut settings allowed a live Sentence action to steal F1 from help.");
    }

    private static void TestPersistedDynamicSpellingBindingSafety()
    {
        AppState app = AppStateStore.Normalize(new AppState());
        SpellingState spelling = SpellingStateStore.Normalize(new SpellingState());
        var recallOnly = new ShortcutManager(app);

        // A dynamic Spelling binding may be present in the shared profile while
        // Spelling state is temporarily unreadable/protected. Recall must neither
        // delete that unknown user binding nor let it poison a live Recall command.
        string protectedUnknown = ActionIds.SpellingSwitchDeck("protected-unknown-r4c-deck");
        app.Shortcuts[protectedUnknown] = (Keys.Control | Keys.K).ToString();
        recallOnly.RefreshDeckDefinitions();
        AssertTrue(app.Shortcuts.ContainsKey(protectedUnknown),
            "Recall-only shortcut refresh deleted a protected dynamic Spelling binding without Spelling deck context.");
        AssertEqual(ActionIds.ShortcutSettings, recallOnly.FindAction(Keys.Control | Keys.K),
            "An unresolved non-live Spelling binding disabled the live Ctrl+K shortcut-settings command.");

        // Once explicit Spelling topology is available, a binding for a deck that
        // does not exist is provably orphaned and can be removed safely.
        recallOnly.RefreshDeckDefinitions(spelling.Decks);
        AssertFalse(app.Shortcuts.ContainsKey(protectedUnknown),
            "Explicit Spelling-topology refresh failed to remove a proven orphaned dynamic Spelling binding.");
        AssertEqual(ActionIds.ShortcutSettings, recallOnly.FindAction(Keys.Control | Keys.K),
            "Ctrl+K changed after safe orphan cleanup.");

        // A binding for a real Spelling deck is live, must dispatch in the full
        // registry, and must participate in cross-mode conflict validation.
        string spellingDeckId = spelling.Decks.First().Id;
        string liveDynamicAction = ActionIds.SpellingSwitchDeck(spellingDeckId);
        Keys liveDynamicKey = Keys.Control | Keys.Shift | Keys.F8;
        app.Shortcuts[liveDynamicAction] = liveDynamicKey.ToString();
        var full = new ShortcutManager(app, spelling.Decks, ShortcutDispatchContext.All);
        AssertTrue(full.Definitions.Any(def => def.Id == liveDynamicAction),
            "Full shortcut registry omitted a valid dynamic Spelling deck action.");
        AssertEqual(liveDynamicAction, full.FindAction(liveDynamicKey),
            "Valid dynamic Spelling binding did not survive into the full registry.");
        AssertFalse(full.TrySet(ActionIds.SaveProgress, liveDynamicKey, out string? liveConflict) || string.IsNullOrWhiteSpace(liveConflict),
            "A live dynamic Spelling binding did not block a duplicate Recall assignment.");
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
