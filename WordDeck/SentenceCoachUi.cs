using System.Text.Json;

namespace WordDeck;

internal sealed class SentenceTargetStats
{
    public int CompletedReviews { get; set; }
    public int FirstTrySuccesses { get; set; }
    public int WrongAttempts { get; set; }
    public int ShowAnswerUses { get; set; }
    public DateTimeOffset? LastReviewedUtc { get; set; }
}

internal sealed class SentenceCoachState
{
    public string? ActivePackId { get; set; }
    public string? ActiveSpellingDeckId { get; set; }
    public int TargetCount { get; set; } = 1;
    public ContextStudyPoolPreset PoolPreset { get; set; } = ContextStudyPoolPreset.Full;
    public string? CurrentSentenceId { get; set; }
    // Kept for backwards-compatible migration from the original one-target state.
    public string? CurrentTargetEntryId { get; set; }
    public List<string> CurrentTargetEntryIds { get; set; } = new();
    public int CurrentTargetIndex { get; set; }
    public bool CurrentTargetHadWrong { get; set; }
    public bool CurrentTargetUsedHint { get; set; }
    public List<string> RecentSentenceIds { get; set; } = new();
    public Dictionary<string, Dictionary<string, SentenceTargetStats>> StatsByDictionary { get; set; } = new(StringComparer.OrdinalIgnoreCase);
}

internal sealed class SentenceCoachStateStore
{
    private readonly string _path;
    private readonly string _backupPath;

    public SentenceCoachStateStore()
        : this(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WordDeck")) { }

    internal SentenceCoachStateStore(string root)
    {
        Directory.CreateDirectory(root);
        _path = Path.Combine(root, "sentence-coach-state.json");
        _backupPath = Path.Combine(root, "sentence-coach-state.backup.json");
    }

    public SentenceCoachState Load() => Normalize(TryLoad(_path) ?? TryLoad(_backupPath) ?? new SentenceCoachState());

    public void Save(SentenceCoachState state)
    {
        Normalize(state);
        string temp = _path + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(state, new JsonSerializerOptions { WriteIndented = true }));
        if (TryLoad(_path) is not null) File.Copy(_path, _backupPath, true);
        File.Move(temp, _path, true);
    }

    private static SentenceCoachState? TryLoad(string path)
    {
        try { return File.Exists(path) ? JsonSerializer.Deserialize<SentenceCoachState>(File.ReadAllText(path)) : null; }
        catch { return null; }
    }

    internal static SentenceCoachState Normalize(SentenceCoachState state)
    {
        state.TargetCount = Math.Clamp(state.TargetCount, 1, 3);
        if (state.PoolPreset is not (ContextStudyPoolPreset.Thirty or ContextStudyPoolPreset.Hundred or ContextStudyPoolPreset.TwoHundred or ContextStudyPoolPreset.Full))
            state.PoolPreset = ContextStudyPoolPreset.Full;
        state.CurrentTargetEntryIds ??= new();
        state.CurrentTargetEntryIds = state.CurrentTargetEntryIds
            .Where(id => !string.IsNullOrWhiteSpace(id))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Take(3)
            .ToList();

        if (state.CurrentTargetEntryIds.Count == 0 && !string.IsNullOrWhiteSpace(state.CurrentTargetEntryId))
            state.CurrentTargetEntryIds.Add(state.CurrentTargetEntryId);

        state.CurrentTargetEntryId = state.CurrentTargetEntryIds.FirstOrDefault();
        if (state.CurrentTargetEntryIds.Count == 0)
        {
            state.CurrentTargetIndex = 0;
            state.CurrentTargetHadWrong = false;
            state.CurrentTargetUsedHint = false;
        }
        else
        {
            state.CurrentTargetIndex = Math.Clamp(state.CurrentTargetIndex, 0, state.CurrentTargetEntryIds.Count - 1);
        }

        state.RecentSentenceIds ??= new();
        state.RecentSentenceIds = state.RecentSentenceIds
            .Where(id => !string.IsNullOrWhiteSpace(id))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .TakeLast(30)
            .ToList();
        state.StatsByDictionary ??= new(StringComparer.OrdinalIgnoreCase);
        state.StatsByDictionary = state.StatsByDictionary.ToDictionary(
            pair => pair.Key,
            pair => new Dictionary<string, SentenceTargetStats>(pair.Value ?? new(), StringComparer.OrdinalIgnoreCase),
            StringComparer.OrdinalIgnoreCase);
        return state;
    }
}

internal sealed class SentenceCoachForm : Form
{
    private sealed record PackChoice(string Name, InstalledSentencePack Installed)
    {
        public override string ToString() => Name;
    }

