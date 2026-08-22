using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Text.Json;

namespace WordDeck;

internal static class SpellingR2HardeningSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (!Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            return;
        SpellingR2HardeningSelfTest.Run();
    }
}

internal static class SpellingR2HardeningSelfTest
{
    public static void Run()
    {
        TestCanonicalShortcutHardeningWasPreserved();
        TestCompleteCorpusSpellingScopesAndIsolation();
        TestExactMatcherMatrix();
        TestDeterministicCoachStress();
        TestPopulatedStateStressRoundTrip();
        TestProfileCorpusMismatchFailsBeforeMutation();
        Console.WriteLine("WordDeck R2 Spelling hardening passed: canonical shortcut conflict safety, 5446 scope coverage, exact matcher matrix, 500 Coach decisions, 100 scope/deck cycles, populated persistence and incompatible-profile fail-closed behavior verified.");
    }

    private static void TestCanonicalShortcutHardeningWasPreserved()
    {
        AppState app = AppStateStore.Normalize(new AppState());
        SpellingState spelling = SpellingStateStore.Normalize(new SpellingState());
        var manager = new ShortcutManager(app, spelling.Decks);

        Require(ShortcutFormatter.Format(Keys.Control | Keys.OemQuestion) == "Ctrl+/", "Canonical human-readable Ctrl+/ formatting regressed.");
        Require(ShortcutFormatter.Format(Keys.Shift | Keys.Back) == "Shift+Backspace", "Canonical human-readable Backspace formatting regressed.");

        Keys duplicate = Keys.Control | Keys.Alt | Keys.F10;
        app.Shortcuts[ActionIds.SpellingShowAnswer] = duplicate.ToString();
        app.Shortcuts[ActionIds.SpellingRepeatPrompt] = duplicate.ToString();
        Require(manager.Get(ActionIds.SpellingShowAnswer) == Keys.None, "Imported duplicate Spelling binding did not fail closed for Show Answer.");
        Require(manager.Get(ActionIds.SpellingRepeatPrompt) == Keys.None, "Imported duplicate Spelling binding did not fail closed for Repeat Prompt.");
        Require(manager.FindAction(duplicate) is null, "Ambiguous imported binding still dispatched an action.");

        Require(!manager.TrySet(ActionIds.SpellingDeleteDeck, Keys.Control | Keys.Alt | Keys.Delete, out _), "Ctrl+Alt+Delete was accepted as a Spelling shortcut.");
        Require(!manager.TrySet(ActionIds.SpellingShowAnswer, Keys.Alt | Keys.F4, out _), "Alt+F4 was accepted as a rebind and could block standard close behavior.");
    }

    private static void TestCompleteCorpusSpellingScopesAndIsolation()
    {
        DictionaryPackage package = DictionaryLoader.LoadEmbeddedOxford();
        Require(package.Entries.Count == 5446, $"Expected 5446 canonical entries, got {package.Entries.Count}.");

        SpellingState state = SpellingStateStore.Normalize(new SpellingState());
        var decks = new SpellingDeckService(state);
        var expected = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase)
        {
            [StudyScopeIds.All] = 5446,
            [StudyScopeIds.A1] = 900,
            [StudyScopeIds.A2] = 872,
            [StudyScopeIds.B1] = 809,
            [StudyScopeIds.B2] = 1461,
            [StudyScopeIds.C1] = 1404,
        };

        foreach ((string scopeId, int expectedCount) in expected)
        {
            string[] ids = package.Entries.Where(entry => StudyScopeIds.Includes(scopeId, entry)).Select(entry => entry.Id).ToArray();
            Dictionary<string, string> map = decks.EnsureAssignments(package.Id, scopeId, ids);
            Require(ids.Length == expectedCount, $"Corpus scope {scopeId} expected {expectedCount}, got {ids.Length}.");
            Require(ids.All(map.ContainsKey), $"Spelling scope {scopeId} did not initialize every canonical entry.");
            Require(ids.All(id => map[id] == SpellingDeckIds.Core(1)), $"Fresh Spelling scope {scopeId} did not initialize in core deck 1.");
        }

        DictionaryEntry b2 = package.Entries.First(entry => entry.Level.Equals("B2", StringComparison.OrdinalIgnoreCase));
        Dictionary<string, string> all = decks.EnsureAssignments(package.Id, StudyScopeIds.All, package.Entries.Select(entry => entry.Id));
        Dictionary<string, string> b2Map = decks.EnsureAssignments(package.Id, StudyScopeIds.B2, package.Entries.Where(entry => entry.Level.Equals("B2", StringComparison.OrdinalIgnoreCase)).Select(entry => entry.Id));
        b2Map[b2.Id] = SpellingDeckIds.Core(5);
        Require(all[b2.Id] == SpellingDeckIds.Core(1), "A B2-only Spelling move leaked into All scope.");

