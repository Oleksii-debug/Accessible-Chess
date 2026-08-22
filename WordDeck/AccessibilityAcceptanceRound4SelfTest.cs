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
        TestUnsafeAndNativeKeysFailClosed();
        TestRecallArrowSurfaceContract();
        TestSelectorNavigationContract();
        Console.WriteLine("WordDeck R4 accessibility acceptance passed: shortcut context isolation, unsafe/native keys, Recall arrow surface and selector navigation contracts verified.");
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
