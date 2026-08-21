namespace WordDeck;

internal sealed partial class MainForm
{
    private Round2HelpMessageFilter? _round2HelpFilter;

    protected override void OnShown(EventArgs e)
    {
        base.OnShown(e);

        PreserveFocusAfterSelection(_dictionaryCombo);
        PreserveFocusAfterSelection(_scopeCombo);
        PreserveFocusAfterSelection(_deckCombo);

        _round2HelpFilter ??= new Round2HelpMessageFilter(this);
        Application.AddMessageFilter(_round2HelpFilter);
    }

    protected override void OnFormClosed(FormClosedEventArgs e)
    {
        if (_round2HelpFilter is not null)
        {
            Application.RemoveMessageFilter(_round2HelpFilter);
            _round2HelpFilter = null;
        }
        base.OnFormClosed(e);
    }

    private static void PreserveFocusAfterSelection(ComboBox combo)
    {
        combo.SelectionChangeCommitted += (_, _) =>
        {
            if (!combo.ContainsFocus || combo.IsDisposed)
                return;

            Form? owner = combo.FindForm();
            owner?.BeginInvoke(new Action(() =>
            {
                if (!combo.IsDisposed && combo.CanFocus && owner is not null && owner.ContainsFocus)
                    combo.Focus();
            }));
        };
    }

    private void ShowRound2KeyboardHelp()
    {
        SpellingState spellingState = new SpellingStateStore().Load();
        var helpShortcuts = new ShortcutManager(_state, spellingState.Decks);
        string shortcutLines = string.Join(
            Environment.NewLine,
            helpShortcuts.Definitions.Select(definition =>
                $"{definition.Description}: {ShortcutFormatter.Format(helpShortcuts.Get(definition.Id))}"));

        string help =
            "WORDDECK KEYBOARD HELP\r\n\r\n" +
            "This list is generated from the current shared shortcut registry, including Recall, Spelling and Sentence Spelling. Reassigned and unassigned bindings are shown as they are currently stored.\r\n\r\n" +
            "Recall: Down moves to the next card only while the current English word field has focus. Up returns to the previous actually shown card there. In the translation field, list boxes, combo boxes and other text/navigation controls, arrow keys keep their normal Windows navigation behavior.\r\n\r\n" +
            "Spelling and Sentence Spelling are dialog windows. Alt+F4 closes the active trainer window and normal state saving remains in effect. Enter submits a typed Spelling/Sentence answer where documented by that trainer.\r\n\r\n" +
            "KEYBOARD SHORTCUTS\r\n" + shortcutLines + "\r\n\r\n" +
            "Use Tools > Keyboard shortcuts or Training keyboard shortcuts to reassign supported commands. Windows-reserved and ambiguous duplicate bindings fail closed.";

        using var form = new Form
        {
            Text = "WordDeck keyboard help",
            Width = 860,
            Height = 680,
            StartPosition = FormStartPosition.CenterParent,
            AccessibleName = "WordDeck keyboard help"
        };
        var box = new TextBox
        {
            Dock = DockStyle.Fill,
            Multiline = true,
            ReadOnly = true,
            ScrollBars = ScrollBars.Vertical,
            Text = help,
            AccessibleName = "WordDeck keyboard help text",
            TabStop = true
        };
        form.Controls.Add(box);
        form.Shown += (_, _) =>
        {
            box.Focus();
            box.SelectionStart = 0;
            box.SelectionLength = 0;
        };
        form.ShowDialog(this);
        FocusCurrentWord();
    }

    private sealed class Round2HelpMessageFilter : IMessageFilter
    {
        private const int WmKeyDown = 0x0100;
        private readonly MainForm _owner;

        public Round2HelpMessageFilter(MainForm owner)
        {
            _owner = owner;
        }

        public bool PreFilterMessage(ref Message m)
        {
            if (m.Msg != WmKeyDown || (Keys)(int)m.WParam != Keys.F1 || Form.ActiveForm != _owner)
                return false;

            _owner.BeginInvoke(new Action(_owner.ShowRound2KeyboardHelp));
            return true;
        }
    }
}
