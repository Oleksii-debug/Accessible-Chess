namespace WordDeck;

internal sealed partial class MainForm
{
    private readonly HashSet<ComboBox> _round2HookedCombos = new();
    private readonly HashSet<ComboBox> _round2KeyboardSelectorChange = new();
    private bool _round2IdleHookInstalled;
    private bool _round2RefreshingShortcutPresentation;

    protected override void OnShown(EventArgs e)
    {
        base.OnShown(e);

        _dictionaryCombo.TabIndex = 0;
        _scopeCombo.TabIndex = 1;
        _deckCombo.TabIndex = 2;
        _wordBox.TabIndex = 3;
        _translationBox.TabIndex = 4;

        _dictionaryCombo.AccessibleDescription = "Choose the active dictionary. Up and Down change the selection immediately and focus stays on this selector.";
        _scopeCombo.AccessibleDescription = "Choose All Oxford 5000 or A1 through C1. Up and Down change the selection immediately and focus stays on this selector.";
        _deckCombo.AccessibleDescription = "Choose a Recall deck in the current study scope. Up and Down change the selection immediately and focus stays on this selector.";
        _translationBox.AccessibleDescription = "Ukrainian translation. Arrow, Home, End, Page Up and Page Down remain text-reading keys here and never change the Recall card.";
        _wordBox.AccessibleDescription = "Current English Recall word. Unmodified Down shows the next card and unmodified Up returns to the previous actually shown card.";

        RefreshRound2ShortcutPresentation(reloadPersistedShortcuts: true);
        HookRound2ComboFocus(this);
        if (!_round2IdleHookInstalled)
        {
            Application.Idle += Round2ApplicationIdle;
            _round2IdleHookInstalled = true;
        }
    }

    protected override void OnActivated(EventArgs e)
    {
        base.OnActivated(e);
        if (!IsHandleCreated || IsDisposed) return;
        BeginInvoke(new Action(() => RefreshRound2ShortcutPresentation(reloadPersistedShortcuts: true)));
    }

    protected override void OnFormClosed(FormClosedEventArgs e)
    {
        if (_round2IdleHookInstalled)
        {
            Application.Idle -= Round2ApplicationIdle;
            _round2IdleHookInstalled = false;
        }
        base.OnFormClosed(e);
    }

    private void RefreshRound2ShortcutPresentation(bool reloadPersistedShortcuts)
    {
        if (_round2RefreshingShortcutPresentation || IsDisposed) return;
        _round2RefreshingShortcutPresentation = true;
        try
        {
            if (reloadPersistedShortcuts)
            {
                AppState persisted = _store.Load();
                _state.Shortcuts = new Dictionary<string, string>(persisted.Shortcuts, StringComparer.OrdinalIgnoreCase);
            }

            SpellingState spelling = new SpellingStateStore().Load();
            _shortcuts.RefreshDeckDefinitions(spelling.Decks);

            Label? hint = FindRound2ControlByAccessibleName(this, "Keyboard hint") as Label;
            if (hint is not null)
            {
                hint.Text =
                    $"On Current English word: Down = {ShortcutFormatter.Format(_shortcuts.Get(ActionIds.NextWord))}, Up = {ShortcutFormatter.Format(_shortcuts.Get(ActionIds.PreviousWord))}. " +
                    $"Translation: {ShortcutFormatter.Format(_shortcuts.Get(ActionIds.RevealTranslation))}; once translation has focus, arrows stay inside the text and never change cards. " +
                    "Dictionary, Study scope and Deck selectors use native Up/Down and keep focus. " +
                    $"Shortcut settings: {ShortcutFormatter.Format(_shortcuts.Get(ActionIds.ShortcutSettings))}. Help: {ShortcutFormatter.Format(_shortcuts.Get(ActionIds.Help))}.";
                hint.AccessibleDescription = "Generated from current bindings and the Round 2 focus contract.";
            }
        }
        finally
        {
            _round2RefreshingShortcutPresentation = false;
        }
    }

    private void Round2ApplicationIdle(object? sender, EventArgs e)
    {
        foreach (Form form in Application.OpenForms)
            HookRound2ComboFocus(form);
    }

    private void HookRound2ComboFocus(Control root)
    {
        foreach (Control child in root.Controls)
        {
            if (child is ComboBox combo && _round2HookedCombos.Add(combo))
            {
                combo.PreviewKeyDown += Round2ComboPreviewKeyDown;
                combo.KeyUp += Round2ComboKeyUp;
                combo.SelectedIndexChanged += Round2ComboSelectedIndexChanged;
            }
            if (child.HasChildren) HookRound2ComboFocus(child);
        }
    }

    private void Round2ComboPreviewKeyDown(object? sender, PreviewKeyDownEventArgs e)
    {
        if (sender is not ComboBox combo || !AccessibilityKeyboardPolicy.IsSelectorNavigationKey(e.KeyData)) return;
        e.IsInputKey = true;
        _round2KeyboardSelectorChange.Add(combo);
    }

    private void Round2ComboKeyUp(object? sender, KeyEventArgs e)
    {
        if (sender is ComboBox combo && AccessibilityKeyboardPolicy.IsSelectorNavigationKey(e.KeyData))
            _round2KeyboardSelectorChange.Remove(combo);
    }

    private void Round2ComboSelectedIndexChanged(object? sender, EventArgs e)
    {
        if (sender is not ComboBox combo || !_round2KeyboardSelectorChange.Contains(combo)) return;
        if (combo.IsDisposed || combo.FindForm()?.IsDisposed != false) return;

        // Existing handlers may refresh an exercise and focus its primary text
        // surface. Restore the selector only after they finish; do not synthesize
        // speech here because native ComboBox/UIA selection and focus events are
        // the screen-reader source of truth.
        combo.BeginInvoke(new Action(() =>
        {
            if (!combo.IsDisposed && combo.Visible && combo.Enabled && combo.FindForm()?.ContainsFocus == true)
                combo.Focus();
        }));
    }

    private static Control? FindRound2ControlByAccessibleName(Control root, string accessibleName)
    {
        foreach (Control child in root.Controls)
        {
            if (string.Equals(child.AccessibleName, accessibleName, StringComparison.OrdinalIgnoreCase)) return child;
            Control? nested = FindRound2ControlByAccessibleName(child, accessibleName);
            if (nested is not null) return nested;
        }
        return null;
    }
}
