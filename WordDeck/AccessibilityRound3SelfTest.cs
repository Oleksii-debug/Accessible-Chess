namespace WordDeck;

internal static class AccessibilityRound3SelfTest
{
    public static void Run()
    {
        TestSharedRegistryAndContexts();
        TestFixedAltF4();
        TestUnsafeNativeKeys();
        TestDuplicateBindingsFailClosed();
        TestRecallFocusPolicy();
        Console.WriteLine("Accessibility Round 3 self-test passed.");
    }

    private static void TestSharedRegistryAndContexts()
    {
        var state = new AppState();
        var manager = new ShortcutManager(state);

        Require(manager.CurrentDefinitions.Any(def => def.Id == ActionIds.OpenSpelling), "Open Spelling must be present in the shared registry even without a spelling-deck list.");
        Require(manager.CurrentDefinitions.Any(def => def.Id == ActionIds.OpenSentenceCoach), "Open Sentence Spelling must be present in the shared registry.");
        Require(manager.CurrentDefinitions.Any(def => def.Id == ShortcutManager.StandardSpellingCloseActionId), "Fixed Spelling Alt+F4 must be visible in the shared registry.");

        Keys next = manager.Get(ActionIds.NextWord);
        Keys spelling = manager.Get(ActionIds.SpellingShowAnswer);
        Keys sentence = manager.Get(ActionIds.SentenceShowAnswer);

        Require(manager.FindAction(next, ShortcutDispatchContext.Recall) == ActionIds.NextWord, "Recall context must dispatch Recall actions.");
        Require(manager.FindAction(spelling, ShortcutDispatchContext.Recall) is null, "Recall context must not dispatch Spelling actions.");
        Require(manager.FindAction(sentence, ShortcutDispatchContext.Recall) is null, "Recall context must not dispatch Sentence actions.");

        Require(manager.FindAction(spelling, ShortcutDispatchContext.Spelling) == ActionIds.SpellingShowAnswer, "Spelling context must dispatch Spelling actions.");
        Require(manager.FindAction(next, ShortcutDispatchContext.Spelling) is null, "Spelling context must not dispatch Recall actions.");
        Require(manager.FindAction(sentence, ShortcutDispatchContext.Spelling) is null, "Spelling context must not dispatch Sentence actions.");

        Require(manager.FindAction(sentence, ShortcutDispatchContext.Sentence) == ActionIds.SentenceShowAnswer, "Sentence context must dispatch Sentence actions.");
        Require(manager.FindAction(next, ShortcutDispatchContext.Sentence) is null, "Sentence context must not dispatch Recall actions.");
        Require(manager.FindAction(spelling, ShortcutDispatchContext.Sentence) is null, "Sentence context must not dispatch Spelling actions.");

        Require(manager.FindAction(spelling, ShortcutDispatchContext.All) == ActionIds.SpellingShowAnswer, "All context must expose Spelling actions for presentation/settings use.");
        Require(manager.FindAction(sentence, ShortcutDispatchContext.All) == ActionIds.SentenceShowAnswer, "All context must expose Sentence actions for presentation/settings use.");
    }

    private static void TestFixedAltF4()
    {
        var state = new AppState();
        var manager = new ShortcutManager(state);
        Keys altF4 = Keys.Alt | Keys.F4;

        Require(manager.Get(ShortcutManager.StandardSpellingCloseActionId) == altF4, "Spelling close must be documented as Alt+F4.");
        Require(!manager.IsRebindable(ShortcutManager.StandardSpellingCloseActionId), "Alt+F4 must not be rebindable.");
        Require(manager.FindAction(altF4, ShortcutDispatchContext.Recall) is null, "Alt+F4 must remain native in Recall.");
        Require(manager.FindAction(altF4, ShortcutDispatchContext.Spelling) is null, "Alt+F4 must remain native in Spelling.");
        Require(manager.FindAction(altF4, ShortcutDispatchContext.Sentence) is null, "Alt+F4 must remain native in Sentence.");
        Require(!manager.TrySet(ShortcutManager.StandardSpellingCloseActionId, Keys.Control | Keys.Q, out _), "Fixed Alt+F4 must reject rebinding.");
        manager.Clear(ShortcutManager.StandardSpellingCloseActionId);
        Require(manager.Get(ShortcutManager.StandardSpellingCloseActionId) == altF4, "Clearing a fixed Windows command must have no effect.");
    }

