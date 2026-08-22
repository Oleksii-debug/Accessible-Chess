using System.Text.Json;

namespace WordDeck;

internal static class SpellingSelfTest
{
    private const string DictionaryId = "spelling-self-test-dictionary";

    public static void Run()
    {
        TestMatcher();
        TestRandomSession();
        TestDeckServiceAndPersistence();
        TestCoachDeterminismAndUndo();
        TestStudyScopeIsolation();
        TestProfileRoundTripAndFailureSafety();
        TestSpellingShortcutRegistry();
        Console.WriteLine("WordDeck Spelling self-test passed: exact matcher, random sessions, five-plus-user decks, deterministic coach/undo, scope isolation, profile round-trip/fail-closed, and explicit Spelling-context shortcut registry validated.");
    }

    private static void TestMatcher()
    {
        Require(SpellingMatcher.IsExact("colour", "colour"), "Exact spelling was rejected.");
        Require(SpellingMatcher.IsExact(" colour ", "colour"), "Technical outer whitespace normalization failed.");
        Require(!SpellingMatcher.IsExact("Colour", "colour"), "Case difference was incorrectly accepted.");
        Require(!SpellingMatcher.IsExact("color", "colour"), "American spelling was incorrectly accepted for British target.");
        Require(!SpellingMatcher.IsExact("co lour", "colour"), "Internal whitespace difference was incorrectly accepted.");
        Require(!SpellingMatcher.IsExact("cafe", "café"), "Diacritic difference was incorrectly accepted.");
    }

    private static void TestRandomSession()
    {
        string[] ids = { "a", "b", "c", "d" };
        var first = new SpellingRandomSession(new Random(41));
        string current = first.Next(ids);
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { current };
        for (int i = 0; i < ids.Length - 1; i++)
        {
            string next = first.Next(ids, current);
            Require(!string.Equals(next, current, StringComparison.OrdinalIgnoreCase), "Random spelling session immediately repeated the current card.");
            seen.Add(next);
            current = next;
        }
        Require(seen.SetEquals(ids), "Random spelling bag repeated/lost entries before exhausting the active deck.");
    }

    private static void TestDeckServiceAndPersistence()
    {
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck-spelling-self-test-{Guid.NewGuid():N}");
        try
        {
            var store = new SpellingStateStore(root);
            SpellingState state = SpellingStateStore.Normalize(new SpellingState());
            var service = new SpellingDeckService(state);
            Require(state.Decks.Count == 5 && state.Decks.All(d => d.IsCore), "Spelling did not initialize exactly five permanent core decks.");
            service.Rename(SpellingDeckIds.Core(1), "New spelling words");
            DeckDefinition custom = service.Create("Hard spellings");
            Require(!custom.IsCore, "User spelling deck was not created as a user deck.");
            Dictionary<string, string> assignments = service.EnsureAssignments(DictionaryId, StudyScopeIds.All, new[] { "a", "b", "c" });
            assignments["a"] = custom.Id;
            state.ActiveDeckId = custom.Id;
            state.ActiveStudyScope = StudyScopeIds.All;
            store.Save(state);

            SpellingState reloaded = new SpellingStateStore(root).Load();
            Require(reloaded.ActiveDeckId == custom.Id, "Active spelling deck did not survive restart.");
            Require(reloaded.Decks.Any(d => d.Id == custom.Id && d.Name == "Hard spellings"), "User spelling deck did not survive restart.");
            Require(reloaded.DeckIdsByDictionaryScope[DictionaryId][StudyScopeIds.All]["a"] == custom.Id,
                "Spelling deck assignment did not survive restart.");

            bool unsafeDelete = false;
            try { new SpellingDeckService(reloaded).DeleteUserDeck(custom.Id, null); } catch (InvalidOperationException) { unsafeDelete = true; }
            Require(unsafeDelete, "Non-empty spelling user deck was deleted without destination.");
            new SpellingDeckService(reloaded).DeleteUserDeck(custom.Id, SpellingDeckIds.Core(2));
            Require(reloaded.DeckIdsByDictionaryScope[DictionaryId][StudyScopeIds.All]["a"] == SpellingDeckIds.Core(2),
                "Deleting spelling user deck did not move assigned words.");
        }
        finally
        {
            try { if (Directory.Exists(root)) Directory.Delete(root, true); } catch { }
        }
    }

