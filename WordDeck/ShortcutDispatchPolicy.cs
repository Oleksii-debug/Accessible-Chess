namespace WordDeck;

internal enum ShortcutDispatchContext
{
    Recall,
    Spelling,
    Sentence,
    Listening,
    All
}

internal static class ShortcutDispatchPolicy
{
    public static bool ActionMatchesContext(string actionId, ShortcutDispatchContext context)
    {
        if (context == ShortcutDispatchContext.All) return true;

        bool spelling = actionId.StartsWith("spelling_", StringComparison.OrdinalIgnoreCase);
        bool sentence = actionId.StartsWith("sentence_", StringComparison.OrdinalIgnoreCase);
        bool listening = actionId.StartsWith("listening_", StringComparison.OrdinalIgnoreCase);

        return context switch
        {
            ShortcutDispatchContext.Recall => !spelling && !sentence && !listening,
            ShortcutDispatchContext.Spelling => spelling,
            ShortcutDispatchContext.Sentence => sentence,
            ShortcutDispatchContext.Listening => listening,
            _ => false
        };
    }
}
