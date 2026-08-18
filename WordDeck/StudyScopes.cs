namespace WordDeck;

internal static class StudyScopeIds
{
    public const string All = "all";
    public const string A1 = "a1";
    public const string A2 = "a2";
    public const string B1 = "b1";
    public const string B2 = "b2";
    public const string C1 = "c1";

    public static IReadOnlyList<string> Ordered { get; } = new[] { All, A1, A2, B1, B2, C1 };

    public static string DisplayName(string scopeId) => scopeId.ToLowerInvariant() switch
    {
        All => "All Oxford 5000",
        A1 => "A1",
        A2 => "A2",
        B1 => "B1",
        B2 => "B2",
        C1 => "C1",
        _ => throw new ArgumentOutOfRangeException(nameof(scopeId), scopeId, "Unknown study scope.")
    };

    public static bool Includes(string scopeId, DictionaryEntry entry) =>
        string.Equals(scopeId, All, StringComparison.OrdinalIgnoreCase) ||
        string.Equals(entry.Level, scopeId, StringComparison.OrdinalIgnoreCase);
}

internal sealed class RecallStudyScopeService
{
    private readonly AppState _state;
    private readonly string _dictionaryId;
    private readonly IReadOnlyList<DictionaryEntry> _entries;
    private readonly RecallStudyScopeDictionaryState _dictionaryState;

    public RecallStudyScopeService(AppState state, string dictionaryId, IReadOnlyList<DictionaryEntry> entries)
    {
        _state = state ?? throw new ArgumentNullException(nameof(state));
        _dictionaryId = string.IsNullOrWhiteSpace(dictionaryId) ? throw new ArgumentException("Dictionary ID is required.", nameof(dictionaryId)) : dictionaryId;
        _entries = entries ?? throw new ArgumentNullException(nameof(entries));
        _state.RecallStudyScopesByDictionary ??= new Dictionary<string, RecallStudyScopeDictionaryState>(StringComparer.OrdinalIgnoreCase);

        if (!_state.RecallStudyScopesByDictionary.TryGetValue(_dictionaryId, out RecallStudyScopeDictionaryState? dictionaryState) || dictionaryState is null)
        {
            dictionaryState = new RecallStudyScopeDictionaryState();
            _state.RecallStudyScopesByDictionary[_dictionaryId] = dictionaryState;
        }
        dictionaryState.Scopes ??= new Dictionary<string, RecallStudyScopeState>(StringComparer.OrdinalIgnoreCase);
        dictionaryState.Scopes = new Dictionary<string, RecallStudyScopeState>(dictionaryState.Scopes, StringComparer.OrdinalIgnoreCase);
        _dictionaryState = dictionaryState;

        EnsureAllScopes();
    }

    public string ActiveScopeId
    {
        get => StudyScopeIds.Ordered.Contains(_dictionaryState.ActiveScopeId, StringComparer.OrdinalIgnoreCase)
            ? _dictionaryState.ActiveScopeId
            : StudyScopeIds.All;
        set
        {
            if (!StudyScopeIds.Ordered.Contains(value, StringComparer.OrdinalIgnoreCase))
                throw new ArgumentOutOfRangeException(nameof(value));
            _dictionaryState.ActiveScopeId = StudyScopeIds.Ordered.First(id => string.Equals(id, value, StringComparison.OrdinalIgnoreCase));
        }
    }

    public IReadOnlyList<DictionaryEntry> EligibleEntries(string scopeId) =>
        _entries.Where(entry => StudyScopeIds.Includes(scopeId, entry)).ToList();

    public RecallStudyScopeState Get(string scopeId)
    {
        if (!_dictionaryState.Scopes.TryGetValue(scopeId, out RecallStudyScopeState? scope) || scope is null)
            throw new ArgumentOutOfRangeException(nameof(scopeId));
        return scope;
    }

    public Dictionary<string, string> Assignments(string scopeId) => Get(scopeId).DeckIds;

    public int Count(string scopeId, string deckId) =>
        Get(scopeId).DeckIds.Values.Count(id => string.Equals(id, deckId, StringComparison.OrdinalIgnoreCase));

    public int ScopeTotal(string scopeId) => EligibleEntries(scopeId).Count;

    public void SetActiveDeck(string scopeId, string deckId)
    {
        if (!_state.Decks.Any(deck => string.Equals(deck.Id, deckId, StringComparison.OrdinalIgnoreCase)))
            throw new ArgumentOutOfRangeException(nameof(deckId));
        Get(scopeId).ActiveDeckId = deckId;
        SyncLegacyAll(scopeId);
    }

