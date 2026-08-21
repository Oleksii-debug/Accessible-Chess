namespace WordDeck;

internal enum ShortcutDispatchContext
{
    Recall,
    Spelling,
    Sentence,
    All
}

internal static class AccessibilityKeyboardPolicy
{
    public static bool IsUnmodifiedVerticalArrow(Keys keyData)
    {
        Keys code = keyData & Keys.KeyCode;
        Keys modifiers = keyData & Keys.Modifiers;
        return modifiers == Keys.None && (code == Keys.Up || code == Keys.Down);
    }

    public static bool ShouldUseFastRecallArrow(Keys keyData, bool englishWordSurfaceFocused) =>
        englishWordSurfaceFocused && IsUnmodifiedVerticalArrow(keyData);

    public static bool IsSelectorNavigationKey(Keys keyData)
    {
        Keys code = keyData & Keys.KeyCode;
        Keys modifiers = keyData & Keys.Modifiers;
        return modifiers == Keys.None && (code == Keys.Up || code == Keys.Down);
    }

    public static bool ActionMatchesContext(string actionId, ShortcutDispatchContext context)
    {
        if (context == ShortcutDispatchContext.All) return true;
        bool spelling = actionId.StartsWith("spelling_", StringComparison.OrdinalIgnoreCase);
        bool sentence = actionId.StartsWith("sentence_", StringComparison.OrdinalIgnoreCase);
        return context switch
        {
            ShortcutDispatchContext.Recall => !spelling && !sentence,
            ShortcutDispatchContext.Spelling => spelling,
            ShortcutDispatchContext.Sentence => sentence,
            _ => false
        };
    }
}
