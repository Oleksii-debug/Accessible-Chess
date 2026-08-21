namespace WordDeck;

internal sealed partial class MainForm
{
    private ComboBox? _keyboardSelectorPendingFocus;

    internal AppState SharedAppStateForTraining => _state;

    internal DictionaryPackage ActivePackageForTraining => _package;

    internal void SaveSharedStateAfterTraining()
    {
        SaveState();
    }

    internal void InstallReleaseSelectorFocusRetention()
    {
        InstallSelectorFocusRetention(_dictionaryCombo);
        InstallSelectorFocusRetention(_scopeCombo);
        InstallSelectorFocusRetention(_deckCombo);
    }

    private void InstallSelectorFocusRetention(ComboBox combo)
    {
        combo.KeyDown += (_, e) =>
        {
            if (e.Modifiers == Keys.None && (e.KeyCode == Keys.Up || e.KeyCode == Keys.Down))
                _keyboardSelectorPendingFocus = combo;
        };
        combo.SelectedIndexChanged += (_, _) =>
        {
            if (!ReferenceEquals(_keyboardSelectorPendingFocus, combo)) return;
            _keyboardSelectorPendingFocus = null;
            BeginInvoke(new Action(() =>
            {
                if (!IsDisposed && combo.CanFocus)
                    combo.Focus();
            }));
        };
        combo.Leave += (_, _) =>
        {
            if (ReferenceEquals(_keyboardSelectorPendingFocus, combo))
                _keyboardSelectorPendingFocus = null;
        };
    }
}
