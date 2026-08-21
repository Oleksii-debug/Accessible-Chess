namespace WordDeck;

internal static class AccessibilityRound2SelfTest
{
    public static void Run()
    {
        AppState state = AppStateStore.Normalize(new AppState());
        SpellingState spellingState = SpellingStateStore.Normalize(new SpellingState());

        var recall = new ShortcutManager(state, spellingState.Decks, ShortcutDispatchContext.Recall);
        Require(recall.FindAction(Keys.Down) == ActionIds.NextWord, "Recall Down binding no longer dispatches on the Recall context.");
        Require(recall.FindAction(Keys.Up) == ActionIds.PreviousWord, "Recall Up binding no longer dispatches on the Recall context.");
        Require(recall.FindAction(Keys.Control | Keys.Shift | Keys.S) is null, "Recall context leaked the Spelling open action.");
        Require(recall.CurrentDefinitions.Any(def => def.Id == ActionIds.OpenSpelling), "Main help lost fixed Spelling definitions.");
        Require(recall.CurrentDefinitions.Any(def => def.Id == ActionIds.OpenSentenceCoach), "Main help lost fixed Sentence definitions.");

        var spelling = new ShortcutManager(state, spellingState.Decks, ShortcutDispatchContext.Spelling);
        Require(spelling.FindAction(spelling.Get(ActionIds.OpenSpelling)) == ActionIds.OpenSpelling, "Spelling context cannot dispatch its open shortcut.");
        Require(spelling.FindAction(Keys.Down) is null, "Spelling context leaked Recall Down navigation.");
        Require(spelling.FindAction(spelling.Get(ActionIds.SentenceShowAnswer)) is null, "Spelling context leaked a Sentence action.");

        var sentence = new ShortcutManager(state, spellingState.Decks, ShortcutDispatchContext.Sentence);
        Require(sentence.FindAction(sentence.Get(ActionIds.SentenceShowAnswer)) == ActionIds.SentenceShowAnswer, "Sentence context cannot dispatch its show-answer shortcut.");
        Require(sentence.FindAction(sentence.Get(ActionIds.SpellingShowAnswer)) is null, "Sentence context leaked a Spelling action.");

        Keys altF4 = Keys.Alt | Keys.F4;
        Require(recall.Get(ShortcutManager.StandardSpellingCloseActionId) == altF4, "F1/help no longer exposes standard Spelling Alt+F4 close.");
        Require(spelling.FindAction(altF4) is null, "Alt+F4 was converted into an application shortcut instead of native Windows close.");
        Require(!spelling.TrySet(ShortcutManager.StandardSpellingCloseActionId, Keys.Control | Keys.Q, out _), "Fixed Windows close shortcut became rebindable.");
        spelling.Clear(ShortcutManager.StandardSpellingCloseActionId);
        Require(spelling.Get(ShortcutManager.StandardSpellingCloseActionId) == altF4, "Clearing shortcuts removed fixed Alt+F4 documentation.");

        Require(!AccessibilityKeyboardPolicy.ShouldUseFastRecallArrow(Keys.Down, englishWordSurfaceFocused: false), "Down became fast Recall navigation outside the English word surface.");
        Require(!AccessibilityKeyboardPolicy.ShouldUseFastRecallArrow(Keys.Up, englishWordSurfaceFocused: false), "Up became fast Recall navigation outside the English word surface.");
        Require(AccessibilityKeyboardPolicy.ShouldUseFastRecallArrow(Keys.Down, englishWordSurfaceFocused: true), "English word surface lost fast Down navigation.");
        Require(AccessibilityKeyboardPolicy.ShouldUseFastRecallArrow(Keys.Up, englishWordSurfaceFocused: true), "English word surface lost fast Up navigation.");
        Require(!AccessibilityKeyboardPolicy.IsUnmodifiedVerticalArrow(Keys.Control | Keys.Down), "Modified Down was misclassified as unmodified Recall navigation.");
        Require(AccessibilityKeyboardPolicy.IsSelectorNavigationKey(Keys.Down) && AccessibilityKeyboardPolicy.IsSelectorNavigationKey(Keys.Up), "Native selector Up/Down contract is missing.");

        Require(!recall.TrySet(ActionIds.RevealTranslation, Keys.Control | Keys.C, out _), "Ctrl+C text-editing chord became rebindable.");
        Require(!recall.TrySet(ActionIds.RevealTranslation, Keys.Alt | Keys.F4, out _), "Alt+F4 Windows close became rebindable.");
        Require(!recall.TrySet(ActionIds.RevealTranslation, Keys.Control | Keys.Alt | Keys.Delete, out _), "Ctrl+Alt+Delete became rebindable.");
        Require(!recall.TrySet(ActionIds.RevealTranslation, Keys.A, out _), "Unmodified typing key became rebindable.");

        var duplicateState = AppStateStore.Normalize(new AppState());
        Keys duplicate = Keys.Control | Keys.Q;
        duplicateState.Shortcuts[ActionIds.RevealTranslation] = duplicate.ToString();
        duplicateState.Shortcuts[ActionIds.RepeatWord] = duplicate.ToString();
        var duplicateManager = new ShortcutManager(duplicateState, spellingState.Decks, ShortcutDispatchContext.Recall);
        Require(duplicateManager.Get(ActionIds.RevealTranslation) == Keys.None, "Duplicate imported shortcut did not fail closed for first action.");
        Require(duplicateManager.Get(ActionIds.RepeatWord) == Keys.None, "Duplicate imported shortcut did not fail closed for second action.");
        Require(duplicateManager.FindAction(duplicate) is null, "Ambiguous imported shortcut dispatched despite fail-closed policy.");

        // Long pure-policy stability check: the field-specific decision must not
        // drift after repeated selector/translation cycles.
        for (int i = 0; i < 100; i++)
        {
            Require(!AccessibilityKeyboardPolicy.ShouldUseFastRecallArrow(Keys.Down, false), $"Translation/selector Down policy drifted at cycle {i}.");
            Require(!AccessibilityKeyboardPolicy.ShouldUseFastRecallArrow(Keys.Up, false), $"Translation/selector Up policy drifted at cycle {i}.");
            Require(AccessibilityKeyboardPolicy.ShouldUseFastRecallArrow(Keys.Down, true), $"Word Down policy drifted at cycle {i}.");
            Require(AccessibilityKeyboardPolicy.ShouldUseFastRecallArrow(Keys.Up, true), $"Word Up policy drifted at cycle {i}.");
        }

        Console.WriteLine("WordDeck accessibility Round 2 acceptance passed: field-specific Recall arrows, context-isolated shortcuts, fixed Alt+F4 help, unsafe chord rejection, imported duplicate fail-closed behavior and 100-cycle policy stability verified.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }
}
