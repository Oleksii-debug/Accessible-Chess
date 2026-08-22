namespace WordDeck;

internal enum ShortcutDispatchContext
{
    Recall,
    Spelling,
    Sentence,
    All
}

internal static class ShortcutDispatchPolicy
{
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