    private static void TestUnsafeNativeKeys()
    {
        var state = new AppState();
        var manager = new ShortcutManager(state);
        string action = ActionIds.RestoreAllHiddenWords;
        Keys[] unsafeKeys =
        {
            Keys.Control | Keys.C,
            Keys.Control | Keys.X,
            Keys.Control | Keys.V,
            Keys.Control | Keys.Left,
            Keys.Control | Keys.Right,
            Keys.Control | Keys.Home,
            Keys.Control | Keys.End,
            Keys.Control | Keys.PageUp,
            Keys.Control | Keys.PageDown,
            Keys.Left,
            Keys.Right,
            Keys.Home,
            Keys.End,
            Keys.PageUp,
            Keys.PageDown,
            Keys.A,
            Keys.D1,
            Keys.Alt | Keys.Space,
            Keys.Control | Keys.Alt | Keys.Delete,
            Keys.Alt | Keys.F4
        };

        foreach (Keys keys in unsafeKeys)
            Require(!manager.TrySet(action, keys, out _), $"Unsafe/native key must be rejected for rebinding: {keys}.");

        Require(manager.TrySet(ActionIds.NextWord, Keys.Down, out _), "Down must remain valid only for Recall next-word semantics.");
        Require(manager.TrySet(ActionIds.PreviousWord, Keys.Up, out _), "Up must remain valid only for Recall previous-word semantics.");
        Require(!manager.TrySet(action, Keys.Down, out _), "Unmodified Down must not be assignable to arbitrary actions.");
        Require(!manager.TrySet(action, Keys.Up, out _), "Unmodified Up must not be assignable to arbitrary actions.");
    }

    private static void TestDuplicateBindingsFailClosed()
    {
        Keys duplicate = Keys.Control | Keys.Q;
        var state = new AppState
        {
            Shortcuts = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                [ActionIds.NextWord] = duplicate.ToString(),
                [ActionIds.RevealTranslation] = duplicate.ToString()
            }
        };
        var manager = new ShortcutManager(state);

        Require(manager.Get(ActionIds.NextWord) == Keys.None, "Ambiguous imported next-word binding must fail closed.");
        Require(manager.Get(ActionIds.RevealTranslation) == Keys.None, "Ambiguous imported reveal binding must fail closed.");
        Require(manager.FindAction(duplicate, ShortcutDispatchContext.Recall) is null, "Ambiguous imported shortcut must not dispatch.");
    }

    private static void TestRecallFocusPolicy()
    {
        Require(RecallKeyboardFocusPolicy.IsFastCardArrow(Keys.Down, true), "Down must be a fast Recall arrow on the English word surface.");
        Require(RecallKeyboardFocusPolicy.IsFastCardArrow(Keys.Up, true), "Up must be a fast Recall arrow on the English word surface.");
        Require(!RecallKeyboardFocusPolicy.IsFastCardArrow(Keys.Down, false), "Translation/selectors must not become fast Recall arrow surfaces.");
        Require(!RecallKeyboardFocusPolicy.IsFastCardArrow(Keys.Up, false), "Translation/selectors must not become fast Recall arrow surfaces.");
        Require(!RecallKeyboardFocusPolicy.IsFastCardArrow(Keys.Control | Keys.Down, true), "Modified Down must not use fast unmodified Recall routing.");
        Require(!RecallKeyboardFocusPolicy.IsFastCardArrow(Keys.Left, true), "Native horizontal text navigation must not become Recall navigation.");
        Require(!RecallKeyboardFocusPolicy.ShouldFocusCardAfterSelectorChange(true), "A focused selector must keep focus after its selection changes.");
        Require(RecallKeyboardFocusPolicy.ShouldFocusCardAfterSelectorChange(false), "Programmatic/non-focused selector changes may restore card focus.");

        for (int i = 0; i < 100; i++)
        {
            Require(RecallKeyboardFocusPolicy.IsFastCardArrow(i % 2 == 0 ? Keys.Down : Keys.Up, true), "Repeated English-word arrow routing must remain stable.");
            Require(!RecallKeyboardFocusPolicy.ShouldFocusCardAfterSelectorChange(true), "Repeated selector focus policy must remain stable.");
        }
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException("Accessibility R3 regression: " + message);
    }
}
