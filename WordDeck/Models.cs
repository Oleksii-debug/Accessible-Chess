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

internal sealed class AppState
{
    public string? ActiveDictionaryId { get; set; }
    public int ActiveDeck { get; set; } = 1;
    public Dictionary<string, Dictionary<string, int>> DecksByDictionary { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public Dictionary<string, string> Shortcuts { get; set; } = new(StringComparer.OrdinalIgnoreCase);
}

internal static class ActionIds
{
    public const string NextWord = "next_word";
    public const string PreviousWord = "previous_word";
    public const string RevealTranslation = "reveal_translation";
    public const string RepeatWord = "repeat_word";
    public const string ShortcutSettings = "shortcut_settings";
    public const string Help = "help";

    public static string SwitchDeck(int deck) => $"switch_deck_{deck}";
    public static string MoveToDeck(int deck) => $"move_to_deck_{deck}";
}

internal sealed record ShortcutDefinition(string Id, string Description, Keys DefaultKeys);
