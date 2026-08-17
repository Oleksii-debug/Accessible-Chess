namespace WordDeck;

internal sealed class DeckService
{
    private readonly AppState _state;

    public DeckService(AppState state)
    {
        _state = state;
    }

    public IReadOnlyList<DeckDefinition> Decks =>
        _state.Decks.OrderBy(deck => deck.Order).ThenBy(deck => deck.Name, StringComparer.CurrentCultureIgnoreCase).ToList();

    public DeckDefinition FirstDeck => Decks.First();

    public DeckDefinition? Find(string deckId) =>
        _state.Decks.FirstOrDefault(deck => string.Equals(deck.Id, deckId, StringComparison.OrdinalIgnoreCase));

    public Dictionary<string, string> EnsureDictionaryAssignments(string dictionaryId, IEnumerable<string> entryIds)
    {
        if (!_state.DeckIdsByDictionary.TryGetValue(dictionaryId, out Dictionary<string, string>? map))
        {
            map = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            _state.DeckIdsByDictionary[dictionaryId] = map;
        }

        var validEntryIds = new HashSet<string>(entryIds, StringComparer.OrdinalIgnoreCase);
        var validDeckIds = new HashSet<string>(_state.Decks.Select(deck => deck.Id), StringComparer.OrdinalIgnoreCase);
        string fallbackDeckId = FirstDeck.Id;

        foreach (string staleId in map.Keys.Where(id => !validEntryIds.Contains(id)).ToList())
            map.Remove(staleId);

        foreach (string entryId in validEntryIds)
        {
            if (!map.TryGetValue(entryId, out string? deckId) || string.IsNullOrWhiteSpace(deckId) || !validDeckIds.Contains(deckId))
                map[entryId] = fallbackDeckId;
        }

        return map;
    }

    public DeckDefinition Create(string name)
    {
        name = NormalizeName(name);
        EnsureUniqueName(name, exceptDeckId: null);

        var deck = new DeckDefinition
        {
            Id = $"user-{Guid.NewGuid():N}",
            Name = name,
            IsCore = false,
            Order = _state.Decks.Count == 0 ? 0 : _state.Decks.Max(item => item.Order) + 1
        };
        _state.Decks.Add(deck);
        NormalizeOrder();
        return deck;
    }

    public void Rename(string deckId, string newName)
    {
        DeckDefinition deck = Find(deckId) ?? throw new InvalidOperationException("Deck no longer exists.");
        newName = NormalizeName(newName);
        EnsureUniqueName(newName, deck.Id);
        deck.Name = newName;
    }

    public bool Move(string deckId, int direction)
    {
        if (direction is not -1 and not 1)
            throw new ArgumentOutOfRangeException(nameof(direction));

        List<DeckDefinition> ordered = Decks.ToList();
        int index = ordered.FindIndex(deck => string.Equals(deck.Id, deckId, StringComparison.OrdinalIgnoreCase));
        int target = index + direction;
        if (index < 0 || target < 0 || target >= ordered.Count)
            return false;

        (ordered[index], ordered[target]) = (ordered[target], ordered[index]);
        for (int i = 0; i < ordered.Count; i++)
            ordered[i].Order = i;
        return true;
    }

    public int CountInDictionary(string dictionaryId, string deckId)
    {
        if (!_state.DeckIdsByDictionary.TryGetValue(dictionaryId, out Dictionary<string, string>? map))
            return 0;
        return map.Values.Count(value => string.Equals(value, deckId, StringComparison.OrdinalIgnoreCase));
    }

    public int CountEverywhere(string deckId) =>
        _state.DeckIdsByDictionary.Values.Sum(map =>
            map.Values.Count(value => string.Equals(value, deckId, StringComparison.OrdinalIgnoreCase)));

    public void DeleteUserDeck(string deckId, string? destinationDeckId)
    {
        DeckDefinition deck = Find(deckId) ?? throw new InvalidOperationException("Deck no longer exists.");
        if (deck.IsCore)
            throw new InvalidOperationException("The five default decks are permanent and cannot be deleted.");

        int assignedCount = CountEverywhere(deckId);
        if (assignedCount > 0)
        {
            if (string.IsNullOrWhiteSpace(destinationDeckId))
                throw new InvalidOperationException("A destination deck is required before deleting a non-empty deck.");
            if (string.Equals(destinationDeckId, deckId, StringComparison.OrdinalIgnoreCase) || Find(destinationDeckId) is null)
                throw new InvalidOperationException("The destination deck is invalid.");

            foreach (Dictionary<string, string> map in _state.DeckIdsByDictionary.Values)
            {
                foreach (string entryId in map.Where(pair => string.Equals(pair.Value, deckId, StringComparison.OrdinalIgnoreCase)).Select(pair => pair.Key).ToList())
                    map[entryId] = destinationDeckId;
            }
        }

        _state.Decks.Remove(deck);
        _state.Shortcuts.Remove(ActionIds.SwitchDeck(deckId));
        _state.Shortcuts.Remove(ActionIds.MoveToDeck(deckId));
        if (string.Equals(_state.ActiveDeckId, deckId, StringComparison.OrdinalIgnoreCase))
            _state.ActiveDeckId = destinationDeckId ?? FirstRemainingDeckId(deckId);
        NormalizeOrder();
    }

    private string FirstRemainingDeckId(string deletingDeckId) =>
        Decks.First(deck => !string.Equals(deck.Id, deletingDeckId, StringComparison.OrdinalIgnoreCase)).Id;

    private void NormalizeOrder()
    {
        List<DeckDefinition> ordered = _state.Decks.OrderBy(deck => deck.Order).ThenBy(deck => deck.Name, StringComparer.CurrentCultureIgnoreCase).ToList();
        for (int i = 0; i < ordered.Count; i++)
            ordered[i].Order = i;
    }

    private static string NormalizeName(string name)
    {
        string normalized = (name ?? string.Empty).Trim();
        if (normalized.Length == 0)
            throw new InvalidOperationException("Deck name cannot be blank.");
        if (normalized.Length > 80)
            throw new InvalidOperationException("Deck name cannot be longer than 80 characters.");
        return normalized;
    }

    private void EnsureUniqueName(string name, string? exceptDeckId)
    {
        bool duplicate = _state.Decks.Any(deck =>
            !string.Equals(deck.Id, exceptDeckId, StringComparison.OrdinalIgnoreCase) &&
            string.Equals(deck.Name, name, StringComparison.CurrentCultureIgnoreCase));
        if (duplicate)
            throw new InvalidOperationException("A deck with that name already exists.");
    }
}
