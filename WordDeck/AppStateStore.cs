using System.Text.Json;

namespace WordDeck;

internal sealed class AppStateStore
{
    private readonly string _root;
    private readonly string _statePath;
    private readonly string _backupPath;
    public string DictionaryDirectory { get; }

    public AppStateStore()
        : this(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WordDeck"))
    {
    }

    internal AppStateStore(string root)
    {
        if (string.IsNullOrWhiteSpace(root))
            throw new ArgumentException("State root directory must not be blank.", nameof(root));

        _root = root;
        DictionaryDirectory = Path.Combine(_root, "Dictionaries");
        _statePath = Path.Combine(_root, "state.json");
        _backupPath = Path.Combine(_root, "state.backup.json");
        Directory.CreateDirectory(_root);
        Directory.CreateDirectory(DictionaryDirectory);
    }

    public AppState Load()
    {
        AppState? primary = TryLoad(_statePath);
        if (primary is not null)
            return Normalize(primary);

        AppState? backup = TryLoad(_backupPath);
        if (backup is not null)
            return Normalize(backup);

        return Normalize(new AppState());
    }

    public void Save(AppState state)
    {
        Normalize(state);
        string temp = _statePath + ".tmp";
        string json = JsonSerializer.Serialize(state, new JsonSerializerOptions { WriteIndented = true });
        File.WriteAllText(temp, json);

        // Keep the last parseable state as a recovery point. Never overwrite a good backup
        // with a corrupted primary file.
        if (TryLoad(_statePath) is not null)
            File.Copy(_statePath, _backupPath, true);

        File.Move(temp, _statePath, true);
    }

    public string ImportDictionary(string sourcePath)
    {
        string fileName = Path.GetFileName(sourcePath);
        string destination = Path.Combine(DictionaryDirectory, fileName);
        File.Copy(sourcePath, destination, true);
        return destination;
    }

    public IEnumerable<string> EnumerateDictionaryFiles() =>
        Directory.EnumerateFiles(DictionaryDirectory, "*.tsv", SearchOption.TopDirectoryOnly);

    private static AppState? TryLoad(string path)
    {
        try
        {
            if (!File.Exists(path))
                return null;
            string json = File.ReadAllText(path);
            return JsonSerializer.Deserialize<AppState>(json);
        }
        catch
        {
            return null;
        }
    }

    internal static AppState Normalize(AppState state)
    {
        state.Shortcuts ??= new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        state.Shortcuts = new Dictionary<string, string>(state.Shortcuts, StringComparer.OrdinalIgnoreCase);
        state.Decks ??= new List<DeckDefinition>();
        state.DeckIdsByDictionary ??= new Dictionary<string, Dictionary<string, string>>(StringComparer.OrdinalIgnoreCase);
        state.DecksByDictionary ??= new Dictionary<string, Dictionary<string, int>>(StringComparer.OrdinalIgnoreCase);

        // Deduplicate malformed deck records by stable ID before guaranteeing the five core decks.
        state.Decks = state.Decks
            .Where(deck => deck is not null && !string.IsNullOrWhiteSpace(deck.Id))
            .GroupBy(deck => deck.Id, StringComparer.OrdinalIgnoreCase)
            .Select(group => group.First())
            .ToList();

        for (int number = 1; number <= 5; number++)
        {
            string coreId = DeckIds.Core(number);
            DeckDefinition? core = state.Decks.FirstOrDefault(deck => string.Equals(deck.Id, coreId, StringComparison.OrdinalIgnoreCase));
            if (core is null)
            {
                core = new DeckDefinition
                {
                    Id = coreId,
                    Name = $"Deck {number}",
                    IsCore = true,
                    Order = number - 1
                };
                state.Decks.Add(core);
            }
            else
            {
                core.IsCore = true;
                if (string.IsNullOrWhiteSpace(core.Name))
                    core.Name = $"Deck {number}";
            }
        }

        // User decks keep their stable IDs and names. Repair only unusable names/order.
        int nextOrder = state.Decks.Count == 0 ? 0 : state.Decks.Max(deck => deck.Order) + 1;
        foreach (DeckDefinition deck in state.Decks)
        {
            if (string.IsNullOrWhiteSpace(deck.Name))
                deck.Name = deck.IsCore ? "Deck" : "Untitled deck";
            if (deck.Order < 0)
                deck.Order = nextOrder++;
        }

        List<DeckDefinition> ordered = state.Decks
            .OrderBy(deck => deck.Order)
            .ThenBy(deck => deck.IsCore ? 0 : 1)
            .ThenBy(deck => deck.Name, StringComparer.CurrentCultureIgnoreCase)
            .ToList();
        for (int i = 0; i < ordered.Count; i++)
            ordered[i].Order = i;
        state.Decks = ordered;

        state.DeckIdsByDictionary = state.DeckIdsByDictionary.ToDictionary(
            pair => pair.Key,
            pair => new Dictionary<string, string>(pair.Value ?? new Dictionary<string, string>(), StringComparer.OrdinalIgnoreCase),
            StringComparer.OrdinalIgnoreCase);
        state.DecksByDictionary = state.DecksByDictionary.ToDictionary(
            pair => pair.Key,
            pair => new Dictionary<string, int>(pair.Value ?? new Dictionary<string, int>(), StringComparer.OrdinalIgnoreCase),
            StringComparer.OrdinalIgnoreCase);

        // Lossless legacy migration: copy every old entry assignment that does
        // not already have a durable deck-ID assignment.
        foreach ((string dictionaryId, Dictionary<string, int> legacyMap) in state.DecksByDictionary)
        {
            if (!state.DeckIdsByDictionary.TryGetValue(dictionaryId, out Dictionary<string, string>? newMap))
            {
                newMap = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                state.DeckIdsByDictionary[dictionaryId] = newMap;
            }

            foreach ((string entryId, int legacyDeck) in legacyMap)
                newMap.TryAdd(entryId, DeckIds.Core(Math.Clamp(legacyDeck, 1, 5)));
        }

        var validDeckIds = new HashSet<string>(state.Decks.Select(deck => deck.Id), StringComparer.OrdinalIgnoreCase);
        string fallbackDeckId = DeckIds.Core(1);
        foreach (Dictionary<string, string> map in state.DeckIdsByDictionary.Values)
        {
            foreach (string entryId in map.Keys.ToList())
            {
                string? deckId = map[entryId];
                if (string.IsNullOrWhiteSpace(deckId) || !validDeckIds.Contains(deckId))
                    map[entryId] = fallbackDeckId;
            }
        }

        // Preserve user-customized fixed-deck bindings by transferring them
        // from the original numeric action IDs to stable core-deck action IDs.
        for (int number = 1; number <= 5; number++)
        {
            string coreId = DeckIds.Core(number);
            CopyShortcutIfMissing(state.Shortcuts, ActionIds.LegacySwitchDeck(number), ActionIds.SwitchDeck(coreId));
            CopyShortcutIfMissing(state.Shortcuts, ActionIds.LegacyMoveToDeck(number), ActionIds.MoveToDeck(coreId));
        }

        if (string.IsNullOrWhiteSpace(state.ActiveDeckId) || !validDeckIds.Contains(state.ActiveDeckId))
            state.ActiveDeckId = DeckIds.Core(Math.Clamp(state.ActiveDeck, 1, 5));

        return state;
    }

    private static void CopyShortcutIfMissing(Dictionary<string, string> shortcuts, string legacyId, string durableId)
    {
        if (!shortcuts.ContainsKey(durableId) && shortcuts.TryGetValue(legacyId, out string? value) && !string.IsNullOrWhiteSpace(value))
            shortcuts[durableId] = value;
    }
}