    public void SetCurrentEntry(string scopeId, string? entryId)
    {
        RecallStudyScopeState scope = Get(scopeId);
        scope.CurrentEntryId = entryId is not null && scope.DeckIds.ContainsKey(entryId) ? entryId : null;
        SyncLegacyAll(scopeId);
    }

    public void Move(string scopeId, string entryId, string deckId)
    {
        RecallStudyScopeState scope = Get(scopeId);
        if (!scope.DeckIds.ContainsKey(entryId))
            throw new InvalidOperationException("The entry is not eligible in this study scope.");
        if (!_state.Decks.Any(deck => string.Equals(deck.Id, deckId, StringComparison.OrdinalIgnoreCase)))
            throw new InvalidOperationException("Destination deck does not exist.");
        scope.DeckIds[entryId] = deckId;
        SyncLegacyAll(scopeId);
    }

    private void EnsureAllScopes()
    {
        var validDeckIds = new HashSet<string>(_state.Decks.Select(deck => deck.Id), StringComparer.OrdinalIgnoreCase);
        string firstDeck = DeckIds.Core(1);

        foreach (string scopeId in StudyScopeIds.Ordered)
        {
            if (!_dictionaryState.Scopes.TryGetValue(scopeId, out RecallStudyScopeState? scope) || scope is null)
            {
                scope = new RecallStudyScopeState();
                _dictionaryState.Scopes[scopeId] = scope;
            }
            scope.DeckIds ??= new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            scope.DeckIds = new Dictionary<string, string>(scope.DeckIds, StringComparer.OrdinalIgnoreCase);

            IReadOnlyList<DictionaryEntry> eligible = EligibleEntries(scopeId);
            var validEntries = new HashSet<string>(eligible.Select(entry => entry.Id), StringComparer.OrdinalIgnoreCase);

            if (string.Equals(scopeId, StudyScopeIds.All, StringComparison.OrdinalIgnoreCase) && scope.DeckIds.Count == 0 &&
                _state.DeckIdsByDictionary.TryGetValue(_dictionaryId, out Dictionary<string, string>? legacy))
            {
                foreach ((string entryId, string deckId) in legacy)
                    if (validEntries.Contains(entryId)) scope.DeckIds[entryId] = validDeckIds.Contains(deckId) ? deckId : firstDeck;
                if (!string.IsNullOrWhiteSpace(_state.ActiveDeckId) && validDeckIds.Contains(_state.ActiveDeckId))
                    scope.ActiveDeckId = _state.ActiveDeckId;
                if (_state.CurrentEntryIdByDictionary.TryGetValue(_dictionaryId, out string? current) && validEntries.Contains(current))
                    scope.CurrentEntryId = current;
            }

            foreach (string stale in scope.DeckIds.Keys.Where(id => !validEntries.Contains(id)).ToList()) scope.DeckIds.Remove(stale);
            foreach (DictionaryEntry entry in eligible)
            {
                if (!scope.DeckIds.TryGetValue(entry.Id, out string? deckId) || !validDeckIds.Contains(deckId))
                    scope.DeckIds[entry.Id] = firstDeck;
            }
            if (!validDeckIds.Contains(scope.ActiveDeckId)) scope.ActiveDeckId = firstDeck;
            if (scope.CurrentEntryId is not null && !scope.DeckIds.ContainsKey(scope.CurrentEntryId)) scope.CurrentEntryId = null;
        }

        if (!StudyScopeIds.Ordered.Contains(_dictionaryState.ActiveScopeId, StringComparer.OrdinalIgnoreCase))
            _dictionaryState.ActiveScopeId = StudyScopeIds.All;
        SyncLegacyAll(StudyScopeIds.All);
    }

    private void SyncLegacyAll(string scopeId)
    {
        if (!string.Equals(scopeId, StudyScopeIds.All, StringComparison.OrdinalIgnoreCase)) return;
        RecallStudyScopeState all = Get(StudyScopeIds.All);
        _state.DeckIdsByDictionary[_dictionaryId] = new Dictionary<string, string>(all.DeckIds, StringComparer.OrdinalIgnoreCase);
        _state.ActiveDeckId = all.ActiveDeckId;
        if (all.CurrentEntryId is null) _state.CurrentEntryIdByDictionary.Remove(_dictionaryId);
        else _state.CurrentEntryIdByDictionary[_dictionaryId] = all.CurrentEntryId;
    }
}