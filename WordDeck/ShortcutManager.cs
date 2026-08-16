namespace WordDeck;

internal sealed class ShortcutManager
{
    public static IReadOnlyList<ShortcutDefinition> Definitions { get; } = BuildDefinitions();
    private readonly AppState _state;

    public ShortcutManager(AppState state)
    {
        _state = state;
        EnsureDefaults();
    }

    public Keys Get(string actionId)
    {
        if (_state.Shortcuts.TryGetValue(actionId, out string? raw) && Enum.TryParse(raw, out Keys keys))
            return keys;
        return Definitions.First(x => x.Id == actionId).DefaultKeys;
    }

    public string? FindAction(Keys keyData)
    {
        return Definitions.FirstOrDefault(def => Get(def.Id) == keyData)?.Id;
    }

    public bool TrySet(string actionId, Keys keys, out string? conflictDescription)
    {
        var conflict = Definitions.FirstOrDefault(def => def.Id != actionId && Get(def.Id) == keys);
        if (conflict is not null)
        {
            conflictDescription = conflict.Description;
            return false;
        }

        _state.Shortcuts[actionId] = keys.ToString();
        conflictDescription = null;
        return true;
    }

    public void ResetDefaults()
    {
        _state.Shortcuts.Clear();
        EnsureDefaults();
    }

    private void EnsureDefaults()
    {
        foreach (ShortcutDefinition def in Definitions)
            _state.Shortcuts.TryAdd(def.Id, def.DefaultKeys.ToString());
    }

    private static IReadOnlyList<ShortcutDefinition> BuildDefinitions()
    {
        var defs = new List<ShortcutDefinition>
        {
            new(ActionIds.NextWord, "Next random word", Keys.Control | Keys.Right),
            new(ActionIds.PreviousWord, "Previous word", Keys.Control | Keys.Left),
            new(ActionIds.RevealTranslation, "Reveal translation", Keys.Control | Keys.T),
            new(ActionIds.RepeatWord, "Repeat/focus current English word", Keys.Control | Keys.R),
            new(ActionIds.ShortcutSettings, "Open shortcut settings", Keys.Control | Keys.K),
            new(ActionIds.Help, "Open help", Keys.F1),
        };

        for (int deck = 1; deck <= 5; deck++)
            defs.Add(new(ActionIds.SwitchDeck(deck), $"Switch to deck {deck}", Keys.Control | (Keys)((int)Keys.D0 + deck)));
        for (int deck = 1; deck <= 5; deck++)
            defs.Add(new(ActionIds.MoveToDeck(deck), $"Move current word to deck {deck}", Keys.Alt | (Keys)((int)Keys.D0 + deck)));

        return defs;
    }
}
