namespace WordDeck;

internal sealed class MainForm : Form
{
    private sealed record MoveUndo(string DictionaryId, string EntryId, int FromDeck, int ToDeck);

    private readonly AppStateStore _store = new();
    private readonly AppState _state;
    private readonly ShortcutManager _shortcuts;
    private readonly Dictionary<string, DictionaryPackage> _packages = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, DictionaryEntry> _entriesById = new(StringComparer.OrdinalIgnoreCase);
    private DictionaryPackage _package = null!;
    private Dictionary<string, int> _deckMap = null!;
    private int _activeDeck;
    private readonly Random _random = new();
    private readonly Queue<string> _shuffleBag = new();
    private readonly List<string> _history = new();
    private int _historyIndex = -1;
    private DictionaryEntry? _current;
    private MoveUndo? _lastMove;

    private readonly ComboBox _dictionaryCombo;
    private readonly ComboBox _deckCombo;
    private readonly TextBox _wordBox;
    private readonly TextBox _translationBox;
    private readonly Label _statusLabel;
    private readonly Label _countLabel;

    public MainForm()
    {
        _state = _store.Load();
        _shortcuts = new ShortcutManager(_state);
        LoadPackages();

        Text = "WordDeck";
        Width = 880;
        Height = 500;
        MinimumSize = new Size(620, 380);
        StartPosition = FormStartPosition.CenterScreen;
        KeyPreview = true;
        AccessibleName = "WordDeck vocabulary trainer";

        MainMenuStrip = BuildMenu();
        Controls.Add(MainMenuStrip);

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 8,
            Padding = new Padding(16),
            AutoSize = false
        };
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 50));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 50));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));

        var top = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoSize = true, WrapContents = true };
        top.Controls.Add(new Label { Text = "Dictionary:", AutoSize = true, Padding = new Padding(0, 6, 4, 0) });
        _dictionaryCombo = new ComboBox
        {
            DropDownStyle = ComboBoxStyle.DropDownList,
            Width = 330,
            AccessibleName = "Dictionary"
        };
        _dictionaryCombo.SelectedIndexChanged += (_, _) => ChangeDictionaryFromCombo();
        top.Controls.Add(_dictionaryCombo);

        top.Controls.Add(new Label { Text = "Deck:", AutoSize = true, Padding = new Padding(12, 6, 4, 0) });
        _deckCombo = new ComboBox
        {
            DropDownStyle = ComboBoxStyle.DropDownList,
            Width = 150,
            AccessibleName = "Active deck"
        };
        for (int i = 1; i <= 5; i++)
            _deckCombo.Items.Add($"Deck {i}");
        _deckCombo.SelectedIndexChanged += (_, _) =>
        {
            if (_deckCombo.SelectedIndex >= 0 && _deckCombo.SelectedIndex + 1 != _activeDeck)
                SwitchDeck(_deckCombo.SelectedIndex + 1);
        };
        top.Controls.Add(_deckCombo);

        _countLabel = new Label
        {
            AutoSize = true,
            AccessibleName = "Deck word count",
            Padding = new Padding(0, 8, 0, 8)
        };
        var wordHeading = new Label
        {
            Text = "English word",
            AutoSize = true,
            Font = new Font(Font, FontStyle.Bold)
        };
        _wordBox = new TextBox
        {
            ReadOnly = true,
            Dock = DockStyle.Fill,
            Multiline = true,
            TextAlign = HorizontalAlignment.Center,
            Font = new Font(Font.FontFamily, 28, FontStyle.Bold),
            AccessibleName = "Current English word",
            TabStop = true
        };
        _wordBox.Enter += (_, _) => _wordBox.SelectAll();

        var translationHeading = new Label
        {
            Text = "Translation (hidden until requested)",
            AutoSize = true,
            Font = new Font(Font, FontStyle.Bold)
        };
        _translationBox = new TextBox
        {
            ReadOnly = true,
            Dock = DockStyle.Fill,
            Multiline = true,
            TextAlign = HorizontalAlignment.Center,
            Font = new Font(Font.FontFamily, 18),
            AccessibleName = "Ukrainian translation",
            TabStop = true
        };
        _translationBox.Enter += (_, _) => _translationBox.SelectAll();

        _statusLabel = new Label
        {
            AutoSize = true,
            AccessibleName = "Status",
            Padding = new Padding(0, 8, 0, 0)
        };
        var hintLabel = new Label
        {
            AutoSize = true,
            AccessibleName = "Keyboard hint",
            Text = "F1: help. All shortcuts can be reassigned in Tools > Keyboard shortcuts."
        };

        root.Controls.Add(top, 0, 0);
        root.Controls.Add(_countLabel, 0, 1);
        root.Controls.Add(wordHeading, 0, 2);
        root.Controls.Add(_wordBox, 0, 3);
        root.Controls.Add(translationHeading, 0, 4);
        root.Controls.Add(_translationBox, 0, 5);
        root.Controls.Add(_statusLabel, 0, 6);
        root.Controls.Add(hintLabel, 0, 7);
        Controls.Add(root);
        root.BringToFront();

        PopulateDictionaryCombo();
        SelectInitialPackage();
        Shown += (_, _) => BeginInvoke(new Action(NextWord));
        FormClosing += (_, _) => SaveState();
    }

    private MenuStrip BuildMenu()
    {
        var menu = new MenuStrip { AccessibleName = "Application menu" };
        var file = new ToolStripMenuItem("&File");
        var import = new ToolStripMenuItem("&Import dictionary...");
        import.Click += (_, _) => ImportDictionary();
        var exit = new ToolStripMenuItem("E&xit");
        exit.Click += (_, _) => Close();
        file.DropDownItems.Add(import);
        file.DropDownItems.Add(new ToolStripSeparator());
        file.DropDownItems.Add(exit);

        var decks = new ToolStripMenuItem("&Deck");
        var undoMove = new ToolStripMenuItem("&Undo last deck move");
        undoMove.Click += (_, _) => UndoLastMove();
        decks.DropDownItems.Add(undoMove);
        decks.DropDownItems.Add(new ToolStripSeparator());
        for (int i = 1; i <= 5; i++)
        {
            int deck = i;
            var switchItem = new ToolStripMenuItem($"Switch to deck {deck}");
            switchItem.Click += (_, _) => SwitchDeck(deck);
            decks.DropDownItems.Add(switchItem);
        }

        var tools = new ToolStripMenuItem("&Tools");
        var shortcuts = new ToolStripMenuItem("&Keyboard shortcuts...");
        shortcuts.Click += (_, _) => OpenShortcutSettings();
        tools.DropDownItems.Add(shortcuts);

        var help = new ToolStripMenuItem("&Help");
        var helpItem = new ToolStripMenuItem("&WordDeck help");
        helpItem.Click += (_, _) => ShowHelp();
        help.DropDownItems.Add(helpItem);

        menu.Items.Add(file);
        menu.Items.Add(decks);
        menu.Items.Add(tools);
        menu.Items.Add(help);
        return menu;
    }

    private void LoadPackages()
    {
        DictionaryPackage embedded = DictionaryLoader.LoadEmbeddedOxford();
        _packages[embedded.Id] = embedded;

        foreach (string path in _store.EnumerateDictionaryFiles())
        {
            try
            {
                DictionaryPackage package = DictionaryLoader.LoadFromFile(path);
                _packages[package.Id] = package;
            }
            catch
            {
                // A broken optional imported dictionary must not block the built-in Oxford deck.
            }
        }
    }

    private void PopulateDictionaryCombo()
    {
        _dictionaryCombo.DisplayMember = "Name";
        _dictionaryCombo.ValueMember = "Id";
        _dictionaryCombo.DataSource = _packages.Values.OrderBy(x => x.Name).ToList();
    }

    private void SelectInitialPackage()
    {
        DictionaryPackage? selected = null;
        if (_state.ActiveDictionaryId is not null)
            _packages.TryGetValue(_state.ActiveDictionaryId, out selected);
        selected ??= _packages.Values.First();

        int index = ((List<DictionaryPackage>)_dictionaryCombo.DataSource!).FindIndex(x => x.Id == selected.Id);
        _dictionaryCombo.SelectedIndex = Math.Max(0, index);
        ActivatePackage(selected);
    }

    private void ChangeDictionaryFromCombo()
    {
        if (_dictionaryCombo.SelectedItem is DictionaryPackage package && (_package is null || package.Id != _package.Id))
        {
            ActivatePackage(package);
            NextWord();
        }
    }

    private void ActivatePackage(DictionaryPackage package)
    {
        _package = package;
        _state.ActiveDictionaryId = package.Id;
        _lastMove = null;

        _entriesById.Clear();
        foreach (DictionaryEntry entry in package.Entries)
            _entriesById[entry.Id] = entry;

        if (!_state.DecksByDictionary.TryGetValue(package.Id, out Dictionary<string, int>? deckMap))
        {
            deckMap = package.Entries.ToDictionary(entry => entry.Id, _ => 1, StringComparer.OrdinalIgnoreCase);
            _state.DecksByDictionary[package.Id] = deckMap;
        }
        _deckMap = deckMap;

        var validIds = new HashSet<string>(_entriesById.Keys, StringComparer.OrdinalIgnoreCase);
        foreach (string staleId in _deckMap.Keys.Where(id => !validIds.Contains(id)).ToList())
            _deckMap.Remove(staleId);
        foreach (DictionaryEntry entry in package.Entries)
        {
            if (_deckMap.TryGetValue(entry.Id, out int deck))
                _deckMap[entry.Id] = Math.Clamp(deck, 1, 5);
            else
                _deckMap[entry.Id] = 1;
        }

        _activeDeck = Math.Clamp(_state.ActiveDeck, 1, 5);
        _deckCombo.SelectedIndex = _activeDeck - 1;
        ResetSequence();
        UpdateCounts();
        SaveState();
    }

    private void SwitchDeck(int deck)
    {
        _activeDeck = Math.Clamp(deck, 1, 5);
        _state.ActiveDeck = _activeDeck;
        if (_deckCombo.SelectedIndex != _activeDeck - 1)
            _deckCombo.SelectedIndex = _activeDeck - 1;

        ResetSequence();
        UpdateCounts();
        _statusLabel.Text = $"Switched to deck {_activeDeck}.";
        NextWord();
        SaveState();
    }

    private IReadOnlyList<DictionaryEntry> EntriesInActiveDeck() =>
        _package.Entries.Where(entry => _deckMap.GetValueOrDefault(entry.Id, 1) == _activeDeck).ToList();

    private void ResetSequence()
    {
        _shuffleBag.Clear();
        _history.Clear();
        _historyIndex = -1;
        _current = null;
        FillShuffleBag();
    }

    private void FillShuffleBag()
    {
        List<string> ids = EntriesInActiveDeck().Select(entry => entry.Id).ToList();
        for (int i = ids.Count - 1; i > 0; i--)
        {
            int j = _random.Next(i + 1);
            (ids[i], ids[j]) = (ids[j], ids[i]);
        }

        if (_current is not null && ids.Count > 1 && ids[0] == _current.Id)
            (ids[0], ids[1]) = (ids[1], ids[0]);

        foreach (string id in ids)
            _shuffleBag.Enqueue(id);
    }

    private void NextWord()
    {
        IReadOnlyList<DictionaryEntry> active = EntriesInActiveDeck();
        if (active.Count == 0)
        {
            _current = null;
            _wordBox.Text = "No words in this deck";
            _translationBox.Clear();
            _statusLabel.Text = $"Deck {_activeDeck} is empty.";
            UpdateCounts();
            _wordBox.Focus();
            AccessibilityAnnouncer.Announce(_wordBox, _wordBox.Text);
            return;
        }

        while (_historyIndex >= 0 && _historyIndex < _history.Count - 1)
        {
            _historyIndex++;
            string historyId = _history[_historyIndex];
            if (_deckMap.GetValueOrDefault(historyId, 1) == _activeDeck)
            {
                ShowEntryById(historyId);
                return;
            }
        }

        if (_shuffleBag.Count == 0)
            FillShuffleBag();

        while (_shuffleBag.Count > 0)
        {
            string id = _shuffleBag.Dequeue();
            if (_deckMap.GetValueOrDefault(id, 1) != _activeDeck)
                continue;

            _history.Add(id);
            _historyIndex = _history.Count - 1;
            ShowEntryById(id);
            return;
        }

        FillShuffleBag();
        if (_shuffleBag.Count > 0)
            NextWord();
    }

    private void PreviousWord()
    {
        if (_historyIndex <= 0)
        {
            AnnounceStatus("No earlier word in this session.");
            FocusCurrentWord();
            return;
        }

        int candidate = _historyIndex - 1;
        while (candidate >= 0)
        {
            string id = _history[candidate];
            if (_deckMap.GetValueOrDefault(id, 1) == _activeDeck)
            {
                _historyIndex = candidate;
                ShowEntryById(id);
                return;
            }
            candidate--;
        }

        AnnounceStatus("No earlier word remaining in this deck.");
        FocusCurrentWord();
    }

    private void ShowEntryById(string id)
    {
        if (!_entriesById.TryGetValue(id, out DictionaryEntry? entry))
            return;

        _current = entry;
        _wordBox.Text = entry.Source;
        _translationBox.Clear();
        _statusLabel.Text = $"Level {entry.Level}. Deck {_activeDeck}.";
        UpdateCounts();
        FocusCurrentWord();
        AccessibilityAnnouncer.Announce(_wordBox, entry.Source);
    }

    private void RevealTranslation()
    {
        if (_current is null)
            return;

        _translationBox.Text = _current.Target;
        _translationBox.Focus();
        _translationBox.SelectAll();
        AccessibilityAnnouncer.Announce(_translationBox, _current.Target);
    }

    private void RepeatCurrentWord()
    {
        if (_current is null)
            return;

        FocusCurrentWord();
        AccessibilityAnnouncer.Announce(_wordBox, _current.Source);
    }

    private void FocusCurrentWord()
    {
        _wordBox.Focus();
        _wordBox.SelectAll();
    }

    private void MoveCurrentToDeck(int targetDeck)
    {
        if (_current is null)
            return;

        targetDeck = Math.Clamp(targetDeck, 1, 5);
        int fromDeck = _deckMap.GetValueOrDefault(_current.Id, 1);
        string movedWord = _current.Source;

        if (targetDeck == fromDeck)
        {
            AnnounceStatus($"{movedWord} is already in deck {targetDeck}.");
            RepeatCurrentWord();
            return;
        }

        _deckMap[_current.Id] = targetDeck;
        _lastMove = new MoveUndo(_package.Id, _current.Id, fromDeck, targetDeck);
        _translationBox.Clear();
        UpdateCounts();
        SaveState();
        AnnounceStatus($"Moved {movedWord} from deck {fromDeck} to deck {targetDeck}. Undo is available.");
        NextWord();
    }

    private void UndoLastMove()
    {
        MoveUndo? undo = _lastMove;
        if (undo is null || !string.Equals(undo.DictionaryId, _package.Id, StringComparison.OrdinalIgnoreCase))
        {
            AnnounceStatus("No deck move is available to undo.");
            RepeatCurrentWord();
            return;
        }

        if (!_entriesById.TryGetValue(undo.EntryId, out DictionaryEntry? entry))
        {
            _lastMove = null;
            AnnounceStatus("The previous deck move can no longer be undone.");
            RepeatCurrentWord();
            return;
        }

        int currentDeck = _deckMap.GetValueOrDefault(undo.EntryId, 1);
        if (currentDeck != undo.ToDeck)
        {
            _lastMove = null;
            AnnounceStatus("The previous deck move has already changed and can no longer be undone.");
            RepeatCurrentWord();
            return;
        }

        _deckMap[undo.EntryId] = undo.FromDeck;
        _lastMove = null;
        UpdateCounts();
        SaveState();

        if (_activeDeck == undo.FromDeck)
        {
            ShowEntryById(undo.EntryId);
            AnnounceStatus($"Undid move. {entry.Source} is back in deck {undo.FromDeck}.");
        }
        else
        {
            AnnounceStatus($"Undid move. {entry.Source} is back in deck {undo.FromDeck}.");
            RepeatCurrentWord();
        }
    }

    private void UpdateCounts()
    {
        int count = _package.Entries.Count(entry => _deckMap.GetValueOrDefault(entry.Id, 1) == _activeDeck);
        _countLabel.Text = $"Deck {_activeDeck}: {count} words. Dictionary total: {_package.Entries.Count}.";
    }

    private void AnnounceStatus(string text)
    {
        _statusLabel.Text = text;
        AccessibilityAnnouncer.Announce(_statusLabel, text);
    }

    private void ImportDictionary()
    {
        using var dialog = new OpenFileDialog
        {
            Title = "Import WordDeck dictionary",
            Filter = "WordDeck TSV dictionaries (*.tsv)|*.tsv|All files (*.*)|*.*"
        };
        if (dialog.ShowDialog(this) != DialogResult.OK)
            return;

        try
        {
            DictionaryPackage package = DictionaryLoader.LoadFromFile(dialog.FileName);
            string savedPath = _store.ImportDictionary(dialog.FileName);
            package = DictionaryLoader.LoadFromFile(savedPath);
            _packages[package.Id] = package;
            PopulateDictionaryCombo();
            int index = ((List<DictionaryPackage>)_dictionaryCombo.DataSource!).FindIndex(x => x.Id == package.Id);
            _dictionaryCombo.SelectedIndex = index;
            AnnounceStatus($"Imported {package.Name}: {package.Entries.Count} entries.");
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "Dictionary import failed", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private void OpenShortcutSettings()
    {
        using var dialog = new ShortcutSettingsForm(_shortcuts);
        dialog.ShowDialog(this);
        SaveState();
        RepeatCurrentWord();
    }

    private void ShowHelp()
    {
        string shortcutLines = string.Join(Environment.NewLine,
            ShortcutManager.Definitions.Select(def => $"{def.Description}: {_shortcuts.Get(def.Id)}"));
        string help =
            "WORDDECK HELP\r\n\r\n" +
            "WordDeck shows only the English side of a card by default. Reveal the Ukrainian translation only when you need it. " +
            "Words are drawn from the active deck in a shuffled bag: every word is presented once before the deck is reshuffled.\r\n\r\n" +
            "Decks are user-controlled. Move the current word directly to any of the five decks. If you move a word accidentally, use Undo last deck move. " +
            "Switching decks changes which set you are training. All progress is saved locally in your Windows user profile and a recovery backup is maintained.\r\n\r\n" +
            "KEYBOARD SHORTCUTS\r\n" + shortcutLines + "\r\n\r\n" +
            "Use Tools > Keyboard shortcuts to reassign shortcuts. Use File > Import dictionary to add another WordDeck TSV dictionary.";

        using var form = new Form
        {
            Text = "WordDeck help",
            Width = 760,
            Height = 600,
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
            AccessibleName = "WordDeck help text"
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

    protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
    {
        string? action = _shortcuts.FindAction(keyData);
        if (action is null)
            return base.ProcessCmdKey(ref msg, keyData);

        if (action == ActionIds.NextWord) NextWord();
        else if (action == ActionIds.PreviousWord) PreviousWord();
        else if (action == ActionIds.RevealTranslation) RevealTranslation();
        else if (action == ActionIds.RepeatWord) RepeatCurrentWord();
        else if (action == ActionIds.UndoMove) UndoLastMove();
        else if (action == ActionIds.ShortcutSettings) OpenShortcutSettings();
        else if (action == ActionIds.Help) ShowHelp();
        else
        {
            for (int deck = 1; deck <= 5; deck++)
            {
                if (action == ActionIds.SwitchDeck(deck))
                {
                    SwitchDeck(deck);
                    break;
                }
                if (action == ActionIds.MoveToDeck(deck))
                {
                    MoveCurrentToDeck(deck);
                    break;
                }
            }
        }
        return true;
    }

    private void SaveState()
    {
        _state.ActiveDictionaryId = _package?.Id;
        _state.ActiveDeck = _activeDeck;
        _store.Save(_state);
    }
}
