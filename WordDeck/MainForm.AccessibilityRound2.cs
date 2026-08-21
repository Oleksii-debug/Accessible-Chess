namespace WordDeck;

internal sealed partial class MainForm
{
    private const string Round2HelpMarker = "ROUND 2 KEYBOARD FOCUS RULES";
    private readonly HashSet<ComboBox> _round2HookedCombos = new();
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
        {
            HookRound2ComboFocus(form);
            PatchRound2HelpIfOpen(form);
        }
    }

    private void HookRound2ComboFocus(Control root)
    {
        foreach (Control child in root.Controls)
        {
            if (child is ComboBox combo && _round2HookedCombos.Add(combo))
            {
                combo.PreviewKeyDown += Round2ComboPreviewKeyDown;
                combo.SelectionChangeCommitted += Round2ComboSelectionChangeCommitted;
            }
            if (child.HasChildren) HookRound2ComboFocus(child);
        }
    }

    private static void Round2ComboPreviewKeyDown(object? sender, PreviewKeyDownEventArgs e)
    {
        if (sender is ComboBox && AccessibilityKeyboardPolicy.IsSelectorNavigationKey(e.KeyData))
            e.IsInputKey = true;
    }

    private static void Round2ComboSelectionChangeCommitted(object? sender, EventArgs e)
    {
        if (sender is not ComboBox combo || combo.IsDisposed || combo.FindForm()?.IsDisposed != false) return;

        // User-committed ComboBox changes can synchronously refresh an exercise
        // and focus its card/input. Restore the selector after every user commit.
        // Programmatic initialization does not raise SelectionChangeCommitted,
        // so startup/population is unaffected and no reentrant selection loop is
        // introduced. Native ComboBox/UIA events remain the speech source.
        combo.BeginInvoke(new Action(() =>
        {
            if (!combo.IsDisposed && combo.Visible && combo.Enabled && combo.FindForm()?.ContainsFocus == true)
                combo.Focus();
        }));
    }

    private static void PatchRound2HelpIfOpen(Form form)
    {
        if (!string.Equals(form.Text, "WordDeck help", StringComparison.OrdinalIgnoreCase) &&
            !string.Equals(form.AccessibleName, "WordDeck help", StringComparison.OrdinalIgnoreCase))
            return;

        TextBox? box = FindRound2ControlByAccessibleName(form, "WordDeck help text") as TextBox;
        if (box is null || box.Text.Contains(Round2HelpMarker, StringComparison.Ordinal)) return;

        string corrected = box.Text;
        corrected = corrected.Replace(
            "The five core deck definitions and their shortcuts are shared, so Ctrl+1 through Ctrl+5 switches decks inside the CURRENT scope and Alt+1 through Alt+5 moves the current word inside the CURRENT scope. Scope-switch actions are rebindable and start unassigned.",
            "The five core deck definitions are shared between Recall scopes. Use the actual active bindings listed in KEYBOARD SHORTCUTS below; scope-switch actions may be unassigned or rebound.",
            StringComparison.Ordinal);
        corrected = corrected.Replace(
            "WordDeck shows only the English side of a Recall card by default. Down Arrow moves to the next card; Up Arrow returns to the previous actually shown eligible card. After moving back, Down moves forward through history before drawing a new shuffled card. Left and Right remain normal text/caret navigation. Ctrl+Right and Ctrl+Left remain compatibility next/previous keys. Reveal the Ukrainian translation only when needed.",
            "WordDeck shows only the English side of a Recall card by default. Unmodified Down and Up are fast Recall navigation only while Current English word has focus. Down moves next; Up returns to the previous actually shown eligible card; after moving back, Down follows forward history before drawing a new shuffled card. After Reveal translation moves focus to Ukrainian translation, Up, Down, Left, Right, Home, End, Page Up and Page Down remain native text-reading/navigation keys and never change the card. Dictionary, Study scope and Deck selectors use native Up/Down without Enter and keep focus. Ctrl+Right and Ctrl+Left remain compatibility next/previous keys.",
            StringComparison.Ordinal);

        corrected =
            Round2HelpMarker + "\r\n" +
            "Fast unmodified Recall Up/Down works only on Current English word. Translation arrows stay inside translation. Dictionary, Study scope and Deck selectors change with native Up/Down without Enter and retain focus. Spelling closes safely with the fixed standard Windows Alt+F4 command.\r\n\r\n" +
            corrected;

        int selectionStart = Math.Min(box.SelectionStart, corrected.Length);
        box.Text = corrected;
        box.SelectionStart = selectionStart;
        box.SelectionLength = 0;
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
