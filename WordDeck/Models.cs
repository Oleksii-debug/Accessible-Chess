namespace WordDeck;

internal sealed record DictionaryEntry(string Id, string Level, string Source, string Target);

internal sealed record CustomEntryRecord(string Id, string Source, string Target, string Level = "CUSTOM");

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

internal sealed class RecallStudyScopeState
{
    public string ActiveDeckId { get; set; } = DeckIds.Core(1);
    public string? CurrentEntryId { get; set; }
    public Dictionary<string, string> DeckIds { get; set; } = new(StringComparer.OrdinalIgnoreCase);
}

internal sealed class RecallStudyScopeDictionaryState
{
    public string ActiveScopeId { get; set; } = StudyScopeIds.All;
    public Dictionary<string, RecallStudyScopeState> Scopes { get; set; } = new(StringComparer.OrdinalIgnoreCase);
}

internal sealed class AppState
{
    public string? ActiveDictionaryId { get; set; }

    public string? ActiveDeckId { get; set; }
    public List<DeckDefinition> Decks { get; set; } = new();
    public Dictionary<string, Dictionary<string, string>> DeckIdsByDictionary { get; set; } = new(StringComparer.OrdinalIgnoreCase);

    public Dictionary<string, List<CustomEntryRecord>> CustomEntriesByDictionary { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public Dictionary<string, string> CurrentEntryIdByDictionary { get; set; } = new(StringComparer.OrdinalIgnoreCase);

    // Recall study workspaces. Legacy Recall fields above remain for migration and
    // compatibility; the All scope is initialized losslessly from them.
    public Dictionary<string, RecallStudyScopeDictionaryState> RecallStudyScopesByDictionary { get; set; } = new(StringComparer.OrdinalIgnoreCase);

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
    public const string AddWords = "add_words";
    public const string SaveProgress = "save_progress";
    public const string UndoMove = "undo_move";
    public const string ShortcutSettings = "shortcut_settings";
    public const string Help = "help";

    public const string OpenSpelling = "spelling_open";
    public const string SpellingShowAnswer = "spelling_show_answer";
    public const string SpellingRepeatPrompt = "spelling_repeat_prompt";
    public const string SpellingPlayPronunciation = "spelling_play_pronunciation";
    public const string SpellingToggleCoach = "spelling_toggle_coach";
    public const string SpellingUndoCoachMove = "spelling_undo_coach_move";
    public const string SpellingMoveChooser = "spelling_move_chooser";
    public const string SpellingCreateDeck = "spelling_create_deck";
    public const string SpellingRenameDeck = "spelling_rename_deck";
    public const string SpellingDeleteDeck = "spelling_delete_deck";
    public const string SpellingMoveDeckUp = "spelling_move_deck_up";
    public const string SpellingMoveDeckDown = "spelling_move_deck_down";

    public const string OpenSentenceCoach = "sentence_open";
    public const string SentenceShowAnswer = "sentence_show_answer";
    public const string SentenceRepeatPrompt = "sentence_repeat_prompt";
    public const string SentenceImportPack = "sentence_import_pack";

    public static string SwitchDeck(string deckId) => $"switch_deck_{deckId}";
    public static string MoveToDeck(string deckId) => $"move_to_deck_{deckId}";
    public static string SwitchStudyScope(string scopeId) => $"recall_scope_{scopeId}";
    public static string SpellingSwitchDeck(string deckId) => $"spelling_switch_deck_{deckId}";
    public static string SpellingMoveToDeck(string deckId) => $"spelling_move_to_deck_{deckId}";

    public static string SwitchDeck(int deck) => SwitchDeck(DeckIds.Core(deck));
    public static string MoveToDeck(int deck) => MoveToDeck(DeckIds.Core(deck));

    public static string LegacySwitchDeck(int deck) => $"switch_deck_{deck}";
    public static string LegacyMoveToDeck(int deck) => $"move_to_deck_{deck}";
}

internal sealed record ShortcutDefinition(string Id, string Description, Keys DefaultKeys);