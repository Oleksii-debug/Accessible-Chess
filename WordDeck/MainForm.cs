namespace WordDeck;

internal sealed partial class MainForm : Form
{
    private sealed record MoveUndo(string DictionaryId, string ScopeId, string EntryId, string FromDeckId, string ToDeckId);
    private sealed record ScopeOption(string Id, string Name)
    {
        public override string ToString() => Name;
    }

    private readonly AppStateStore _store = new();
    private readonly AppState _state;
    private readonly DeckService _decks;
    private readonly ShortcutManager _shortcuts;
    private readonly PronunciationAudio _audio = new();
    private readonly Dictionary<string, DictionaryPackage> _packages = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, DictionaryEntry> _entriesById = new(StringComparer.OrdinalIgnoreCase);
    private DictionaryPackage _package = null!;
    private RecallStudyScopeService _scopeService = null!;
    private Dictionary<string, string> _deckMap = null!;
    private string _activeDeckId = DeckIds.Core(1);
    private readonly Random _random = new();
    private readonly Queue<string> _shuffleBag = new();
    private DictionaryEntry? _current;
    private MoveUndo? _lastMove;
    private bool _changingScopeUi;

    private readonly ComboBox _dictionaryCombo;
    private readonly ComboBox _scopeCombo;
    private readonly ComboBox _deckCombo;
    private readonly TextBox _wordBox;
    private readonly TextBox _translationBox;
    private readonly Label _statusLabel;
    private readonly Label _countLabel;
    private ToolStripMenuItem _deckMenu = null!;
    private ToolStripMenuItem _switchDeckMenu = null!;
    private ToolStripMenuItem _autoPronunciationMenuItem = null!;

    private string ActiveScopeId => _scopeService?.ActiveScopeId ?? StudyScopeIds.All;

    public MainForm()
    {
        _state = _store.Load();
        _decks = new DeckService(_state);
        _shortcuts = new ShortcutManager(_state);
        LoadPackages();

        Text = "WordDeck";
        Width = 1040;
        Height = 540;
        MinimumSize = new Size(720, 420);
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
            Width = 300,
            AccessibleName = "Dictionary"
        };
        _dictionaryCombo.SelectedIndexChanged += (_, _) => ChangeDictionaryFromCombo();
        top.Controls.Add(_dictionaryCombo);

        top.Controls.Add(new Label { Text = "Study scope:", AutoSize = true, Padding = new Padding(12, 6, 4, 0) });
        _scopeCombo = new ComboBox
        {
            DropDownStyle = ComboBoxStyle.DropDownList,
            Width = 190,
            AccessibleName = "Recall study scope",
            AccessibleDescription = "Choose All Oxford 5000 or a CEFR workspace A1, A2, B1, B2, or C1. Each scope keeps independent Recall deck progress."
        };
        _scopeCombo.SelectedIndexChanged += (_, _) =>
        {
            if (!_changingScopeUi && _scopeCombo.SelectedItem is ScopeOption option &&
                !string.Equals(option.Id, ActiveScopeId, StringComparison.OrdinalIgnoreCase))
                SwitchStudyScope(option.Id);
        };
        top.Controls.Add(_scopeCombo);

        top.Controls.Add(new Label { Text = "Deck:", AutoSize = true, Padding = new Padding(12, 6, 4, 0) });
        _deckCombo = new ComboBox
        {
            DropDownStyle = ComboBoxStyle.DropDownList,
            Width = 190,
            DisplayMember = nameof(DeckDefinition.Name),
            AccessibleName = "Active Recall deck",
            AccessibleDescription = "Choose a deck inside the current Recall study scope."
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
            AccessibleName = "Current study scope deck counts",
            AccessibleDescription = "Word counts for every deck in the current Recall study scope.",
            Padding = new Padding(0, 8, 0, 8)
        };
        var wordHeading = new Label { Text = "English word", AutoSize = true, Font = new Font(Font, FontStyle.Bold) };
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

        var translationHeading = new Label { Text = "Translation (hidden until requested)", AutoSize = true, Font = new Font(Font, FontStyle.Bold) };
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

