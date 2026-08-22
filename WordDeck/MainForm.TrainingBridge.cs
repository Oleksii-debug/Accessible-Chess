namespace WordDeck;

internal sealed partial class MainForm
{
    // Training modes must operate on the same live AppState instance as Recall.
    // Loading a second AppStateStore copy here can later overwrite newer
    // shortcuts/profile/Recall changes when either copy is persisted.
    internal AppState SharedAppStateForTraining => _state;
    internal DictionaryPackage ActivePackageForTraining => _package;
    internal void SaveSharedStateAfterTraining() => SaveState();

    // Keep one complete shortcut registry for F1/settings while the main form's
    // dispatch context remains Recall-only. That lets help show the current
    // Spelling/Sentence and dynamic spelling-deck assignments without causing
    // the Recall form to swallow training-window accelerators.
    internal void RefreshTrainingShortcutDefinitions(IEnumerable<DeckDefinition> spellingDecks) =>
        _shortcuts.RefreshDeckDefinitions(spellingDecks);

    private MainHelpShortcutFilter? _currentHelpFilter;

    internal void InstallCurrentHelpRoute(MenuStrip menu)
    {
        if (_currentHelpFilter is null)
        {
            _currentHelpFilter = new MainHelpShortcutFilter(this);
            Application.AddMessageFilter(_currentHelpFilter);
            FormClosed += (_, _) =>
            {
                if (_currentHelpFilter is null) return;
                Application.RemoveMessageFilter(_currentHelpFilter);
                _currentHelpFilter = null;
            };
        }

        ToolStripMenuItem? helpMenu = menu.Items.OfType<ToolStripMenuItem>()
            .FirstOrDefault(item => (item.Text ?? string.Empty).Replace("&", string.Empty)
                .Equals("Help", StringComparison.OrdinalIgnoreCase));
        if (helpMenu is null) return;

        // Replace the historical hard-coded help item. F1 remains rebindable, so
        // the displayed shortcut string is refreshed whenever the menu opens.
        helpMenu.DropDownItems.Clear();
        var helpItem = new ToolStripMenuItem("&WordDeck help")
        {
            AccessibleName = "WordDeck help",
            ShowShortcutKeys = true
        };
        helpItem.Click += (_, _) => ShowCurrentWordDeckHelp();
        helpMenu.DropDownOpening += (_, _) =>
            helpItem.ShortcutKeyDisplayString = ShortcutFormatter.Format(_shortcuts.Get(ActionIds.Help));
        helpMenu.DropDownItems.Add(helpItem);
    }

    internal Keys CurrentHelpShortcut => _shortcuts.Get(ActionIds.Help);