    private sealed record TargetCountChoice(int Count, string Name)
    {
        public override string ToString() => Name;
    }

    private sealed record PoolChoice(ContextStudyPoolPreset Preset, string Name)
    {
        public override string ToString() => Name;
    }

    private sealed record NaturalExercise(
        SentenceRecord Sentence,
        IReadOnlyList<DictionaryEntry> Targets,
        int DifficultyScore);

    private readonly SpellingDeckService _spellingDecks;
    private readonly ShortcutManager _shortcuts;
    private readonly DictionaryPackage _package;
    private readonly ContextTargetLexicon _lexicon;
    private readonly Dictionary<string, DictionaryEntry> _entries;
    private readonly Dictionary<string, string> _spellingDeckMap;
    private readonly SentencePackStore _packStore;
    private readonly SentenceCoachStateStore _stateStore;
    private readonly SentenceCoachState _state;
    private readonly Random _random = new();
    private readonly Dictionary<string, HashSet<string>> _coverageCache = new(StringComparer.OrdinalIgnoreCase);

    private readonly ComboBox _packCombo = new()
    {
        DropDownStyle = ComboBoxStyle.DropDownList,
        Width = 320,
        AccessibleName = "Sentence pack",
        AccessibleDescription = "Choose a validated installed offline SentencePack. WordDeck never fabricates a production corpus when no pack is available."
    };
    private readonly ComboBox _deckCombo = new()
    {
        DropDownStyle = ComboBoxStyle.DropDownList,
        Width = 245,
        DisplayMember = nameof(DeckDefinition.Name),
        AccessibleName = "Sentence training spelling deck"
    };
    private readonly ComboBox _poolCombo = new()
    {
        DropDownStyle = ComboBoxStyle.DropDownList,
        Width = 150,
        AccessibleName = "Sentence study pool size",
        AccessibleDescription = "Choose the first 30, 100, 200, or the full resolved target pool inside the selected spelling deck."
    };
    private readonly ComboBox _targetCountCombo = new()
    {
        DropDownStyle = ComboBoxStyle.DropDownList,
        Width = 190,
        AccessibleName = "Number of target words per sentence",
        AccessibleDescription = "Choose one target, two natural targets, or three natural targets. Multi-target modes are used only when the installed corpus contains a real sentence with all targets."
    };
    private readonly TextBox _prompt = new()
    {
        ReadOnly = true,
        Multiline = true,
        Dock = DockStyle.Fill,
        TabStop = true,
        AccessibleName = "Ukrainian sentence prompt",
        Font = new Font(SystemFonts.DefaultFont.FontFamily, 16)
    };
    private readonly TextBox _cloze = new()
    {
        ReadOnly = true,
        Multiline = true,
        Dock = DockStyle.Fill,
        TabStop = true,
        AccessibleName = "English sentence with current target blank"
    };
    private readonly TextBox _answer = new()
    {
        Multiline = true,
        Dock = DockStyle.Fill,
        AcceptsReturn = false,
        AccessibleName = "Type the current English target word or phrase",
        AccessibleDescription = "Type only the current target form, not the full English sentence, then press Enter."
    };
    private readonly Label _target = new() { AutoSize = true, AccessibleName = "Current Sentence target" };
    private readonly Label _status = new() { AutoSize = true, AccessibleName = "Sentence Coach status" };
    private readonly Label _coverage = new() { AutoSize = true, AccessibleName = "Sentence Coach scope coverage" };
    private readonly Label _modeInfo = new() { AutoSize = true, AccessibleName = "Sentence Coach mode information" };

    private ISentenceCorpus? _corpus;
    private string _activeDeckId;
    private SentenceRecord? _currentSentence;
    private readonly List<DictionaryEntry> _currentTargets = new();
    private SentenceCoachTargetOnlySession? _targetSession;