        _statusLabel = new Label { AutoSize = true, AccessibleName = "Status", Padding = new Padding(0, 8, 0, 0) };
        var hintLabel = new Label
        {
            AutoSize = true,
            AccessibleName = "Keyboard hint",
            Text = "Keyboard shortcuts are configurable. Open WordDeck help for the currently active bindings."
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
        var exportProfile = new ToolStripMenuItem("&Export personal progress profile...") { AccessibleName = "Export personal progress profile" };
        exportProfile.Click += (_, _) => ExportPersonalProfile();
        var importProfile = new ToolStripMenuItem("I&mport personal progress profile...") { AccessibleName = "Import personal progress profile" };
        importProfile.Click += (_, _) => ImportPersonalProfile();
        var resetLearning = new ToolStripMenuItem("&Reset Recall learning data...") { AccessibleName = "Reset Recall learning data with automatic backup" };
        resetLearning.Click += (_, _) => ResetLearningData();
        var import = new ToolStripMenuItem("&Import dictionary...");
        import.Click += (_, _) => ImportDictionary();
        var exit = new ToolStripMenuItem("E&xit");
        exit.Click += (_, _) => Close();
        file.DropDownItems.Add(addWords);
        file.DropDownItems.Add(save);
        file.DropDownItems.Add(new ToolStripSeparator());
        file.DropDownItems.Add(exportProfile);
        file.DropDownItems.Add(importProfile);
        file.DropDownItems.Add(resetLearning);
        file.DropDownItems.Add(new ToolStripSeparator());
        file.DropDownItems.Add(import);
        file.DropDownItems.Add(new ToolStripSeparator());
        file.DropDownItems.Add(exit);

        _deckMenu = new ToolStripMenuItem("&Deck");
        var moveCurrent = new ToolStripMenuItem("&Move current word to deck...");
        moveCurrent.Click += (_, _) => MoveCurrentToDeckChooser();
        var undoMove = new ToolStripMenuItem("&Undo last deck move");
        undoMove.Click += (_, _) => UndoLastMove();
        var hideCurrent = new ToolStripMenuItem("&Hide current word from study...") { AccessibleName = "Hide current word from Recall study" };
        hideCurrent.Click += (_, _) => HideCurrentWord();
        var restoreHidden = new ToolStripMenuItem("&Restore hidden word...") { AccessibleName = "Restore a hidden Recall word" };
        restoreHidden.Click += (_, _) => RestoreHiddenWord();
        var restoreAllHidden = new ToolStripMenuItem("Restore &all hidden words...") { AccessibleName = "Restore all hidden Recall words" };
        restoreAllHidden.Click += (_, _) => RestoreAllHiddenWords();
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
        _deckMenu.DropDownItems.Add(hideCurrent);
        _deckMenu.DropDownItems.Add(restoreHidden);
        _deckMenu.DropDownItems.Add(restoreAllHidden);
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
                // Broken optional imports must not block the embedded Oxford dictionary.
            }
        }
    }

    private void PopulateDictionaryCombo()
    {
        _dictionaryCombo.DisplayMember = "Name";
        _dictionaryCombo.ValueMember = "Id";
        _dictionaryCombo.DataSource = _packages.Values.OrderBy(x => x.Name).ToList();
    }

    private void PopulateScopeCombo()
    {
        _changingScopeUi = true;
        try
        {
            _scopeCombo.Items.Clear();
            foreach (string id in StudyScopeIds.Ordered)
                _scopeCombo.Items.Add(new ScopeOption(id, StudyScopeIds.DisplayName(id)));
            SelectActiveScopeInCombo();
        }
        finally
        {
            _changingScopeUi = false;
        }
    }

    private void SelectActiveScopeInCombo()
    {
        for (int i = 0; i < _scopeCombo.Items.Count; i++)
        {
            if (_scopeCombo.Items[i] is ScopeOption option && string.Equals(option.Id, ActiveScopeId, StringComparison.OrdinalIgnoreCase))
            {
                _scopeCombo.SelectedIndex = i;
                return;
            }
        }
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
            RestoreCurrentOrNextWord();
        }
    }

    private void ActivatePackage(DictionaryPackage basePackage)
    {
        _package = WithCustomEntries(basePackage);
        _state.ActiveDictionaryId = basePackage.Id;
        _lastMove = null;
        _navigationHistory.Clear();
        ReindexEntries();

        // Keep the legacy map reconciled first so first-time All migration is lossless.
        _decks.EnsureDictionaryAssignments(_package.Id, _package.Entries.Select(entry => entry.Id));
        _scopeService = new RecallStudyScopeService(_state, _package.Id, _package.Entries);
        _deckMap = _scopeService.Assignments(ActiveScopeId);
        _activeDeckId = _scopeService.Get(ActiveScopeId).ActiveDeckId;

        PopulateScopeCombo();
        RefreshDeckUi();
        RestoreSequenceForScope();
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
            if (baseIds.Add(record.Id)) entries.Add(new DictionaryEntry(record.Id, record.Level, record.Source, record.Target));
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
        foreach (DictionaryEntry entry in _package.Entries) _entriesById[entry.Id] = entry;
    }

    private void SwitchStudyScope(string scopeId)
    {
        if (!StudyScopeIds.Ordered.Contains(scopeId, StringComparer.OrdinalIgnoreCase)) return;
        PersistActiveShuffle();
        _scopeService.SetCurrentEntry(ActiveScopeId, _current?.Id);
        _scopeService.ActiveScopeId = scopeId;
        _deckMap = _scopeService.Assignments(scopeId);
        _activeDeckId = _scopeService.Get(scopeId).ActiveDeckId;
        _current = null;
        _lastMove = null;
        _navigationHistory.Clear();
        _translationBox.Clear();

        _changingScopeUi = true;
        try { SelectActiveScopeInCombo(); }
        finally { _changingScopeUi = false; }
        RefreshDeckUi();
        RestoreSequenceForScope();
        UpdateCounts();
        SaveState();
        AnnounceStatus($"Recall study scope: {StudyScopeIds.DisplayName(scopeId)}. {_scopeService.ScopeTotal(scopeId)} words in this scope.");
        RestoreCurrentOrNextWord();
    }

    private void RefreshDeckUi()
    {
        IReadOnlyList<DeckDefinition> ordered = _decks.Decks;
        _deckCombo.BeginUpdate();
        _deckCombo.Items.Clear();
        foreach (DeckDefinition deck in ordered) _deckCombo.Items.Add(deck);
        int selectedIndex = ordered.ToList().FindIndex(deck => string.Equals(deck.Id, _activeDeckId, StringComparison.OrdinalIgnoreCase));
        if (selectedIndex >= 0) _deckCombo.SelectedIndex = selectedIndex;
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
            int count = _scopeService is null ? 0 : _scopeService.Count(ActiveScopeId, deck.Id);
            var item = new ToolStripMenuItem($"{deck.Name} ({count} words)")
            {
                Checked = string.Equals(deck.Id, _activeDeckId, StringComparison.OrdinalIgnoreCase),
                AccessibleName = $"Switch to {deck.Name}, {count} words, scope {StudyScopeIds.DisplayName(ActiveScopeId)}"
            };
            item.Click += (_, _) => SwitchDeck(deckId);
            _switchDeckMenu.DropDownItems.Add(item);
        }
    }

    private void SwitchDeck(string deckId)
    {
        DeckDefinition? deck = _decks.Find(deckId);
        if (deck is null) return;
        PersistActiveShuffle();
        _activeDeckId = deck.Id;
        _scopeService.SetActiveDeck(ActiveScopeId, deck.Id);
        _scopeService.SetCurrentEntry(ActiveScopeId, null);
        _current = null;
        _navigationHistory.Clear();
        SelectActiveDeckInCombo();
        RebuildSwitchDeckMenu();
        ResetSequence();
        UpdateCounts();
        SaveState();
        AnnounceStatus($"{StudyScopeIds.DisplayName(ActiveScopeId)}: switched to {deck.Name}.");
        NextWord();
    }

    private void SelectActiveDeckInCombo()
    {
        for (int i = 0; i < _deckCombo.Items.Count; i++)
        {
            if (_deckCombo.Items[i] is DeckDefinition deck && string.Equals(deck.Id, _activeDeckId, StringComparison.OrdinalIgnoreCase))
            {
                if (_deckCombo.SelectedIndex != i) _deckCombo.SelectedIndex = i;
                return;
            }
        }
    }

    private IReadOnlyList<DictionaryEntry> EntriesInActiveDeck() =>
        _scopeService.EligibleEntries(ActiveScopeId)
            .Where(entry => !UserProgressService.IsHidden(_state, entry.Id))
            .Where(entry => string.Equals(_deckMap.GetValueOrDefault(entry.Id, _decks.FirstDeck.Id), _activeDeckId, StringComparison.OrdinalIgnoreCase))
            .ToList();

    private void ResetSequence()
    {
        _shuffleBag.Clear();
        _current = null;
        _scopeService.SetCurrentEntry(ActiveScopeId, null);
        FillShuffleBag();
    }

    private void RestoreSequenceForScope()
    {
        _shuffleBag.Clear();
        foreach (string id in _scopeService.RemainingShuffle(ActiveScopeId))
        {
            if (_entriesById.ContainsKey(id) && !UserProgressService.IsHidden(_state, id) &&
                string.Equals(_deckMap.GetValueOrDefault(id, _decks.FirstDeck.Id), _activeDeckId, StringComparison.OrdinalIgnoreCase))
                _shuffleBag.Enqueue(id);
        }
        if (_shuffleBag.Count == 0 && EntriesInActiveDeck().Count > 0) FillShuffleBag();
    }

    private void FillShuffleBag()
    {
        List<string> ids = EntriesInActiveDeck().Select(entry => entry.Id).ToList();
        for (int i = ids.Count - 1; i > 0; i--)
        {
            int j = _random.Next(i + 1);
            (ids[i], ids[j]) = (ids[j], ids[i]);
        }
        if (_current is not null && ids.Count > 1 && string.Equals(ids[0], _current.Id, StringComparison.OrdinalIgnoreCase))
            (ids[0], ids[1]) = (ids[1], ids[0]);
        _shuffleBag.Clear();
        foreach (string id in ids) _shuffleBag.Enqueue(id);
        PersistActiveShuffle();
    }

    private void PersistActiveShuffle()
    {
        if (_scopeService is not null) _scopeService.SetRemainingShuffle(ActiveScopeId, _shuffleBag);
    }

    private void RestoreCurrentOrNextWord()
    {
        string? id = _scopeService.Get(ActiveScopeId).CurrentEntryId;
        if (id is not null && _entriesById.ContainsKey(id) && !UserProgressService.IsHidden(_state, id) &&
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
        foreach (string candidate in remaining) _shuffleBag.Enqueue(candidate);
        PersistActiveShuffle();
    }

    private void NextWord()
    {
        if (TryShowForwardHistory()) return;
        IReadOnlyList<DictionaryEntry> active = EntriesInActiveDeck();
        DeckDefinition activeDeck = _decks.Find(_activeDeckId) ?? _decks.FirstDeck;
        if (active.Count == 0)
        {
            _audio.Stop();
            _current = null;
            _scopeService.SetCurrentEntry(ActiveScopeId, null);
            _wordBox.Text = "No words in this deck";
            _translationBox.Clear();
            _statusLabel.Text = $"{StudyScopeIds.DisplayName(ActiveScopeId)} — {activeDeck.Name} is empty.";
            UpdateCounts();
            SaveState();
            _wordBox.Focus();
            AccessibilityAnnouncer.Announce(_wordBox, _wordBox.Text);
            return;
        }

        if (_shuffleBag.Count == 0) FillShuffleBag();
        while (_shuffleBag.Count > 0)
        {
            string id = _shuffleBag.Dequeue();
            PersistActiveShuffle();
            if (!string.Equals(_deckMap.GetValueOrDefault(id, _decks.FirstDeck.Id), _activeDeckId, StringComparison.OrdinalIgnoreCase)) continue;
            ShowEntryById(id);
            return;
        }
        FillShuffleBag();
        if (_shuffleBag.Count > 0) NextWord();
    }

    private void ShowEntryById(string id)
    {
        if (!_entriesById.TryGetValue(id, out DictionaryEntry? entry)) return;
        if (UserProgressService.IsHidden(_state, id)) return;
        _current = entry;
        if (!_showingHistoryNavigation) _navigationHistory.Visit(id);
        UserProgressService.RecordSeen(_state, id, ActiveScopeId, _activeDeckId);
        _scopeService.SetCurrentEntry(ActiveScopeId, id);
        _wordBox.Text = entry.Source;
        _translationBox.Clear();
        string deckName = _decks.Find(_activeDeckId)?.Name ?? "Deck";
        _statusLabel.Text = $"Scope {StudyScopeIds.DisplayName(ActiveScopeId)}. Level {entry.Level}. {deckName}.";
        UpdateCounts();
        SaveState();
        FocusCurrentWord();
        bool nativeAudioPlayed = _state.AutoPlayPronunciationOnCardChange && TryPlayCurrentPronunciation(announceFailure: false);
        if (!nativeAudioPlayed) AccessibilityAnnouncer.Announce(_wordBox, entry.Source);
    }

    private void RevealTranslation()
    {
        if (_current is null) return;
        _translationBox.Text = _current.Target;
        UserProgressService.RecordTranslationReveal(_state, _current.Id);
        SaveState();
        _translationBox.Focus();
        _translationBox.SelectAll();
        AccessibilityAnnouncer.Announce(_translationBox, _current.Target);
    }

    private void RepeatCurrentWord()
    {
        if (_current is null) return;
        FocusCurrentWord();
        AccessibilityAnnouncer.Announce(_wordBox, _current.Source);
    }

    private void PlayCurrentPronunciation()
    {
        if (_current is null) { AnnounceStatus("No word is currently selected."); return; }
        TryPlayCurrentPronunciation(announceFailure: true);
    }

    private bool TryPlayCurrentPronunciation(bool announceFailure)
    {
        if (_current is null) return false;
        if (_audio.TryPlay(_package, _current, out string? error)) return true;
        if (announceFailure && !string.IsNullOrWhiteSpace(error)) AnnounceStatus(error);
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
            if (_current is not null) TryPlayCurrentPronunciation(announceFailure: true);
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
        if (!string.Equals(ActiveScopeId, StudyScopeIds.All, StringComparison.OrdinalIgnoreCase))
        {
            AnnounceStatus("Custom pasted cards are added only in All Oxford 5000 so CEFR workspaces remain limited to official level entries. Switch to All Oxford 5000 first.");
            return;
        }

        DeckDefinition activeDeck = _decks.Find(_activeDeckId) ?? _decks.FirstDeck;
        using var dialog = new BulkWordImportForm(activeDeck.Name);
        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        try
        {
            IReadOnlyList<WordPair> pairs = BulkWordParser.Parse(dialog.PastedText);
            if (!_state.CustomEntriesByDictionary.TryGetValue(_package.Id, out List<CustomEntryRecord>? custom))
            {
                custom = new List<CustomEntryRecord>();
                _state.CustomEntriesByDictionary[_package.Id] = custom;
            }
            var existingPairs = new HashSet<string>(_package.Entries.Select(entry => PairKey(entry.Source, entry.Target)), StringComparer.OrdinalIgnoreCase);
            var addedIds = new List<string>();
            foreach (WordPair pair in pairs)
            {
                if (!existingPairs.Add(PairKey(pair.Source, pair.Target))) continue;
                string id;
                do { id = $"custom-{Guid.NewGuid():N}"; } while (_entriesById.ContainsKey(id));
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
            Dictionary<string, string> legacy = _decks.EnsureDictionaryAssignments(_package.Id, _package.Entries.Select(entry => entry.Id));
            foreach (string id in addedIds) legacy[id] = _activeDeckId;
            _scopeService = new RecallStudyScopeService(_state, _package.Id, _package.Entries);
            _scopeService.ActiveScopeId = StudyScopeIds.All;
            _deckMap = _scopeService.Assignments(StudyScopeIds.All);
            foreach (string id in addedIds) _scopeService.Move(StudyScopeIds.All, id, _activeDeckId);

            ResetSequence();
            RebuildSwitchDeckMenu();
            UpdateCounts();
            ShowEntryById(addedIds[0]);
            RemoveFromShuffleBag(addedIds[0]);
            SaveState();
            AnnounceStatus($"Added {addedIds.Count} new cards to {activeDeck.Name} in All Oxford 5000. Custom cards are saved locally.");
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "Cannot add words", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
    }

    private static string PairKey(string source, string target) => source.Trim() + "\u001f" + target.Trim();

    private void MoveCurrentToDeckChooser()
    {
        if (_current is null) { AnnounceStatus("No word is currently selected."); return; }
        string? target = DeckDialogs.ChooseDeck(this, "Move current word", $"Move {_current.Source} to which deck in {StudyScopeIds.DisplayName(ActiveScopeId)}?", _decks.Decks, _activeDeckId);
        if (target is not null) MoveCurrentToDeck(target);
    }

    private void MoveCurrentToDeck(string targetDeckId)
    {
        if (_current is null) return;
        DeckDefinition? targetDeck = _decks.Find(targetDeckId);
        if (targetDeck is null) return;
        string fromDeckId = _deckMap.GetValueOrDefault(_current.Id, _decks.FirstDeck.Id);
        DeckDefinition fromDeck = _decks.Find(fromDeckId) ?? _decks.FirstDeck;
        string movedWord = _current.Source;
        if (string.Equals(targetDeck.Id, fromDeck.Id, StringComparison.OrdinalIgnoreCase))
        {
            AnnounceStatus($"{movedWord} is already in {targetDeck.Name} in {StudyScopeIds.DisplayName(ActiveScopeId)}.");
            RepeatCurrentWord();
            return;
        }

        string scopeId = ActiveScopeId;
        _scopeService.Move(scopeId, _current.Id, targetDeck.Id);
        _lastMove = new MoveUndo(_package.Id, scopeId, _current.Id, fromDeck.Id, targetDeck.Id);
        _translationBox.Clear();
        UpdateCounts();
        RebuildSwitchDeckMenu();
        SaveState();
        AnnounceStatus($"Moved {movedWord} from {fromDeck.Name} to {targetDeck.Name} in {StudyScopeIds.DisplayName(scopeId)}. Undo is available.");
        NextWord();
    }

    private void UndoLastMove()
    {
        MoveUndo? undo = _lastMove;
        if (undo is null || !string.Equals(undo.DictionaryId, _package.Id, StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(undo.ScopeId, ActiveScopeId, StringComparison.OrdinalIgnoreCase))
        {
            AnnounceStatus("No deck move is available to undo in the current study scope.");
            RepeatCurrentWord();
            return;
        }
        if (!_entriesById.TryGetValue(undo.EntryId, out DictionaryEntry? entry) || _decks.Find(undo.FromDeckId) is not DeckDefinition fromDeck || _decks.Find(undo.ToDeckId) is not DeckDefinition toDeck)
        {
            _lastMove = null;
            AnnounceStatus("The previous deck move can no longer be undone.");
            return;
        }
        string currentDeckId = _deckMap.GetValueOrDefault(undo.EntryId, _decks.FirstDeck.Id);
        if (!string.Equals(currentDeckId, undo.ToDeckId, StringComparison.OrdinalIgnoreCase))
        {
            _lastMove = null;
            AnnounceStatus("The previous deck move has already changed and can no longer be undone.");
            return;
        }
        _scopeService.Move(undo.ScopeId, undo.EntryId, undo.FromDeckId);
        _lastMove = null;
        UpdateCounts();
        RebuildSwitchDeckMenu();
        SaveState();
        if (string.Equals(_activeDeckId, undo.FromDeckId, StringComparison.OrdinalIgnoreCase))
        {
            ShowEntryById(undo.EntryId);
            AnnounceStatus($"Undid move. {entry.Source} is back in {fromDeck.Name} in {StudyScopeIds.DisplayName(undo.ScopeId)}.");
        }
        else AnnounceStatus($"Undid move. {entry.Source} is back in {fromDeck.Name}; it was removed from {toDeck.Name}.");
    }

    private void CreateDeck()
    {
        string? name = DeckDialogs.PromptForName(this, "Create deck", "Enter a name for the new empty deck:");
        if (name is null) return;
        try
        {
            DeckDefinition deck = _decks.Create(name);
            _activeDeckId = deck.Id;
            _scopeService.SetActiveDeck(ActiveScopeId, deck.Id);
            _shortcuts.RefreshDeckDefinitions();
            RefreshDeckUi();
            ResetSequence();
            UpdateCounts();
            SaveState();
            AnnounceStatus($"Created empty deck {deck.Name}. It is active in {StudyScopeIds.DisplayName(ActiveScopeId)}.");
            NextWord();
        }
        catch (Exception ex) { MessageBox.Show(this, ex.Message, "Cannot create deck", MessageBoxButtons.OK, MessageBoxIcon.Warning); }
    }

    private void RenameActiveDeck()
    {
        DeckDefinition? deck = _decks.Find(_activeDeckId);
        if (deck is null) return;
        string? name = DeckDialogs.PromptForName(this, "Rename deck", "Enter the new deck name:", deck.Name);
        if (name is null) return;
        try
        {
            _decks.Rename(deck.Id, name);
            _shortcuts.RefreshDeckDefinitions();
            RefreshDeckUi();
            UpdateCounts();
            SaveState();
            AnnounceStatus($"Deck renamed to {deck.Name}. Its stable ID and assignments in every study scope were preserved.");
        }
        catch (Exception ex) { MessageBox.Show(this, ex.Message, "Cannot rename deck", MessageBoxButtons.OK, MessageBoxIcon.Warning); }
    }

    private void DeleteActiveDeck()
    {
        DeckDefinition? deck = _decks.Find(_activeDeckId);
        if (deck is null) return;
        if (deck.IsCore) { AnnounceStatus("The five default decks are permanent and cannot be deleted."); return; }

        int scopeAssigned = _scopeService.CountEverywhere(deck.Id);
        int legacyAssigned = _decks.CountEverywhere(deck.Id);
        int assigned = Math.Max(scopeAssigned, legacyAssigned);
        string? destination = null;
        if (assigned > 0)
        {
            destination = DeckDialogs.ChooseDeck(this, "Delete non-empty deck", $"{deck.Name} has saved word assignments. Choose a destination deck for every Recall scope, or cancel deletion:", _decks.Decks.Where(candidate => !string.Equals(candidate.Id, deck.Id, StringComparison.OrdinalIgnoreCase)), DeckIds.Core(1));
            if (destination is null) return;
        }
        else
        {
            DialogResult result = MessageBox.Show(this, $"Delete empty deck {deck.Name}?", "Delete deck", MessageBoxButtons.YesNo, MessageBoxIcon.Question, MessageBoxDefaultButton.Button2);
            if (result != DialogResult.Yes) return;
        }

        try
        {
            string deletedName = deck.Name;
            if (destination is not null) _scopeService.ReplaceDeckEverywhere(deck.Id, destination);
            _decks.DeleteUserDeck(deck.Id, destination);
            _activeDeckId = _scopeService.Get(ActiveScopeId).ActiveDeckId;
            _lastMove = null;
            _shortcuts.RefreshDeckDefinitions();
            RefreshDeckUi();
            ResetSequence();
            UpdateCounts();
            SaveState();
            AnnounceStatus(assigned > 0 ? $"Deleted {deletedName}. Saved Recall assignments were moved to {_decks.Find(destination!)?.Name} across study scopes." : $"Deleted empty deck {deletedName}.");
            NextWord();
        }
        catch (Exception ex) { MessageBox.Show(this, ex.Message, "Cannot delete deck", MessageBoxButtons.OK, MessageBoxIcon.Warning); }
    }

    private void ReorderActiveDeck(int direction)
    {
        DeckDefinition? deck = _decks.Find(_activeDeckId);
        if (deck is null) return;
        if (!_decks.Move(deck.Id, direction))
        {
            AnnounceStatus(direction < 0 ? "This deck is already first." : "This deck is already last.");
            return;
        }
        RefreshDeckUi();
        UpdateCounts();
        SaveState();
        AnnounceStatus($"Moved {deck.Name} {(direction < 0 ? "up" : "down")} in shared deck order. Scope assignments were preserved.");
    }

    private void UpdateCounts()
    {
        if (_package is null || _scopeService is null) return;
        string scopeId = ActiveScopeId;
        string summary = string.Join("; ", _decks.Decks.Select(deck =>
        {
            int count = AvailableDeckCount(scopeId, deck.Id);
            string active = string.Equals(deck.Id, _activeDeckId, StringComparison.OrdinalIgnoreCase) ? " active" : string.Empty;
            return $"{deck.Name}: {count} available{active}";
        }));
        int canonical = _scopeService.ScopeTotal(scopeId);
        int available = AvailableScopeTotal(scopeId);
        int hidden = canonical - available;
        _countLabel.Text = $"Scope {StudyScopeIds.DisplayName(scopeId)} — {summary}. Available: {available}; canonical scope size: {canonical}; hidden in this scope: {hidden}.";
    }

    private void AnnounceStatus(string text)
    {
        _statusLabel.Text = text;
        AccessibilityAnnouncer.Announce(_statusLabel, text);
    }

    private void ImportDictionary()
    {
        using var dialog = new OpenFileDialog { Title = "Import WordDeck dictionary", Filter = "WordDeck TSV dictionaries (*.tsv)|*.tsv|All files (*.*)|*.*" };
        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        try
        {
            DictionaryPackage package = DictionaryLoader.LoadFromFile(dialog.FileName);
            string savedPath = _store.ImportDictionary(dialog.FileName);
            package = DictionaryLoader.LoadFromFile(savedPath);
            _packages[package.Id] = package;
            PopulateDictionaryCombo();
            int index = ((List<DictionaryPackage>)_dictionaryCombo.DataSource!).FindIndex(x => x.Id == package.Id);
            _dictionaryCombo.SelectedIndex = index;
            AnnounceStatus($"Imported {package.Name}: {package.Entries.Count} entries. Study scopes were initialized safely from CEFR levels.");
        }
        catch (Exception ex) { MessageBox.Show(this, ex.Message, "Dictionary import failed", MessageBoxButtons.OK, MessageBoxIcon.Error); }
    }

    private void SaveProgressNow()
    {
        SaveState();
        AnnounceStatus($"Progress saved locally for {StudyScopeIds.DisplayName(ActiveScopeId)}. Scope assignments, active deck, current card and shuffle progress are stored.");
    }

    private void OpenShortcutSettings()
    {
        _shortcuts.RefreshDeckDefinitions(new SpellingStateStore().Load().Decks);
        using var dialog = new ShortcutSettingsForm(_shortcuts);
        dialog.ShowDialog(this);
        SaveState();
        RefreshAccessibleShortcutPresentation(reloadPersistedShortcuts: false);
        RepeatCurrentWord();
    }

    private void ShowHelp()
    {
        _shortcuts.RefreshDeckDefinitions(new SpellingStateStore().Load().Decks);
        string shortcutLines = string.Join(Environment.NewLine, _shortcuts.Definitions.Select(def => $"{def.Description}: {ShortcutFormatter.Format(_shortcuts.Get(def.Id))}"));
        string audioMode = _state.AutoPlayPronunciationOnCardChange ? "enabled" : "disabled";
        string help =
            "WORDDECK HELP\r\n\r\n" +
            "SHORTCUT TRUTH\r\n" +
            "The KEYBOARD SHORTCUTS section at the end of this help is generated from the bindings that are active now. If a line says Unassigned, that action has no key combination at the moment; use its menu route where available or assign a shortcut in Tools > Keyboard shortcuts.\r\n\r\n" +
            "RECALL STUDY SCOPES\r\n" +
            "Recall has six independent study workspaces: All Oxford 5000, A1, A2, B1, B2 and C1. There is no Oxford C2 workspace because the Oxford 5000 list does not define a C2 subset. Choose the scope with the standard Study scope combo box. Each scope keeps its own deck assignments, active deck, current card and shuffle progress. Moving a word in A1 does not move it in All or another scope. The five core deck definitions are shared; use the currently configured switch/move bindings shown below. Scope-switch actions are rebindable and may be Unassigned.\r\n\r\n" +
            "RECALL NAVIGATION\r\n" +
            "WordDeck shows only the English side of a Recall card by default. The currently configured next-card action advances to the next card; the currently configured previous-card action returns to the previous actually shown eligible card. After moving back, next-card first moves forward through history before drawing a new shuffled card. Left and Right remain normal text/caret navigation. Ctrl+Right and Ctrl+Left are fixed compatibility next/previous keys and are intentionally not available for reassignment. Revealing the Ukrainian translation does not advance the card.\r\n\r\n" +
            "RECALL DECKS AND USER DATA\r\n" +
            "The five default Recall decks are permanent but may be renamed and reordered. User decks are shared definitions; saved Recall assignments remain scope-specific and are migrated safely if a user deck is deleted. Custom pasted cards are added only in All Oxford 5000 so CEFR workspaces remain restricted to official level-tagged entries. Use one card per line; the safest format is English, TAB, Ukrainian.\r\n\r\n" +
            "Deck > Hide current word removes a word only from normal Recall study. It does not delete the canonical dictionary, audio or saved deck assignments. Hidden words can be restored individually or all at once. File > Reset Recall learning data requires confirmation and creates a recovery profile before clearing learning overlays.\r\n\r\n" +
            "Personal progress is stored outside the program ZIP under %LOCALAPPDATA%\\WordDeck. New program ZIPs reuse that state automatically. File > Export personal progress profile creates a small user-state-only JSON for backup or transfer; Import validates it, creates a recovery copy and restores it atomically. Progress is saved automatically after changes and on normal exit. Use the currently configured Save progress action shown below for an explicit checkpoint. state.json also has recovery protection and the profile format is versioned for migration.\r\n\r\n" +
            "OFFLINE BRITISH PRONUNCIATION\r\n" +
            "Generated British pronunciation is an optional offline audio layer keyed by stable dictionary and entry IDs. " +
            $"Automatic pronunciation on card change is currently {audioMode}. If generated audio is unavailable, WordDeck reports a readable status and the normal screen-reader announcement remains the fallback.\r\n\r\n" +
            "SPELLING AND ADAPTIVE COACH\r\n" +
            "Open the Spelling trainer with its current binding shown below or from the Tools menu. Type the exact English spelling and press Enter. Standard typing, caret movement and editing keys remain native in the answer field. Show-answer, repeat-prompt, British-pronunciation hint, Coach toggle, Coach undo and spelling-deck actions use the bindings shown below. The deterministic conservative Coach can move a word one core spelling deck earlier after an error or hint, or one core deck later after the configured clean-success threshold; its last automatic move can be undone. The five core spelling decks are permanent; user spelling decks can be created, renamed, reordered and safely deleted.\r\n\r\n" +
            "SENTENCE SPELLING\r\n" +
            "Open Sentence Spelling with its current binding shown below or from the Tools menu. Choose an installed offline SentencePack, spelling-deck scope and one- or two-target mode. Type the required English word forms and press Enter; word order is not assessed. Show-answer, repeat-Ukrainian and SentencePack-import actions use the current bindings shown below.\r\n\r\n" +
            "ACCESSIBILITY\r\n" +
            "Essential learning paths are designed for keyboard use with standard WinForms controls, accessible names, explicit status text and predictable focus. Combo boxes, menus and text fields keep their normal navigation behavior instead of having unrelated module shortcuts swallowed. Automated engineering checks do not equal a real manual NVDA acceptance test on the user's physical Windows computer.\r\n\r\n" +
            "KEYBOARD SHORTCUTS — ACTIVE NOW\r\n" + shortcutLines + "\r\n\r\n" +
            "Use Tools > Keyboard shortcuts to assign, clear or reassign shortcuts. Conflicts and unsafe Windows/text-navigation combinations are rejected instead of being silently accepted.";

        using var form = new Form { Text = "WordDeck help", Width = 820, Height = 650, StartPosition = FormStartPosition.CenterParent, AccessibleName = "WordDeck help" };
        var box = new TextBox
        {
            Dock = DockStyle.Fill,
            Multiline = true,
            ReadOnly = true,
            ScrollBars = ScrollBars.Vertical,
            Text = help,
            AccessibleName = "WordDeck help text",
            AccessibleDescription = "Read-only help. The shortcut list reflects current saved bindings."
        };
        form.Controls.Add(box);
        form.Shown += (_, _) => { box.Focus(); box.SelectionStart = 0; box.SelectionLength = 0; };
        form.ShowDialog(this);
        RepeatCurrentWord();
    }

    protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
    {
        if (ShouldDeferUnmodifiedRecallArrow(keyData)) return base.ProcessCmdKey(ref msg, keyData);
        if (keyData == (Keys.Control | Keys.Right)) { NextWord(); return true; }
        if (keyData == (Keys.Control | Keys.Left)) { PreviousWord(); return true; }
        string? action = _shortcuts.FindAction(keyData);
        if (action is null) return base.ProcessCmdKey(ref msg, keyData);

        if (action == ActionIds.NextWord) NextWord();
        else if (action == ActionIds.PreviousWord) PreviousWord();
        else if (action == ActionIds.RevealTranslation) RevealTranslation();
        else if (action == ActionIds.RepeatWord) RepeatCurrentWord();
        else if (action == ActionIds.PlayPronunciation) PlayCurrentPronunciation();
        else if (action == ActionIds.ToggleAutoPronunciation) ToggleAutoPronunciation();
        else if (action == ActionIds.AddWords) AddWordsToActiveDeck();
        else if (action == ActionIds.SaveProgress) SaveProgressNow();
        else if (action == ActionIds.UndoMove) UndoLastMove();
        else if (action == ActionIds.HideCurrentWord) HideCurrentWord();
        else if (action == ActionIds.RestoreHiddenWords) RestoreHiddenWord();
        else if (action == ActionIds.RestoreAllHiddenWords) RestoreAllHiddenWords();
        else if (action == ActionIds.ExportProfile) ExportPersonalProfile();
        else if (action == ActionIds.ImportProfile) ImportPersonalProfile();
        else if (action == ActionIds.ResetLearningData) ResetLearningData();
        else if (action == ActionIds.ShortcutSettings) OpenShortcutSettings();
        else if (action == ActionIds.Help) ShowHelp();
        else
        {
            foreach (string scopeId in StudyScopeIds.Ordered)
            {
                if (action == ActionIds.SwitchStudyScope(scopeId))
                {
                    SwitchStudyScope(scopeId);
                    return true;
                }
            }
            foreach (DeckDefinition deck in _decks.Decks)
            {
                if (action == ActionIds.SwitchDeck(deck.Id)) { SwitchDeck(deck.Id); return true; }
                if (action == ActionIds.MoveToDeck(deck.Id)) { MoveCurrentToDeck(deck.Id); return true; }
            }
        }
        return true;
    }

    private void SaveState()
    {
        _state.ActiveDictionaryId = _package?.Id;
        if (_scopeService is not null)
        {
            _scopeService.SetActiveDeck(ActiveScopeId, _activeDeckId);
            _scopeService.SetCurrentEntry(ActiveScopeId, _current?.Id);
            PersistActiveShuffle();
        }
        _store.Save(_state);
    }
}