    internal void ShowCurrentWordDeckHelp()
    {
        _shortcuts.RefreshDeckDefinitions();
        string shortcutLines = string.Join(
            Environment.NewLine,
            _shortcuts.Definitions.Select(def => $"{def.Description}: {ShortcutFormatter.Format(_shortcuts.Get(def.Id))}"));
        string audioMode = _state.AutoPlayPronunciationOnCardChange ? "enabled" : "disabled";

        string help =
            "WORDDECK HELP\r\n\r\n" +
            "RECALL STUDY SCOPES\r\n" +
            "Recall has six independent study workspaces: All Oxford 5000, A1, A2, B1, B2 and C1. There is no Oxford C2 workspace because the Oxford 5000 list does not define a C2 subset. Each scope keeps its own Recall deck assignments, active deck, current card and shuffle progress.\r\n\r\n" +
            "RECALL KEYBOARD BEHAVIOR\r\n" +
            "Fast Down Arrow/Up Arrow card navigation works only while the Current English word field is focused: Down moves to the next card and Up returns to the previous actually shown eligible card. In the Ukrainian translation TextBox, Dictionary/Study scope/Deck selectors, menus, dialogs and other standard controls, arrow keys keep their native control behavior and do not switch Recall cards. Changing a selector with Up/Down keeps focus in that selector. Ctrl+Right and Ctrl+Left remain compatibility next/previous keys.\r\n\r\n" +
            "SPELLING\r\n" +
            "Open Spelling with its configured shortcut or Tools menu entry. Type the English spelling and press Enter. An empty or whitespace-only Enter is ignored before learning statistics are changed, including a rapid second Enter after a completed answer. Close the Spelling window with Alt+F4; normal close saves through the existing state lifecycle. Alt+F4 remains a standard Windows close command and is not assignable as a WordDeck shortcut.\r\n\r\n" +
            "SENTENCE SPELLING\r\n" +
            "Open Sentence Spelling with its configured shortcut or Tools menu entry. It uses an installed offline SentencePack and never invents a production corpus when none is installed. Type the required English word forms and press Enter; word order is not assessed. Empty or whitespace-only Enter is a non-learning event and does not alter wrong-attempt statistics. Close the window with Alt+F4.\r\n\r\n" +
            "PERSONAL PROGRESS AND UPDATE SAFETY\r\n" +
            "Personal progress is stored outside the program ZIP under %LOCALAPPDATA%\\WordDeck, so replacing the program ZIP does not intentionally erase progress. File > Export personal progress profile and its configured shortcut export one complete personal profile containing Recall, Spelling and Sentence learning state; the canonical dictionary and audio are not copied into that profile. Import validates the profile, creates recovery material before replacement and applies it through the unified profile service.\r\n\r\n" +
            "Deck > Hide current word removes a word only from normal Recall study. It does not delete the canonical dictionary, audio or saved deck assignments. Hidden words can be restored individually or all at once. File > Reset Recall learning data resets Recall learning overlays only and creates recovery material first; it is not described as a global Spelling/Sentence reset.\r\n\r\n" +
            "OFFLINE PRONUNCIATION\r\n" +
            "Generated British pronunciation is an optional offline audio layer keyed by stable dictionary and entry IDs. " +
            $"Automatic pronunciation on card change is currently {audioMode}. If generated audio is unavailable, WordDeck reports a readable status and the normal screen-reader announcement remains the fallback.\r\n\r\n" +
            "KEYBOARD SHORTCUTS\r\n" + shortcutLines + "\r\n\r\n" +
            "Use Tools > Keyboard shortcuts to assign or reassign shortcuts. Standard Windows navigation and reserved keys remain protected. Training-window shortcuts are listed here from the same live shortcut registry used by the application.";

        using var form = new Form
        {
            Text = "WordDeck help",
            Width = 820,
            Height = 650,
            StartPosition = FormStartPosition.CenterParent,
            AccessibleName = "WordDeck help"
        };
        var box = new TextBox
        {
            Dock = DockStyle.Fill,
            Multiline = true,
            ReadOnly = true,
            ScrollBars = ScrollBars.Vertical,
            Text = help,
            AccessibleName = "WordDeck help text",
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
        RepeatCurrentWord();
    }

    private sealed class MainHelpShortcutFilter : IMessageFilter
    {
        private const int WmKeyDown = 0x0100;
        private readonly MainForm _owner;

        public MainHelpShortcutFilter(MainForm owner) => _owner = owner;

        public bool PreFilterMessage(ref Message m)
        {
            if (m.Msg != WmKeyDown || !_owner.ContainsFocus)
                return false;

            Keys keyCode = (Keys)m.WParam.ToInt32();
            if (keyCode is Keys.ControlKey or Keys.ShiftKey or Keys.Menu)
                return false;

            Keys configured = _owner.CurrentHelpShortcut;
            if (configured == Keys.None)
                return false;

            Keys keyData = keyCode | Control.ModifierKeys;
            if (keyData != configured)
                return false;

            _owner.BeginInvoke(new Action(_owner.ShowCurrentWordDeckHelp));
            return true;
        }
    }
}
