namespace WordDeck;

internal sealed record DictionaryEntry(string Id, string Level, string Source, string Target);

internal sealed class DictionaryPackage
{
    public required string Id { get; init; }
    public required string Name { get; init; }
    public required string SourceLanguage { get; init; }
    public required string TargetLanguage { get; init; }
    public required IReadOnlyList<DictionaryEntry> Entries { get; init; }
}

internal sealed class DeckDefinition
{
    public required string Id { get; set; }
    public required string Name { get; set; }
    public bool IsCore { get; set; }
    public int Order { get; set; }

    public override string ToString() => Name;
}

internal static class DeckIds
{
    public static string Core(int number) => $"core-{number}";
    public static IReadOnlyList<string> CoreDecks { get; } = Enumerable.Range(1, 5).Select(Core).ToArray();
}

internal sealed class AppState
{
    public string? ActiveDictionaryId { get; set; }

    // Durable dynamic-deck state. Deck IDs, not display names or positions,
    // own assignments and keyboard shortcuts.
    public string? ActiveDeckId { get; set; }
    public List<DeckDefinition> Decks { get; set; } = new();
    public Dictionary<string, Dictionary<string, string>> DeckIdsByDictionary { get; set; } = new(StringComparer.OrdinalIgnoreCase);

    // Legacy v1 fields are intentionally retained for lossless one-way
    // migration of existing installations. New code does not write study
    // progress through these fields.
    public int ActiveDeck { get; set; } = 1;
    public Dictionary<string, Dictionary<string, int>> DecksByDictionary { get; set; } = new(StringComparer.OrdinalIgnoreCase);

    public Dictionary<string, string> Shortcuts { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public bool AutoPlayPronunciationOnCardChange { get; set; }
}

internal static class ActionIds
{
    public const string NextWord = "next_word";
    public const string PreviousWord = "previous_word";
    public const string RevealTranslation = "reveal_translation";
    public const string RepeatWord = "repeat_word";
    public const string PlayPronunciation = "play_pronunciation";
    public const string ToggleAutoPronunciation = "toggle_auto_pronunciation";
    public const string UndoMove = "undo_move";
    public const string ShortcutSettings = "shortcut_settings";
    public const string Help = "help";

    public static string SwitchDeck(string deckId) => $"switch_deck_{deckId}";
    public static string MoveToDeck(string deckId) => $"move_to_deck_{deckId}";

    // Legacy action IDs from the original fixed five-deck model.
    public static string LegacySwitchDeck(int deck) => $"switch_deck_{deck}";
    public static string LegacyMoveToDeck(int deck) => $"move_to_deck_{deck}";
}

internal sealed record ShortcutDefinition(string Id, string Description, Keys DefaultKeys);
