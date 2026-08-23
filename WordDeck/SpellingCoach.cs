using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

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
    string ScopeId,
    string EntryId,
    string FromDeckId,
    string ToDeckId,
    string Reason,
    DateTimeOffset TimestampUtc);

internal sealed class SpellingState
{
    public int SchemaVersion { get; set; }
    public string? ActiveDeckId { get; set; }
    public List<DeckDefinition> Decks { get; set; } = new();

    // Legacy pre-scope maps are retained for migration. The All scope is kept
    // mirrored to this map so older builds can still recover the user's work.
    public Dictionary<string, Dictionary<string, string>> DeckIdsByDictionary { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public Dictionary<string, string> CurrentEntryIdByDictionary { get; set; } = new(StringComparer.OrdinalIgnoreCase);

    // v1 Spelling workspaces. Deck assignments are independent between All and
    // A1/A2/B1/B2/C1, just as Recall workspaces are independent.
    public Dictionary<string, Dictionary<string, Dictionary<string, string>>> DeckIdsByDictionaryScope { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public Dictionary<string, string> ActiveScopeIdByDictionary { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public Dictionary<string, Dictionary<string, string>> CurrentEntryIdsByDictionaryScope { get; set; } = new(StringComparer.OrdinalIgnoreCase);

    // Review statistics are keyed by stable dictionary/entry IDs and intentionally
    // shared across scopes so the deterministic coach learns from the same word,
    // not from a display label or list position.
    public Dictionary<string, Dictionary<string, SpellingEntryStats>> StatsByDictionary { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public bool CoachEnabled { get; set; } = true;
    public SpellingCoachMove? LastCoachMove { get; set; }

    [JsonExtensionData]
    public Dictionary<string, JsonElement>? ExtensionData { get; set; }
}

internal sealed class SpellingStateStore
{
    public const int CurrentSchemaVersion = 1;

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        PropertyNameCaseInsensitive = true
    };

    private readonly string _path;
    private readonly string _backupPath;
    private readonly string _backupsDirectory;

    public SpellingStateStore()
        : this(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WordDeck"))
    {
    }

    internal SpellingStateStore(string root)
    {
        if (string.IsNullOrWhiteSpace(root))
            throw new ArgumentException("Spelling state root directory must not be blank.", nameof(root));
        Directory.CreateDirectory(root);
        _path = Path.Combine(root, "spelling-state.json");
        _backupPath = Path.Combine(root, "spelling-state.backup.json");
        _backupsDirectory = Path.Combine(root, "Backups");
        Directory.CreateDirectory(_backupsDirectory);
    }

    public SpellingState Load()
    {
        SpellingState? primary = TryLoad(_path);
        if (primary is not null) return PrepareLoaded(primary, _path);

        SpellingState? backup = TryLoad(_backupPath);
        if (backup is not null) return PrepareLoaded(backup, _backupPath);

        if (File.Exists(_path) || File.Exists(_backupPath))
            throw new InvalidDataException("WordDeck Spelling state is unreadable and no verified backup can be loaded. Existing files were left untouched.");

        return Normalize(new SpellingState());
    }

    private SpellingState PrepareLoaded(SpellingState state, string sourcePath)
    {
        if (state.SchemaVersion > CurrentSchemaVersion)
            throw new InvalidDataException($"This Spelling state uses newer schema {state.SchemaVersion}; this build supports up to {CurrentSchemaVersion}. No Spelling state was changed.");

        bool migrationNeeded = state.SchemaVersion < CurrentSchemaVersion;
        if (migrationNeeded)
        {
            CreateTimestampedFileBackup(sourcePath, "pre-migration");
            Normalize(state);
            Save(state);
        }
        else
        {
            Normalize(state);
        }
        return state;
    }

    public void Save(SpellingState state)
    {
        Normalize(state);
        state.SchemaVersion = CurrentSchemaVersion;
        string temp = _path + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(state, JsonOptions));
        if (TryLoad(_path) is not null)
            File.Copy(_path, _backupPath, true);
        File.Move(temp, _path, true);
    }

    public string CreateTimestampedBackup(string reason)
    {
        string? source = TryLoad(_path) is not null ? _path : TryLoad(_backupPath) is not null ? _backupPath : null;
        if (source is null)
            throw new InvalidDataException("No parseable WordDeck Spelling state exists to back up.");
        return CreateTimestampedFileBackup(source, reason);
    }

    private string CreateTimestampedFileBackup(string sourcePath, string reason)
    {
        Directory.CreateDirectory(_backupsDirectory);
        string safeReason = string.Concat(reason.Select(ch => char.IsLetterOrDigit(ch) || ch is '-' or '_' ? ch : '-'));
        string destination = Path.Combine(_backupsDirectory, $"spelling-state-{DateTime.UtcNow:yyyyMMdd-HHmmssfff}-{safeReason}.json");
        File.Copy(sourcePath, destination, false);
        foreach (FileInfo stale in new DirectoryInfo(_backupsDirectory).GetFiles("spelling-state-*.json")
                     .OrderByDescending(file => file.LastWriteTimeUtc).Skip(20))
        {
            try { stale.Delete(); } catch { }
        }
        return destination;
    }

    private static SpellingState? TryLoad(string path)
    {
        try
        {
            return File.Exists(path) ? JsonSerializer.Deserialize<SpellingState>(File.ReadAllText(path), JsonOptions) : null;
        }
        catch
        {
            return null;
        }
    }

    internal static SpellingState Clone(SpellingState state) =>
        JsonSerializer.Deserialize<SpellingState>(JsonSerializer.Serialize(state, JsonOptions), JsonOptions)
        ?? throw new InvalidDataException("Could not clone WordDeck Spelling state.");

    internal static void Replace(SpellingState destination, SpellingState source)
    {
        destination.SchemaVersion = source.SchemaVersion;
        destination.ActiveDeckId = source.ActiveDeckId;
        destination.Decks = source.Decks;
        destination.DeckIdsByDictionary = source.DeckIdsByDictionary;
        destination.CurrentEntryIdByDictionary = source.CurrentEntryIdByDictionary;
        destination.DeckIdsByDictionaryScope = source.DeckIdsByDictionaryScope;
        destination.ActiveScopeIdByDictionary = source.ActiveScopeIdByDictionary;
        destination.CurrentEntryIdsByDictionaryScope = source.CurrentEntryIdsByDictionaryScope;
        destination.StatsByDictionary = source.StatsByDictionary;
        destination.CoachEnabled = source.CoachEnabled;
        destination.LastCoachMove = source.LastCoachMove;
        destination.ExtensionData = source.ExtensionData;
        Normalize(destination);
    }

    internal static SpellingState Normalize(SpellingState state)
    {
        if (state.SchemaVersion > CurrentSchemaVersion)
            throw new InvalidDataException($"Spelling state schema {state.SchemaVersion} is newer than supported schema {CurrentSchemaVersion}.");

        state.Decks ??= new();
        state.DeckIdsByDictionary ??= new(StringComparer.OrdinalIgnoreCase);
        state.CurrentEntryIdByDictionary ??= new(StringComparer.OrdinalIgnoreCase);
        state.DeckIdsByDictionaryScope ??= new(StringComparer.OrdinalIgnoreCase);
        state.ActiveScopeIdByDictionary ??= new(StringComparer.OrdinalIgnoreCase);
        state.CurrentEntryIdsByDictionaryScope ??= new(StringComparer.OrdinalIgnoreCase);
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
                if (string.IsNullOrWhiteSpace(deck.Name)) deck.Name = $"Spelling deck {number}";
            }
        }

        List<DeckDefinition> ordered = state.Decks
            .OrderBy(d => d.Order)
            .ThenBy(d => d.IsCore ? 0 : 1)
            .ThenBy(d => d.Name, StringComparer.CurrentCultureIgnoreCase)
            .ToList();
        for (int i = 0; i < ordered.Count; i++) ordered[i].Order = i;
        state.Decks = ordered;

        var validDeckIds = new HashSet<string>(state.Decks.Select(d => d.Id), StringComparer.OrdinalIgnoreCase);
        string fallback = SpellingDeckIds.Core(1);

        state.DeckIdsByDictionary = state.DeckIdsByDictionary
            .Where(pair => !string.IsNullOrWhiteSpace(pair.Key))
            .ToDictionary(
                pair => pair.Key,
                pair => new Dictionary<string, string>(pair.Value ?? new Dictionary<string, string>(), StringComparer.OrdinalIgnoreCase),
                StringComparer.OrdinalIgnoreCase);

        state.DeckIdsByDictionaryScope = state.DeckIdsByDictionaryScope
            .Where(pair => !string.IsNullOrWhiteSpace(pair.Key))
            .ToDictionary(
                pair => pair.Key,
                pair => (pair.Value ?? new Dictionary<string, Dictionary<string, string>>())
                    .Where(scope => StudyScopeIds.Ordered.Contains(scope.Key, StringComparer.OrdinalIgnoreCase))
                    .ToDictionary(
                        scope => StudyScopeIds.Ordered.First(id => string.Equals(id, scope.Key, StringComparison.OrdinalIgnoreCase)),
                        scope => new Dictionary<string, string>(scope.Value ?? new Dictionary<string, string>(), StringComparer.OrdinalIgnoreCase),
                        StringComparer.OrdinalIgnoreCase),
                StringComparer.OrdinalIgnoreCase);

        foreach (string dictionaryId in state.DeckIdsByDictionary.Keys.Concat(state.DeckIdsByDictionaryScope.Keys).Distinct(StringComparer.OrdinalIgnoreCase).ToList())
        {
            if (!state.DeckIdsByDictionaryScope.TryGetValue(dictionaryId, out Dictionary<string, Dictionary<string, string>>? scopes))
            {
                scopes = new(StringComparer.OrdinalIgnoreCase);
                state.DeckIdsByDictionaryScope[dictionaryId] = scopes;
            }
            if (!scopes.TryGetValue(StudyScopeIds.All, out Dictionary<string, string>? all))
            {
                all = state.DeckIdsByDictionary.TryGetValue(dictionaryId, out Dictionary<string, string>? legacy)
                    ? new Dictionary<string, string>(legacy, StringComparer.OrdinalIgnoreCase)
                    : new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                scopes[StudyScopeIds.All] = all;
            }
            state.DeckIdsByDictionary[dictionaryId] = all;
        }

        foreach (Dictionary<string, Dictionary<string, string>> scopes in state.DeckIdsByDictionaryScope.Values)
        {
            foreach (Dictionary<string, string> map in scopes.Values)
            {
                foreach (string entryId in map.Keys.ToList())
                {
                    if (string.IsNullOrWhiteSpace(entryId)) { map.Remove(entryId); continue; }
                    if (string.IsNullOrWhiteSpace(map[entryId]) || !validDeckIds.Contains(map[entryId]))
                        map[entryId] = fallback;
                }
            }
        }

        if (string.IsNullOrWhiteSpace(state.ActiveDeckId) || !validDeckIds.Contains(state.ActiveDeckId))
            state.ActiveDeckId = fallback;

        state.ActiveScopeIdByDictionary = state.ActiveScopeIdByDictionary
            .Where(pair => !string.IsNullOrWhiteSpace(pair.Key))
            .ToDictionary(
                pair => pair.Key,
                pair => StudyScopeIds.Ordered.Contains(pair.Value, StringComparer.OrdinalIgnoreCase)
                    ? StudyScopeIds.Ordered.First(id => string.Equals(id, pair.Value, StringComparison.OrdinalIgnoreCase))
                    : StudyScopeIds.All,
                StringComparer.OrdinalIgnoreCase);

        state.CurrentEntryIdByDictionary = new Dictionary<string, string>(state.CurrentEntryIdByDictionary, StringComparer.OrdinalIgnoreCase);
        state.CurrentEntryIdsByDictionaryScope = state.CurrentEntryIdsByDictionaryScope
            .Where(pair => !string.IsNullOrWhiteSpace(pair.Key))
            .ToDictionary(
                pair => pair.Key,
                pair => new Dictionary<string, string>(pair.Value ?? new Dictionary<string, string>(), StringComparer.OrdinalIgnoreCase),
                StringComparer.OrdinalIgnoreCase);
        foreach ((string dictionaryId, string entryId) in state.CurrentEntryIdByDictionary.ToList())
        {
            if (!state.CurrentEntryIdsByDictionaryScope.TryGetValue(dictionaryId, out Dictionary<string, string>? scopes))
            {
                scopes = new(StringComparer.OrdinalIgnoreCase);
                state.CurrentEntryIdsByDictionaryScope[dictionaryId] = scopes;
            }
            if (!string.IsNullOrWhiteSpace(entryId)) scopes.TryAdd(StudyScopeIds.All, entryId);
        }

        state.StatsByDictionary = state.StatsByDictionary
            .Where(pair => !string.IsNullOrWhiteSpace(pair.Key))
            .ToDictionary(
                pair => pair.Key,
                pair => new Dictionary<string, SpellingEntryStats>(pair.Value ?? new Dictionary<string, SpellingEntryStats>(), StringComparer.OrdinalIgnoreCase),
                StringComparer.OrdinalIgnoreCase);
        foreach (Dictionary<string, SpellingEntryStats> stats in state.StatsByDictionary.Values)
        {
            foreach (string entryId in stats.Keys.ToList())
            {
                if (string.IsNullOrWhiteSpace(entryId) || stats[entryId] is null) { stats.Remove(entryId); continue; }
                SpellingEntryStats value = stats[entryId];
                value.CompletedReviews = Math.Max(0, value.CompletedReviews);
                value.FirstTrySuccesses = Math.Clamp(value.FirstTrySuccesses, 0, value.CompletedReviews);
                value.WrongAttempts = Math.Max(0, value.WrongAttempts);
                value.HintUses = Math.Max(0, value.HintUses);
                value.ShowAnswerUses = Math.Clamp(value.ShowAnswerUses, 0, value.HintUses);
                value.CurrentStreak = Math.Clamp(value.CurrentStreak, 0, value.CompletedReviews);
                value.RecentOutcomes ??= new();
                if (value.RecentOutcomes.Count > 10) value.RecentOutcomes = value.RecentOutcomes.TakeLast(10).ToList();
            }
        }

        state.SchemaVersion = CurrentSchemaVersion;
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

    public Dictionary<string, string> EnsureAssignments(string dictionaryId, IEnumerable<string> entryIds) =>
        EnsureAssignments(dictionaryId, StudyScopeIds.All, entryIds);

    public Dictionary<string, string> EnsureAssignments(string dictionaryId, string scopeId, IEnumerable<string> entryIds)
    {
        scopeId = StudyScopeIds.Ordered.Contains(scopeId, StringComparer.OrdinalIgnoreCase)
            ? StudyScopeIds.Ordered.First(id => string.Equals(id, scopeId, StringComparison.OrdinalIgnoreCase))
            : StudyScopeIds.All;
        if (!_state.DeckIdsByDictionaryScope.TryGetValue(dictionaryId, out Dictionary<string, Dictionary<string, string>>? scopes))
        {
            scopes = new(StringComparer.OrdinalIgnoreCase);
            _state.DeckIdsByDictionaryScope[dictionaryId] = scopes;
        }
        if (!scopes.TryGetValue(scopeId, out Dictionary<string, string>? map))
        {
            map = new(StringComparer.OrdinalIgnoreCase);
            if (string.Equals(scopeId, StudyScopeIds.All, StringComparison.OrdinalIgnoreCase) &&
                _state.DeckIdsByDictionary.TryGetValue(dictionaryId, out Dictionary<string, string>? legacy))
            {
                foreach ((string entryId, string deckId) in legacy) map[entryId] = deckId;
            }
            scopes[scopeId] = map;
        }

        var validDecks = new HashSet<string>(_state.Decks.Select(d => d.Id), StringComparer.OrdinalIgnoreCase);
        foreach (string id in entryIds.Where(id => !string.IsNullOrWhiteSpace(id)).Distinct(StringComparer.OrdinalIgnoreCase))
            if (!map.TryGetValue(id, out string? deckId) || !validDecks.Contains(deckId)) map[id] = FirstDeck.Id;

        // Unknown stable IDs are deliberately retained rather than discarded.
        // They are inert in the current corpus and can be quarantined/recovered by
        // the personal-profile importer.
        if (string.Equals(scopeId, StudyScopeIds.All, StringComparison.OrdinalIgnoreCase))
            _state.DeckIdsByDictionary[dictionaryId] = map;
        return map;
    }

    public DeckDefinition Create(string name)
    {
        name = NormalizeName(name);
        EnsureUnique(name, null);
        var deck = new DeckDefinition
        {
            Id = $"spelling-user-{Guid.NewGuid():N}",
            Name = name,
            IsCore = false,
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

    public int CountInDictionary(string dictionaryId, string scopeId, string deckId) =>
        _state.DeckIdsByDictionaryScope.TryGetValue(dictionaryId, out Dictionary<string, Dictionary<string, string>>? scopes) &&
        scopes.TryGetValue(scopeId, out Dictionary<string, string>? map)
            ? map.Values.Count(id => string.Equals(id, deckId, StringComparison.OrdinalIgnoreCase))
            : 0;

    public int CountEverywhere(string deckId) => _state.DeckIdsByDictionaryScope.Values
        .SelectMany(scopes => scopes.Values)
        .Sum(map => map.Values.Count(id => string.Equals(id, deckId, StringComparison.OrdinalIgnoreCase)));

    public void DeleteUserDeck(string id, string? destinationId)
    {
        DeckDefinition deck = Find(id) ?? throw new InvalidOperationException("Spelling deck no longer exists.");
        if (deck.IsCore) throw new InvalidOperationException("The five core spelling decks are permanent.");
        int assigned = CountEverywhere(id);
        if (assigned > 0)
        {
            if (string.IsNullOrWhiteSpace(destinationId) || string.Equals(destinationId, id, StringComparison.OrdinalIgnoreCase) || Find(destinationId) is null)
                throw new InvalidOperationException("Choose a valid destination before deleting a non-empty spelling deck.");
            foreach (Dictionary<string, Dictionary<string, string>> scopes in _state.DeckIdsByDictionaryScope.Values)
                foreach (Dictionary<string, string> map in scopes.Values)
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

internal static class SpellingAnswerComparer
{
    public static bool IsCorrect(string typed, string expected) =>
        string.Equals(NormalizeTechnical(typed), NormalizeTechnical(expected), StringComparison.Ordinal);

    internal static string NormalizeTechnical(string value)
    {
        string text = (value ?? string.Empty).Trim().Normalize(NormalizationForm.FormC);
        var builder = new StringBuilder(text.Length);
        foreach (char ch in text)
        {
            builder.Append(ch switch
            {
                '\u00A0' => ' ',
                '\u2018' or '\u2019' or '\u02BC' or '\uFF07' => '\'',
                '\u2010' or '\u2011' or '\u2212' or '\uFF0D' => '-',
                _ => ch
            });
        }
        return builder.ToString().Normalize(NormalizationForm.FormC);
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
        if (current == 0)
            return new(null, "Coach hold: user-created spelling decks are never redistributed automatically.");

        if (!firstTryCorrect || usedHint)
        {
            if (current > 1)
                return new(SpellingDeckIds.Core(current - 1), "Coach moved this word one core deck earlier because this review needed a retry or hint.");
            return new(null, "Coach hold: this review needed a retry or hint, and the word is already in the earliest core deck.");
        }

        if (stats.CompletedReviews < 3)
            return new(null, $"Coach hold: {stats.CompletedReviews} completed clean/assisted reviews are not enough for the three-review promotion gate.");

        double lifetimeCleanRate = stats.CompletedReviews == 0 ? 0 : (double)stats.FirstTrySuccesses / stats.CompletedReviews;
        int recentCount = stats.RecentOutcomes.Count;
        double recentCleanRate = recentCount == 0 ? 0 : (double)stats.RecentOutcomes.Count(value => value) / recentCount;
        int lifetimePercent = (int)Math.Round(lifetimeCleanRate * 100, MidpointRounding.AwayFromZero);
        int recentPercent = (int)Math.Round(recentCleanRate * 100, MidpointRounding.AwayFromZero);

        bool statisticallyReady = stats.CurrentStreak >= 3 && lifetimeCleanRate >= 0.75 && recentCleanRate >= 0.80;
        if (statisticallyReady && current < 5)
            return new(SpellingDeckIds.Core(current + 1), $"Coach moved this word one core deck later: clean streak {stats.CurrentStreak}, lifetime clean rate {lifetimePercent}%, recent clean rate {recentPercent}%.");
        if (statisticallyReady)
            return new(null, $"Coach hold: promotion thresholds are met, but this word is already in the latest core deck. Clean streak {stats.CurrentStreak}, lifetime {lifetimePercent}%, recent {recentPercent}%.");

        return new(null, $"Coach hold: promotion needs streak 3+, lifetime clean rate 75%+, and recent clean rate 80%+. Current values: streak {stats.CurrentStreak}, lifetime {lifetimePercent}%, recent {recentPercent}%.");
    }
}

internal sealed class SpellingForm : Form
{
    private sealed record ScopeOption(string Id, string Name)
    {
        public override string ToString() => Name;
    }

    private readonly AppState _appState;
    private readonly SpellingState _state;
    private readonly SpellingStateStore _store;
    private readonly SpellingDeckService _decks;
    private readonly ShortcutManager _shortcuts;
    private readonly DictionaryPackage _package;
    private readonly Dictionary<string, DictionaryEntry> _entries;
    private Dictionary<string, string> _deckMap;
    private readonly PronunciationAudio _audio = new();
    private readonly ISpellingScheduler _scheduler = new ConservativeSpellingScheduler();
    private readonly Random _random = new();
    private readonly Queue<string> _shuffleBag = new();
    private readonly ComboBox _scopeCombo = new() { DropDownStyle = ComboBoxStyle.DropDownList, AccessibleName = "Spelling study scope", Width = 220 };
    private readonly ComboBox _deckCombo = new() { DropDownStyle = ComboBoxStyle.DropDownList, DisplayMember = nameof(DeckDefinition.Name), AccessibleName = "Active spelling deck", Width = 260 };
    private readonly Label _counts = new() { AutoSize = true, AccessibleName = "Spelling scope and deck counts" };
    private readonly TextBox _prompt = new() { ReadOnly = true, Multiline = true, Dock = DockStyle.Fill, AccessibleName = "Ukrainian spelling prompt", Font = new Font(SystemFonts.DefaultFont.FontFamily, 18), TabStop = true };
    private readonly TextBox _answer = new() { Multiline = false, Dock = DockStyle.Fill, AccessibleName = "Type English spelling answer" };
    private readonly Label _status = new() { AutoSize = true, AccessibleName = "Spelling status" };
    private string _activeScopeId;
    private string _activeDeckId;
    private DictionaryEntry? _current;
    private bool _hadWrong;
    private bool _usedHint;
    private bool _changingScopeUi;

    public SpellingForm(AppState appState, SpellingState state, SpellingStateStore store, ShortcutManager shortcuts, DictionaryPackage package)
    {
        _appState = appState;
        _state = SpellingStateStore.Normalize(state);
        _store = store;
        _decks = new SpellingDeckService(state);
        _shortcuts = shortcuts;
        _package = package;
        _entries = package.Entries.ToDictionary(e => e.Id, StringComparer.OrdinalIgnoreCase);
        _activeScopeId = state.ActiveScopeIdByDictionary.TryGetValue(package.Id, out string? persistedScope) && StudyScopeIds.Ordered.Contains(persistedScope, StringComparer.OrdinalIgnoreCase)
            ? StudyScopeIds.Ordered.First(id => string.Equals(id, persistedScope, StringComparison.OrdinalIgnoreCase))
            : StudyScopeIds.All;
        _deckMap = _decks.EnsureAssignments(package.Id, _activeScopeId, EligibleEntries().Select(e => e.Id));
        _activeDeckId = _decks.Find(state.ActiveDeckId ?? string.Empty)?.Id ?? _decks.FirstDeck.Id;
        _state.ActiveDeckId = _activeDeckId;
        _state.ActiveScopeIdByDictionary[_package.Id] = _activeScopeId;

        Text = "WordDeck Spelling";
        Width = 900;
        Height = 550;
        MinimumSize = new Size(680, 440);
        StartPosition = FormStartPosition.CenterParent;
        KeyPreview = true;
        AccessibleName = "WordDeck Spelling trainer";
        AccessibleDescription = "Keyboard-first English spelling practice from Ukrainian prompts with independent study scopes and deterministic adaptive coaching.";
        MainMenuStrip = BuildMenu();
        Controls.Add(MainMenuStrip);

        var root = new TableLayoutPanel { Dock = DockStyle.Fill, RowCount = 7, ColumnCount = 1, Padding = new Padding(16) };
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 45));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));

        var top = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoSize = true, WrapContents = true };
        top.Controls.Add(new Label { Text = "Study scope:", AutoSize = true, Padding = new Padding(0, 6, 4, 0) });
        top.Controls.Add(_scopeCombo);
        top.Controls.Add(new Label { Text = "Spelling deck:", AutoSize = true, Padding = new Padding(12, 6, 4, 0) });
        top.Controls.Add(_deckCombo);
        root.Controls.Add(top, 0, 0);
        root.Controls.Add(_counts, 0, 1);
        root.Controls.Add(new Label { Text = "Ukrainian prompt", AutoSize = true, Font = new Font(Font, FontStyle.Bold) }, 0, 2);
        root.Controls.Add(_prompt, 0, 3);
        root.Controls.Add(new Label { Text = "Type exact English spelling and press Enter", AutoSize = true, Font = new Font(Font, FontStyle.Bold) }, 0, 4);
        root.Controls.Add(_answer, 0, 5);
        root.Controls.Add(_status, 0, 6);
        Controls.Add(root);
        root.BringToFront();

        _scopeCombo.SelectedIndexChanged += (_, _) =>
        {
            if (!_changingScopeUi && _scopeCombo.SelectedItem is ScopeOption option &&
                !string.Equals(option.Id, _activeScopeId, StringComparison.OrdinalIgnoreCase))
                SwitchScope(option.Id);
        };
        _deckCombo.SelectedIndexChanged += (_, _) =>
        {
            if (_deckCombo.SelectedItem is DeckDefinition d && !string.Equals(d.Id, _activeDeckId, StringComparison.OrdinalIgnoreCase))
                SwitchDeck(d.Id);
        };
        _answer.KeyDown += (_, e) =>
        {
            if (e.KeyCode == Keys.Enter)
            {
                e.SuppressKeyPress = true;
                Submit();
            }
        };
        RefreshScopeUi();
        RefreshDeckUi();
        Shown += (_, _) => BeginInvoke(new Action(RestoreOrNext));
        FormClosing += (_, _) => { _audio.Dispose(); Save(); };
    }

    private MenuStrip BuildMenu()
    {
        var menu = new MenuStrip { AccessibleName = "Spelling menu" };
        var training = new ToolStripMenuItem("&Training");
        Add(training, "&Show spelling answer", ShowAnswer);
        Add(training, "&Repeat Ukrainian prompt", RepeatPrompt);
        Add(training, "Play &British pronunciation hint", PlayPronunciation);
        Add(training, "&Toggle adaptive coach", ToggleCoach);
        Add(training, "&Undo last coach move", UndoCoachMove);
        var decks = new ToolStripMenuItem("&Spelling decks");
        Add(decks, "&Move current word to spelling deck...", MoveCurrentChooser);
        Add(decks, "&Create spelling deck...", CreateDeck);
        Add(decks, "&Rename active spelling deck...", RenameDeck);
        Add(decks, "&Delete active user spelling deck...", DeleteDeck);
        Add(decks, "Move spelling deck &up", () => ReorderDeck(-1));
        Add(decks, "Move spelling deck &down", () => ReorderDeck(1));
        menu.Items.Add(training);
        menu.Items.Add(decks);
        return menu;
    }

    private static void Add(ToolStripMenuItem parent, string text, Action action)
    {
        var item = new ToolStripMenuItem(text);
        item.Click += (_, _) => action();
        parent.DropDownItems.Add(item);
    }

    private void RefreshScopeUi()
    {
        _changingScopeUi = true;
        try
        {
            _scopeCombo.Items.Clear();
            foreach (string id in StudyScopeIds.Ordered)
                _scopeCombo.Items.Add(new ScopeOption(id, StudyScopeIds.DisplayName(id)));
            for (int i = 0; i < _scopeCombo.Items.Count; i++)
            {
                if (_scopeCombo.Items[i] is ScopeOption option && string.Equals(option.Id, _activeScopeId, StringComparison.OrdinalIgnoreCase))
                {
                    _scopeCombo.SelectedIndex = i;
                    break;
                }
            }
        }
        finally
        {
            _changingScopeUi = false;
        }
    }

    private void RefreshDeckUi()
    {
        _deckCombo.BeginUpdate();
        _deckCombo.Items.Clear();
        foreach (DeckDefinition d in _decks.Decks) _deckCombo.Items.Add(d);
        for (int i = 0; i < _deckCombo.Items.Count; i++)
            if (_deckCombo.Items[i] is DeckDefinition d && string.Equals(d.Id, _activeDeckId, StringComparison.OrdinalIgnoreCase))
                _deckCombo.SelectedIndex = i;
        _deckCombo.EndUpdate();
        UpdateCounts();
        _shortcuts.RefreshDeckDefinitions(_decks.Decks);
    }

    private IReadOnlyList<DictionaryEntry> EligibleEntries() => _package.Entries
        .Where(e => StudyScopeIds.Includes(_activeScopeId, e))
        .Where(e => !UserProgressService.IsHidden(_appState, e.Id))
        .ToList();

    private IReadOnlyList<DictionaryEntry> ActiveEntries() => EligibleEntries()
        .Where(e => string.Equals(_deckMap.GetValueOrDefault(e.Id, _decks.FirstDeck.Id), _activeDeckId, StringComparison.OrdinalIgnoreCase))
        .ToList();

    private Dictionary<string, string> CurrentEntryScopes()
    {
        if (!_state.CurrentEntryIdsByDictionaryScope.TryGetValue(_package.Id, out Dictionary<string, string>? scopes))
        {
            scopes = new(StringComparer.OrdinalIgnoreCase);
            _state.CurrentEntryIdsByDictionaryScope[_package.Id] = scopes;
        }
        return scopes;
    }

    private void RestoreOrNext()
    {
        Dictionary<string, string> currents = CurrentEntryScopes();
        if (currents.TryGetValue(_activeScopeId, out string? id) && _entries.TryGetValue(id, out DictionaryEntry? entry) &&
            StudyScopeIds.Includes(_activeScopeId, entry) && !UserProgressService.IsHidden(_appState, id) &&
            string.Equals(_deckMap.GetValueOrDefault(id, _decks.FirstDeck.Id), _activeDeckId, StringComparison.OrdinalIgnoreCase))
        {
            Show(entry);
            FillShuffleBag(ActiveEntries());
            RemoveFromShuffleBag(id);
        }
        else
        {
            Next();
        }
    }

    private void Next()
    {
        IReadOnlyList<DictionaryEntry> entries = ActiveEntries();
        if (entries.Count == 0)
        {
            _shuffleBag.Clear();
            _current = null;
            CurrentEntryScopes().Remove(_activeScopeId);
            if (string.Equals(_activeScopeId, StudyScopeIds.All, StringComparison.OrdinalIgnoreCase))
                _state.CurrentEntryIdByDictionary.Remove(_package.Id);
            _prompt.Text = "No words in this spelling deck and scope";
            _answer.Clear();
            Save();
            Announce($"{StudyScopeIds.DisplayName(_activeScopeId)}: this spelling deck is empty.");
            return;
        }

        var activeById = entries.ToDictionary(entry => entry.Id, StringComparer.OrdinalIgnoreCase);
        if (_shuffleBag.Count == 0)
            FillShuffleBag(entries);

        while (_shuffleBag.Count > 0)
        {
            string id = _shuffleBag.Dequeue();
            if (activeById.TryGetValue(id, out DictionaryEntry? next))
            {
                Show(next);
                return;
            }
        }

        // The deck may have changed while the current card was being reviewed.
        // Rebuild once from the exact current active set rather than falling back
        // to random-with-replacement selection.
        FillShuffleBag(entries);
        if (_shuffleBag.Count > 0)
            Show(activeById[_shuffleBag.Dequeue()]);
    }

    private void FillShuffleBag(IReadOnlyList<DictionaryEntry> entries)
    {
        _shuffleBag.Clear();
        foreach (string id in ShuffleBag.Create(entries.Select(entry => entry.Id), _random, _current?.Id))
            _shuffleBag.Enqueue(id);
    }

    private void RemoveFromShuffleBag(string entryId)
    {
        if (_shuffleBag.Count == 0) return;
        string[] remaining = _shuffleBag
            .Where(id => !string.Equals(id, entryId, StringComparison.OrdinalIgnoreCase))
            .ToArray();
        _shuffleBag.Clear();
        foreach (string id in remaining) _shuffleBag.Enqueue(id);
    }

    private void Show(DictionaryEntry entry)
    {
        _current = entry;
        _hadWrong = false;
        _usedHint = false;
        _prompt.Text = entry.Target;
        _answer.Clear();
        _answer.Focus();
        CurrentEntryScopes()[_activeScopeId] = entry.Id;
        if (string.Equals(_activeScopeId, StudyScopeIds.All, StringComparison.OrdinalIgnoreCase))
            _state.CurrentEntryIdByDictionary[_package.Id] = entry.Id;
        Save();
        AccessibilityAnnouncer.Announce(_prompt, entry.Target);
    }

    private void Submit()
    {
        if (_current is null) return;
        SpellingEntryStats stats = GetStats(_current.Id);
        if (!SpellingAnswerComparer.IsCorrect(_answer.Text, _current.Source))
        {
            _hadWrong = true;
            stats.WrongAttempts++;
            stats.CurrentStreak = 0;
            Save();
            _answer.SelectAll();
            Announce("Incorrect spelling. This card did not advance and no completed-review outcome was recorded. Try again.");
            return;
        }

        bool cleanFirstTry = !_hadWrong && !_usedHint;
        stats.CompletedReviews++;
        if (cleanFirstTry) stats.FirstTrySuccesses++;
        stats.CurrentStreak = cleanFirstTry ? stats.CurrentStreak + 1 : 0;
        stats.LastReviewedUtc = DateTimeOffset.UtcNow;
        AddRecent(stats, cleanFirstTry);
        string coachMessage = ApplyCoach(stats, cleanFirstTry);
        Save();
        Announce($"Correct. {coachMessage}");
        Next();
    }

    private SpellingEntryStats GetStats(string entryId)
    {
        if (!_state.StatsByDictionary.TryGetValue(_package.Id, out Dictionary<string, SpellingEntryStats>? map))
        {
            map = new(StringComparer.OrdinalIgnoreCase);
            _state.StatsByDictionary[_package.Id] = map;
        }
        if (!map.TryGetValue(entryId, out SpellingEntryStats? stats))
        {
            stats = new();
            map[entryId] = stats;
        }
        return stats;
    }

    private static void AddRecent(SpellingEntryStats stats, bool result)
    {
        stats.RecentOutcomes.Add(result);
        if (stats.RecentOutcomes.Count > 10) stats.RecentOutcomes.RemoveAt(0);
    }

    private void ShowAnswer()
    {
        if (_current is null) return;
        _usedHint = true;
        SpellingEntryStats stats = GetStats(_current.Id);
        stats.HintUses++;
        stats.ShowAnswerUses++;
        Save();
        Announce($"Correct spelling: {_current.Source}. Showing the answer never passes the card; type it correctly and press Enter.");
        _answer.Focus();
    }

    private void RepeatPrompt()
    {
        if (_current is null) return;
        _prompt.Focus();
        _prompt.SelectAll();
        AccessibilityAnnouncer.Announce(_prompt, _current.Target);
        _answer.Focus();
    }

    private void PlayPronunciation()
    {
        if (_current is null) return;
        _usedHint = true;
        GetStats(_current.Id).HintUses++;
        Save();
        if (!_audio.TryPlay(_package, _current, out string? error) && error is not null) Announce(error);
    }

    private void ToggleCoach()
    {
        _state.CoachEnabled = !_state.CoachEnabled;
        Save();
        Announce(_state.CoachEnabled ? "Adaptive spelling coach enabled." : "Adaptive spelling coach disabled.");
    }

    private string ApplyCoach(SpellingEntryStats stats, bool cleanFirstTry)
    {
        if (!_state.CoachEnabled || _current is null) return "Adaptive coach is disabled.";
        string from = _deckMap.GetValueOrDefault(_current.Id, _decks.FirstDeck.Id);
        SpellingScheduleDecision decision = _scheduler.Decide(from, stats, cleanFirstTry, _usedHint);
        if (decision.TargetDeckId is null || string.Equals(decision.TargetDeckId, from, StringComparison.OrdinalIgnoreCase))
            return decision.Explanation;

        _deckMap[_current.Id] = decision.TargetDeckId;
        _state.LastCoachMove = new(_package.Id, _activeScopeId, _current.Id, from, decision.TargetDeckId, decision.Explanation, DateTimeOffset.UtcNow);
        UpdateCounts();
        return decision.Explanation;
    }

    private void UndoCoachMove()
    {
        SpellingCoachMove? move = _state.LastCoachMove;
        if (move is null || !string.Equals(move.DictionaryId, _package.Id, StringComparison.OrdinalIgnoreCase))
        {
            Announce("No adaptive spelling move is available to undo.");
            return;
        }
        if (!StudyScopeIds.Ordered.Contains(move.ScopeId, StringComparer.OrdinalIgnoreCase))
        {
            _state.LastCoachMove = null;
            Save();
            Announce("The last adaptive move used an unknown scope and cannot be undone safely.");
            return;
        }
        Dictionary<string, string> map = _decks.EnsureAssignments(_package.Id, move.ScopeId,
            _package.Entries.Where(e => StudyScopeIds.Includes(move.ScopeId, e)).Select(e => e.Id));
        if (!string.Equals(map.GetValueOrDefault(move.EntryId), move.ToDeckId, StringComparison.OrdinalIgnoreCase) || _decks.Find(move.FromDeckId) is null)
        {
            _state.LastCoachMove = null;
            Save();
            Announce("The last adaptive move can no longer be undone because the word or deck assignment changed.");
            return;
        }
        map[move.EntryId] = move.FromDeckId;
        _state.LastCoachMove = null;
        Save();
        UpdateCounts();
        Announce($"Undid the last adaptive spelling deck move in {StudyScopeIds.DisplayName(move.ScopeId)}.");
    }

    private void MoveCurrentChooser()
    {
        if (_current is null) return;
        string? target = DeckDialogs.ChooseDeck(this, "Move spelling word", $"Move {_current.Source} to which spelling deck in {StudyScopeIds.DisplayName(_activeScopeId)}?", _decks.Decks, _activeDeckId);
        if (target is not null) MoveCurrent(target);
    }

    private void MoveCurrent(string target)
    {
        if (_current is null || _decks.Find(target) is null) return;
        _deckMap[_current.Id] = target;
        _state.LastCoachMove = null;
        Save();
        UpdateCounts();
        Announce($"Moved {_current.Source} to {_decks.Find(target)!.Name} in {StudyScopeIds.DisplayName(_activeScopeId)}.");
        Next();
    }

    private void SwitchScope(string scopeId)
    {
        if (!StudyScopeIds.Ordered.Contains(scopeId, StringComparer.OrdinalIgnoreCase)) return;
        _activeScopeId = StudyScopeIds.Ordered.First(id => string.Equals(id, scopeId, StringComparison.OrdinalIgnoreCase));
        _state.ActiveScopeIdByDictionary[_package.Id] = _activeScopeId;
        _deckMap = _decks.EnsureAssignments(_package.Id, _activeScopeId, EligibleEntries().Select(e => e.Id));
        _shuffleBag.Clear();
        _current = null;
        Save();
        RefreshScopeUi();
        RefreshDeckUi();
        Announce($"Spelling study scope: {StudyScopeIds.DisplayName(_activeScopeId)}. {EligibleEntries().Count} available words.");
        RestoreOrNext();
    }

    private void SwitchDeck(string id)
    {
        if (_decks.Find(id) is null) return;
        _activeDeckId = id;
        _state.ActiveDeckId = id;
        _shuffleBag.Clear();
        _current = null;
        Save();
        RefreshDeckUi();
        Announce($"{StudyScopeIds.DisplayName(_activeScopeId)}: switched to {_decks.Find(id)!.Name}.");
        RestoreOrNext();
    }

    private void CreateDeck()
    {
        string? name = DeckDialogs.PromptForName(this, "Create spelling deck", "Enter a name for the new empty spelling deck:");
        if (name is null) return;
        try
        {
            DeckDefinition deck = _decks.Create(name);
            _activeDeckId = deck.Id;
            _state.ActiveDeckId = deck.Id;
            _shuffleBag.Clear();
            Save();
            RefreshDeckUi();
            Next();
            Announce($"Created spelling deck {deck.Name}. It is active in {StudyScopeIds.DisplayName(_activeScopeId)}.");
        }
        catch (Exception ex) { Warn(ex.Message); }
    }

    private void RenameDeck()
    {
        DeckDefinition? deck = _decks.Find(_activeDeckId);
        if (deck is null) return;
        string? name = DeckDialogs.PromptForName(this, "Rename spelling deck", "Enter the new spelling deck name:", deck.Name);
        if (name is null) return;
        try
        {
            _decks.Rename(deck.Id, name);
            Save();
            RefreshDeckUi();
            Announce($"Spelling deck renamed to {deck.Name}. Stable assignments were preserved in every scope.");
        }
        catch (Exception ex) { Warn(ex.Message); }
    }

    private void DeleteDeck()
    {
        DeckDefinition? deck = _decks.Find(_activeDeckId);
        if (deck is null) return;
        if (deck.IsCore)
        {
            Announce("The five core spelling decks are permanent and cannot be deleted.");
            return;
        }
        int count = _decks.CountEverywhere(deck.Id);
        string? target = count > 0
            ? DeckDialogs.ChooseDeck(this, "Delete spelling deck", $"Choose a destination for {count} saved spelling assignments across all scopes:", _decks.Decks.Where(x => x.Id != deck.Id), SpellingDeckIds.Core(1))
            : SpellingDeckIds.Core(1);
        if (count > 0 && target is null) return;
        try
        {
            string name = deck.Name;
            _decks.DeleteUserDeck(deck.Id, target);
            _activeDeckId = _state.ActiveDeckId ?? _decks.FirstDeck.Id;
            _state.LastCoachMove = null;
            _deckMap = _decks.EnsureAssignments(_package.Id, _activeScopeId, EligibleEntries().Select(e => e.Id));
            _shuffleBag.Clear();
            Save();
            RefreshDeckUi();
            Next();
            Announce(count > 0 ? $"Deleted {name}; saved assignments were transferred safely across spelling scopes." : $"Deleted empty spelling deck {name}.");
        }
        catch (Exception ex) { Warn(ex.Message); }
    }

    private void ReorderDeck(int direction)
    {
        if (_decks.Move(_activeDeckId, direction))
        {
            Save();
            RefreshDeckUi();
            Announce(direction < 0 ? "Moved spelling deck up." : "Moved spelling deck down.");
        }
        else
        {
            Announce(direction < 0 ? "This spelling deck is already first." : "This spelling deck is already last.");
        }
    }

    private void UpdateCounts()
    {
        IReadOnlyList<DictionaryEntry> eligible = EligibleEntries();
        string summary = string.Join("; ", _decks.Decks.Select(deck =>
        {
            int count = eligible.Count(entry => string.Equals(_deckMap.GetValueOrDefault(entry.Id, _decks.FirstDeck.Id), deck.Id, StringComparison.OrdinalIgnoreCase));
            string active = string.Equals(deck.Id, _activeDeckId, StringComparison.OrdinalIgnoreCase) ? " active" : string.Empty;
            return $"{deck.Name}: {count}{active}";
        }));
        _counts.Text = $"Scope {StudyScopeIds.DisplayName(_activeScopeId)} — {summary}. Available words in scope: {eligible.Count}.";
    }

    private void Save()
    {
        _state.ActiveDeckId = _activeDeckId;
        _state.ActiveScopeIdByDictionary[_package.Id] = _activeScopeId;
        if (_current is not null)
        {
            CurrentEntryScopes()[_activeScopeId] = _current.Id;
            if (string.Equals(_activeScopeId, StudyScopeIds.All, StringComparison.OrdinalIgnoreCase))
                _state.CurrentEntryIdByDictionary[_package.Id] = _current.Id;
        }
        _store.Save(_state);
    }

    private void Announce(string text)
    {
        _status.Text = text;
        AccessibilityAnnouncer.Announce(_status, text);
    }

    private void Warn(string text) => MessageBox.Show(this, text, "Spelling", MessageBoxButtons.OK, MessageBoxIcon.Warning);

    protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
    {
        string? action = _shortcuts.FindAction(keyData);
        if (action is null) return base.ProcessCmdKey(ref msg, keyData);
        if (action == ActionIds.SpellingShowAnswer) ShowAnswer();
        else if (action == ActionIds.SpellingRepeatPrompt) RepeatPrompt();
        else if (action == ActionIds.SpellingPlayPronunciation) PlayPronunciation();
        else if (action == ActionIds.SpellingToggleCoach) ToggleCoach();
        else if (action == ActionIds.SpellingUndoCoachMove) UndoCoachMove();
        else if (action == ActionIds.SpellingMoveChooser) MoveCurrentChooser();
        else if (action == ActionIds.SpellingCreateDeck) CreateDeck();
        else if (action == ActionIds.SpellingRenameDeck) RenameDeck();
        else if (action == ActionIds.SpellingDeleteDeck) DeleteDeck();
        else if (action == ActionIds.SpellingMoveDeckUp) ReorderDeck(-1);
        else if (action == ActionIds.SpellingMoveDeckDown) ReorderDeck(1);
        else
        {
            foreach (DeckDefinition deck in _decks.Decks)
            {
                if (action == ActionIds.SpellingSwitchDeck(deck.Id)) { SwitchDeck(deck.Id); break; }
                if (action == ActionIds.SpellingMoveToDeck(deck.Id)) { MoveCurrent(deck.Id); break; }
            }
        }
        return true;
    }
}
