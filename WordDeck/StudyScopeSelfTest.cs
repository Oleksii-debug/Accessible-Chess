namespace WordDeck;

internal static class StudyScopeSelfTest
{
    public static void Run()
    {
        const string dictionaryId = "oxford-test";
        var entries = new List<DictionaryEntry>
        {
            new("a1-one", "A1", "one", "один"),
            new("a1-two", "A1", "two", "два"),
            new("b2-one", "B2", "advanced", "просунутий"),
            new("c1-one", "C1", "rigorous", "суворий")
        };

        AppState state = AppStateStore.Normalize(new AppState { ActiveDeckId = DeckIds.Core(3) });
        state.DeckIdsByDictionary[dictionaryId] = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["a1-one"] = DeckIds.Core(2),
            ["a1-two"] = DeckIds.Core(4),
            ["b2-one"] = DeckIds.Core(5),
            ["c1-one"] = DeckIds.Core(1)
        };
        state.CurrentEntryIdByDictionary[dictionaryId] = "a1-two";

        var scopes = new RecallStudyScopeService(state, dictionaryId, entries);
        Require(scopes.ScopeTotal(StudyScopeIds.All) == 4, "All scope must contain every lexical entry.");
        Require(scopes.ScopeTotal(StudyScopeIds.A1) == 2, "A1 scope must contain only A1 entries.");
        Require(scopes.ScopeTotal(StudyScopeIds.B2) == 1 && scopes.ScopeTotal(StudyScopeIds.C1) == 1, "CEFR scope filtering failed.");
        Require(scopes.ScopeTotal(StudyScopeIds.A2) == 0 && scopes.ScopeTotal(StudyScopeIds.B1) == 0, "Empty CEFR scopes must remain empty, not invent entries.");

        Require(scopes.Assignments(StudyScopeIds.All)["a1-one"] == DeckIds.Core(2), "Legacy Recall assignment was not migrated into All.");
        Require(scopes.Get(StudyScopeIds.All).CurrentEntryId == "a1-two", "Legacy current card was not migrated into All.");
        Require(scopes.Assignments(StudyScopeIds.A1).Values.All(deck => deck == DeckIds.Core(1)), "New level scope must initialize deterministically to deck 1.");

        scopes.Move(StudyScopeIds.A1, "a1-one", DeckIds.Core(5));
        Require(scopes.Assignments(StudyScopeIds.A1)["a1-one"] == DeckIds.Core(5), "A1 move was not stored.");
        Require(scopes.Assignments(StudyScopeIds.All)["a1-one"] == DeckIds.Core(2), "A1 move leaked into All scope.");

        scopes.Move(StudyScopeIds.All, "a1-one", DeckIds.Core(3));
        Require(state.DeckIdsByDictionary[dictionaryId]["a1-one"] == DeckIds.Core(3), "All scope did not keep legacy compatibility map synchronized.");
        Require(scopes.Assignments(StudyScopeIds.A1)["a1-one"] == DeckIds.Core(5), "All move leaked into A1 scope.");

        bool rejected = false;
        try { scopes.Move(StudyScopeIds.C1, "a1-one", DeckIds.Core(2)); }
        catch (InvalidOperationException) { rejected = true; }
        Require(rejected, "Scope accepted an ineligible entry.");

        var shortcuts = new ShortcutManager(state);
        foreach (string scopeId in StudyScopeIds.Ordered)
        {
            string actionId = ActionIds.SwitchStudyScope(scopeId);
            Require(shortcuts.Definitions.Any(def => def.Id == actionId), $"Missing scope shortcut action {actionId}.");
            Require(shortcuts.Get(actionId) == Keys.None, "Scope shortcuts must start unassigned to avoid conflicts.");
        }

        Require(ShortcutFormatter.Format(Keys.Control | Keys.Shift | Keys.B) == "Ctrl+Shift+B", "Canonical formatter failed Ctrl+Shift+B.");
        Require(ShortcutFormatter.Format(Keys.Control | Keys.Alt | Keys.Delete) == "Ctrl+Alt+Delete", "Canonical formatter failed Ctrl+Alt+Delete.");
        Require(ShortcutFormatter.Format(Keys.Control | Keys.Shift | Keys.Delete) == "Ctrl+Shift+Delete", "Spelling delete display must match its actual default.");
        Require(ShortcutFormatter.Format(Keys.None) == "Unassigned", "Unassigned shortcut display changed.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }
}