    private static void TestCoachDeterminismAndUndo()
    {
        SpellingState state = SpellingStateStore.Normalize(new SpellingState());
        var service = new SpellingDeckService(state);
        Dictionary<string, string> map = service.EnsureAssignments(DictionaryId, StudyScopeIds.All, new[] { "entry" });
        map["entry"] = SpellingDeckIds.Core(3);
        var coach = new SpellingAdaptiveCoach(state);

        for (int i = 0; i < 4; i++) coach.Record(DictionaryId, StudyScopeIds.All, "entry", correct: false, firstTry: false);
        SpellingCoachDecision hard = coach.Decide(DictionaryId, StudyScopeIds.All, "entry", SpellingDeckIds.Core(3));
        Require(hard.MoveToDeckId == SpellingDeckIds.Core(2), "Deterministic Coach did not move repeated-error word toward harder review deck.");
        coach.Apply(service, DictionaryId, StudyScopeIds.All, "entry", hard);
        Require(map["entry"] == SpellingDeckIds.Core(2), "Coach decision was not applied.");
        Require(coach.UndoLast(service) && map["entry"] == SpellingDeckIds.Core(3), "Coach undo did not restore previous deck.");

        SpellingState clone = JsonSerializer.Deserialize<SpellingState>(JsonSerializer.Serialize(state))!;
        SpellingCoachDecision a = new SpellingAdaptiveCoach(state).Decide(DictionaryId, StudyScopeIds.All, "entry", SpellingDeckIds.Core(3));
        SpellingCoachDecision b = new SpellingAdaptiveCoach(clone).Decide(DictionaryId, StudyScopeIds.All, "entry", SpellingDeckIds.Core(3));
        Require(a == b, "Adaptive Coach is not deterministic for identical persisted state.");
    }

    private static void TestStudyScopeIsolation()
    {
        SpellingState state = SpellingStateStore.Normalize(new SpellingState());
        var service = new SpellingDeckService(state);
        Dictionary<string, string> all = service.EnsureAssignments(DictionaryId, StudyScopeIds.All, new[] { "a", "b" });
        Dictionary<string, string> a1 = service.EnsureAssignments(DictionaryId, StudyScopeIds.A1, new[] { "a" });
        all["a"] = SpellingDeckIds.Core(4);
        a1["a"] = SpellingDeckIds.Core(2);
        Require(all["a"] == SpellingDeckIds.Core(4) && a1["a"] == SpellingDeckIds.Core(2), "Spelling deck assignments leaked between study scopes.");
    }

