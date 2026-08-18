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

        scopes.SetActiveDeck(StudyScopeIds.All, DeckIds.Core(4));
        scopes.SetCurrentEntry(StudyScopeIds.All, "a1-two");
        scopes.SetRemainingShuffle(StudyScopeIds.All, new[] { "b2-one", "c1-one", "b2-one" });
        scopes.SetActiveDeck(StudyScopeIds.A1, DeckIds.Core(5));
        scopes.SetCurrentEntry(StudyScopeIds.A1, "a1-one");
        scopes.SetRemainingShuffle(StudyScopeIds.A1, new[] { "a1-two" });
        scopes.ActiveScopeId = StudyScopeIds.A1;

        Require(scopes.RemainingShuffle(StudyScopeIds.All).SequenceEqual(new[] { "b2-one", "c1-one" }), "All shuffle state did not deduplicate deterministically.");
        Require(scopes.RemainingShuffle(StudyScopeIds.A1).SequenceEqual(new[] { "a1-two" }), "A1 shuffle state was not independent.");
        Require(scopes.Get(StudyScopeIds.All).ActiveDeckId == DeckIds.Core(4) && scopes.Get(StudyScopeIds.A1).ActiveDeckId == DeckIds.Core(5), "Active deck leaked across scopes.");
        Require(scopes.Get(StudyScopeIds.All).CurrentEntryId == "a1-two" && scopes.Get(StudyScopeIds.A1).CurrentEntryId == "a1-one", "Current card leaked across scopes.");

        bool rejected = false;
        try { scopes.Move(StudyScopeIds.C1, "a1-one", DeckIds.Core(2)); }
        catch (InvalidOperationException) { rejected = true; }
        Require(rejected, "Scope accepted an ineligible entry.");

        string root = Path.Combine(Path.GetTempPath(), $"WordDeck-scope-self-test-{Guid.NewGuid():N}");
        try
        {
            var store = new AppStateStore(root);
            store.Save(state);
            AppState reloaded = new AppStateStore(root).Load();
            var restored = new RecallStudyScopeService(reloaded, dictionaryId, entries);
            Require(restored.ActiveScopeId == StudyScopeIds.A1, "Active study scope did not survive JSON round-trip.");
            Require(restored.Assignments(StudyScopeIds.All)["a1-one"] == DeckIds.Core(3), "All assignment did not survive JSON round-trip.");
            Require(restored.Assignments(StudyScopeIds.A1)["a1-one"] == DeckIds.Core(5), "A1 assignment did not survive JSON round-trip.");
            Require(restored.Get(StudyScopeIds.All).ActiveDeckId == DeckIds.Core(4), "All active deck did not survive JSON round-trip.");
            Require(restored.Get(StudyScopeIds.A1).ActiveDeckId == DeckIds.Core(5), "A1 active deck did not survive JSON round-trip.");
            Require(restored.RemainingShuffle(StudyScopeIds.All).SequenceEqual(new[] { "b2-one", "c1-one" }), "All shuffle progress did not survive JSON round-trip.");
            Require(restored.RemainingShuffle(StudyScopeIds.A1).SequenceEqual(new[] { "a1-two" }), "A1 shuffle progress did not survive JSON round-trip.");
        }
        finally
        {
            try { if (Directory.Exists(root)) Directory.Delete(root, true); } catch { }
        }

        var shortcuts = new ShortcutManager(state);
        foreach (string scopeId in StudyScopeIds.Ordered)
        {
            string actionId = ActionIds.SwitchStudyScope(scopeId);
            Require(shortcuts.Definitions.Any(def => def.Id == actionId), $"Missing scope shortcut action {actionId}.");
            Require(shortcuts.Get(actionId) == Keys.None, "Scope shortcuts must start unassigned to avoid conflicts.");
        }

        string a1Action = ActionIds.SwitchStudyScope(StudyScopeIds.A1);
        Require(shortcuts.TrySet(a1Action, Keys.Control | Keys.Alt | Keys.F8, out string? scopeError), $"Could not bind a scope shortcut: {scopeError}");
        Require(shortcuts.FindAction(Keys.Control | Keys.Alt | Keys.F8) == a1Action, "Bound scope shortcut did not dispatch by stable action ID.");
        Require(!shortcuts.TrySet(ActionIds.SwitchStudyScope(StudyScopeIds.A2), Keys.Control | Keys.Alt | Keys.F8, out string? conflict) && !string.IsNullOrWhiteSpace(conflict), "Scope shortcut conflict was not rejected.");

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
