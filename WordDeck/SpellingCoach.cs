using System.Text.Json;

namespace WordDeck;

internal static class SpellingDeckIds
{
    public static string Core(int number) => $"spelling-core-{number}";
    public static IReadOnlyList<string> CoreDecks { get; } = Enumerable.Range(1, 5).Select(Core).ToArray();
}

internal sealed class SpellingEntryStats
{
    public int CompletedReviews { get; set; }
    public int FirstTrySuccesses { get; set; }
    public int WrongAttempts { get; set; }
    public int HintUses { get; set; }
    public int ShowAnswerUses { get; set; }
    public int CurrentStreak { get; set; }
    public List<bool> RecentOutcomes { get; set; } = new();
    public DateTimeOffset? LastReviewedUtc { get; set; }
}

internal sealed record SpellingCoachMove(
    string DictionaryId,
    string EntryId,
    string FromDeckId,
    string ToDeckId,
    string Reason,
    DateTimeOffset TimestampUtc);

internal sealed class SpellingState
{
    public string? ActiveDeckId { get; set; }
    public List<DeckDefinition> Decks { get; set; } = new();
    public Dictionary<string, Dictionary<string, string>> DeckIdsByDictionary { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public Dictionary<string, string> CurrentEntryIdByDictionary { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public Dictionary<string, Dictionary<string, SpellingEntryStats>> StatsByDictionary { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public bool CoachEnabled { get; set; } = true;
    public SpellingCoachMove? LastCoachMove { get; set; }
}

internal sealed class SpellingStateStore
{
    private readonly string _path;
    private readonly string _backupPath;

    public SpellingStateStore()
    {
        string root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WordDeck");
        Directory.CreateDirectory(root);
        _path = Path.Combine(root, "spelling-state.json");
        _backupPath = Path.Combine(root, "spelling-state.backup.json");
    }

    internal SpellingStateStore(string root)
    {
        Directory.CreateDirectory(root);
        _path = Path.Combine(root, "spelling-state.json");
        _backupPath = Path.Combine(root, "spelling-state.backup.json");
    }

    public SpellingState Load() => Normalize(TryLoad(_path) ?? TryLoad(_backupPath) ?? new SpellingState());

    public void Save(SpellingState state)
    {
        Normalize(state);
        string temp = _path + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(state, new JsonSerializerOptions { WriteIndented = true }));
        if (TryLoad(_path) is not null)
            File.Copy(_path, _backupPath, true);
        File.Move(temp, _path, true);
    }

    private static SpellingState? TryLoad(string path)
    {
        try
        {
            return File.Exists(path) ? JsonSerializer.Deserialize<SpellingState>(File.ReadAllText(path)) : null;
        }
        catch
        {
            return null;
        }
    }

    internal static SpellingState Normalize(SpellingState state)
    {
        state.Decks ??= new();
        state.DeckIdsByDictionary ??= new(StringComparer.OrdinalIgnoreCase);
        state.CurrentEntryIdByDictionary ??= new(StringComparer.OrdinalIgnoreCase);
        state.StatsByDictionary ??= new(StringComparer.OrdinalIgnoreCase);

        state.Decks = state.Decks
            .Where(deck => deck is not null && !string.IsNullOrWhiteSpace(deck.Id))
            .GroupBy(deck => deck.Id, StringComparer.OrdinalIgnoreCase)
            .Select(group => group.First())
            .ToList();

        for (int number = 1; number <= 5; number++)
        {
            string id = SpellingDeckIds.Core(number);
            DeckDefinition? deck = state.Decks.FirstOrDefault(item => string.Equals(item.Id, id, StringComparison.OrdinalIgnoreCase));
            if (deck is null)
            {
                state.Decks.Add(new DeckDefinition { Id = id, Name = $"Spelling deck {number}", IsCore = true, Order = number - 1 });
            }
            else
            {
                deck.IsCore = true;
                if (string.IsNullOrWhiteSpace(deck.Name))
                    deck.Name = $"Spelling deck {number}";
            }
        }

        List<DeckDefinition> ordered = state.Decks.OrderBy(d => d.Order).ThenBy(d => d.Name, StringComparer.CurrentCultureIgnoreCase).ToList();
        for (int i = 0; i < ordered.Count; i++) ordered[i].Order = i;
        state.Decks = ordered;

        var validDeckIds = new HashSet<string>(state.Decks.Select(d => d.Id), StringComparer.OrdinalIgnoreCase);
        string fallback = SpellingDeckIds.Core(1);
        foreach (Dictionary<string, string> map in state.DeckIdsByDictionary.Values)
        {
            foreach (string entryId in map.Keys.ToList())
                if (string.IsNullOrWhiteSpace(map[entryId]) || !validDeckIds.Contains(map[entryId]))
                    map[entryId] = fallback;
        }

        if (string.IsNullOrWhiteSpace(state.ActiveDeckId) || !validDeckIds.Contains(state.ActiveDeckId))
            state.ActiveDeckId = fallback;

        foreach (Dictionary<string, SpellingEntryStats> stats in state.StatsByDictionary.Values)
        {
            foreach (SpellingEntryStats value in stats.Values)
            {
                value.RecentOutcomes ??= new();
                if (value.RecentOutcomes.Count > 10)
                    value.RecentOutcomes = value.RecentOutcomes.TakeLast(10).ToList();
            }
        }
        return state;
    }
}

internal sealed class SpellingDeckService
{
    private readonly SpellingState _state;
    public SpellingDeckService(SpellingState state) => _state = state;
    public IReadOnlyList<DeckDefinition> Decks => _state.Decks.OrderBy(d => d.Order).ToList();
    public DeckDefinition FirstDeck => Decks.First();
    public DeckDefinition? Find(string id) => _state.Decks.FirstOrDefault(d => string.Equals(d.Id, id, StringComparison.OrdinalIgnoreCase));

    public Dictionary<string, string> EnsureAssignments(string dictionaryId, IEnumerable<string> entryIds)
    {
        if (!_state.DeckIdsByDictionary.TryGetValue(dictionaryId, out Dictionary<string, string>? map))
        {
            map = new(StringComparer.OrdinalIgnoreCase);
            _state.DeckIdsByDictionary[dictionaryId] = map;
        }
        var validEntries = new HashSet<string>(entryIds, StringComparer.OrdinalIgnoreCase);
        var validDecks = new HashSet<string>(_state.Decks.Select(d => d.Id), StringComparer.OrdinalIgnoreCase);
        foreach (string stale in map.Keys.Where(id => !validEntries.Contains(id)).ToList()) map.Remove(stale);
        foreach (string id in validEntries)
            if (!map.TryGetValue(id, out string? deckId) || !validDecks.Contains(deckId)) map[id] = FirstDeck.Id;
        return map;
    }

    public DeckDefinition Create(string name)
    {
        name = NormalizeName(name);
        EnsureUnique(name, null);
        var deck = new DeckDefinition
        {
            Id = $"spelling-user-{Guid.NewGuid():N}", Name = name, IsCore = false,
            Order = _state.Decks.Count == 0 ? 0 : _state.Decks.Max(d => d.Order) + 1
        };
        _state.Decks.Add(deck);
        NormalizeOrder();
        return deck;
    }

    public void Rename(string id, string name)
    {
        DeckDefinition deck = Find(id) ?? throw new InvalidOperationException("Spelling deck no longer exists.");
        name = NormalizeName(name);
        EnsureUnique(name, id);
        deck.Name = name;
    }

    public bool Move(string id, int direction)
    {
        List<DeckDefinition> ordered = Decks.ToList();
        int index = ordered.FindIndex(d => string.Equals(d.Id, id, StringComparison.OrdinalIgnoreCase));
        int target = index + direction;
        if (index < 0 || target < 0 || target >= ordered.Count) return false;
        (ordered[index], ordered[target]) = (ordered[target], ordered[index]);
        for (int i = 0; i < ordered.Count; i++) ordered[i].Order = i;
        return true;
    }

    public int CountInDictionary(string dictionaryId, string deckId) =>
        _state.DeckIdsByDictionary.TryGetValue(dictionaryId, out Dictionary<string, string>? map)
            ? map.Values.Count(id => string.Equals(id, deckId, StringComparison.OrdinalIgnoreCase)) : 0;

    public int CountEverywhere(string deckId) => _state.DeckIdsByDictionary.Values.Sum(map => map.Values.Count(id => string.Equals(id, deckId, StringComparison.OrdinalIgnoreCase)));

    public void DeleteUserDeck(string id, string? destinationId)
    {
        DeckDefinition deck = Find(id) ?? throw new InvalidOperationException("Spelling deck no longer exists.");
        if (deck.IsCore) throw new InvalidOperationException("The five core spelling decks are permanent.");
        int assigned = CountEverywhere(id);
        if (assigned > 0)
        {
            if (string.IsNullOrWhiteSpace(destinationId) || string.Equals(destinationId, id, StringComparison.OrdinalIgnoreCase) || Find(destinationId) is null)
                throw new InvalidOperationException("Choose a valid destination before deleting a non-empty spelling deck.");
            foreach (Dictionary<string, string> map in _state.DeckIdsByDictionary.Values)
                foreach (string entryId in map.Where(pair => string.Equals(pair.Value, id, StringComparison.OrdinalIgnoreCase)).Select(pair => pair.Key).ToList())
                    map[entryId] = destinationId;
        }
        _state.Decks.Remove(deck);
        if (string.Equals(_state.ActiveDeckId, id, StringComparison.OrdinalIgnoreCase))
            _state.ActiveDeckId = destinationId ?? Decks.First(d => !string.Equals(d.Id, id, StringComparison.OrdinalIgnoreCase)).Id;
        NormalizeOrder();
    }

    private void NormalizeOrder()
    {
        List<DeckDefinition> ordered = _state.Decks.OrderBy(d => d.Order).ThenBy(d => d.Name, StringComparer.CurrentCultureIgnoreCase).ToList();
        for (int i = 0; i < ordered.Count; i++) ordered[i].Order = i;
    }
    private static string NormalizeName(string name)
    {
        string value = (name ?? string.Empty).Trim();
        if (value.Length == 0) throw new InvalidOperationException("Deck name cannot be blank.");
        if (value.Length > 80) throw new InvalidOperationException("Deck name cannot be longer than 80 characters.");
        return value;
    }
    private void EnsureUnique(string name, string? exceptId)
    {
        if (_state.Decks.Any(d => !string.Equals(d.Id, exceptId, StringComparison.OrdinalIgnoreCase) && string.Equals(d.Name, name, StringComparison.CurrentCultureIgnoreCase)))
            throw new InvalidOperationException("A spelling deck with that name already exists.");
    }
}

internal sealed record SpellingScheduleDecision(string? TargetDeckId, string Explanation);

internal interface ISpellingScheduler
{
    SpellingScheduleDecision Decide(string currentDeckId, SpellingEntryStats stats, bool firstTryCorrect, bool usedHint);
}

internal sealed class ConservativeSpellingScheduler : ISpellingScheduler
{
    public SpellingScheduleDecision Decide(string currentDeckId, SpellingEntryStats stats, bool firstTryCorrect, bool usedHint)
    {
        int current = SpellingDeckIds.CoreDecks.ToList().FindIndex(id => string.Equals(id, currentDeckId, StringComparison.OrdinalIgnoreCase)) + 1;
        if (current == 0) return new(null, "Adaptive coach never moves words in user-created spelling decks.");
        if ((!firstTryCorrect || usedHint) && current > 1)
            return new(SpellingDeckIds.Core(current - 1), "Moved one core deck earlier after a wrong attempt or hint so the word is reviewed more often.");
        if (firstTryCorrect && !usedHint && stats.CurrentStreak >= 3 && current < 5)
            return new(SpellingDeckIds.Core(current + 1), "Moved one core deck later after three consecutive clean first-try spellings.");
        return new(null, "No adaptive move: conservative thresholds were not crossed.");
    }
}

internal sealed class SpellingForm : Form
{
    private readonly AppState _appState;
    private readonly SpellingState _state;
    private readonly SpellingStateStore _store;
    private readonly SpellingDeckService _decks;
    private readonly ShortcutManager _shortcuts;
    private readonly DictionaryPackage _package;
    private readonly Dictionary<string, DictionaryEntry> _entries;
    private readonly Dictionary<string, string> _deckMap;
    private readonly PronunciationAudio _audio = new();
    private readonly ISpellingScheduler _scheduler = new ConservativeSpellingScheduler();
    private readonly Random _random = new();
    private readonly ComboBox _deckCombo = new()
    {
        DropDownStyle = ComboBoxStyle.DropDownList,
        DisplayMember = nameof(DeckDefinition.Name),
        AccessibleName = "Active spelling deck",
        AccessibleDescription = "Use standard Up and Down selection. Changing the deck while this selector is focused keeps focus in the selector.",
        Width = 260
    };
    private readonly Label _counts = new() { AutoSize = true, AccessibleName = "Spelling deck counts" };
    private readonly TextBox _prompt = new() { ReadOnly = true, Multiline = true, Dock = DockStyle.Fill, AccessibleName = "Ukrainian spelling prompt", Font = new Font(SystemFonts.DefaultFont.FontFamily, 18) };
    private readonly TextBox _answer = new() { Multiline = false, Dock = DockStyle.Fill, AccessibleName = "Type English spelling answer" };
    private readonly Label _status = new() { AutoSize = true, AccessibleName = "Spelling status" };
    private string _activeDeckId;
    private DictionaryEntry? _current;
    private bool _hadWrong;
    private bool _usedHint;

    public SpellingForm(AppState appState, SpellingState state, SpellingStateStore store, ShortcutManager shortcuts, DictionaryPackage package)
    {
        _appState = appState;
        _state = state;
        _store = store;
        _decks = new SpellingDeckService(state);
        _shortcuts = shortcuts;
        _package = package;
        _entries = package.Entries.ToDictionary(e => e.Id, StringComparer.OrdinalIgnoreCase);
        _deckMap = _decks.EnsureAssignments(package.Id, package.Entries.Select(e => e.Id));
        _activeDeckId = _decks.Find(state.ActiveDeckId ?? string.Empty)?.Id ?? _decks.FirstDeck.Id;
        _state.ActiveDeckId = _activeDeckId;

        Text = "WordDeck Spelling";
        Width = 880; Height = 520; MinimumSize = new Size(650, 420); StartPosition = FormStartPosition.CenterParent; KeyPreview = true;
        AccessibleName = "WordDeck Spelling trainer";
        MainMenuStrip = BuildMenu(); Controls.Add(MainMenuStrip);

        var root = new TableLayoutPanel { Dock = DockStyle.Fill, RowCount = 7, ColumnCount = 1, Padding = new Padding(16) };
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize)); root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize)); root.RowStyles.Add(new RowStyle(SizeType.Percent, 45));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize)); root.RowStyles.Add(new RowStyle(SizeType.AutoSize)); root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        var top = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoSize = true };
        top.Controls.Add(new Label { Text = "Spelling deck:", AutoSize = true, Padding = new Padding(0, 6, 4, 0) }); top.Controls.Add(_deckCombo);
        root.Controls.Add(top, 0, 0); root.Controls.Add(_counts, 0, 1);
        root.Controls.Add(new Label { Text = "Ukrainian prompt", AutoSize = true, Font = new Font(Font, FontStyle.Bold) }, 0, 2);
        root.Controls.Add(_prompt, 0, 3);
        root.Controls.Add(new Label { Text = "Type exact English spelling and press Enter", AutoSize = true, Font = new Font(Font, FontStyle.Bold) }, 0, 4);
        root.Controls.Add(_answer, 0, 5); root.Controls.Add(_status, 0, 6); Controls.Add(root); root.BringToFront();

        _deckCombo.SelectedIndexChanged += (_, _) =>
        {
            if (_deckCombo.SelectedItem is DeckDefinition d && !string.Equals(d.Id, _activeDeckId, StringComparison.OrdinalIgnoreCase))
                SwitchDeck(d.Id, focusAnswer: !_deckCombo.ContainsFocus);
        };
        _answer.KeyDown += (_, e) => { if (e.KeyCode == Keys.Enter) { e.SuppressKeyPress = true; Submit(); } };
        RefreshDeckUi();
        Shown += (_, _) => BeginInvoke(new Action(RestoreOrNext));
        FormClosing += (_, _) => { _audio.Dispose(); Save(); };
    }

    private MenuStrip BuildMenu()
    {
        var menu = new MenuStrip { AccessibleName = "Spelling menu" };
        var training = new ToolStripMenuItem("&Training");
        Add(training, "&Show spelling answer", ShowAnswer); Add(training, "&Repeat Ukrainian prompt", RepeatPrompt); Add(training, "Play &British pronunciation hint", PlayPronunciation);
        Add(training, "&Toggle adaptive coach", ToggleCoach); Add(training, "&Undo last coach move", UndoCoachMove);
        var decks = new ToolStripMenuItem("&Spelling decks");
        Add(decks, "&Move current word to spelling deck...", MoveCurrentChooser); Add(decks, "&Create spelling deck...", CreateDeck); Add(decks, "&Rename active spelling deck...", RenameDeck);
        Add(decks, "&Delete active user spelling deck...", DeleteDeck); Add(decks, "Move spelling deck &up", () => ReorderDeck(-1)); Add(decks, "Move spelling deck &down", () => ReorderDeck(1));
        menu.Items.Add(training); menu.Items.Add(decks); return menu;
    }

    private static void Add(ToolStripMenuItem parent, string text, Action action) { var item = new ToolStripMenuItem(text); item.Click += (_, _) => action(); parent.DropDownItems.Add(item); }

    private void RefreshDeckUi()
    {
        _deckCombo.BeginUpdate(); _deckCombo.Items.Clear(); foreach (DeckDefinition d in _decks.Decks) _deckCombo.Items.Add(d);
        for (int i = 0; i < _deckCombo.Items.Count; i++) if (_deckCombo.Items[i] is DeckDefinition d && string.Equals(d.Id, _activeDeckId, StringComparison.OrdinalIgnoreCase)) _deckCombo.SelectedIndex = i;
        _deckCombo.EndUpdate(); UpdateCounts(); _shortcuts.RefreshDeckDefinitions(_decks.Decks);
    }

    private IReadOnlyList<DictionaryEntry> ActiveEntries() => _package.Entries.Where(e => string.Equals(_deckMap.GetValueOrDefault(e.Id, _decks.FirstDeck.Id), _activeDeckId, StringComparison.OrdinalIgnoreCase)).ToList();
    private void RestoreOrNext()
    {
        if (_state.CurrentEntryIdByDictionary.TryGetValue(_package.Id, out string? id) && _entries.TryGetValue(id, out DictionaryEntry? e) && string.Equals(_deckMap.GetValueOrDefault(id), _activeDeckId, StringComparison.OrdinalIgnoreCase)) Show(e); else Next();
    }
    private void Next(bool focusAnswer = true)
    {
        IReadOnlyList<DictionaryEntry> entries = ActiveEntries();
        if (entries.Count == 0) { _current = null; _prompt.Text = "No words in this spelling deck"; _answer.Clear(); Announce("This spelling deck is empty."); return; }
        DictionaryEntry next = entries[_random.Next(entries.Count)]; if (_current is not null && entries.Count > 1) while (next.Id == _current.Id) next = entries[_random.Next(entries.Count)]; Show(next, focusAnswer);
    }
    private void Show(DictionaryEntry entry, bool focusAnswer = true)
    {
        _current = entry; _hadWrong = false; _usedHint = false; _prompt.Text = entry.Target; _answer.Clear(); if (focusAnswer) _answer.Focus();
        _state.CurrentEntryIdByDictionary[_package.Id] = entry.Id; Save(); AccessibilityAnnouncer.Announce(_prompt, entry.Target);
    }
    private void Submit()
    {
        if (_current is null) return;
        string typed = _answer.Text.Trim();
        SpellingEntryStats stats = GetStats(_current.Id);
        if (!string.Equals(typed, _current.Source, StringComparison.Ordinal))
        {
            _hadWrong = true; stats.WrongAttempts++; stats.CurrentStreak = 0; AddRecent(stats, false); Save();
            _answer.SelectAll(); Announce("Incorrect spelling. The word will not advance. Try again."); return;
        }
        bool cleanFirstTry = !_hadWrong && !_usedHint;
        stats.CompletedReviews++; if (cleanFirstTry) stats.FirstTrySuccesses++; stats.CurrentStreak = cleanFirstTry ? stats.CurrentStreak + 1 : 0; stats.LastReviewedUtc = DateTimeOffset.UtcNow; AddRecent(stats, true);
        ApplyCoach(stats, cleanFirstTry); Save(); Announce("Correct."); Next();
    }
    private SpellingEntryStats GetStats(string entryId)
    {
        if (!_state.StatsByDictionary.TryGetValue(_package.Id, out Dictionary<string, SpellingEntryStats>? map)) { map = new(StringComparer.OrdinalIgnoreCase); _state.StatsByDictionary[_package.Id] = map; }
        if (!map.TryGetValue(entryId, out SpellingEntryStats? stats)) { stats = new(); map[entryId] = stats; } return stats;
    }
    private static void AddRecent(SpellingEntryStats stats, bool result) { stats.RecentOutcomes.Add(result); if (stats.RecentOutcomes.Count > 10) stats.RecentOutcomes.RemoveAt(0); }
    private void ShowAnswer() { if (_current is null) return; _usedHint = true; SpellingEntryStats s = GetStats(_current.Id); s.HintUses++; s.ShowAnswerUses++; Save(); Announce($"Correct spelling: {_current.Source}. You must still type it correctly before this word can advance."); _answer.Focus(); }
    private void RepeatPrompt() { if (_current is not null) { _prompt.Focus(); _prompt.SelectAll(); AccessibilityAnnouncer.Announce(_prompt, _current.Target); _answer.Focus(); } }
    private void PlayPronunciation() { if (_current is null) return; _usedHint = true; GetStats(_current.Id).HintUses++; Save(); if (!_audio.TryPlay(_package, _current, out string? error) && error is not null) Announce(error); }
    private void ToggleCoach() { _state.CoachEnabled = !_state.CoachEnabled; Save(); Announce(_state.CoachEnabled ? "Adaptive spelling coach enabled." : "Adaptive spelling coach disabled."); }
    private void ApplyCoach(SpellingEntryStats stats, bool cleanFirstTry)
    {
        if (!_state.CoachEnabled || _current is null) return;
        string from = _deckMap.GetValueOrDefault(_current.Id, _decks.FirstDeck.Id); SpellingScheduleDecision decision = _scheduler.Decide(from, stats, cleanFirstTry, _usedHint);
        if (decision.TargetDeckId is null || string.Equals(decision.TargetDeckId, from, StringComparison.OrdinalIgnoreCase)) return;
        _deckMap[_current.Id] = decision.TargetDeckId; _state.LastCoachMove = new(_package.Id, _current.Id, from, decision.TargetDeckId, decision.Explanation, DateTimeOffset.UtcNow);
        Announce(decision.Explanation);
    }
    private void UndoCoachMove()
    {
        SpellingCoachMove? move = _state.LastCoachMove; if (move is null || !string.Equals(move.DictionaryId, _package.Id, StringComparison.OrdinalIgnoreCase)) { Announce("No adaptive spelling move is available to undo."); return; }
        if (_deckMap.GetValueOrDefault(move.EntryId) != move.ToDeckId) { _state.LastCoachMove = null; Save(); Announce("The last adaptive move can no longer be undone because the word moved again."); return; }
        _deckMap[move.EntryId] = move.FromDeckId; _state.LastCoachMove = null; Save(); UpdateCounts(); Announce("Undid the last adaptive spelling deck move.");
    }
    private void MoveCurrentChooser()
    {
        if (_current is null) return; string? target = DeckDialogs.ChooseDeck(this, "Move spelling word", $"Move {_current.Source} to which spelling deck?", _decks.Decks, _activeDeckId); if (target is not null) MoveCurrent(target);
    }
    private void MoveCurrent(string target)
    {
        if (_current is null || _decks.Find(target) is null) return; _deckMap[_current.Id] = target; _state.LastCoachMove = null; Save(); UpdateCounts(); Announce($"Moved {_current.Source} to {_decks.Find(target)!.Name}."); Next();
    }
    private void SwitchDeck(string id, bool focusAnswer = true) { if (_decks.Find(id) is null) return; _activeDeckId = id; _state.ActiveDeckId = id; Save(); RefreshDeckUi(); Announce($"Switched to {_decks.Find(id)!.Name}."); Next(focusAnswer); }
    private void CreateDeck() { string? name = DeckDialogs.PromptForName(this, "Create spelling deck", "Enter a name for the new empty spelling deck:"); if (name is null) return; try { DeckDefinition d = _decks.Create(name); _activeDeckId = d.Id; _state.ActiveDeckId = d.Id; Save(); RefreshDeckUi(); Next(); } catch (Exception ex) { Warn(ex.Message); } }
    private void RenameDeck() { DeckDefinition? d = _decks.Find(_activeDeckId); if (d is null) return; string? name = DeckDialogs.PromptForName(this, "Rename spelling deck", "Enter the new spelling deck name:", d.Name); if (name is null) return; try { _decks.Rename(d.Id, name); Save(); RefreshDeckUi(); } catch (Exception ex) { Warn(ex.Message); } }
    private void DeleteDeck()
    {
        DeckDefinition? d = _decks.Find(_activeDeckId); if (d is null) return; if (d.IsCore) { Announce("The five core spelling decks are permanent and cannot be deleted."); return; }
        int count = _decks.CountEverywhere(d.Id); string? target = count > 0 ? DeckDialogs.ChooseDeck(this, "Delete spelling deck", $"Choose a destination for {count} assigned words:", _decks.Decks.Where(x => x.Id != d.Id), SpellingDeckIds.Core(1)) : SpellingDeckIds.Core(1); if (count > 0 && target is null) return;
        try { _decks.DeleteUserDeck(d.Id, target); _activeDeckId = _state.ActiveDeckId ?? _decks.FirstDeck.Id; Save(); RefreshDeckUi(); Next(); } catch (Exception ex) { Warn(ex.Message); }
    }
    private void ReorderDeck(int direction) { if (_decks.Move(_activeDeckId, direction)) { Save(); RefreshDeckUi(); } else Announce(direction < 0 ? "This spelling deck is already first." : "This spelling deck is already last."); }
    private void UpdateCounts() { _counts.Text = "Spelling counts — " + string.Join("; ", _decks.Decks.Select(d => $"{d.Name}: {_decks.CountInDictionary(_package.Id, d.Id)}{(d.Id == _activeDeckId ? " active" : string.Empty)}")); }
    private void Save() { _state.ActiveDeckId = _activeDeckId; if (_current is not null) _state.CurrentEntryIdByDictionary[_package.Id] = _current.Id; _store.Save(_state); }
    private void Announce(string text) { _status.Text = text; AccessibilityAnnouncer.Announce(_status, text); }
    private void Warn(string text) => MessageBox.Show(this, text, "Spelling", MessageBoxButtons.OK, MessageBoxIcon.Warning);

    protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
    {
        string? action = _shortcuts.FindAction(keyData, ShortcutDispatchContext.Spelling);
        if (action is null) return base.ProcessCmdKey(ref msg, keyData);
        if (action == ActionIds.SpellingShowAnswer) { ShowAnswer(); return true; }
        if (action == ActionIds.SpellingRepeatPrompt) { RepeatPrompt(); return true; }
        if (action == ActionIds.SpellingPlayPronunciation) { PlayPronunciation(); return true; }
        if (action == ActionIds.SpellingToggleCoach) { ToggleCoach(); return true; }
        if (action == ActionIds.SpellingUndoCoachMove) { UndoCoachMove(); return true; }
        if (action == ActionIds.SpellingMoveChooser) { MoveCurrentChooser(); return true; }
        if (action == ActionIds.SpellingCreateDeck) { CreateDeck(); return true; }
        if (action == ActionIds.SpellingRenameDeck) { RenameDeck(); return true; }
        if (action == ActionIds.SpellingDeleteDeck) { DeleteDeck(); return true; }
        if (action == ActionIds.SpellingMoveDeckUp) { ReorderDeck(-1); return true; }
        if (action == ActionIds.SpellingMoveDeckDown) { ReorderDeck(1); return true; }
        foreach (DeckDefinition d in _decks.Decks)
        {
            if (action == ActionIds.SpellingSwitchDeck(d.Id)) { SwitchDeck(d.Id); return true; }
            if (action == ActionIds.SpellingMoveToDeck(d.Id)) { MoveCurrent(d.Id); return true; }
        }
        return base.ProcessCmdKey(ref msg, keyData);
    }
}
