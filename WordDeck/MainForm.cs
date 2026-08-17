namespace WordDeck;

internal sealed class MainForm : Form
{
    private sealed record MoveUndo(string DictionaryId, string EntryId, string FromDeckId, string ToDeckId);

    private readonly AppStateStore _store = new();
    private readonly AppState _state;
    private readonly DeckService _decks;
    private readonly ShortcutManager _shortcuts;
    private readonly PronunciationAudio _audio = new();
    private readonly Dictionary<string, DictionaryPackage> _packages = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, DictionaryEntry> _entriesById = new(StringComparer.OrdinalIgnoreCase);
    private DictionaryPackage _package = null!;
    private Dictionary<string, string> _deckMap = null!;
    private string _activeDeckId = DeckIds.Core(1);
    private readonly Random _random = new();
    private readonly Queue<string> _shuffleBag = new();
    private DictionaryEntry? _current;
    private MoveUndo? _lastMove;

    private readonly ComboBox _dictionaryCombo;
    private readonly ComboBox _deckCombo;
    private readonly TextBox _wordBox;
    private readonly TextBox _translationBox;
    private readonly Label _statusLabel;
    private readonly Label _countLabel;
    private ToolStripMenuItem _deckMenu = null!;
    private ToolStripMenuItem _switchDeckMenu = null!;
    private ToolStripMenuItem _autoPronunciationMenuItem = null!;

    public MainForm()
    {
        _state = _store.Load();
        _decks = new DeckService(_state);
        _shortcuts = new ShortcutManager(_state);
        LoadPackages();

        Text = "WordDeck";
        Width = 920;
        Height = 520;
        MinimumSize = new Size(640, 400);
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
            Width = 220,
            DisplayMember = nameof(DeckDefinition.Name),
            AccessibleName = "Active deck",
            AccessibleDescription = "Choose any default or user-created deck to study."
        };
        _deckCombo.SelectedIndexChanged += (_, _) =>
        {
            if (_deckCombo.SelectedItem is DeckDefinition deck &&
                !string.Equals(deck.Id, _activeDeckId, StringComparison.OrdinalIgnoreCase))
                SwitchDeck(deck.Id);
        };
        top.Controls.Add(_deckCombo);

        _countLabel = new Label
        {
            AutoSize = true,
            AccessibleName = "All deck word counts",
            AccessibleDescription = "Word counts for every deck in the active dictionary.",
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
            Text = "F1: help. Ctrl+S saves now. All shortcuts can be reassigned in Tools > Keyboard shortcuts."
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
        Shown += (_, _) => BeginInvoke(new Action(RestoreCurrentOrNextWord));
        FormClosing += (_, _) =>
        {
            _audio.Dispose();
            SaveState();
        };
    }

