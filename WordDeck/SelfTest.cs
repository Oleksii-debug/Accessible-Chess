namespace WordDeck;

internal static class SelfTest
{
    private const int Oxford3000BaselineCount = 3308;
    private const int Oxford5000BetaAdditionCount = ReviewedOxford5000Bootstrap.ExpectedCanonicalRows;

    public static int Run()
    {
        try
        {
            TestEmbeddedOxford();
            TestImportParserFailsClosed();
            TestBulkWordParser();
            TestLegacyDeckMigrationAndDynamicDeckOperations();
            TestShuffleBagForCoreAndUserDecks();
            TestShortcutRegistryAndRebinding();
            TestPronunciationAudioLayer();
            TestStatePersistenceAndRecovery();
            Console.WriteLine("WordDeck self-test passed: Oxford 5000 verified beta bridge, baseline-ID preservation, strict imports, pasted custom cards, dynamic decks, scoped shortcut registry, pronunciation paths, resume state, and recovery persistence validated.");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"WordDeck self-test FAILED: {ex}");
            return 1;
        }
    }

    private static void TestEmbeddedOxford()
    {
        DictionaryPackage baseline = DictionaryLoader.LoadEmbeddedOxford3000Baseline();
        DictionaryPackage package = DictionaryLoader.LoadEmbeddedOxford();

        Require(baseline.Entries.Count == Oxford3000BaselineCount, $"Expected {Oxford3000BaselineCount} baseline entries, got {baseline.Entries.Count}.");
        Require(package.Id == baseline.Id && package.Id == "oxford-3000-en-uk", $"Durable Oxford dictionary ID changed: {package.Id}.");
        Require(package.SourceLanguage.Equals("en", StringComparison.OrdinalIgnoreCase), "Source language must be en.");
        Require(package.TargetLanguage.Equals("uk", StringComparison.OrdinalIgnoreCase), "Target language must be uk.");
        Require(package.Entries.Count == Oxford3000BaselineCount + Oxford5000BetaAdditionCount,
            $"Expected {Oxford3000BaselineCount + Oxford5000BetaAdditionCount} production-shaped beta entries, got {package.Entries.Count}.");

        for (int i = 0; i < baseline.Entries.Count; i++)
        {
            DictionaryEntry before = baseline.Entries[i];
            DictionaryEntry after = package.Entries[i];
            Require(before.Id == after.Id && before.Level == after.Level && before.Source == after.Source && before.Target == after.Target,
                $"Existing Oxford 3000 row changed at index {i}: {before.Id}.");
        }

        IReadOnlyList<DictionaryEntry> additions = package.Entries.Skip(Oxford3000BaselineCount).ToArray();
        Require(additions.Count == Oxford5000BetaAdditionCount, "Canonical Oxford 5000 addition count changed.");
        Require(additions.All(entry => entry.Level is "B2" or "C1"), "Oxford 5000 additions contain a non-B2/C1 level.");
        Require(additions.Any(entry => entry.Level == "B2") && additions.Any(entry => entry.Level == "C1"), "Beta additions must exercise both B2 and C1 scopes.");
        Require(additions[0].Source == "abolish" && additions[0].Level == "C1", "Canonical beta does not start at abolish C1.");
        Require(additions.Any(entry => entry.Source == "blow" && entry.Level == "B2"), "Canonical beta lost the audited blow noun B2 row.");
        Require(additions.Take(additions.Count - 1).Any(entry => entry.Id == "ox5000-a2e2cc33789e9d3a823a" && entry.Source == "deployment" && entry.Level == "C1"),
            "Historical deployment noun C1 boundary is missing or was incorrectly treated as the global corpus tail.");
        Require(additions.Any(entry => entry.Source == "assumption" && entry.Level == "B2"), "Audited assumption noun B2 row is missing.");
        Require(additions.Any(entry => entry.Id == "ox5000-9db773c2d55fe19ff774" && entry.Source == "counter" && entry.Level == "C1"), "Activated counter verb C1 row is missing or has an unstable ID.");
        Require(additions.Any(entry => entry.Id == "ox5000-3696c35db49c6bca85da" && entry.Source == "crude" && entry.Level == "C1"), "Activated crude adjective C1 row is missing or has an unstable ID.");
        Require(additions.Any(entry => entry.Id == "ox5000-be649ccedfa00436941b" && entry.Source == "dam" && entry.Level == "C1"), "Activated dam noun C1 row is missing or has an unstable ID.");
        Require(additions.Any(entry => entry.Id == "ox5000-a2e2cc33789e9d3a823a" && entry.Source == "deployment" && entry.Level == "C1"), "Activated deployment noun C1 row is missing or has an unstable ID.");
        Require(additions.All(entry => entry.Id.StartsWith("ox5000-", StringComparison.Ordinal)), "Canonical additions must use stable ox5000 lexical IDs.");

        var actualCounts = package.Entries.GroupBy(entry => entry.Level, StringComparer.OrdinalIgnoreCase)
            .ToDictionary(group => group.Key, group => group.Count(), StringComparer.OrdinalIgnoreCase);
        Require(actualCounts.GetValueOrDefault("A1") == 900, "A1 baseline count changed.");
        Require(actualCounts.GetValueOrDefault("A2") == 872, "A2 baseline count changed.");
        Require(actualCounts.GetValueOrDefault("B1") == 809, "B1 baseline count changed.");
        Require(actualCounts.GetValueOrDefault("B2") > 727, "B2 scope did not gain verified Oxford 5000 additions.");
        Require(actualCounts.GetValueOrDefault("C1") > 0, "C1 scope is unexpectedly empty.");
        Require(actualCounts.Keys.All(level => level is "A1" or "A2" or "B1" or "B2" or "C1"), "Embedded Oxford package invented an unsupported CEFR scope.");

        Require(package.Entries.Select(entry => entry.Id).Distinct(StringComparer.OrdinalIgnoreCase).Count() == package.Entries.Count,
            "Duplicate entry IDs found.");
        Require(package.Entries.All(entry => !string.IsNullOrWhiteSpace(entry.Source) && !string.IsNullOrWhiteSpace(entry.Target)),
            "Blank source or translation found.");
    }

    private static void TestImportParserFailsClosed()
    {
        const string valid = "entryId\tlevel\tsource\ttarget\ncustom-1\tA1\thello\tпривіт";
        DictionaryPackage parsed = DictionaryLoader.Parse(valid);
        Require(parsed.Entries.Count == 1 && parsed.Entries[0].Source == "hello", "Valid TSV import did not parse correctly.");
        ExpectInvalid("entryId\tlevel\tsource\ttarget\ncustom-1\tA1\thello", "malformed row");
        ExpectInvalid("entryId\tlevel\tsource\ttarget\ncustom-1\tA1\t\tпривіт", "blank source");
        ExpectInvalid("entryId\tlevel\tsource\ttarget\ncustom-1\tA1\thello\t", "blank translation");
        ExpectInvalid("entryId\tlevel\tsource\ttarget\ncustom-1\tA1\thello\tпривіт\ncustom-1\tA1\thi\tвітаю", "duplicate entry id");
    }

    private static void TestBulkWordParser()
    {
        const string pasted = "apple\tяблуко\r\ntake care of | піклуватися про\r\nbook, книга\r\nlook after — доглядати за";
        IReadOnlyList<WordPair> pairs = BulkWordParser.Parse(pasted);
        Require(pairs.Count == 4, $"Expected four pasted cards, got {pairs.Count}.");
        Require(pairs[0] == new WordPair("apple", "яблуко"), "TAB-separated pair was parsed incorrectly.");
        Require(pairs[1] == new WordPair("take care of", "піклуватися про"), "Pipe-separated phrase was parsed incorrectly.");
        Require(pairs[2] == new WordPair("book", "книга"), "Comma-separated pair was parsed incorrectly.");
        Require(pairs[3] == new WordPair("look after", "доглядати за"), "Dash-separated pair was parsed incorrectly.");
        Require(BulkWordParser.Parse("apple\tяблуко\nAPPLE\tЯБЛУКО").Count == 1, "Duplicate pasted pairs were not deduplicated case-insensitively.");
        bool rejected = false;
        try { BulkWordParser.Parse("this line has no separator"); } catch (InvalidDataException) { rejected = true; }
        Require(rejected, "Ambiguous pasted text without a pair separator was accepted.");
    }

    private static void TestLegacyDeckMigrationAndDynamicDeckOperations()
    {
        const string dictionaryId = "oxford-3000-en-uk";
        var legacy = new AppState { ActiveDeck = 4 };
        legacy.DecksByDictionary[dictionaryId] = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase)
        {
            ["word-1"] = 3,
            ["word-2"] = 5
        };
        legacy.Shortcuts[ActionIds.LegacySwitchDeck(3)] = (Keys.Control | Keys.Shift | Keys.D3).ToString();
        legacy.Shortcuts[ActionIds.LegacyMoveToDeck(5)] = (Keys.Alt | Keys.Shift | Keys.D5).ToString();

        AppState migrated = AppStateStore.Normalize(legacy);
        Require(migrated.Decks.Count == 5 && migrated.Decks.All(deck => deck.IsCore), "Five permanent core decks were not preserved during migration.");
        Require(migrated.ActiveDeckId == DeckIds.Core(4), "Legacy active deck did not migrate to its stable core ID.");
        Require(migrated.DeckIdsByDictionary[dictionaryId]["word-1"] == DeckIds.Core(3), "Legacy deck 3 assignment was lost.");
        Require(migrated.DeckIdsByDictionary[dictionaryId]["word-2"] == DeckIds.Core(5), "Legacy deck 5 assignment was lost.");
        Require(migrated.Shortcuts[ActionIds.SwitchDeck(DeckIds.Core(3))] == (Keys.Control | Keys.Shift | Keys.D3).ToString(), "Legacy switch shortcut did not migrate.");
        Require(migrated.Shortcuts[ActionIds.MoveToDeck(DeckIds.Core(5))] == (Keys.Alt | Keys.Shift | Keys.D5).ToString(), "Legacy move shortcut did not migrate.");

        var service = new DeckService(migrated);
        service.Rename(DeckIds.Core(1), "New words");
        DeckDefinition custom = service.Create("Phrasal verbs");
        Require(!custom.IsCore && service.CountEverywhere(custom.Id) == 0, "New user deck was not created empty.");
        Dictionary<string, string> map = service.EnsureDictionaryAssignments(dictionaryId, new[] { "word-1", "word-2", "word-3" });
        Require(map["word-1"] == DeckIds.Core(3) && map["word-2"] == DeckIds.Core(5), "Existing migrated assignments changed.");
        Require(map["word-3"] == DeckIds.Core(1), "New entry did not initialize in deck 1.");
        map["word-3"] = custom.Id;
        service.Rename(custom.Id, "Review later");
        string stableId = custom.Id;
        Require(service.Move(custom.Id, -1) && service.Find(stableId)?.Name == "Review later", "User deck stable identity broke after rename/reorder.");
        bool unsafeDeleteRejected = false;
        try { service.DeleteUserDeck(custom.Id, null); } catch (InvalidOperationException) { unsafeDeleteRejected = true; }
        Require(unsafeDeleteRejected && service.Find(custom.Id) is not null, "Non-empty user deck deletion was not fail-closed.");
        service.DeleteUserDeck(custom.Id, DeckIds.Core(2));
        Require(service.Find(custom.Id) is null && map["word-3"] == DeckIds.Core(2), "Safe user-deck deletion did not move assigned words.");
    }

    private static void TestShuffleBagForCoreAndUserDecks()
    {
        var decks = new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase)
        {
            [DeckIds.Core(1)] = new[] { "a", "b", "c", "d", "e" },
            [DeckIds.Core(5)] = new[] { "f", "g", "h" },
            ["user-test"] = new[] { "i", "j", "k", "l" }
        };
        int seed = 100;
        foreach ((string deckId, string[] ids) in decks)
        {
            Queue<string> bag = ShuffleBag.Create(ids, new Random(seed++), ids[0]);
            string[] drawn = bag.ToArray();
            Require(drawn.Length == ids.Length && drawn.Distinct(StringComparer.OrdinalIgnoreCase).Count() == ids.Length, $"Shuffle bag repeated/lost entries for {deckId}.");
            Require(new HashSet<string>(drawn, StringComparer.OrdinalIgnoreCase).SetEquals(ids), $"Shuffle bag invented entries for {deckId}.");
            if (ids.Length > 1) Require(!string.Equals(drawn[0], ids[0], StringComparison.OrdinalIgnoreCase), $"Shuffle refill immediately repeated the previous card in {deckId}.");
        }
    }

    private static void TestShortcutRegistryAndRebinding()
    {
        var state = AppStateStore.Normalize(new AppState());
        var manager = new ShortcutManager(state);
        Require(manager.Definitions.Count == 33, $"Expected 33 Recall/scope/core-deck actions, got {manager.Definitions.Count}.");
        Require(manager.Definitions.Select(def => def.Id).Distinct(StringComparer.OrdinalIgnoreCase).Count() == manager.Definitions.Count, "Shortcut action IDs must be unique.");
        Require(manager.Definitions.Where(def => def.DefaultKeys != Keys.None).Select(def => def.DefaultKeys).Distinct().Count() == manager.Definitions.Count(def => def.DefaultKeys != Keys.None), "Assigned default shortcuts must be unique.");
        foreach (string scopeId in StudyScopeIds.Ordered)
        {
            string actionId = ActionIds.SwitchStudyScope(scopeId);
            Require(manager.Definitions.Any(def => def.Id == actionId), $"Missing stable scope action {actionId}.");
            Require(manager.Get(actionId) == Keys.None, "Scope actions must start unassigned.");
        }
        Require(manager.Get(ActionIds.NextWord) == Keys.Down, "Down Arrow must be the primary Recall next-card key.");
        Require(manager.Get(ActionIds.PreviousWord) == Keys.Up, "Up Arrow must be the primary true previous-card key.");
        Require(manager.FindAction(Keys.Down) == ActionIds.NextWord && manager.FindAction(Keys.Up) == ActionIds.PreviousWord,
            "Recall Up/Down dispatch does not preserve distinct next/previous actions.");
        Require(!manager.TrySet(ActionIds.SaveProgress, Keys.Left, out _), "Unmodified Left Arrow must remain standard caret/text navigation.");
        Require(!manager.TrySet(ActionIds.SaveProgress, Keys.Right, out _), "Unmodified Right Arrow must remain standard caret/text navigation.");
        Require(manager.Get(ActionIds.SaveProgress) == (Keys.Control | Keys.S), "Ctrl+S save default changed.");
        Require(manager.Get(ActionIds.AddWords) == (Keys.Control | Keys.Shift | Keys.A), "Bulk-add default changed.");
        Require(ShortcutFormatter.Format(Keys.Control | Keys.Shift | Keys.B) == "Ctrl+Shift+B", "Shared shortcut formatter regression.");

        string a1Action = ActionIds.SwitchStudyScope(StudyScopeIds.A1);
        Require(manager.TrySet(a1Action, Keys.Control | Keys.Alt | Keys.F8, out string? scopeError), $"Could not bind scope shortcut: {scopeError}");
        Require(manager.FindAction(Keys.Control | Keys.Alt | Keys.F8) == a1Action, "Rebound scope shortcut did not dispatch.");
        Require(!manager.TrySet(ActionIds.SwitchStudyScope(StudyScopeIds.A2), Keys.Control | Keys.Alt | Keys.F8, out string? conflict) && !string.IsNullOrWhiteSpace(conflict), "Scope shortcut conflict was accepted.");
        Require(!manager.TrySet(ActionIds.SaveProgress, Keys.Alt | Keys.F4, out _), "Unsafe Alt+F4 shortcut was accepted.");
        Require(!manager.TrySet(ActionIds.SaveProgress, Keys.Control | Keys.Alt | Keys.Delete, out _), "Unsafe Ctrl+Alt+Delete shortcut was accepted.");

        var service = new DeckService(state);
        DeckDefinition userDeck = service.Create("Custom study");
        manager.RefreshDeckDefinitions();
        Require(manager.Definitions.Count == 35, "Creating a Recall user deck did not add switch/move actions.");
        string switchAction = ActionIds.SwitchDeck(userDeck.Id);
        string moveAction = ActionIds.MoveToDeck(userDeck.Id);
        Require(manager.Get(switchAction) == Keys.None && manager.Get(moveAction) == Keys.None, "User-deck shortcuts must start unassigned.");
        Require(manager.TrySet(switchAction, Keys.Control | Keys.Alt | Keys.F10, out _), "Could not bind user-deck switch shortcut.");
        service.Rename(userDeck.Id, "Renamed custom study");
        service.Move(userDeck.Id, -1);
        manager.RefreshDeckDefinitions();
        Require(manager.Get(switchAction) == (Keys.Control | Keys.Alt | Keys.F10), "Stable user-deck shortcut broke after rename/reorder.");
        service.DeleteUserDeck(userDeck.Id, null);
        manager.RefreshDeckDefinitions();
        Require(!manager.Definitions.Any(def => def.Id == switchAction || def.Id == moveAction), "Deleted user deck left orphaned shortcut actions.");
    }

    private static void TestPronunciationAudioLayer()
    {
        IReadOnlyList<string> paths = PronunciationAudio.CandidatePaths("oxford-3000-en-uk", "oxford-a1-0001");
        Require(paths.Count == 2, $"Expected portable and local audio-pack paths, got {paths.Count}.");
        string expectedTail = Path.Combine("oxford-3000-en-uk", "oxford-a1-0001.mp3");
        Require(paths.All(path => path.EndsWith(expectedTail, StringComparison.OrdinalIgnoreCase)), "Pronunciation paths are not keyed by stable IDs.");
        IReadOnlyList<string> sanitized = PronunciationAudio.CandidatePaths("custom dictionary/uk", "entry 1");
        Require(sanitized.All(path => path.Contains("custom_dictionary_uk", StringComparison.OrdinalIgnoreCase)), "Unsafe dictionary ID characters were not sanitized.");
        Require(sanitized.All(path => path.EndsWith(Path.Combine("custom_dictionary_uk", "entry_1.mp3"), StringComparison.OrdinalIgnoreCase)), "Unsafe entry ID characters were not sanitized.");
        using var audio = new PronunciationAudio();
        var package = new DictionaryPackage { Id = "self-test-dictionary", Name = "Self test", SourceLanguage = "en", TargetLanguage = "uk", Entries = Array.Empty<DictionaryEntry>() };
        var missingEntry = new DictionaryEntry("definitely-missing-self-test-audio", "A1", "missing", "відсутній");
        Require(!audio.TryPlay(package, missingEntry, out string? missingError) && missingError?.Contains("not installed", StringComparison.OrdinalIgnoreCase) == true,
            "Missing local pronunciation did not return a readable non-crashing status.");
    }

    private static void TestStatePersistenceAndRecovery()
    {
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck-self-test-{Guid.NewGuid():N}");
        try
        {
            const string dictionaryId = "oxford-3000-en-uk";
            var store = new AppStateStore(root);
            var state = AppStateStore.Normalize(new AppState { ActiveDictionaryId = dictionaryId, AutoPlayPronunciationOnCardChange = true });
            var service = new DeckService(state);
            service.Rename(DeckIds.Core(1), "Inbox words");
            DeckDefinition custom = service.Create("Persistent custom");
            state.ActiveDeckId = custom.Id;
            state.DeckIdsByDictionary[dictionaryId] = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                ["oxford-a1-0001"] = DeckIds.Core(3),
                ["oxford-a1-0002"] = custom.Id,
                ["custom-test-1"] = custom.Id
            };
            state.CustomEntriesByDictionary[dictionaryId] = new List<CustomEntryRecord> { new("custom-test-1", "useful phrase", "корисна фраза") };
            state.CurrentEntryIdByDictionary[dictionaryId] = "custom-test-1";
            var shortcuts = new ShortcutManager(state);
            Keys persistedShortcut = Keys.Control | Keys.Shift | Keys.Z;
            Require(shortcuts.TrySet(ActionIds.RevealTranslation, persistedShortcut, out _), "Could not prepare persisted shortcut.");
            store.Save(state);

            AppState reloaded = new AppStateStore(root).Load();
            Require(reloaded.ActiveDictionaryId == dictionaryId && reloaded.ActiveDeckId == custom.Id, "Active dictionary/deck did not survive restart.");
            Require(reloaded.Decks.Any(deck => deck.Id == custom.Id && deck.Name == "Persistent custom" && !deck.IsCore), "User-created deck did not survive restart.");
            Require(reloaded.DeckIdsByDictionary[dictionaryId]["oxford-a1-0001"] == DeckIds.Core(3), "Core assignment did not survive restart.");
            Require(reloaded.DeckIdsByDictionary[dictionaryId]["oxford-a1-0002"] == custom.Id, "User-deck assignment did not survive restart.");
            Require(reloaded.CustomEntriesByDictionary[dictionaryId].Single().Source == "useful phrase", "User-added card did not survive restart.");
            Require(reloaded.CurrentEntryIdByDictionary[dictionaryId] == "custom-test-1", "Current card did not survive restart.");
            Require(new ShortcutManager(reloaded).Get(ActionIds.RevealTranslation) == persistedShortcut, "Rebound shortcut did not survive restart.");

            reloaded.ActiveDeckId = DeckIds.Core(2);
            reloaded.DeckIdsByDictionary[dictionaryId]["oxford-a1-0001"] = DeckIds.Core(5);
            store.Save(reloaded);
            File.WriteAllText(Path.Combine(root, "state.json"), "{ definitely not valid json");
            AppState recovered = new AppStateStore(root).Load();
            Require(recovered.ActiveDeckId == custom.Id, "Backup recovery did not restore last known-good active deck.");
            Require(recovered.DeckIdsByDictionary[dictionaryId]["oxford-a1-0001"] == DeckIds.Core(3), "Backup recovery did not restore last known-good assignment.");
            Require(recovered.CurrentEntryIdByDictionary[dictionaryId] == "custom-test-1", "Backup recovery did not restore current card.");
        }
        finally
        {
            try { if (Directory.Exists(root)) Directory.Delete(root, true); } catch { }
        }
    }

    private static void ExpectInvalid(string text, string description)
    {
        try { DictionaryLoader.Parse(text); }
        catch (InvalidDataException) { return; }
        throw new InvalidDataException($"Parser accepted invalid dictionary: {description}.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }
}