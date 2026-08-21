namespace WordDeck;

internal static class RecallKeyboardFocusPolicy
{
    public static bool IsFastCardArrow(Keys keyData, bool englishWordSurfaceFocused)
    {
        Keys code = keyData & Keys.KeyCode;
        Keys modifiers = keyData & Keys.Modifiers;
        return modifiers == Keys.None &&
               (code == Keys.Up || code == Keys.Down) &&
               englishWordSurfaceFocused;
    }

    public static bool ShouldFocusCardAfterSelectorChange(bool selectorContainsFocus) =>
        !selectorContainsFocus;
}