    private MenuStrip BuildMenu()
    {
        var menu = new MenuStrip { AccessibleName = "Application menu" };
        var file = new ToolStripMenuItem("&File");
        var addWords = new ToolStripMenuItem("&Add pasted words to active deck...");
        addWords.Click += (_, _) => AddWordsToActiveDeck();
        var save = new ToolStripMenuItem("&Save progress now");
        save.Click += (_, _) => SaveProgressNow();
        var import = new ToolStripMenuItem("&Import dictionary...");
        import.Click += (_, _) => ImportDictionary();
        var exit = new ToolStripMenuItem("E&xit");
        exit.Click += (_, _) => Close();
        file.DropDownItems.Add(addWords);
        file.DropDownItems.Add(save);
        file.DropDownItems.Add(new ToolStripSeparator());
        file.DropDownItems.Add(import);
        file.DropDownItems.Add(new ToolStripSeparator());
        file.DropDownItems.Add(exit);

        _deckMenu = new ToolStripMenuItem("&Deck");
        var moveCurrent = new ToolStripMenuItem("&Move current word to deck...");
        moveCurrent.Click += (_, _) => MoveCurrentToDeckChooser();
        var undoMove = new ToolStripMenuItem("&Undo last deck move");
        undoMove.Click += (_, _) => UndoLastMove();
        var createDeck = new ToolStripMenuItem("&Create deck...");
        createDeck.Click += (_, _) => CreateDeck();
        var renameDeck = new ToolStripMenuItem("&Rename active deck...");
        renameDeck.Click += (_, _) => RenameActiveDeck();
        var deleteDeck = new ToolStripMenuItem("&Delete active user deck...");
        deleteDeck.Click += (_, _) => DeleteActiveDeck();
        var moveUp = new ToolStripMenuItem("Move active deck &up");
        moveUp.Click += (_, _) => ReorderActiveDeck(-1);
        var moveDown = new ToolStripMenuItem("Move active deck &down");
        moveDown.Click += (_, _) => ReorderActiveDeck(1);
        _switchDeckMenu = new ToolStripMenuItem("&Switch deck");

        _deckMenu.DropDownItems.Add(moveCurrent);
        _deckMenu.DropDownItems.Add(undoMove);
        _deckMenu.DropDownItems.Add(new ToolStripSeparator());
        _deckMenu.DropDownItems.Add(createDeck);
        _deckMenu.DropDownItems.Add(renameDeck);
        _deckMenu.DropDownItems.Add(deleteDeck);
        _deckMenu.DropDownItems.Add(moveUp);
        _deckMenu.DropDownItems.Add(moveDown);
        _deckMenu.DropDownItems.Add(new ToolStripSeparator());
        _deckMenu.DropDownItems.Add(_switchDeckMenu);

        var tools = new ToolStripMenuItem("&Tools");
        var playPronunciation = new ToolStripMenuItem("&Play generated British pronunciation");
        playPronunciation.Click += (_, _) => PlayCurrentPronunciation();
        _autoPronunciationMenuItem = new ToolStripMenuItem("&Automatic British pronunciation on card change")
        {
            Checked = _state.AutoPlayPronunciationOnCardChange,
            CheckOnClick = false,
            AccessibleName = "Automatic British pronunciation on card change"
        };
        _autoPronunciationMenuItem.Click += (_, _) => ToggleAutoPronunciation();
        var shortcuts = new ToolStripMenuItem("&Keyboard shortcuts...");
        shortcuts.Click += (_, _) => OpenShortcutSettings();
        tools.DropDownItems.Add(playPronunciation);
        tools.DropDownItems.Add(_autoPronunciationMenuItem);
        tools.DropDownItems.Add(new ToolStripSeparator());
        tools.DropDownItems.Add(shortcuts);

        var help = new ToolStripMenuItem("&Help");
        var helpItem = new ToolStripMenuItem("&WordDeck help");
        helpItem.Click += (_, _) => ShowHelp();
        help.DropDownItems.Add(helpItem);

        menu.Items.Add(file);
        menu.Items.Add(_deckMenu);
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

    private void ActivatePackage(DictionaryPackage basePackage)
    {
        _package = WithCustomEntries(basePackage);
        _state.ActiveDictionaryId = basePackage.Id;
        _lastMove = null;
        ReindexEntries();

        _deckMap = _decks.EnsureDictionaryAssignments(_package.Id, _package.Entries.Select(entry => entry.Id));
        string desiredDeckId = _state.ActiveDeckId ?? _decks.FirstDeck.Id;
        _activeDeckId = _decks.Find(desiredDeckId)?.Id ?? _decks.FirstDeck.Id;
        _state.ActiveDeckId = _activeDeckId;

        RefreshDeckUi();
        ResetSequence();
        UpdateCounts();
        SaveState();
    }

    private DictionaryPackage WithCustomEntries(DictionaryPackage basePackage)
    {
        if (!_state.CustomEntriesByDictionary.TryGetValue(basePackage.Id, out List<CustomEntryRecord>? custom) || custom.Count == 0)
            return basePackage;

        var baseIds = new HashSet<string>(basePackage.Entries.Select(entry => entry.Id), StringComparer.OrdinalIgnoreCase);
        var entries = new List<DictionaryEntry>(basePackage.Entries);
        foreach (CustomEntryRecord record in custom)
        {
            if (baseIds.Add(record.Id))
                entries.Add(new DictionaryEntry(record.Id, record.Level, record.Source, record.Target));
        }

        return new DictionaryPackage
        {
            Id = basePackage.Id,
            Name = basePackage.Name,
            SourceLanguage = basePackage.SourceLanguage,
            TargetLanguage = basePackage.TargetLanguage,
            Entries = entries
        };
    }

    private void ReindexEntries()
    {
        _entriesById.Clear();
        foreach (DictionaryEntry entry in _package.Entries)
            _entriesById[entry.Id] = entry;
    }

    private void RefreshDeckUi()
    {
        IReadOnlyList<DeckDefinition> ordered = _decks.Decks;
        _deckCombo.BeginUpdate();
        _deckCombo.Items.Clear();
        foreach (DeckDefinition deck in ordered)
            _deckCombo.Items.Add(deck);
        int selectedIndex = ordered.ToList().FindIndex(deck => string.Equals(deck.Id, _activeDeckId, StringComparison.OrdinalIgnoreCase));
        if (selectedIndex >= 0)
            _deckCombo.SelectedIndex = selectedIndex;
        _deckCombo.EndUpdate();

        _shortcuts.RefreshDeckDefinitions();
        RebuildSwitchDeckMenu();
    }

    private void RebuildSwitchDeckMenu()
    {
        _switchDeckMenu.DropDownItems.Clear();
        foreach (DeckDefinition deck in _decks.Decks)
        {
            string deckId = deck.Id;
            int count = _package is null ? 0 : _decks.CountInDictionary(_package.Id, deck.Id);
            var item = new ToolStripMenuItem($"{deck.Name} ({count} words)")
            {
                Checked = string.Equals(deck.Id, _activeDeckId, StringComparison.OrdinalIgnoreCase),
                AccessibleName = $"Switch to {deck.Name}, {count} words"
            };
            item.Click += (_, _) => SwitchDeck(deckId);
            _switchDeckMenu.DropDownItems.Add(item);
        }
    }

    private void SwitchDeck(string deckId)
    {
        DeckDefinition? deck = _decks.Find(deckId);
        if (deck is null)
            return;

        _activeDeckId = deck.Id;
        _state.ActiveDeckId = deck.Id;
        SelectActiveDeckInCombo();
        RebuildSwitchDeckMenu();
        ResetSequence();
        UpdateCounts();
        _statusLabel.Text = $"Switched to {deck.Name}.";
        NextWord();
        SaveState();
    }

    private void SelectActiveDeckInCombo()
    {
        for (int i = 0; i < _deckCombo.Items.Count; i++)
        {
            if (_deckCombo.Items[i] is DeckDefinition deck && string.Equals(deck.Id, _activeDeckId, StringComparison.OrdinalIgnoreCase))
            {
                if (_deckCombo.SelectedIndex != i)
                    _deckCombo.SelectedIndex = i;
                return;
            }
        }
    }

    private IReadOnlyList<DictionaryEntry> EntriesInActiveDeck() =>
        _package.Entries.Where(entry => string.Equals(_deckMap.GetValueOrDefault(entry.Id, _decks.FirstDeck.Id), _activeDeckId, StringComparison.OrdinalIgnoreCase)).ToList();

    private void ResetSequence()
    {
        _shuffleBag.Clear();
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

    private void RestoreCurrentOrNextWord()
    {
        if (_state.CurrentEntryIdByDictionary.TryGetValue(_package.Id, out string? id) &&
            _entriesById.ContainsKey(id) &&
            string.Equals(_deckMap.GetValueOrDefault(id, _decks.FirstDeck.Id), _activeDeckId, StringComparison.OrdinalIgnoreCase))
        {
            ShowEntryById(id);
            RemoveFromShuffleBag(id);
            return;
        }
        NextWord();
    }

    private void RemoveFromShuffleBag(string id)
    {
        string[] remaining = _shuffleBag.Where(candidate => !string.Equals(candidate, id, StringComparison.OrdinalIgnoreCase)).ToArray();
        _shuffleBag.Clear();
        foreach (string candidate in remaining)
            _shuffleBag.Enqueue(candidate);
    }

    private void NextWord()
    {
        IReadOnlyList<DictionaryEntry> active = EntriesInActiveDeck();
        DeckDefinition activeDeck = _decks.Find(_activeDeckId) ?? _decks.FirstDeck;
        if (active.Count == 0)
        {
            _audio.Stop();
            _current = null;
            _wordBox.Text = "No words in this deck";
            _translationBox.Clear();
            _statusLabel.Text = $"{activeDeck.Name} is empty.";
            UpdateCounts();
            _wordBox.Focus();
            AccessibilityAnnouncer.Announce(_wordBox, _wordBox.Text);
            return;
        }

        if (_shuffleBag.Count == 0)
            FillShuffleBag();

        while (_shuffleBag.Count > 0)
        {
            string id = _shuffleBag.Dequeue();
            if (!string.Equals(_deckMap.GetValueOrDefault(id, _decks.FirstDeck.Id), _activeDeckId, StringComparison.OrdinalIgnoreCase))
                continue;

            ShowEntryById(id);
            return;
        }

        FillShuffleBag();
        if (_shuffleBag.Count > 0)
            NextWord();
    }

    private void ShowEntryById(string id)
    {
        if (!_entriesById.TryGetValue(id, out DictionaryEntry? entry))
            return;

        _current = entry;
        _wordBox.Text = entry.Source;
        _translationBox.Clear();
        string deckName = _decks.Find(_activeDeckId)?.Name ?? "Deck";
        _statusLabel.Text = $"Level {entry.Level}. {deckName}.";
        UpdateCounts();
        FocusCurrentWord();

        bool nativeAudioPlayed = _state.AutoPlayPronunciationOnCardChange && TryPlayCurrentPronunciation(announceFailure: false);
        if (!nativeAudioPlayed)
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

    private void PlayCurrentPronunciation()
    {
        if (_current is null)
        {
            AnnounceStatus("No word is currently selected.");
            return;
        }

        TryPlayCurrentPronunciation(announceFailure: true);
    }

    private bool TryPlayCurrentPronunciation(bool announceFailure)
    {
        if (_current is null)
            return false;

        if (_audio.TryPlay(_package, _current, out string? error))
            return true;

        if (announceFailure && !string.IsNullOrWhiteSpace(error))
            AnnounceStatus(error);
        return false;
    }

    private void ToggleAutoPronunciation()
    {
        _state.AutoPlayPronunciationOnCardChange = !_state.AutoPlayPronunciationOnCardChange;
        _autoPronunciationMenuItem.Checked = _state.AutoPlayPronunciationOnCardChange;
        SaveState();

        if (_state.AutoPlayPronunciationOnCardChange)
        {
            AnnounceStatus("Automatic British pronunciation enabled.");
            if (_current is not null)
                TryPlayCurrentPronunciation(announceFailure: true);
        }
        else
        {
            _audio.Stop();
            AnnounceStatus("Automatic British pronunciation disabled. Screen-reader word announcements remain enabled.");
        }
    }

    private void FocusCurrentWord()
    {
        _wordBox.Focus();
        _wordBox.SelectAll();
    }

    private void AddWordsToActiveDeck()
    {
        DeckDefinition activeDeck = _decks.Find(_activeDeckId) ?? _decks.FirstDeck;
        using var dialog = new BulkWordImportForm(activeDeck.Name);
        if (dialog.ShowDialog(this) != DialogResult.OK)
            return;

        try
        {
            IReadOnlyList<WordPair> pairs = BulkWordParser.Parse(dialog.PastedText);
            if (!_state.CustomEntriesByDictionary.TryGetValue(_package.Id, out List<CustomEntryRecord>? custom))
            {
                custom = new List<CustomEntryRecord>();
                _state.CustomEntriesByDictionary[_package.Id] = custom;
            }

            var existingPairs = new HashSet<string>(
                _package.Entries.Select(entry => PairKey(entry.Source, entry.Target)),
                StringComparer.OrdinalIgnoreCase);
            var addedIds = new List<string>();
            foreach (WordPair pair in pairs)
            {
                if (!existingPairs.Add(PairKey(pair.Source, pair.Target)))
                    continue;

                string id;
                do
                {
                    id = $"custom-{Guid.NewGuid():N}";
                }
                while (_entriesById.ContainsKey(id));

                custom.Add(new CustomEntryRecord(id, pair.Source, pair.Target));
                addedIds.Add(id);
            }

            if (addedIds.Count == 0)
            {
                AnnounceStatus("No new cards were added because all pasted pairs already exist in this dictionary.");
                return;
            }

            DictionaryPackage basePackage = _packages[_package.Id];
            _package = WithCustomEntries(basePackage);
            ReindexEntries();
            _deckMap = _decks.EnsureDictionaryAssignments(_package.Id, _package.Entries.Select(entry => entry.Id));
            foreach (string id in addedIds)
                _deckMap[id] = _activeDeckId;

            ResetSequence();
            RebuildSwitchDeckMenu();
            UpdateCounts();
            ShowEntryById(addedIds[0]);
            RemoveFromShuffleBag(addedIds[0]);
            SaveState();
            AnnounceStatus($"Added {addedIds.Count} new cards to {activeDeck.Name}. Custom cards are saved locally. Generated pronunciation is optional and may be absent for these cards.");
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "Cannot add words", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private static string PairKey(string source, string target) => source.Trim() + "\u001f" + target.Trim();

    private void MoveCurrentToDeckChooser()
    {
        if (_current is null)
        {
            AnnounceStatus("No word is currently selected.");
            return;
        }

        string? target = DeckDialogs.ChooseDeck(
            this,
            "Move current word",
            $"Move {_current.Source} to which deck?",
            _decks.Decks,
            _activeDeckId);
        if (target is not null)
            MoveCurrentToDeck(target);
    }

    private void MoveCurrentToDeck(string targetDeckId)
    {
        if (_current is null)
            return;

        DeckDefinition? targetDeck = _decks.Find(targetDeckId);
        if (targetDeck is null)
            return;
        string fromDeckId = _deckMap.GetValueOrDefault(_current.Id, _decks.FirstDeck.Id);
        DeckDefinition fromDeck = _decks.Find(fromDeckId) ?? _decks.FirstDeck;
        string movedWord = _current.Source;

        if (string.Equals(targetDeck.Id, fromDeck.Id, StringComparison.OrdinalIgnoreCase))
        {
            AnnounceStatus($"{movedWord} is already in {targetDeck.Name}.");
            RepeatCurrentWord();
            return;
        }

        _deckMap[_current.Id] = targetDeck.Id;
        _lastMove = new MoveUndo(_package.Id, _current.Id, fromDeck.Id, targetDeck.Id);
        _translationBox.Clear();
        UpdateCounts();
        RebuildSwitchDeckMenu();
        SaveState();
        AnnounceStatus($"Moved {movedWord} from {fromDeck.Name} to {targetDeck.Name}. Undo is available.");
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

        if (!_entriesById.TryGetValue(undo.EntryId, out DictionaryEntry? entry) ||
            _decks.Find(undo.FromDeckId) is not DeckDefinition fromDeck ||
            _decks.Find(undo.ToDeckId) is not DeckDefinition toDeck)
        {
            _lastMove = null;
            AnnounceStatus("The previous deck move can no longer be undone.");
            RepeatCurrentWord();
            return;
        }

        string currentDeckId = _deckMap.GetValueOrDefault(undo.EntryId, _decks.FirstDeck.Id);
        if (!string.Equals(currentDeckId, undo.ToDeckId, StringComparison.OrdinalIgnoreCase))
        {
            _lastMove = null;
            AnnounceStatus("The previous deck move has already changed and can no longer be undone.");
            RepeatCurrentWord();
            return;
        }

        _deckMap[undo.EntryId] = undo.FromDeckId;
        _lastMove = null;
        UpdateCounts();
        RebuildSwitchDeckMenu();
        SaveState();

        if (string.Equals(_activeDeckId, undo.FromDeckId, StringComparison.OrdinalIgnoreCase))
        {
            ShowEntryById(undo.EntryId);
            AnnounceStatus($"Undid move. {entry.Source} is back in {fromDeck.Name}.");
        }
        else
        {
            AnnounceStatus($"Undid move. {entry.Source} is back in {fromDeck.Name}; it was removed from {toDeck.Name}.");
            RepeatCurrentWord();
        }
    }

    private void CreateDeck()
    {
        string? name = DeckDialogs.PromptForName(this, "Create deck", "Enter a name for the new empty deck:");
        if (name is null)
            return;

        try
        {
            DeckDefinition deck = _decks.Create(name);
            _activeDeckId = deck.Id;
            _state.ActiveDeckId = deck.Id;
            _shortcuts.RefreshDeckDefinitions();
            RefreshDeckUi();
            ResetSequence();
            UpdateCounts();
            SaveState();
            AnnounceStatus($"Created empty deck {deck.Name}. It is now active. Assign switch and move shortcuts in Keyboard shortcuts if desired.");
            NextWord();
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "Cannot create deck", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private void RenameActiveDeck()
    {
        DeckDefinition? deck = _decks.Find(_activeDeckId);
        if (deck is null)
            return;
        string? name = DeckDialogs.PromptForName(this, "Rename deck", "Enter the new deck name:", deck.Name);
        if (name is null)
            return;

        try
        {
            _decks.Rename(deck.Id, name);
            _shortcuts.RefreshDeckDefinitions();
            RefreshDeckUi();
            UpdateCounts();
            SaveState();
            AnnounceStatus($"Deck renamed to {deck.Name}. Its stable ID, word assignments, and shortcuts were preserved.");
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "Cannot rename deck", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private void DeleteActiveDeck()
    {
        DeckDefinition? deck = _decks.Find(_activeDeckId);
        if (deck is null)
            return;
        if (deck.IsCore)
        {
            AnnounceStatus("The five default decks are permanent. You can rename or reorder this deck, but you cannot delete it.");
            return;
        }

        int assigned = _decks.CountEverywhere(deck.Id);
        string? destination = null;
        if (assigned > 0)
        {
            destination = DeckDialogs.ChooseDeck(
                this,
                "Delete non-empty deck",
                $"{deck.Name} contains {assigned} word assignments across dictionaries. Choose a destination for every word, or cancel deletion:",
                _decks.Decks.Where(candidate => !string.Equals(candidate.Id, deck.Id, StringComparison.OrdinalIgnoreCase)),
                DeckIds.Core(1));
            if (destination is null)
                return;
        }
        else
        {
            DialogResult result = MessageBox.Show(
                this,
                $"Delete empty deck {deck.Name}?",
                "Delete deck",
                MessageBoxButtons.YesNo,
                MessageBoxIcon.Question,
                MessageBoxDefaultButton.Button2);
            if (result != DialogResult.Yes)
                return;
        }

        try
        {
            string deletedName = deck.Name;
            _decks.DeleteUserDeck(deck.Id, destination);
            _activeDeckId = _state.ActiveDeckId ?? _decks.FirstDeck.Id;
            _lastMove = null;
            _shortcuts.RefreshDeckDefinitions();
            RefreshDeckUi();
            ResetSequence();
            UpdateCounts();
            SaveState();
            AnnounceStatus(assigned > 0
                ? $"Deleted {deletedName}. All {assigned} word assignments were moved safely to {_decks.Find(destination!)?.Name}."
                : $"Deleted empty deck {deletedName}.");
            NextWord();
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "Cannot delete deck", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private void ReorderActiveDeck(int direction)
    {
        DeckDefinition? deck = _decks.Find(_activeDeckId);
        if (deck is null)
            return;
        if (!_decks.Move(deck.Id, direction))
        {
            AnnounceStatus(direction < 0 ? "This deck is already first." : "This deck is already last.");
            return;
        }

        RefreshDeckUi();
        UpdateCounts();
        SaveState();
        AnnounceStatus($"Moved {deck.Name} {(direction < 0 ? "up" : "down")} in the deck order. Its shortcuts and word assignments were preserved.");
    }

    private void UpdateCounts()
    {
        if (_package is null)
            return;
        string summary = string.Join("; ", _decks.Decks.Select(deck =>
        {
            int count = _decks.CountInDictionary(_package.Id, deck.Id);
            string active = string.Equals(deck.Id, _activeDeckId, StringComparison.OrdinalIgnoreCase) ? " active" : string.Empty;
            return $"{deck.Name}: {count} words{active}";
        }));
        _countLabel.Text = $"Deck counts — {summary}. Dictionary total: {_package.Entries.Count}.";
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
            AnnounceStatus($"Imported {package.Name}: {package.Entries.Count} entries. New entries start in {_decks.FirstDeck.Name}.");
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "Dictionary import failed", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    private void SaveProgressNow()
    {
        SaveState();
        AnnounceStatus("Progress saved locally. Deck assignments, custom cards, active deck and current card are stored.");
    }

    private void OpenShortcutSettings()
    {
        _shortcuts.RefreshDeckDefinitions();
        using var dialog = new ShortcutSettingsForm(_shortcuts);
        dialog.ShowDialog(this);
        SaveState();
        RepeatCurrentWord();
    }

    private void ShowHelp()
    {
        _shortcuts.RefreshDeckDefinitions();
        string shortcutLines = string.Join(Environment.NewLine,
            _shortcuts.Definitions.Select(def => $"{def.Description}: {FormatShortcut(_shortcuts.Get(def.Id))}"));
        string audioMode = _state.AutoPlayPronunciationOnCardChange ? "enabled" : "disabled";
        string help =
            "WORDDECK HELP\r\n\r\n" +
            "WordDeck shows only the English side of a card by default. Reveal the Ukrainian translation only when you need it. " +
            "Both navigation shortcuts draw another random card from the active deck. Every word is presented once before the shuffle bag is refilled, and the refill avoids an immediate repeat when the deck has more than one word.\r\n\r\n" +
            "The original five default decks are permanent for compatibility, but they can be renamed and reordered. You can create any number of additional empty decks, rename them, reorder them, and delete user-created decks. " +
            "Deleting a non-empty user deck always requires choosing another deck for all of its words; cancelling leaves the deck untouched. Every deck owns stable switch and move-to shortcut actions, so renaming and reordering do not break its bindings.\r\n\r\n" +
            "To add your own cards to the active deck, use Add pasted words. Use one card per line. The safest format is English, TAB, Ukrainian. " +
            "The importer also accepts a pipe, equals sign, em dash, en dash, or comma+space between English and Ukrainian. Custom cards are saved locally and remain in their assigned decks after restart.\r\n\r\n" +
            "Generated British pronunciation is an optional offline audio layer keyed by stable dictionary and entry IDs. " +
            $"Automatic pronunciation on card change is currently {audioMode}. When automatic audio successfully starts, WordDeck suppresses its extra UI Automation word notification to reduce double speech; if audio is missing or cannot play, the normal screen-reader announcement remains the fallback. " +
            "Custom cards do not require generated audio; when no audio file exists, screen-reader pronunciation remains available.\r\n\r\n" +
            "Progress is saved automatically after deck changes and on normal exit. Save progress now provides an explicit manual checkpoint. The current dictionary, active deck and last card are restored on the next launch when still valid. A recovery backup is maintained.\r\n\r\n" +
            "KEYBOARD SHORTCUTS\r\n" + shortcutLines + "\r\n\r\n" +
            "Use Tools > Keyboard shortcuts to assign or reassign any shortcut. User-created deck switch and move shortcuts start unassigned. Use File > Import dictionary to add another WordDeck TSV dictionary.";

        using var form = new Form
        {
            Text = "WordDeck help",
            Width = 780,
            Height = 620,
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

    private static string FormatShortcut(Keys keys) => keys == Keys.None ? "Unassigned" : keys.ToString();

    protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
    {
        string? action = _shortcuts.FindAction(keyData);
        if (action is null)
            return base.ProcessCmdKey(ref msg, keyData);

        if (action == ActionIds.NextWord) NextWord();
        else if (action == ActionIds.RevealTranslation) RevealTranslation();
        else if (action == ActionIds.RepeatWord) RepeatCurrentWord();
        else if (action == ActionIds.PlayPronunciation) PlayCurrentPronunciation();
        else if (action == ActionIds.ToggleAutoPronunciation) ToggleAutoPronunciation();
        else if (action == ActionIds.AddWords) AddWordsToActiveDeck();
        else if (action == ActionIds.SaveProgress) SaveProgressNow();
        else if (action == ActionIds.UndoMove) UndoLastMove();
        else if (action == ActionIds.ShortcutSettings) OpenShortcutSettings();
        else if (action == ActionIds.Help) ShowHelp();
        else
        {
            foreach (DeckDefinition deck in _decks.Decks)
            {
                if (action == ActionIds.SwitchDeck(deck.Id))
                {
                    SwitchDeck(deck.Id);
                    break;
                }
                if (action == ActionIds.MoveToDeck(deck.Id))
                {
                    MoveCurrentToDeck(deck.Id);
                    break;
                }
            }
        }
        return true;
    }

    private void SaveState()
    {
        _state.ActiveDictionaryId = _package?.Id;
        _state.ActiveDeckId = _activeDeckId;
        if (_package is not null && _current is not null)
            _state.CurrentEntryIdByDictionary[_package.Id] = _current.Id;
        _store.Save(_state);
    }
}