namespace WordDeck;

internal sealed partial class MainForm
{
    private readonly HashSet<ComboBox> _round2HookedCombos = new();
    private readonly HashSet<ComboBox> _round2KeyboardSelectorChange = new();
    private bool _round2IdleHookInstalled;

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

        HookRound2ComboFocus(this);
        if (!_round2IdleHookInstalled)
        {
            Application.Idle += Round2ApplicationIdle;
            _round2IdleHookInstalled = true;
        }
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

        // Existing selection handlers may refresh the current exercise/card and
        // focus its primary text surface. For a keyboard selector change, restore
        // focus after those handlers complete so native ComboBox Up/Down remains
        // a continuous, no-Enter-required workflow.
        combo.BeginInvoke(new Action(() =>
        {
            if (!combo.IsDisposed && combo.Visible && combo.Enabled && combo.FindForm()?.ContainsFocus == true)
            {
                combo.Focus();
                AccessibilityAnnouncer.Announce(combo, combo.Text);
            }
        }));
    }
}