        var app = AppStateStore.Normalize(new AppState());
        app.HiddenEntryIds.Add(b2.Id);
        Require(UserProgressService.IsHidden(app, b2.Id), "Shared hide overlay is unavailable to Spelling.");
        Require(package.Entries.Count == 5446, "Hiding a study word mutated the canonical dictionary.");
    }

    private static void TestExactMatcherMatrix()
    {
        (string Typed, string Expected, bool Accepted)[] cases =
        {
            ("word", "word", true),
            ("  word  ", "word", true),
            ("O’Neill", "O'Neill", true),
            ("well‑being", "well-being", true),
            ("cafe\u0301", "café", true),
            ("credit card", "credit card", true),
            ("Word", "word", false),
            ("cooperate", "co-operate", false),
            ("credit  card", "credit card", false),
            ("can't", "cant", false),
            ("organise", "organize", false),
            ("word!", "word", false),
        };
        foreach ((string typed, string expected, bool accepted) in cases)
            Require(SpellingAnswerComparer.IsCorrect(typed, expected) == accepted, $"Exact Spelling matcher policy changed for [{typed}] vs [{expected}].");
    }

    private static void TestDeterministicCoachStress()
    {
        var scheduler = new ConservativeSpellingScheduler();
        var stats = new SpellingEntryStats();
        var stopwatch = Stopwatch.StartNew();

        for (int review = 1; review <= 500; review++)
        {
            bool clean = review % 7 != 0;
            stats.CompletedReviews++;
            if (clean) stats.FirstTrySuccesses++;
            stats.CurrentStreak = clean ? stats.CurrentStreak + 1 : 0;
            stats.RecentOutcomes.Add(clean);
            if (stats.RecentOutcomes.Count > 10) stats.RecentOutcomes.RemoveAt(0);

            string deck = SpellingDeckIds.Core(Math.Min(5, 1 + review / 120));
            SpellingScheduleDecision first = scheduler.Decide(deck, stats, clean, usedHint: false);
            SpellingScheduleDecision second = scheduler.Decide(deck, stats, clean, usedHint: false);
            Require(first == second, $"Coach decision was not deterministic at review {review}.");
            Require(first.TargetDeckId is null || SpellingDeckIds.CoreDecks.Contains(first.TargetDeckId, StringComparer.OrdinalIgnoreCase), "Coach targeted a non-core deck automatically.");
            Require(!string.IsNullOrWhiteSpace(first.Explanation), "Coach emitted an unexplained decision.");
        }

        SpellingScheduleDecision userDeck = scheduler.Decide("spelling-user-r2", stats, firstTryCorrect: true, usedHint: false);
        Require(userDeck.TargetDeckId is null, "Coach automatically redistributed a user-created deck during stress testing.");
        stopwatch.Stop();
        Console.WriteLine($"R2 Coach stress: 500 deterministic decisions completed in {stopwatch.ElapsedMilliseconds} ms.");
    }

    private static void TestPopulatedStateStressRoundTrip()
    {
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck-r2-spelling-stress-{Guid.NewGuid():N}");
        try
        {
            DictionaryPackage package = DictionaryLoader.LoadEmbeddedOxford();
            var store = new SpellingStateStore(root);
            SpellingState state = store.Load();
            var decks = new SpellingDeckService(state);
            DeckDefinition custom = decks.Create("R2 stress deck");

            foreach (string scopeId in StudyScopeIds.Ordered)
            {
                string[] ids = package.Entries.Where(entry => StudyScopeIds.Includes(scopeId, entry)).Select(entry => entry.Id).ToArray();
                Dictionary<string, string> map = decks.EnsureAssignments(package.Id, scopeId, ids);
                for (int i = 0; i < ids.Length; i += 137)
                    map[ids[i]] = i % 2 == 0 ? custom.Id : SpellingDeckIds.Core(4);
                if (ids.Length > 0)
                {
                    if (!state.CurrentEntryIdsByDictionaryScope.TryGetValue(package.Id, out Dictionary<string, string>? current))
                    {
                        current = new(StringComparer.OrdinalIgnoreCase);
                        state.CurrentEntryIdsByDictionaryScope[package.Id] = current;
                    }
                    current[scopeId] = ids[^1];
                }
            }

            var stats = new Dictionary<string, SpellingEntryStats>(StringComparer.OrdinalIgnoreCase);
            foreach (DictionaryEntry entry in package.Entries.Take(1500))
                stats[entry.Id] = new SpellingEntryStats { CompletedReviews = 12, FirstTrySuccesses = 9, WrongAttempts = 3, CurrentStreak = 2, RecentOutcomes = new List<bool> { true, false, true, true, true, false, true, true, true, true } };
            state.StatsByDictionary[package.Id] = stats;

            for (int i = 0; i < 100; i++)
                state.ActiveScopeIdByDictionary[package.Id] = StudyScopeIds.Ordered[i % StudyScopeIds.Ordered.Count];
            state.ActiveScopeIdByDictionary[package.Id] = StudyScopeIds.C1;
            store.Save(state);

            SpellingState restored = new SpellingStateStore(root).Load();
            Require(restored.ActiveScopeIdByDictionary[package.Id] == StudyScopeIds.C1, "Active Spelling scope did not survive populated restart.");
            Require(restored.StatsByDictionary[package.Id].Count == 1500, "Populated Spelling statistics were lost on restart.");
            Require(restored.Decks.Any(deck => deck.Id == custom.Id), "User-created Spelling deck was lost on restart.");
            foreach (string scopeId in StudyScopeIds.Ordered)
                Require(restored.DeckIdsByDictionaryScope[package.Id].ContainsKey(scopeId), $"Populated scope {scopeId} was lost on restart.");
        }
        finally
        {
            try { if (Directory.Exists(root)) Directory.Delete(root, true); } catch { }
        }
    }

    private static void TestProfileCorpusMismatchFailsBeforeMutation()
    {
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck-r2-profile-{Guid.NewGuid():N}");
        try
        {
            Directory.CreateDirectory(root);
            var appStore = new AppStateStore(root);
            var spellingStore = new SpellingStateStore(root);
            var service = new SpellingProfileService(appStore, spellingStore);
            AppState app = AppStateStore.Normalize(new AppState { ActiveDictionaryId = "d" });
            SpellingState spelling = SpellingStateStore.Normalize(new SpellingState());
            Dictionary<string, string> map = new SpellingDeckService(spelling).EnsureAssignments("d", StudyScopeIds.All, new[] { "entry-1" });
            map["entry-1"] = SpellingDeckIds.Core(4);
            appStore.Save(app);
            spellingStore.Save(spelling);

            var jsonOptions = new JsonSerializerOptions { WriteIndented = true };
            string legacy = Path.Combine(root, "legacy-mismatch.json");
            var legacyProfile = new WordDeckProfile
            {
                ProfileSchemaVersion = AppStateStore.ProfileSchemaVersion,
                StateSchemaVersion = AppStateStore.CurrentSchemaVersion,
                SourceAppVersion = AppStateStore.SourceAppVersion,
                CorpusIdentity = "incompatible-corpus-r2",
                ExportedAtUtc = DateTimeOffset.UtcNow,
                State = AppStateStore.Normalize(new AppState { ActiveDictionaryId = "d" })
            };
            File.WriteAllText(legacy, JsonSerializer.Serialize(legacyProfile, jsonOptions));

            bool rejected = false;
            try { service.Import(legacy, app, spelling, new[] { "entry-1" }, new[] { "d" }); }
            catch (InvalidDataException) { rejected = true; }
            Require(rejected, "Legacy incompatible-corpus profile was accepted.");
            Require(map["entry-1"] == SpellingDeckIds.Core(4), "Rejected incompatible legacy profile mutated Spelling state.");

            string v2 = Path.Combine(root, "v2-mismatch.json");
            var v2Profile = new WordDeckCombinedProfile
            {
                ProfileSchemaVersion = SpellingProfileService.CurrentProfileSchemaVersion,
                StateSchemaVersion = AppStateStore.CurrentSchemaVersion,
                SpellingSchemaVersion = SpellingStateStore.CurrentSchemaVersion,
                SourceAppVersion = AppStateStore.SourceAppVersion,
                CorpusIdentity = "incompatible-corpus-r2",
                ExportedAtUtc = DateTimeOffset.UtcNow,
                State = AppStateStore.Normalize(new AppState { ActiveDictionaryId = "d" }),
                SpellingState = SpellingStateStore.Clone(spelling)
            };
            File.WriteAllText(v2, JsonSerializer.Serialize(v2Profile, jsonOptions));
            rejected = false;
            try { service.Import(v2, app, spelling, new[] { "entry-1" }, new[] { "d" }); }
            catch (InvalidDataException) { rejected = true; }
            Require(rejected, "V2 incompatible-corpus profile was accepted.");
            Require(map["entry-1"] == SpellingDeckIds.Core(4), "Rejected incompatible V2 profile mutated Spelling state.");
        }
        finally
        {
            try { if (Directory.Exists(root)) Directory.Delete(root, true); } catch { }
        }
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }
}
