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
    public string? CurrentSentenceId { get; set; }
    // Kept for backwards-compatible migration from the original one-target state.
    public string? CurrentTargetEntryId { get; set; }
    public List<string> CurrentTargetEntryIds { get; set; } = new();
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
        state.TargetCount = Math.Clamp(state.TargetCount, 1, 2);
        state.CurrentTargetEntryIds ??= new();
        state.CurrentTargetEntryIds = state.CurrentTargetEntryIds
            .Where(id => !string.IsNullOrWhiteSpace(id))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Take(2)
            .ToList();

        if (state.CurrentTargetEntryIds.Count == 0 && !string.IsNullOrWhiteSpace(state.CurrentTargetEntryId))
            state.CurrentTargetEntryIds.Add(state.CurrentTargetEntryId);

        state.CurrentTargetEntryId = state.CurrentTargetEntryIds.FirstOrDefault();

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

    private readonly SpellingDeckService _spellingDecks;
    private readonly ShortcutManager _shortcuts;
    private readonly DictionaryPackage _package;
    private readonly Dictionary<string, DictionaryEntry> _entries;
    private readonly Dictionary<string, string> _spellingDeckMap;
    private readonly SentencePackStore _packStore;
    private readonly SentenceCoachStateStore _stateStore;
    private readonly SentenceCoachState _state;
    private readonly Random _random = new();

    private readonly ComboBox _packCombo = new()
    {
        DropDownStyle = ComboBoxStyle.DropDownList,
        Width = 320,
        AccessibleName = "Sentence pack",
        AccessibleDescription = "Choose an installed offline SentencePack. Disk-backed SQLite is preferred automatically when available."
    };
    private readonly ComboBox _deckCombo = new()
    {
        DropDownStyle = ComboBoxStyle.DropDownList,
        Width = 260,
        DisplayMember = nameof(DeckDefinition.Name),
        AccessibleName = "Sentence training spelling deck"
    };
    private readonly ComboBox _targetCountCombo = new()
    {
        DropDownStyle = ComboBoxStyle.DropDownList,
        Width = 150,
        AccessibleName = "Number of target words per sentence"
    };
    private readonly TextBox _prompt = new()
    {
        ReadOnly = true,
        Multiline = true,
        Dock = DockStyle.Fill,
        AccessibleName = "Ukrainian sentence prompt",
        Font = new Font(SystemFonts.DefaultFont.FontFamily, 17)
    };
    private readonly TextBox _answer = new()
    {
        Multiline = true,
        Dock = DockStyle.Fill,
        AcceptsReturn = false,
        AccessibleName = "Type the English sentence words"
    };
    private readonly Label _target = new() { AutoSize = true, AccessibleName = "Sentence target words" };
    private readonly Label _status = new() { AutoSize = true, AccessibleName = "Sentence Coach status" };
    private readonly Label _coverage = new() { AutoSize = true, AccessibleName = "Sentence Coach scope coverage" };
    private readonly Label _modeInfo = new() { AutoSize = true, AccessibleName = "Sentence Coach mode information" };

    private ISentenceCorpus? _corpus;
    private string _activeDeckId;
    private SentenceRecord? _currentSentence;
    private readonly List<DictionaryEntry> _currentTargets = new();
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
        _ = appState;
        _spellingDecks = new SpellingDeckService(spellingState);
        _shortcuts = shortcuts;
        _package = package;
        _entries = package.Entries.ToDictionary(entry => entry.Id, StringComparer.OrdinalIgnoreCase);
        _spellingDeckMap = _spellingDecks.EnsureAssignments(package.Id, package.Entries.Select(entry => entry.Id));
        _packStore = packStore;
        _stateStore = stateStore;
        _state = SentenceCoachStateStore.Normalize(state);
        _activeDeckId = _spellingDecks.Find(state.ActiveSpellingDeckId ?? string.Empty)?.Id ?? _spellingDecks.FirstDeck.Id;

        Text = "WordDeck Sentence Spelling";
        Width = 980;
        Height = 640;
        MinimumSize = new Size(700, 490);
        StartPosition = FormStartPosition.CenterParent;
        KeyPreview = true;
        AccessibleName = "WordDeck Sentence Spelling trainer";
        MainMenuStrip = BuildMenu();
        Controls.Add(MainMenuStrip);

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
        top.Controls.Add(new Label { Text = "Sentence pack:", AutoSize = true, Padding = new Padding(0, 6, 4, 0) });
        top.Controls.Add(_packCombo);
        top.Controls.Add(new Label { Text = "Spelling deck scope:", AutoSize = true, Padding = new Padding(12, 6, 4, 0) });
        top.Controls.Add(_deckCombo);
        top.Controls.Add(new Label { Text = "Targets:", AutoSize = true, Padding = new Padding(12, 6, 4, 0) });
        top.Controls.Add(_targetCountCombo);

        root.Controls.Add(top, 0, 0);
        root.Controls.Add(_coverage, 0, 1);
        root.Controls.Add(_target, 0, 2);
        root.Controls.Add(new Label { Text = "Ukrainian sentence", AutoSize = true, Font = new Font(Font, FontStyle.Bold) }, 0, 3);
        root.Controls.Add(_prompt, 0, 4);
        root.Controls.Add(new Label
        {
            Text = "Type all required English word forms and press Enter. Word order is not assessed.",
            AutoSize = true,
            Font = new Font(Font, FontStyle.Bold)
        }, 0, 5);
        root.Controls.Add(_answer, 0, 6);
        root.Controls.Add(_status, 0, 7);
        root.Controls.Add(_modeInfo, 0, 8);
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
        Add(training, "&Show required English sentence", ShowAnswer);
        Add(training, "&Repeat Ukrainian sentence", RepeatPrompt);
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
        _targetCountCombo.Items.Add(new TargetCountChoice(2, "2 targets"));
        _targetCountCombo.SelectedIndex = _state.TargetCount - 1;
        _targetCountCombo.EndUpdate();
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
            _answer.Clear();
            Announce("No SentencePack is installed. Use File, Import SentencePack to add a validated offline .json.gz or .json pack.");
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
            PopulatePacks(installed.PackId);
            Announce($"Imported SentencePack {installed.PackId}, {installed.SentenceCount:N0} sentences, license {installed.License}. Disk-backed runtime index is ready.");
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

    private HashSet<string> CoveredScopeEntryIds(IReadOnlyList<DictionaryEntry> scopeEntries, bool requireSameScopePartner)
    {
        if (_corpus is null)
            return new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        string[] scopeIds = scopeEntries.Select(entry => entry.Id).ToArray();
        if (_corpus is SentencePackSqliteCorpus sqlite)
            return sqlite.GetCoveredScopeEntryIds(scopeIds, requireSameScopePartner);

        if (!requireSameScopePartner)
            return new HashSet<string>(
                scopeEntries.Where(entry => _corpus.LookupByEntryId(entry.Id).Count > 0).Select(entry => entry.Id),
                StringComparer.OrdinalIgnoreCase);

        var allowed = new HashSet<string>(scopeIds, StringComparer.OrdinalIgnoreCase);
        return new HashSet<string>(
            scopeEntries.Where(entry => HasSameScopePartner(entry.Id, allowed)).Select(entry => entry.Id),
            StringComparer.OrdinalIgnoreCase);
    }

    private void UpdateCoverage()
    {
        DeckDefinition deck = _spellingDecks.Find(_activeDeckId) ?? _spellingDecks.FirstDeck;
        IReadOnlyList<DictionaryEntry> scopeEntries = ScopeEntries();
        int scope = scopeEntries.Count;
        if (_corpus is null)
        {
            _coverage.Text = $"{deck.Name}: {scope} target words. No SentencePack loaded.";
            return;
        }

        HashSet<string> covered = CoveredScopeEntryIds(scopeEntries, _state.TargetCount == 2);
        _coverage.Text = _state.TargetCount == 1
            ? $"{deck.Name}: {scope} target words; {covered.Count} currently have at least one corpus sentence in {_corpus.PackId}."
            : $"{deck.Name}: {scope} target words; {covered.Count} currently have at least one same-scope two-target corpus intersection in {_corpus.PackId}.";
    }

    private bool HasSameScopePartner(string entryId, HashSet<string> allowed)
    {
        if (_corpus is null)
            return false;
        foreach (SentenceRecord sentence in _corpus.LookupByEntryId(entryId))
        {
            if (sentence.TargetEntryIds.Any(id =>
                    !string.Equals(id, entryId, StringComparison.OrdinalIgnoreCase) && allowed.Contains(id)))
                return true;
        }
        return false;
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
                var restoredTargets = new List<DictionaryEntry>();
                bool valid = true;
                foreach (string id in targetIds)
                {
                    if (!_entries.TryGetValue(id, out DictionaryEntry? target) ||
                        !string.Equals(
                            _spellingDeckMap.GetValueOrDefault(target.Id, _spellingDecks.FirstDeck.Id),
                            _activeDeckId,
                            StringComparison.OrdinalIgnoreCase))
                    {
                        valid = false;
                        break;
                    }
                    restoredTargets.Add(target);
                }

                SentenceRecord? sentence = valid
                    ? _corpus.LookupAllTargets(targetIds)
                        .FirstOrDefault(item => string.Equals(item.Id, _state.CurrentSentenceId, StringComparison.OrdinalIgnoreCase))
                    : null;

                if (sentence is not null && restoredTargets.All(target =>
                        sentence.TargetEntryIds.Contains(target.Id, StringComparer.OrdinalIgnoreCase)))
                {
                    Show(sentence, restoredTargets);
                    return;
                }
            }
        }
        Next();
    }

    private void Next()
    {
        if (_corpus is null)
            return;

        IReadOnlyList<DictionaryEntry> scope = ScopeEntries();
        var allowed = new HashSet<string>(scope.Select(entry => entry.Id), StringComparer.OrdinalIgnoreCase);
        HashSet<string> coveredIds = CoveredScopeEntryIds(scope, _state.TargetCount == 2);
        List<DictionaryEntry> covered = scope.Where(entry => coveredIds.Contains(entry.Id)).ToList();

        if (covered.Count == 0)
        {
            ClearCurrent();
            _prompt.Text = _state.TargetCount == 1
                ? "No corpus sentence covers a word in this spelling deck"
                : "No corpus sentence covers two words from this spelling deck";
            _answer.Clear();
            Announce(_state.TargetCount == 1
                ? "This spelling deck currently has no one-target sentence coverage in the selected SentencePack."
                : "This spelling deck currently has no same-scope two-target sentence intersections in the selected SentencePack.");
            UpdateCoverage();
            return;
        }

        DictionaryEntry primary = ChooseWeakTarget(covered);
        var targets = new List<DictionaryEntry> { primary };

        if (_state.TargetCount == 2)
        {
            List<DictionaryEntry> partners = GetPartnerCandidates(primary.Id, scope);
            if (partners.Count == 0)
            {
                Announce($"No second same-scope target is currently available with {primary.Target}. Trying another exercise.");
                ClearCurrent();
                Next();
                return;
            }
            targets.Add(ChooseWeakTarget(partners));
        }

        var known = new HashSet<string>(
            _package.Entries
                .Where(entry => IsKnownSpellingDeck(_spellingDeckMap.GetValueOrDefault(entry.Id, _spellingDecks.FirstDeck.Id)))
                .Select(entry => entry.Id),
            StringComparer.OrdinalIgnoreCase);
        var levels = _package.Entries.ToDictionary(entry => entry.Id, entry => entry.Level, StringComparer.OrdinalIgnoreCase);
        var recent = new HashSet<string>(_state.RecentSentenceIds, StringComparer.OrdinalIgnoreCase);
        var context = new SentenceSelectionContext(allowed, known, recent, levels);
        string[] targetIds = targets.Select(target => target.Id).ToArray();
        SentenceSelectionResult? selected = new SentenceSelector(_corpus).Select(targetIds, context);
        if (selected is null)
        {
            Announce($"No suitable corpus sentence is available for the selected {targets.Count}-target exercise.");
            return;
        }
        Show(selected.Sentence, targets);
    }

    private List<DictionaryEntry> GetPartnerCandidates(string primaryId, IReadOnlyList<DictionaryEntry> scope)
    {
        if (_corpus is null)
            return new();

        var scopeById = scope.ToDictionary(entry => entry.Id, StringComparer.OrdinalIgnoreCase);
        var partnerIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (SentenceRecord sentence in _corpus.LookupByEntryId(primaryId))
        {
            foreach (string id in sentence.TargetEntryIds)
            {
                if (!string.Equals(id, primaryId, StringComparison.OrdinalIgnoreCase) && scopeById.ContainsKey(id))
                    partnerIds.Add(id);
            }
        }

        return partnerIds
            .Select(id => scopeById[id])
            .Where(entry => _corpus.LookupAllTargets(new[] { primaryId, entry.Id }).Count > 0)
            .ToList();
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

    private void Show(SentenceRecord sentence, IReadOnlyList<DictionaryEntry> targets)
    {
        _currentSentence = sentence;
        _currentTargets.Clear();
        _currentTargets.AddRange(targets);
        _hadWrong = false;
        _usedHint = false;
        _prompt.Text = sentence.Ukrainian;
        string meanings = string.Join("; ", targets.Select(target => target.Target));
        _target.Text = targets.Count == 1
            ? $"Target meaning from selected scope: {meanings}."
            : $"Two target meanings from selected scope: {meanings}.";
        _answer.Clear();
        _answer.Focus();
        _state.CurrentSentenceId = sentence.Id;
        _state.CurrentTargetEntryIds = targets.Select(target => target.Id).ToList();
        _state.CurrentTargetEntryId = _state.CurrentTargetEntryIds.FirstOrDefault();
        Save();
        AccessibilityAnnouncer.Announce(_prompt, sentence.Ukrainian);
    }

    private void Submit()
    {
        if (_currentSentence is null || _currentTargets.Count == 0)
            return;

        SentenceAnswerResult result = SentenceAnswerEvaluator.Evaluate(_currentSentence.English, _answer.Text);
        if (!result.Accepted)
        {
            _hadWrong = true;
            foreach (DictionaryEntry target in _currentTargets)
                GetStats(target.Id).WrongAttempts++;
            Save();
            _answer.SelectAll();
            Announce(result.Feedback + " The sentence will not advance. Try again.");
            return;
        }

        foreach (DictionaryEntry target in _currentTargets)
        {
            SentenceTargetStats stats = GetStats(target.Id);
            stats.CompletedReviews++;
            if (!_hadWrong && !_usedHint)
                stats.FirstTrySuccesses++;
            stats.LastReviewedUtc = DateTimeOffset.UtcNow;
        }

        RememberSentence(_currentSentence.Id);
        Save();
        Announce(result.Feedback);
        Next();
    }

    private void ShowAnswer()
    {
        if (_currentSentence is null || _currentTargets.Count == 0)
            return;
        _usedHint = true;
        foreach (DictionaryEntry target in _currentTargets)
            GetStats(target.Id).ShowAnswerUses++;
        Save();
        Announce($"Required English forms: {_currentSentence.English}. You must still type all required forms correctly before advancing. Word order is not assessed.");
        _answer.Focus();
    }

    private void RepeatPrompt()
    {
        if (_currentSentence is null)
            return;
        AccessibilityAnnouncer.Announce(_prompt, _currentSentence.Ukrainian);
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
        _state.CurrentSentenceId = null;
        _state.CurrentTargetEntryId = null;
        _state.CurrentTargetEntryIds.Clear();
    }

    private void Save()
    {
        _state.ActivePackId = _corpus?.PackId;
        _state.ActiveSpellingDeckId = _activeDeckId;
        _stateStore.Save(_state);
    }

    private void UpdateModeInfo()
    {
        _modeInfo.Text = _state.TargetCount == 1
            ? "One-target Sentence Spelling. The target always remains inside the selected spelling-deck scope."
            : "Two-target Sentence Spelling. Both targets must come from the selected spelling-deck scope and the corpus sentence must contain both.";
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
