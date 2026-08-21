namespace WordDeck;

internal sealed partial class MainForm
{
    private bool _refreshingAccessibleShortcutPresentation;

    protected override void OnShown(EventArgs e)
    {
        base.OnShown(e);
        BeginInvoke(new Action(() =>
        {
            RefreshAccessibleShortcutPresentation(reloadPersistedShortcuts: true);
            FocusCurrentWord();
        }));
    }

    protected override void OnActivated(EventArgs e)
    {
        base.OnActivated(e);
        if (!IsHandleCreated || IsDisposed) return;
        BeginInvoke(new Action(() => RefreshAccessibleShortcutPresentation(reloadPersistedShortcuts: true)));
    }

    private void RefreshAccessibleShortcutPresentation(bool reloadPersistedShortcuts)
    {
        if (_refreshingAccessibleShortcutPresentation || IsDisposed) return;
        _refreshingAccessibleShortcutPresentation = true;
        try
        {
            if (reloadPersistedShortcuts)
            {
                AppState persisted = _store.Load();
                _state.Shortcuts = new Dictionary<string, string>(persisted.Shortcuts, StringComparer.OrdinalIgnoreCase);
            }

            SpellingState spellingState = new SpellingStateStore().Load();
            _shortcuts.RefreshDeckDefinitions(spellingState.Decks);
            UpdateKeyboardHintFromActiveBindings();
            SynchronizeTrainingMenuShortcuts();
        }
        finally
        {
            _refreshingAccessibleShortcutPresentation = false;
        }
    }

    private void UpdateKeyboardHintFromActiveBindings()
    {
        Label? hint = FindControlByAccessibleName(this, "Keyboard hint") as Label;
        if (hint is null) return;

        string next = ShortcutFormatter.Format(_shortcuts.Get(ActionIds.NextWord));
        string previous = ShortcutFormatter.Format(_shortcuts.Get(ActionIds.PreviousWord));
        string reveal = ShortcutFormatter.Format(_shortcuts.Get(ActionIds.RevealTranslation));
        string settings = ShortcutFormatter.Format(_shortcuts.Get(ActionIds.ShortcutSettings));
        string help = ShortcutFormatter.Format(_shortcuts.Get(ActionIds.Help));
        hint.Text = $"Next word: {next}. True previous word: {previous}. Translation: {reveal}. Shortcut settings: {settings}. Help with every active binding: {help}.";
        hint.AccessibleDescription = "This hint is generated from the currently active shortcut bindings and updates after shortcut changes.";
    }

    private void SynchronizeTrainingMenuShortcuts()
    {
        if (MainMenuStrip is null) return;
        SetMenuShortcut(MainMenuStrip.Items, "Open Spelling trainer", _shortcuts.Get(ActionIds.OpenSpelling));
        SetMenuShortcut(MainMenuStrip.Items, "Open Sentence Spelling trainer", _shortcuts.Get(ActionIds.OpenSentenceCoach));
    }

    private static void SetMenuShortcut(ToolStripItemCollection items, string accessibleName, Keys shortcut)
    {
        foreach (ToolStripItem item in items)
        {
            if (item is not ToolStripMenuItem menuItem) continue;
            if (string.Equals(menuItem.AccessibleName, accessibleName, StringComparison.OrdinalIgnoreCase))
            {
                menuItem.ShortcutKeys = shortcut;
                menuItem.ShowShortcutKeys = shortcut != Keys.None;
                return;
            }
            if (menuItem.DropDownItems.Count > 0)
                SetMenuShortcut(menuItem.DropDownItems, accessibleName, shortcut);
        }
    }

    private static Control? FindControlByAccessibleName(Control root, string accessibleName)
    {
        foreach (Control child in root.Controls)
        {
            if (string.Equals(child.AccessibleName, accessibleName, StringComparison.OrdinalIgnoreCase)) return child;
            Control? nested = FindControlByAccessibleName(child, accessibleName);
            if (nested is not null) return nested;
        }
        return null;
    }
}
