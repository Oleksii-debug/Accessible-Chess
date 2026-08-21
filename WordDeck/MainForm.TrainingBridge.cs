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
        combo.KeyUp += (_, e) =>
        {
            // If Up/Down was pressed at a list boundary and selection did not
            // change, SelectedIndexChanged does not fire. Clear only after the
            // key gesture finishes; do not clear on Leave because a selection
            // handler may temporarily focus the current card before this late
            // retention handler schedules focus back to the selector.
            if (e.Modifiers == Keys.None && (e.KeyCode == Keys.Up || e.KeyCode == Keys.Down) &&
                ReferenceEquals(_keyboardSelectorPendingFocus, combo))
                _keyboardSelectorPendingFocus = null;
        };
    }
}
