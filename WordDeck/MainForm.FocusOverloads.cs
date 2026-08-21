namespace WordDeck;

internal sealed partial class MainForm
{
    // WinForms Shown/BeginInvoke needs an exact parameterless Action target.
    // The bool overload carries the focus-preservation contract for selector-driven updates.
    private void RestoreCurrentOrNextWord() => RestoreCurrentOrNextWord(focusWord: true);
}
