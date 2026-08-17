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
    public string? CurrentSentenceId { get; set; }
    public string? CurrentTargetEntryId { get; set; }
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
        state.RecentSentenceIds ??= new();
        state.RecentSentenceIds = state.RecentSentenceIds.Where(id => !string.IsNullOrWhiteSpace(id)).Distinct(StringComparer.OrdinalIgnoreCase).TakeLast(30).ToList();
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
    private sealed record PackChoice(string Name, InstalledSentencePack Installed) { public override string ToString() => Name; }

    private readonly AppState _appState;
    private readonly SpellingState _spellingState;
    private readonly SpellingDeckService _spellingDecks;
    private readonly ShortcutManager _shortcuts;
    private readonly DictionaryPackage _package;
    private readonly Dictionary<string, DictionaryEntry> _entries;
    private readonly Dictionary<string, string> _spellingDeckMap;
    private readonly SentencePackStore _packStore;
    private readonly SentenceCoachStateStore _stateStore;
    private readonly SentenceCoachState _state;
    private readonly Random _random = new();

    private readonly ComboBox _packCombo = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 320, AccessibleName = "Sentence pack" };
    private readonly ComboBox _deckCombo = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 260, DisplayMember = nameof(DeckDefinition.Name), AccessibleName = "Sentence training spelling deck" };
    private readonly TextBox _prompt = new() { ReadOnly = true, Multiline = true, Dock = DockStyle.Fill, AccessibleName = "Ukrainian sentence prompt", Font = new Font(SystemFonts.DefaultFont.FontFamily, 17) };
    private readonly TextBox _answer = new() { Multiline = true, Dock = DockStyle.Fill, AcceptsReturn = false, AccessibleName = "Type the English sentence words" };
    private readonly Label _target = new() { AutoSize = true, AccessibleName = "Sentence target word" };
    private readonly Label _status = new() { AutoSize = true, AccessibleName = "Sentence Coach status" };
    private readonly Label _coverage = new() { AutoSize = true, AccessibleName = "Sentence Coach scope coverage" };

    private SentencePack? _pack;
    private string _activeDeckId;
    private SentenceRecord? _currentSentence;
    private DictionaryEntry? _currentTarget;
    private bool _hadWrong;
    private bool _usedHint;

    public SentenceCoachForm(
        AppState appState,
        SpellingState spellingState,
        ShortcutManager shortcuts,
        DictionaryPackage package,
        SentencePackStore packStore,
        SentenceCoachStateStore stateStore,
        SentenceCoachState state)
    {
        _appState = appState;
        _spellingState = spellingState;
        _spellingDecks = new SpellingDeckService(spellingState);
        _shortcuts = shortcuts;
        _package = package;
        _entries = package.Entries.ToDictionary(entry => entry.Id, StringComparer.OrdinalIgnoreCase);
        _spellingDeckMap = _spellingDecks.EnsureAssignments(package.Id, package.Entries.Select(entry => entry.Id));
        _packStore = packStore;
        _stateStore = stateStore;
        _state = state;
        _activeDeckId = _spellingDecks.Find(state.ActiveSpellingDeckId ?? string.Empty)?.Id ?? _spellingDecks.FirstDeck.Id;

        Text = "WordDeck Sentence Spelling";
        Width = 920; Height = 610; MinimumSize = new Size(680, 470); StartPosition = FormStartPosition.CenterParent; KeyPreview = true;
        AccessibleName = "WordDeck Sentence Spelling trainer";
        MainMenuStrip = BuildMenu(); Controls.Add(MainMenuStrip);

        var root = new TableLayoutPanel { Dock = DockStyle.Fill, RowCount = 9, ColumnCount = 1, Padding = new Padding(16) };
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 45));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 35));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));

        var top = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoSize = true, WrapContents = true };
        top.Controls.Add(new Label { Text = "Sentence pack:", AutoSize = true, Padding = new Padding(0, 6, 4, 0) }); top.Controls.Add(_packCombo);
        top.Controls.Add(new Label { Text = "Spelling deck scope:", AutoSize = true, Padding = new Padding(12, 6, 4, 0) }); top.Controls.Add(_deckCombo);
        root.Controls.Add(top, 0, 0);
        root.Controls.Add(_coverage, 0, 1);
        root.Controls.Add(_target, 0, 2);
        root.Controls.Add(new Label { Text = "Ukrainian sentence", AutoSize = true, Font = new Font(Font, FontStyle.Bold) }, 0, 3);
        root.Controls.Add(_prompt, 0, 4);
        root.Controls.Add(new Label { Text = "Type all required English word forms and press Enter. Word order is not assessed.", AutoSize = true, Font = new Font(Font, FontStyle.Bold) }, 0, 5);
        root.Controls.Add(_answer, 0, 6);
        root.Controls.Add(_status, 0, 7);
        root.Controls.Add(new Label { Text = "One-target Sentence Spelling. Training targets never leave the selected spelling-deck scope.", AutoSize = true, AccessibleName = "Sentence Coach mode information" }, 0, 8);
        Controls.Add(root); root.BringToFront();

        _packCombo.SelectedIndexChanged += (_, _) => ChangePack();
        _deckCombo.SelectedIndexChanged += (_, _) =>
        {
            if (_deckCombo.SelectedItem is DeckDefinition deck && !string.Equals(deck.Id, _activeDeckId, StringComparison.OrdinalIgnoreCase))
            {
                _activeDeckId = deck.Id; _state.ActiveSpellingDeckId = deck.Id; ClearCurrent(); Save(); UpdateCoverage(); Next();
            }
        };
        _answer.KeyDown += (_, e) =>
        {
            if (e.KeyCode == Keys.Enter)
            {
                e.SuppressKeyPress = true;
                Submit();
            }
        };

        PopulateDecks();
        PopulatePacks();
        Shown += (_, _) => BeginInvoke(new Action(RestoreOrNext));
        FormClosing += (_, _) => Save();
    }

    private MenuStrip BuildMenu()
    {
        var menu = new MenuStrip { AccessibleName = "Sentence Spelling menu" };
        var file = new ToolStripMenuItem("&File");
        Add(file, "&Import SentencePack...", ImportPack);
        var training = new ToolStripMenuItem("&Training");
        Add(training, "&Show required English sentence", ShowAnswer);
        Add(training, "&Repeat Ukrainian sentence", RepeatPrompt);
        menu.Items.Add(file); menu.Items.Add(training);
        return menu;
    }

    private static void Add(ToolStripMenuItem parent, string text, Action action)
    {
        var item = new ToolStripMenuItem(text); item.Click += (_, _) => action(); parent.DropDownItems.Add(item);
    }

    private void PopulateDecks()
    {
        _deckCombo.BeginUpdate(); _deckCombo.Items.Clear();
        foreach (DeckDefinition deck in _spellingDecks.Decks) _deckCombo.Items.Add(deck);
        for (int i = 0; i < _deckCombo.Items.Count; i++)
            if (_deckCombo.Items[i] is DeckDefinition deck && string.Equals(deck.Id, _activeDeckId, StringComparison.OrdinalIgnoreCase)) _deckCombo.SelectedIndex = i;
        _deckCombo.EndUpdate();
    }

    private void PopulatePacks(string? preferPackId = null)
    {
        IReadOnlyList<InstalledSentencePack> installed = _packStore.LoadInstalled();
        var choices = installed.Select(item => new PackChoice($"{item.Pack.PackId} — {item.Pack.License}", item)).ToList();
        _packCombo.BeginUpdate(); _packCombo.Items.Clear(); foreach (PackChoice choice in choices) _packCombo.Items.Add(choice); _packCombo.EndUpdate();
        string? wanted = preferPackId ?? _state.ActivePackId;
        int index = choices.FindIndex(choice => string.Equals(choice.Installed.Pack.PackId, wanted, StringComparison.OrdinalIgnoreCase));
        if (index < 0 && choices.Count > 0) index = 0;
        if (index >= 0) _packCombo.SelectedIndex = index;
        else
        {
            _pack = null; _state.ActivePackId = null; UpdateCoverage();
            _prompt.Text = "No SentencePack installed"; _answer.Clear();
            Announce("No SentencePack is installed. Use File, Import SentencePack to add a validated offline pack.");
        }
    }

    private void ChangePack()
    {
        if (_packCombo.SelectedItem is not PackChoice choice) return;
        if (_pack is not null && string.Equals(_pack.PackId, choice.Installed.Pack.PackId, StringComparison.OrdinalIgnoreCase)) return;
        _pack = choice.Installed.Pack; _state.ActivePackId = _pack.PackId; ClearCurrent(); Save(); UpdateCoverage(); Next();
    }

    private void ImportPack()
    {
        using var dialog = new OpenFileDialog { Title = "Import WordDeck SentencePack", Filter = "WordDeck SentencePack (*.json)|*.json|JSON files (*.json)|*.json|All files (*.*)|*.*" };
        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        try
        {
            InstalledSentencePack installed = _packStore.Import(dialog.FileName);
            PopulatePacks(installed.Pack.PackId);
            Announce($"Imported SentencePack {installed.Pack.PackId}, {installed.Pack.Sentences.Count} sentences, license {installed.Pack.License}.");
        }
        catch (Exception ex) { Warn("SentencePack import failed: " + ex.Message); }
    }

    private IReadOnlyList<DictionaryEntry> ScopeEntries() =>
        _package.Entries.Where(entry => string.Equals(_spellingDeckMap.GetValueOrDefault(entry.Id, _spellingDecks.FirstDeck.Id), _activeDeckId, StringComparison.OrdinalIgnoreCase)).ToList();

    private void UpdateCoverage()
    {
        DeckDefinition deck = _spellingDecks.Find(_activeDeckId) ?? _spellingDecks.FirstDeck;
        int scope = ScopeEntries().Count;
        int covered = _pack is null ? 0 : ScopeEntries().Count(entry => _pack.LookupByEntryId(entry.Id).Count > 0);
        _coverage.Text = _pack is null
            ? $"{deck.Name}: {scope} target words. No SentencePack loaded."
            : $"{deck.Name}: {scope} target words; {covered} currently have at least one corpus sentence in {_pack.PackId}.";
    }

    private void RestoreOrNext()
    {
        if (_pack is not null && !string.IsNullOrWhiteSpace(_state.CurrentSentenceId) && !string.IsNullOrWhiteSpace(_state.CurrentTargetEntryId) &&
            _entries.TryGetValue(_state.CurrentTargetEntryId, out DictionaryEntry? target) &&
            string.Equals(_spellingDeckMap.GetValueOrDefault(target.Id, _spellingDecks.FirstDeck.Id), _activeDeckId, StringComparison.OrdinalIgnoreCase))
        {
            SentenceRecord? sentence = _pack.Sentences.FirstOrDefault(item => string.Equals(item.Id, _state.CurrentSentenceId, StringComparison.OrdinalIgnoreCase));
            if (sentence is not null && sentence.TargetEntryIds.Contains(target.Id, StringComparer.OrdinalIgnoreCase))
            {
                Show(sentence, target); return;
            }
        }
        Next();
    }

    private void Next()
    {
        if (_pack is null) return;
        IReadOnlyList<DictionaryEntry> scope = ScopeEntries();
        List<DictionaryEntry> covered = scope.Where(entry => _pack.LookupByEntryId(entry.Id).Count > 0).ToList();
        if (covered.Count == 0)
        {
            ClearCurrent(); _prompt.Text = "No corpus sentence covers a word in this spelling deck"; _answer.Clear();
            Announce("This spelling deck currently has no one-target sentence coverage in the selected SentencePack."); UpdateCoverage(); return;
        }

        DictionaryEntry target = ChooseWeakTarget(covered);
        var allowed = new HashSet<string>(scope.Select(entry => entry.Id), StringComparer.OrdinalIgnoreCase);
        var known = new HashSet<string>(
            _package.Entries.Where(entry => IsKnownSpellingDeck(_spellingDeckMap.GetValueOrDefault(entry.Id, _spellingDecks.FirstDeck.Id))).Select(entry => entry.Id),
            StringComparer.OrdinalIgnoreCase);
        var levels = _package.Entries.ToDictionary(entry => entry.Id, entry => entry.Level, StringComparer.OrdinalIgnoreCase);
        var recent = new HashSet<string>(_state.RecentSentenceIds, StringComparer.OrdinalIgnoreCase);
        var context = new SentenceSelectionContext(allowed, known, recent, levels);
        SentenceSelectionResult? selected = new SentenceSelector(_pack).Select(new[] { target.Id }, context);
        if (selected is null)
        {
            Announce($"No suitable corpus sentence is available for {target.Source} in the selected scope."); return;
        }
        Show(selected.Sentence, target);
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
        if (_currentTarget is not null && poolSize > 1)
        {
            List<DictionaryEntry> pool = ranked.Take(poolSize).Where(entry => !string.Equals(entry.Id, _currentTarget.Id, StringComparison.OrdinalIgnoreCase)).ToList();
            if (pool.Count > 0) return pool[_random.Next(pool.Count)];
        }
        return ranked[_random.Next(poolSize)];
    }

    private static int Weakness(SentenceTargetStats? stats) => stats is null ? 1000 : stats.WrongAttempts * 8 + stats.ShowAnswerUses * 6 - stats.FirstTrySuccesses * 2 - stats.CompletedReviews;

    private static bool IsKnownSpellingDeck(string deckId)
    {
        int index = SpellingDeckIds.CoreDecks.ToList().FindIndex(id => string.Equals(id, deckId, StringComparison.OrdinalIgnoreCase));
        return index >= 3;
    }

    private void Show(SentenceRecord sentence, DictionaryEntry target)
    {
        _currentSentence = sentence; _currentTarget = target; _hadWrong = false; _usedHint = false;
        _prompt.Text = sentence.Ukrainian; _target.Text = $"Target from selected scope: {target.Target}."; _answer.Clear(); _answer.Focus();
        _state.CurrentSentenceId = sentence.Id; _state.CurrentTargetEntryId = target.Id; Save();
        AccessibilityAnnouncer.Announce(_prompt, sentence.Ukrainian);
    }

    private void Submit()
    {
        if (_currentSentence is null || _currentTarget is null) return;
        SentenceAnswerResult result = SentenceAnswerEvaluator.Evaluate(_currentSentence.English, _answer.Text);
        SentenceTargetStats stats = GetStats(_currentTarget.Id);
        if (!result.Accepted)
        {
            _hadWrong = true; stats.WrongAttempts++; Save(); _answer.SelectAll(); Announce(result.Feedback + " The sentence will not advance. Try again."); return;
        }
        stats.CompletedReviews++;
        if (!_hadWrong && !_usedHint) stats.FirstTrySuccesses++;
        stats.LastReviewedUtc = DateTimeOffset.UtcNow;
        RememberSentence(_currentSentence.Id); Save();
        Announce(result.Feedback); Next();
    }

    private void ShowAnswer()
    {
        if (_currentSentence is null || _currentTarget is null) return;
        _usedHint = true; GetStats(_currentTarget.Id).ShowAnswerUses++; Save();
        Announce($"Required English forms: {_currentSentence.English}. You must still type all required forms correctly before advancing. Word order is not assessed.");
        _answer.Focus();
    }

    private void RepeatPrompt()
    {
        if (_currentSentence is null) return;
        AccessibilityAnnouncer.Announce(_prompt, _currentSentence.Ukrainian); _answer.Focus();
    }

    private Dictionary<string, SentenceTargetStats> GetStatsMap()
    {
        if (!_state.StatsByDictionary.TryGetValue(_package.Id, out Dictionary<string, SentenceTargetStats>? map))
        {
            map = new(StringComparer.OrdinalIgnoreCase); _state.StatsByDictionary[_package.Id] = map;
        }
        return map;
    }

    private SentenceTargetStats GetStats(string entryId)
    {
        Dictionary<string, SentenceTargetStats> map = GetStatsMap();
        if (!map.TryGetValue(entryId, out SentenceTargetStats? stats)) { stats = new(); map[entryId] = stats; }
        return stats;
    }

    private void RememberSentence(string id)
    {
        _state.RecentSentenceIds.RemoveAll(existing => string.Equals(existing, id, StringComparison.OrdinalIgnoreCase));
        _state.RecentSentenceIds.Add(id);
        if (_state.RecentSentenceIds.Count > 30) _state.RecentSentenceIds.RemoveRange(0, _state.RecentSentenceIds.Count - 30);
    }

    private void ClearCurrent()
    {
        _currentSentence = null; _currentTarget = null; _state.CurrentSentenceId = null; _state.CurrentTargetEntryId = null;
    }

    private void Save()
    {
        _state.ActivePackId = _pack?.PackId; _state.ActiveSpellingDeckId = _activeDeckId; _stateStore.Save(_state);
    }

    private void Announce(string text) { _status.Text = text; AccessibilityAnnouncer.Announce(_status, text); }
    private void Warn(string text) => MessageBox.Show(this, text, "Sentence Spelling", MessageBoxButtons.OK, MessageBoxIcon.Warning);

    protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
    {
        string? action = _shortcuts.FindAction(keyData);
        if (action is null) return base.ProcessCmdKey(ref msg, keyData);
        if (action == ActionIds.SentenceShowAnswer) ShowAnswer();
        else if (action == ActionIds.SentenceRepeatPrompt) RepeatPrompt();
        else if (action == ActionIds.SentenceImportPack) ImportPack();
        else return base.ProcessCmdKey(ref msg, keyData);
        return true;
    }
}