    public SentenceCoachForm(
        AppState appState,
        SpellingState spellingState,
        ShortcutManager shortcuts,
        DictionaryPackage package,
        SentencePackStore packStore,
        SentenceCoachStateStore stateStore,
        SentenceCoachState state)
    {
        _ = appState;
        _spellingDecks = new SpellingDeckService(spellingState);
        _shortcuts = shortcuts;
        _package = package;
        _lexicon = new ContextTargetLexicon(package);
        _entries = package.Entries.ToDictionary(entry => entry.Id, StringComparer.OrdinalIgnoreCase);
        _spellingDeckMap = _spellingDecks.EnsureAssignments(package.Id, package.Entries.Select(entry => entry.Id));
        _packStore = packStore;
        _stateStore = stateStore;
        _state = SentenceCoachStateStore.Normalize(state);
        _activeDeckId = _spellingDecks.Find(state.ActiveSpellingDeckId ?? string.Empty)?.Id ?? _spellingDecks.FirstDeck.Id;

        Text = "WordDeck Sentence Spelling";
        Width = 1040;
        Height = 720;
        MinimumSize = new Size(720, 540);
        StartPosition = FormStartPosition.CenterParent;
        KeyPreview = true;
        AccessibleName = "WordDeck Sentence Spelling trainer";
        MainMenuStrip = BuildMenu();
        Controls.Add(MainMenuStrip);

        var root = new TableLayoutPanel { Dock = DockStyle.Fill, RowCount = 11, ColumnCount = 1, Padding = new Padding(16) };
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 28));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 28));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 24));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));

        var top = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoSize = true, WrapContents = true };
        top.Controls.Add(new Label { Text = "Sentence pack:", AutoSize = true, Padding = new Padding(0, 6, 4, 0) });
        top.Controls.Add(_packCombo);
        top.Controls.Add(new Label { Text = "Spelling deck scope:", AutoSize = true, Padding = new Padding(12, 6, 4, 0) });
        top.Controls.Add(_deckCombo);
        top.Controls.Add(new Label { Text = "Pool:", AutoSize = true, Padding = new Padding(12, 6, 4, 0) });
        top.Controls.Add(_poolCombo);
        top.Controls.Add(new Label { Text = "Targets:", AutoSize = true, Padding = new Padding(12, 6, 4, 0) });
        top.Controls.Add(_targetCountCombo);

        root.Controls.Add(top, 0, 0);
        root.Controls.Add(_coverage, 0, 1);
        root.Controls.Add(_target, 0, 2);
        root.Controls.Add(new Label { Text = "Ukrainian sentence", AutoSize = true, Font = new Font(Font, FontStyle.Bold) }, 0, 3);
        root.Controls.Add(_prompt, 0, 4);
        root.Controls.Add(new Label { Text = "English sentence with the current target blank", AutoSize = true, Font = new Font(Font, FontStyle.Bold) }, 0, 5);
        root.Controls.Add(_cloze, 0, 6);
        root.Controls.Add(new Label
        {
            Text = "Type only the current English target word or phrase and press Enter.",
            AutoSize = true,
            Font = new Font(Font, FontStyle.Bold)
        }, 0, 7);
        root.Controls.Add(_answer, 0, 8);
        root.Controls.Add(_status, 0, 9);
        root.Controls.Add(_modeInfo, 0, 10);
        Controls.Add(root);
        root.BringToFront();

        _packCombo.SelectedIndexChanged += (_, _) => ChangePack();
        _deckCombo.SelectedIndexChanged += (_, _) =>
        {
            if (_deckCombo.SelectedItem is DeckDefinition deck &&
                !string.Equals(deck.Id, _activeDeckId, StringComparison.OrdinalIgnoreCase))
            {
                _activeDeckId = deck.Id;
                _state.ActiveSpellingDeckId = deck.Id;
                ClearCurrent();
                Save();
                UpdateCoverage();
                Next();
            }
        };
        _poolCombo.SelectedIndexChanged += (_, _) =>
        {
            if (_poolCombo.SelectedItem is PoolChoice choice && choice.Preset != _state.PoolPreset)
            {
                _state.PoolPreset = choice.Preset;
                ClearCurrent();
                Save();
                UpdateCoverage();
                Next();
            }
            UpdateModeInfo();
        };
        _targetCountCombo.SelectedIndexChanged += (_, _) =>
        {
            if (_targetCountCombo.SelectedItem is TargetCountChoice choice && choice.Count != _state.TargetCount)
            {
                _state.TargetCount = choice.Count;
                ClearCurrent();
                Save();
                UpdateCoverage();
                Next();
            }
            UpdateModeInfo();
        };
        _answer.KeyDown += (_, e) =>
        {
            if (e.KeyCode == Keys.Enter)
            {
                e.SuppressKeyPress = true;
                Submit();
            }
        };

        PopulateTargetCounts();
        PopulatePoolPresets();
        PopulateDecks();
        PopulatePacks();
        UpdateModeInfo();
        Shown += (_, _) => BeginInvoke(new Action(RestoreOrNext));
        FormClosing += (_, _) => Save();
    }

    private MenuStrip BuildMenu()
    {
        var menu = new MenuStrip { AccessibleName = "Sentence Spelling menu" };
        var file = new ToolStripMenuItem("&File");
        Add(file, "&Import SentencePack...", ImportPack);
        var training = new ToolStripMenuItem("&Training");
        Add(training, "&Show current target answer", ShowAnswer);
        Add(training, "&Repeat current sentence prompt", RepeatPrompt);
        menu.Items.Add(file);
        menu.Items.Add(training);
        return menu;
    }

    private static void Add(ToolStripMenuItem parent, string text, Action action)
    {
        var item = new ToolStripMenuItem(text);
        item.Click += (_, _) => action();
        parent.DropDownItems.Add(item);
    }

    private void PopulateTargetCounts()
    {
        _targetCountCombo.BeginUpdate();
        _targetCountCombo.Items.Clear();
        _targetCountCombo.Items.Add(new TargetCountChoice(1, "1 target"));
        _targetCountCombo.Items.Add(new TargetCountChoice(2, "2 natural targets"));
        _targetCountCombo.Items.Add(new TargetCountChoice(3, "3 natural targets"));
        _targetCountCombo.SelectedIndex = _state.TargetCount - 1;
        _targetCountCombo.EndUpdate();
    }

    private void PopulatePoolPresets()
    {
        PoolChoice[] choices =
        {
            new(ContextStudyPoolPreset.Thirty, "30"),
            new(ContextStudyPoolPreset.Hundred, "100"),
            new(ContextStudyPoolPreset.TwoHundred, "200"),
            new(ContextStudyPoolPreset.Full, "Full")
        };
        _poolCombo.BeginUpdate();
        _poolCombo.Items.Clear();
        foreach (PoolChoice choice in choices)
            _poolCombo.Items.Add(choice);
        _poolCombo.SelectedIndex = Array.FindIndex(choices, choice => choice.Preset == _state.PoolPreset);
        if (_poolCombo.SelectedIndex < 0)
            _poolCombo.SelectedIndex = choices.Length - 1;
        _poolCombo.EndUpdate();
    }

    private void PopulateDecks()
    {
        _deckCombo.BeginUpdate();
        _deckCombo.Items.Clear();
        foreach (DeckDefinition deck in _spellingDecks.Decks)
            _deckCombo.Items.Add(deck);
        for (int i = 0; i < _deckCombo.Items.Count; i++)
        {
            if (_deckCombo.Items[i] is DeckDefinition deck &&
                string.Equals(deck.Id, _activeDeckId, StringComparison.OrdinalIgnoreCase))
                _deckCombo.SelectedIndex = i;
        }
        _deckCombo.EndUpdate();
    }

    private void PopulatePacks(string? preferPackId = null)
    {
        IReadOnlyList<InstalledSentencePack> installed = _packStore.LoadInstalled();
        var choices = installed
            .Select(item => new PackChoice($"{item.PackId} — {item.License} — {item.SentenceCount:N0} sentences", item))
            .ToList();

        _packCombo.BeginUpdate();
        _packCombo.Items.Clear();
        foreach (PackChoice choice in choices)
            _packCombo.Items.Add(choice);
        _packCombo.EndUpdate();

        string? wanted = preferPackId ?? _state.ActivePackId;
        int index = choices.FindIndex(choice => string.Equals(choice.Installed.PackId, wanted, StringComparison.OrdinalIgnoreCase));
        if (index < 0 && choices.Count > 0) index = 0;
        if (index >= 0)
        {
            _packCombo.SelectedIndex = index;
        }
        else
        {
            _corpus = null;
            _state.ActivePackId = null;
            UpdateCoverage();
            _prompt.Text = "No SentencePack installed";
            _cloze.Clear();
            _answer.Clear();
            Announce("No SentencePack is installed. Import a validated attributed offline SentencePack before Sentence Spelling can run.");
        }
    }

    private void ChangePack()
    {
        if (_packCombo.SelectedItem is not PackChoice choice)
            return;
        if (_corpus is not null && string.Equals(_corpus.PackId, choice.Installed.PackId, StringComparison.OrdinalIgnoreCase))
            return;

        _corpus = choice.Installed.Corpus;
        _state.ActivePackId = _corpus.PackId;
        _coverageCache.Clear();
        ClearCurrent();
        Save();
        UpdateCoverage();
        Next();
    }

    private void ImportPack()
    {
        using var dialog = new OpenFileDialog
        {
            Title = "Import WordDeck SentencePack",
            Filter = "WordDeck SentencePack (*.json.gz;*.json)|*.json.gz;*.json|Compressed SentencePack (*.json.gz)|*.json.gz|JSON SentencePack (*.json)|*.json|All files (*.*)|*.*"
        };
        if (dialog.ShowDialog(this) != DialogResult.OK)
            return;

        try
        {
            InstalledSentencePack installed = _packStore.Import(dialog.FileName);
            _coverageCache.Clear();
            PopulatePacks(installed.PackId);
            Announce($"Imported validated SentencePack {installed.PackId}, {installed.SentenceCount:N0} sentences, license {installed.License}.");
        }
        catch (Exception ex)
        {
            Warn("SentencePack import failed: " + ex.Message);
        }
    }

    private IReadOnlyList<DictionaryEntry> ScopeEntries() =>
        _package.Entries
            .Where(entry => string.Equals(
                _spellingDeckMap.GetValueOrDefault(entry.Id, _spellingDecks.FirstDeck.Id),
                _activeDeckId,
                StringComparison.OrdinalIgnoreCase))
            .ToList();

    private IReadOnlyList<DictionaryEntry> ResolvedScopeEntries()
    {
        IReadOnlyList<DictionaryEntry> resolvedFullScope = SentenceCoachTargetOnlyPlanner.ResolvedScope(ScopeEntries(), _lexicon);
        ContextStudyPoolSelection pool = ContextStudyPoolBuilder.Build(resolvedFullScope.Select(entry => entry.Id), _state.PoolPreset);
        return pool.EntryIds.Select(id => _entries[id]).ToList();
    }

    private HashSet<string> CoveredAnchorIds(IReadOnlyList<DictionaryEntry> resolvedScope)
    {
        if (_corpus is null)
            return new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        string key = $"{_corpus.PackId}\u001f{_activeDeckId}\u001f{_state.PoolPreset}\u001f{_state.TargetCount}";
        if (_coverageCache.TryGetValue(key, out HashSet<string>? cached))
            return new HashSet<string>(cached, StringComparer.OrdinalIgnoreCase);

        var covered = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (DictionaryEntry entry in resolvedScope)
        {
            if (SentenceCoachTargetOnlyPlanner.HasNaturalTargetSet(_corpus, entry, resolvedScope, _lexicon, _state.TargetCount))
                covered.Add(entry.Id);
        }
        _coverageCache[key] = new HashSet<string>(covered, StringComparer.OrdinalIgnoreCase);
        return covered;
    }

    private void UpdateCoverage()
    {
        DeckDefinition deck = _spellingDecks.Find(_activeDeckId) ?? _spellingDecks.FirstDeck;
        IReadOnlyList<DictionaryEntry> scope = ScopeEntries();
        IReadOnlyList<DictionaryEntry> resolvedFullScope = SentenceCoachTargetOnlyPlanner.ResolvedScope(scope, _lexicon);
        IReadOnlyList<DictionaryEntry> resolvedPool = ResolvedScopeEntries();
        int ambiguous = scope.Count - resolvedFullScope.Count;
        string poolLabel = _state.PoolPreset == ContextStudyPoolPreset.Full ? "full" : ((int)_state.PoolPreset).ToString();
        if (_corpus is null)
        {
            _coverage.Text = $"{deck.Name}: pool {poolLabel} contains {resolvedPool.Count} of {resolvedFullScope.Count} resolved targets. No SentencePack loaded. {ambiguous} same-written-form ambiguous entries are fail-closed before pool selection.";
            return;
        }

        HashSet<string> covered = CoveredAnchorIds(resolvedPool);
        _coverage.Text = $"{deck.Name}: pool {poolLabel} contains {resolvedPool.Count} of {resolvedFullScope.Count} resolved targets; {covered.Count} currently have a natural {_state.TargetCount}-target corpus exercise in {_corpus.PackId}. {ambiguous} same-written-form ambiguous entries are excluded using full-dictionary identity before pool selection.";
    }

    private void RestoreOrNext()
    {
        if (_corpus is not null && !string.IsNullOrWhiteSpace(_state.CurrentSentenceId))
        {
            List<string> targetIds = _state.CurrentTargetEntryIds
                .Where(id => !string.IsNullOrWhiteSpace(id))
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToList();

            if (targetIds.Count == _state.TargetCount)
            {
                try
                {
                    IReadOnlyList<DictionaryEntry> resolvedScope = ResolvedScopeEntries();
                    var scopeIds = new HashSet<string>(resolvedScope.Select(entry => entry.Id), StringComparer.OrdinalIgnoreCase);
                    List<DictionaryEntry> restoredTargets = targetIds
                        .Where(scopeIds.Contains)
                        .Where(_entries.ContainsKey)
                        .Select(id => _entries[id])
                        .ToList();
                    _lexicon.EnsureDistinctLexicalTargets(targetIds);
                    ContextStableIdentityResolution.EnsureResolvedTargets(_lexicon, targetIds);

                    SentenceRecord? sentence = restoredTargets.Count == targetIds.Count
                        ? _corpus.LookupAllTargets(targetIds)
                            .FirstOrDefault(item => string.Equals(item.Id, _state.CurrentSentenceId, StringComparison.OrdinalIgnoreCase))
                        : null;

                    if (sentence is not null && restoredTargets.All(target =>
                            ContextPhysicalTargetForm.BuildOccurrenceRegex(target.Source).Matches(sentence.English).Count == 1))
                    {
                        Show(sentence, restoredTargets, _state.CurrentTargetIndex, restoring: true);
                        return;
                    }
                }
                catch
                {
                    // Stale or newly ambiguous saved Sentence state fails closed and is replaced by a fresh safe exercise.
                }
            }
        }
        ClearCurrent();
        Save();
        Next();
    }

    private void Next()
    {
        if (_corpus is null)
            return;

        IReadOnlyList<DictionaryEntry> resolvedScope = ResolvedScopeEntries();
        HashSet<string> coveredIds = CoveredAnchorIds(resolvedScope);
        List<DictionaryEntry> covered = resolvedScope.Where(entry => coveredIds.Contains(entry.Id)).ToList();

        if (covered.Count == 0)
        {
            ClearCurrent();
            _prompt.Text = "No safe corpus exercise is available in this pool";
            _cloze.Clear();
            _answer.Clear();
            Announce($"The selected pool currently has no resolved natural {_state.TargetCount}-target SentencePack exercise. WordDeck will not fabricate one or guess a homograph sense.");
            UpdateCoverage();
            return;
        }

        DictionaryEntry anchor = ChooseWeakTarget(covered);
        IReadOnlyList<SentenceCoachTargetSetCandidate> sets = SentenceCoachTargetOnlyPlanner.FindNaturalTargetSets(
            _corpus,
            anchor,
            resolvedScope,
            _lexicon,
            _state.TargetCount,
            maxSets: 100);
        if (sets.Count == 0)
        {
            _coverageCache.Clear();
            Announce("Corpus coverage changed while selecting the next exercise. Rechecking safe coverage.");
            UpdateCoverage();
            return;
        }

        var allowed = new HashSet<string>(resolvedScope.Select(entry => entry.Id), StringComparer.OrdinalIgnoreCase);
        var known = new HashSet<string>(
            _package.Entries
                .Where(entry => IsKnownSpellingDeck(_spellingDeckMap.GetValueOrDefault(entry.Id, _spellingDecks.FirstDeck.Id)))
                .Select(entry => entry.Id),
            StringComparer.OrdinalIgnoreCase);
        var levels = _package.Entries.ToDictionary(entry => entry.Id, entry => entry.Level, StringComparer.OrdinalIgnoreCase);
        var recent = new HashSet<string>(_state.RecentSentenceIds, StringComparer.OrdinalIgnoreCase);
        var context = new SentenceSelectionContext(allowed, known, recent, levels);

        NaturalExercise? selected = sets
            .Select(set => BuildNaturalExercise(set, context))
            .Where(item => item is not null)
            .Cast<NaturalExercise>()
            .OrderBy(item => item.DifficultyScore)
            .ThenBy(item => item.Sentence.Id, StringComparer.Ordinal)
            .FirstOrDefault();
        if (selected is null)
        {
            Announce("No safe natural SentencePack sentence survived exact target-form validation. No exercise was generated.");
            return;
        }

        Show(selected.Sentence, selected.Targets, 0, restoring: false);
    }

    private NaturalExercise? BuildNaturalExercise(SentenceCoachTargetSetCandidate set, SentenceSelectionContext context)
    {
        if (_corpus is null)
            return null;
        SentenceRecord? sentence = _corpus.LookupAllTargets(set.TargetEntryIds)
            .FirstOrDefault(item => string.Equals(item.Id, set.EvidenceSentenceId, StringComparison.OrdinalIgnoreCase));
        if (sentence is null)
            return null;
        List<DictionaryEntry> targets = set.TargetEntryIds
            .Where(_entries.ContainsKey)
            .Select(id => _entries[id])
            .ToList();
        if (targets.Count != set.TargetEntryIds.Count)
            return null;
        int score = SentenceSelector.Score(sentence, set.TargetEntryIds, context);
        return new NaturalExercise(sentence, targets, score);
    }

    private DictionaryEntry ChooseWeakTarget(IReadOnlyList<DictionaryEntry> covered)
    {
        Dictionary<string, SentenceTargetStats> stats = GetStatsMap();
        List<DictionaryEntry> ranked = covered
            .OrderByDescending(entry => Weakness(stats.GetValueOrDefault(entry.Id)))
            .ThenBy(entry => stats.GetValueOrDefault(entry.Id)?.LastReviewedUtc ?? DateTimeOffset.MinValue)
            .ThenBy(entry => entry.Id, StringComparer.Ordinal)
            .ToList();
        int poolSize = Math.Min(10, ranked.Count);
        if (_currentTargets.Count > 0 && poolSize > 1)
        {
            var currentIds = new HashSet<string>(_currentTargets.Select(entry => entry.Id), StringComparer.OrdinalIgnoreCase);
            List<DictionaryEntry> pool = ranked.Take(poolSize).Where(entry => !currentIds.Contains(entry.Id)).ToList();
            if (pool.Count > 0)
                return pool[_random.Next(pool.Count)];
        }
        return ranked[_random.Next(poolSize)];
    }

    private static int Weakness(SentenceTargetStats? stats) =>
        stats is null ? 1000 : stats.WrongAttempts * 8 + stats.ShowAnswerUses * 6 - stats.FirstTrySuccesses * 2 - stats.CompletedReviews;

    private static bool IsKnownSpellingDeck(string deckId)
    {
        int index = SpellingDeckIds.CoreDecks.ToList().FindIndex(id =>
            string.Equals(id, deckId, StringComparison.OrdinalIgnoreCase));
        return index >= 3;
    }

    private void Show(SentenceRecord sentence, IReadOnlyList<DictionaryEntry> targets, int startTargetIndex, bool restoring)
    {
        _currentSentence = sentence;
        _currentTargets.Clear();
        _currentTargets.AddRange(targets);
        _targetSession = SentenceCoachTargetOnlySession.Build(
            sentence,
            targets,
            _lexicon,
            _package,
            _corpus?.PackId ?? throw new InvalidOperationException("SentencePack is not loaded."),
            ContextCorpusKind.RealCorpus,
            sentence.Source,
            sentence.License,
            startTargetIndex);

        if (!restoring)
        {
            _state.CurrentTargetHadWrong = false;
            _state.CurrentTargetUsedHint = false;
        }
        _state.CurrentSentenceId = sentence.Id;
        _state.CurrentTargetEntryIds = targets.Select(target => target.Id).ToList();
        _state.CurrentTargetEntryId = _state.CurrentTargetEntryIds.FirstOrDefault();
        _state.CurrentTargetIndex = _targetSession.CurrentTargetIndex;
        Save();
        PresentCurrentPrompt(restoring ? "Restored the saved Sentence exercise." : "New Sentence exercise.");
    }

    private void PresentCurrentPrompt(string lead)
    {
        if (_targetSession is null || _targetSession.Complete)
            return;
        SentenceCoachTargetOnlyPrompt prompt = _targetSession.CurrentPrompt();
        _prompt.Text = prompt.UkrainianSentence;
        _cloze.Text = prompt.EnglishCloze;
        _target.Text = $"Target {prompt.TargetNumber} of {prompt.TargetCount}. Ukrainian meaning: {prompt.TargetMeaningUkrainian}. Stable target: {prompt.TargetEntryId}.";
        _answer.Clear();
        _answer.Focus();
        _state.CurrentTargetIndex = _targetSession.CurrentTargetIndex;
        Save();
        Announce($"{lead} Target {prompt.TargetNumber} of {prompt.TargetCount}. Meaning: {prompt.TargetMeaningUkrainian}. Ukrainian sentence: {prompt.UkrainianSentence}. English with the current target blank: {prompt.EnglishCloze}. Type only the current target form.");
    }

    private void Submit()
    {
        if (_currentSentence is null || _targetSession is null || _targetSession.Complete || string.IsNullOrWhiteSpace(_answer.Text))
            return;

        SentenceCoachTargetOnlyPrompt prompt = _targetSession.CurrentPrompt();
        SentenceCoachTargetOnlyCheck result = _targetSession.Check(_answer.Text);
        SentenceTargetStats stats = GetStats(prompt.TargetEntryId);
        if (!result.Accepted)
        {
            stats.WrongAttempts++;
            _state.CurrentTargetHadWrong = true;
            Save();
            _answer.SelectAll();
            Announce(result.Feedback + " The target will not advance. Try the current target again.");
            return;
        }

        stats.CompletedReviews++;
        if (!_state.CurrentTargetHadWrong && !_state.CurrentTargetUsedHint)
            stats.FirstTrySuccesses++;
        stats.LastReviewedUtc = DateTimeOffset.UtcNow;

        if (result.SentenceComplete)
        {
            RememberSentence(_currentSentence.Id);
            ClearCurrent();
            Save();
            Announce(result.Feedback);
            Next();
            return;
        }

        _state.CurrentTargetIndex = _targetSession.CurrentTargetIndex;
        _state.CurrentTargetHadWrong = false;
        _state.CurrentTargetUsedHint = false;
        Save();
        PresentCurrentPrompt(result.Feedback);
    }

    private void ShowAnswer()
    {
        if (_targetSession is null || _targetSession.Complete)
            return;
        SentenceCoachTargetOnlyPrompt prompt = _targetSession.CurrentPrompt();
        _state.CurrentTargetUsedHint = true;
        GetStats(prompt.TargetEntryId).ShowAnswerUses++;
        Save();
        string expected = _targetSession.RevealCurrentExpectedForm();
        Announce($"Current target answer: {expected}. Only this target was revealed. Type it correctly to continue.");
        _answer.Focus();
    }

    private void RepeatPrompt()
    {
        if (_targetSession is null || _targetSession.Complete)
            return;
        SentenceCoachTargetOnlyPrompt prompt = _targetSession.CurrentPrompt();
        Announce($"Target {prompt.TargetNumber} of {prompt.TargetCount}. Meaning: {prompt.TargetMeaningUkrainian}. Ukrainian sentence: {prompt.UkrainianSentence}. English with target blank: {prompt.EnglishCloze}.");
        _answer.Focus();
    }

    private Dictionary<string, SentenceTargetStats> GetStatsMap()
    {
        if (!_state.StatsByDictionary.TryGetValue(_package.Id, out Dictionary<string, SentenceTargetStats>? map))
        {
            map = new(StringComparer.OrdinalIgnoreCase);
            _state.StatsByDictionary[_package.Id] = map;
        }
        return map;
    }

    private SentenceTargetStats GetStats(string entryId)
    {
        Dictionary<string, SentenceTargetStats> map = GetStatsMap();
        if (!map.TryGetValue(entryId, out SentenceTargetStats? stats))
        {
            stats = new();
            map[entryId] = stats;
        }
        return stats;
    }

    private void RememberSentence(string id)
    {
        _state.RecentSentenceIds.RemoveAll(existing => string.Equals(existing, id, StringComparison.OrdinalIgnoreCase));
        _state.RecentSentenceIds.Add(id);
        if (_state.RecentSentenceIds.Count > 30)
            _state.RecentSentenceIds.RemoveRange(0, _state.RecentSentenceIds.Count - 30);
    }

    private void ClearCurrent()
    {
        _currentSentence = null;
        _currentTargets.Clear();
        _targetSession = null;
        _state.CurrentSentenceId = null;
        _state.CurrentTargetEntryId = null;
        _state.CurrentTargetEntryIds.Clear();
        _state.CurrentTargetIndex = 0;
        _state.CurrentTargetHadWrong = false;
        _state.CurrentTargetUsedHint = false;
    }

    private void Save()
    {
        _state.ActivePackId = _corpus?.PackId;
        _state.ActiveSpellingDeckId = _activeDeckId;
        _stateStore.Save(_state);
    }

    private void UpdateModeInfo()
    {
        string poolLabel = _state.PoolPreset == ContextStudyPoolPreset.Full ? "full pool" : $"{(int)_state.PoolPreset}-target pool";
        _modeInfo.Text = _state.TargetCount == 1
            ? $"Target-only Sentence Spelling, {poolLabel}: one resolved stable Oxford target. Ambiguous same-written-form identities fail closed before pool selection. Difficulty prefers learner-known context vocabulary before coarse CEFR."
            : $"Target-only Sentence Spelling, {poolLabel}: {_state.TargetCount} distinct resolved targets must co-occur naturally in the installed SentencePack. Targets are answered one at a time; no synthetic production fallback is used.";
    }

    private void Announce(string text)
    {
        _status.Text = text;
        AccessibilityAnnouncer.Announce(_status, text);
    }

    private void Warn(string text) =>
        MessageBox.Show(this, text, "Sentence Spelling", MessageBoxButtons.OK, MessageBoxIcon.Warning);

    protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
    {
        string? action = _shortcuts.FindAction(keyData);
        if (action is null)
            return base.ProcessCmdKey(ref msg, keyData);
        if (action == ActionIds.SentenceShowAnswer) ShowAnswer();
        else if (action == ActionIds.SentenceRepeatPrompt) RepeatPrompt();
        else if (action == ActionIds.SentenceImportPack) ImportPack();
        else return base.ProcessCmdKey(ref msg, keyData);
        return true;
    }
}
