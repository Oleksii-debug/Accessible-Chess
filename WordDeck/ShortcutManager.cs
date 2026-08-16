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
        if (_state.Shortcuts.TryGetValue(actionId, out string? raw) && Enum.TryParse(raw, out Keys keys) && !IsUnsafe(keys))
            return keys;
        return Definitions.First(x => x.Id == actionId).DefaultKeys;
    }

    public string? FindAction(Keys keyData)
    {
        return Definitions.FirstOrDefault(def => Get(def.Id) == keyData)?.Id;
    }

    public bool TrySet(string actionId, Keys keys, out string? errorDescription)
    {
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

    private static IReadOnlyList<ShortcutDefinition> BuildDefinitions()
    {
        var defs = new List<ShortcutDefinition>
        {
            new(ActionIds.NextWord, "Next random word", Keys.Control | Keys.Right),
            new(ActionIds.PreviousWord, "Previous word", Keys.Control | Keys.Left),
            new(ActionIds.RevealTranslation, "Reveal translation", Keys.Control | Keys.T),
            new(ActionIds.RepeatWord, "Repeat current English word", Keys.Control | Keys.R),
            new(ActionIds.UndoMove, "Undo last deck move", Keys.Control | Keys.Z),
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
