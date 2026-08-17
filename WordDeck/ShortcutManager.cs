namespace WordDeck;

internal sealed class ShortcutManager
{
    private readonly AppState _state;
    public IReadOnlyList<ShortcutDefinition> Definitions { get; private set; }

    public ShortcutManager(AppState state)
    {
        _state = AppStateStore.Normalize(state);
        Definitions = BuildDefinitions();
        EnsureDefaults();
    }

    public void RefreshDeckDefinitions()
    {
        Definitions = BuildDefinitions();
        EnsureDefaults();
        RemoveOrphanedDeckShortcuts();
    }

    public Keys Get(string actionId)
    {
        ShortcutDefinition? definition = Definitions.FirstOrDefault(x => x.Id == actionId);
        if (definition is null)
            return Keys.None;

        if (_state.Shortcuts.TryGetValue(actionId, out string? raw) && Enum.TryParse(raw, out Keys keys))
        {
            if (keys == Keys.None && definition.DefaultKeys == Keys.None)
                return Keys.None;
            if (!IsUnsafe(keys))
                return keys;
        }
        return definition.DefaultKeys;
    }

    public string? FindAction(Keys keyData)
    {
        if (keyData == Keys.None)
            return null;

        ShortcutDefinition? definition = Definitions.FirstOrDefault(def => Get(def.Id) != Keys.None && Get(def.Id) == keyData);
        if (definition is null)
            return null;

        // Both directional study bindings intentionally dispatch to the same
        // random shuffle-bag action. There is no deterministic history action
        // behind either arrow binding.
        return definition.Id == ActionIds.PreviousWord ? ActionIds.NextWord : definition.Id;
    }

    public bool TrySet(string actionId, Keys keys, out string? errorDescription)
    {
        if (!Definitions.Any(def => def.Id == actionId))
        {
            errorDescription = "the function no longer exists";
            return false;
        }

        if (IsUnsafe(keys))
        {
            errorDescription = "this combination is reserved for Windows or keyboard navigation";
            return false;
        }

        var conflict = Definitions.FirstOrDefault(def => def.Id != actionId && Get(def.Id) == keys);
        if (conflict is not null)
        {
            errorDescription = $"it is already assigned to {conflict.Description}";
            return false;
        }

        _state.Shortcuts[actionId] = keys.ToString();
        errorDescription = null;
        return true;
    }

    public void Clear(string actionId)
    {
        ShortcutDefinition? definition = Definitions.FirstOrDefault(def => def.Id == actionId);
        if (definition is null)
            return;
        _state.Shortcuts[actionId] = Keys.None.ToString();
    }

    public void ResetDefaults()
    {
        foreach (ShortcutDefinition def in Definitions)
            _state.Shortcuts[def.Id] = def.DefaultKeys.ToString();
    }

    private void EnsureDefaults()
    {
        foreach (ShortcutDefinition def in Definitions)
            _state.Shortcuts.TryAdd(def.Id, def.DefaultKeys.ToString());
    }

    private void RemoveOrphanedDeckShortcuts()
    {
        var valid = new HashSet<string>(Definitions.Select(def => def.Id), StringComparer.OrdinalIgnoreCase);
        foreach (string actionId in _state.Shortcuts.Keys
                     .Where(id => (id.StartsWith("switch_deck_", StringComparison.OrdinalIgnoreCase) || id.StartsWith("move_to_deck_", StringComparison.OrdinalIgnoreCase)) &&
                                  !valid.Contains(id) && !IsLegacyNumericDeckAction(id))
                     .ToList())
            _state.Shortcuts.Remove(actionId);
    }

    private static bool IsLegacyNumericDeckAction(string id)
    {
        string prefix = id.StartsWith("switch_deck_", StringComparison.OrdinalIgnoreCase) ? "switch_deck_" : "move_to_deck_";
        return int.TryParse(id[prefix.Length..], out int number) && number is >= 1 and <= 5;
    }

    private static bool IsUnsafe(Keys keys)
    {
        Keys code = keys & Keys.KeyCode;
        Keys modifiers = keys & Keys.Modifiers;

        if (code is Keys.None or Keys.Tab or Keys.Escape or Keys.Enter)
            return true;

        if (code == Keys.F4 && modifiers.HasFlag(Keys.Alt))
            return true;

        // Bare navigation keys are intentionally left to native WinForms controls and screen readers.
        if (modifiers == Keys.None && code is Keys.Left or Keys.Right or Keys.Up or Keys.Down or Keys.Home or Keys.End or Keys.PageUp or Keys.PageDown)
            return true;

        return false;
    }

    private IReadOnlyList<ShortcutDefinition> BuildDefinitions()
    {
        var defs = new List<ShortcutDefinition>
        {
            new(ActionIds.NextWord, "Another random word (right)", Keys.Control | Keys.Right),
            new(ActionIds.PreviousWord, "Another random word (left)", Keys.Control | Keys.Left),
            new(ActionIds.RevealTranslation, "Reveal translation", Keys.Control | Keys.T),
            new(ActionIds.RepeatWord, "Repeat current English word with screen reader", Keys.Control | Keys.R),
            new(ActionIds.PlayPronunciation, "Play generated British pronunciation", Keys.Control | Keys.P),
            new(ActionIds.ToggleAutoPronunciation, "Toggle automatic British pronunciation", Keys.Control | Keys.Shift | Keys.P),
            new(ActionIds.UndoMove, "Undo last deck move", Keys.Control | Keys.Z),
            new(ActionIds.ShortcutSettings, "Open shortcut settings", Keys.Control | Keys.K),
            new(ActionIds.Help, "Open help", Keys.F1),
        };

        IReadOnlyList<DeckDefinition> ordered = _state.Decks.OrderBy(deck => deck.Order).ToList();
        for (int index = 0; index < ordered.Count; index++)
        {
            DeckDefinition deck = ordered[index];
            Keys switchDefault = Keys.None;
            Keys moveDefault = Keys.None;
            int coreNumber = DeckIds.CoreDecks.ToList().FindIndex(id => string.Equals(id, deck.Id, StringComparison.OrdinalIgnoreCase)) + 1;
            if (coreNumber is >= 1 and <= 5)
            {
                switchDefault = Keys.Control | (Keys)((int)Keys.D0 + coreNumber);
                moveDefault = Keys.Alt | (Keys)((int)Keys.D0 + coreNumber);
            }

            defs.Add(new(ActionIds.SwitchDeck(deck.Id), $"Switch to deck: {deck.Name}", switchDefault));
            defs.Add(new(ActionIds.MoveToDeck(deck.Id), $"Move current word to deck: {deck.Name}", moveDefault));
        }

        return defs;
    }
}
