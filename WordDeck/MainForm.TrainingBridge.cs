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

    internal static string BuildCurrentWordDeckHelpText(string shortcutLines, string audioMode)
    {
        shortcutLines ??= string.Empty;
        string safeAudioMode = string.IsNullOrWhiteSpace(audioMode) ? "unknown" : audioMode.Trim();

        return
            "WORDDECK HELP\r\n\r\n" +
            "RECALL STUDY SCOPES\r\n" +
            "Recall has six independent study workspaces: All Oxford 5000, A1, A2, B1, B2 and C1. There is no Oxford C2 workspace because the Oxford 5000 list does not define a C2 subset. Each scope keeps its own Recall deck assignments, active deck, current card and shuffle progress.\r\n\r\n" +
            "RECALL KEYBOARD BEHAVIOR\r\n" +
            "Fast Down Arrow/Up Arrow card navigation works only while the Current English word field is focused: Down moves to the next card and Up returns to the previous actually shown eligible card. In the Ukrainian translation TextBox, Dictionary/Study scope/Deck selectors, menus, dialogs and other standard controls, arrow keys keep their native control behavior and do not switch Recall cards. Changing a selector with Up/Down keeps focus in that selector. Ctrl+Right and Ctrl+Left remain compatibility next/previous keys.\r\n\r\n" +
            "SPELLING\r\n" +
            "Open Spelling with its configured shortcut or Tools menu entry. Type the English spelling and press Enter. An empty or whitespace-only Enter is ignored before learning statistics are changed, including a rapid second Enter after a completed answer. Close the Spelling window with Alt+F4; normal close saves through the existing state lifecycle. Alt+F4 remains a standard Windows close command and is not assignable as a WordDeck shortcut.\r\n\r\n" +
            "SENTENCE SPELLING\r\n" +
            "Open Sentence Spelling with its configured shortcut or Tools menu entry. It uses a validated installed offline SentencePack and never invents a production corpus when none is installed. Choose a spelling-deck scope, a 30/100/200/full target pool, and one, two or three natural targets. Ambiguous same-written-form Oxford identities are excluded before pool selection unless independent sense identity exists. WordDeck shows the Ukrainian sentence and the English sentence with only the current target blank. Type only that exact target word or phrase and press Enter; multi-target sentences advance one target at a time. Show answer reveals only the current target. Empty or whitespace-only Enter is a non-learning event. Current sentence, target position and current wrong/hint flags are saved for restart continuity.\r\n\r\n" +
            "LISTENING AND DEEP LISTENING\r\n" +
            "Open Listening and Dictation from Tools or with its configured shortcut. It uses installed offline British word audio. Type the English answer; the written answer stays hidden until you check it or use Show answer. Listening keeps its own durable progress, history and unfinished item. Deep Listening groups eligible word-audio work into deterministic five-review journeys reconstructed from Listening history; completing a journey does not by itself create CEFR or mastery evidence.\r\n\r\n" +
            "STORY / COURSE\r\n" +
            "Tools > Open course opens validated installed local WordDeck course manifests. The current learner UI can present course reading, dialogues/stories, comprehension and productive practice. Writing responses can be stored as practice. Speaking or mixed productive tasks currently use a typed fallback in this Course UI because no microphone/capture provider is bound there; typed fallback does not create Speaking or Pronunciation evidence or mastery.\r\n\r\n" +
            "DEEP GRAMMAR\r\n" +
            "Tools > Open Deep Grammar A1 opens the currently governed A1 Present Continuous practice journey. It records ordinary practice and deterministic recommended remediation in learner-course state. Practice, reveal, completion and recommended next work do not by themselves mean mastery, a CEFR level or Fast Track completion.\r\n\r\n" +
            "READING / PRIVATE LOCAL BOOKS\r\n" +
            "Tools > Open Reading / book study opens the keyboard-first private local reader. It accepts local TXT, HTML and EPUB files plus explicitly PDF-derived text; WordDeck does not silently parse a PDF as if extraction were reliable. Imported source bytes and reading data stay under %LOCALAPPDATA%\\WordDeck\\Reading and are not silently uploaded. Known/Learning/New familiarity comes from the selected Recall decks, and ambiguous dictionary forms require an explicit entry choice before capture to a Learning deck.\r\n\r\n" +
            "PERSONAL PROGRESS AND UPDATE SAFETY\r\n" +
            "Personal progress is stored outside the program ZIP under %LOCALAPPDATA%\\WordDeck, so replacing the program ZIP does not intentionally erase progress. Tools > Export complete personal profile exports one personal profile containing Recall, Spelling, Sentence, Listening and Course/Story learner state; the canonical dictionary, audio, course content and SentencePack content are not copied into that profile. Private Reading book files and Reading positions remain separate local Reading data and are not claimed as part of the unified profile export. Import validates the profile, creates recovery material before replacement and applies it through the unified profile service.\r\n\r\n" +
            "Deck > Hide current word removes a word only from normal Recall study. It does not delete the canonical dictionary, audio or saved deck assignments. Hidden words can be restored individually or all at once. File > Reset Recall learning data resets Recall learning overlays only and creates recovery material first; it is not described as a global reset of Spelling, Sentence, Listening, Course/Story or Reading.\r\n\r\n" +
            "OFFLINE PRONUNCIATION\r\n" +
            "Generated British pronunciation is an optional offline audio layer keyed by stable dictionary and entry IDs. " +
            $"Automatic pronunciation on card change is currently {safeAudioMode}. If generated audio is unavailable, WordDeck reports a readable status and the normal screen-reader announcement remains the fallback.\r\n\r\n" +
            "KEYBOARD SHORTCUTS\r\n" + shortcutLines + "\r\n\r\n" +
            "Use Tools > Training keyboard shortcuts to assign or reassign the supported Recall, Spelling, Sentence and Listening shortcuts. Standard Windows navigation and reserved keys remain protected. Training-window shortcuts are listed here from the same live shortcut registry used by the application.";
    }

    internal void ShowCurrentWordDeckHelp()
    {
        _shortcuts.RefreshDeckDefinitions();
        string shortcutLines = string.Join(
            Environment.NewLine,
            _shortcuts.Definitions.Select(def => $"{def.Description}: {ShortcutFormatter.Format(_shortcuts.Get(def.Id))}"));
        string audioMode = _state.AutoPlayPronunciationOnCardChange ? "enabled" : "disabled";

        string help = BuildCurrentWordDeckHelpText(shortcutLines, audioMode);

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