    private static void TestProfileRoundTripAndFailureSafety()
    {
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck-spelling-profile-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            var appStore = new AppStateStore(root);
            var spellingStore = new SpellingStateStore(root);
            var service = new SpellingProfileService(appStore, spellingStore);
            AppState app = AppStateStore.Normalize(new AppState { ActiveDictionaryId = "d" });
            SpellingState spelling = SpellingStateStore.Normalize(new SpellingState { ActiveStudyScope = StudyScopeIds.A1 });
            var deckService = new SpellingDeckService(spelling);
            Dictionary<string, string> assignments = deckService.EnsureAssignments("d", StudyScopeIds.A1, new[] { "entry-1" });
            assignments["entry-1"] = SpellingDeckIds.Core(4);
            spelling.CurrentEntryIdByDictionaryScope["d"] = new Dictionary<string, string?>(StringComparer.OrdinalIgnoreCase)
            {
                [StudyScopeIds.A1] = "entry-1"
            };
            spelling.StatsByDictionaryScope["d"] = new Dictionary<string, Dictionary<string, SpellingStats>>(StringComparer.OrdinalIgnoreCase)
            {
                [StudyScopeIds.A1] = new Dictionary<string, SpellingStats>(StringComparer.OrdinalIgnoreCase)
                {
                    ["entry-1"] = new SpellingStats { Reviews = 4, Correct = 3, Wrong = 1, FirstTryCorrect = 2 }
                }
            };
            spellingStore.Save(spelling);

            string profile = Path.Combine(root, "profile.json");
            service.Export(app, spelling, profile);
            assignments["entry-1"] = SpellingDeckIds.Core(1);
            spelling.StatsByDictionaryScope["d"][StudyScopeIds.A1]["entry-1"].Wrong = 99;
            SpellingProfileImportResult result = service.Import(profile, app, spelling, new[] { "entry-1" }, new[] { "d" });
            Require(File.Exists(result.BackupPath), "Spelling profile import did not create a backup.");
            Require(spelling.DeckIdsByDictionaryScope["d"][StudyScopeIds.A1]["entry-1"] == SpellingDeckIds.Core(4), "Spelling profile did not restore deck assignment.");
            Require(spelling.StatsByDictionaryScope["d"][StudyScopeIds.A1]["entry-1"].Wrong == 1, "Spelling profile did not restore statistics.");

            string invalidPath = Path.Combine(root, "profile-invalid.json");
            File.WriteAllText(invalidPath, JsonSerializer.Serialize(new { ProfileSchemaVersion = 999 }));
            string beforeDeck = spelling.DeckIdsByDictionaryScope["d"][StudyScopeIds.A1]["entry-1"];
            bool invalidRejected = false;
            try { service.Import(invalidPath, app, spelling, new[] { "entry-1" }, new[] { "d" }); } catch (InvalidDataException) { invalidRejected = true; }
            Require(invalidRejected && spelling.DeckIdsByDictionaryScope["d"][StudyScopeIds.A1]["entry-1"] == beforeDeck,
                "Invalid profile changed Spelling state instead of failing closed.");
        }
        finally
        {
            try { if (Directory.Exists(root)) Directory.Delete(root, true); } catch { }
        }
    }

    private static void TestSpellingShortcutRegistry()
    {
        AppState app = AppStateStore.Normalize(new AppState());
        SpellingState spelling = SpellingStateStore.Normalize(new SpellingState());
        var manager = new ShortcutManager(app, spelling.Decks, ShortcutDispatchContext.Spelling);
        Require(manager.Definitions.Any(d => d.Id == ActionIds.OpenSpelling), "Open Spelling is missing from the configurable shortcut registry.");
        Require(manager.Definitions.Any(d => d.Id == ActionIds.SpellingShowAnswer), "Show spelling answer is missing from the configurable shortcut registry.");
        Require(manager.Definitions.Any(d => d.Id == ActionIds.SpellingSwitchDeck(SpellingDeckIds.Core(5))), "Core spelling deck switch shortcut is missing.");
        Require(manager.Definitions.Any(d => d.Id == ActionIds.SpellingMoveToDeck(SpellingDeckIds.Core(5))), "Core spelling move shortcut is missing.");
        Require(manager.Get(ActionIds.SpellingDeleteDeck) == (Keys.Control | Keys.Shift | Keys.Delete),
            "Spelling deck deletion default must be capturable by WordDeck and must not use Windows Ctrl+Alt+Delete.");
        Require(!manager.TrySet(ActionIds.SpellingDeleteDeck, Keys.Control | Keys.Alt | Keys.Delete, out string? secureAttentionError) &&
                !string.IsNullOrWhiteSpace(secureAttentionError),
            "Windows Ctrl+Alt+Delete secure-attention sequence was incorrectly accepted as a WordDeck shortcut.");

        Keys replacement = Keys.Control | Keys.Alt | Keys.Shift | Keys.F11;
        Require(manager.TrySet(ActionIds.SpellingShowAnswer, replacement, out string? error), $"Spelling shortcut could not be rebound: {error}");
        Require(manager.Get(ActionIds.SpellingShowAnswer) == replacement && manager.FindAction(replacement) == ActionIds.SpellingShowAnswer,
            "Rebound spelling shortcut did not dispatch through the shared shortcut manager in explicit Spelling context.");
        Require(!manager.TrySet(ActionIds.SpellingRepeatPrompt, replacement, out string? conflict) && !string.IsNullOrWhiteSpace(conflict),
            "Conflict checking did not reject a duplicate spelling shortcut.");

        var deckService = new SpellingDeckService(spelling);
        DeckDefinition custom = deckService.Create("Shortcut deck");
        manager.RefreshDeckDefinitions(spelling.Decks);
        Require(manager.Definitions.Any(d => d.Id == ActionIds.SpellingSwitchDeck(custom.Id)), "User-created spelling deck did not gain a stable switch action.");
        Require(manager.Get(ActionIds.SpellingSwitchDeck(custom.Id)) == Keys.None, "User-created spelling deck switch shortcut should start unassigned.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }
}
