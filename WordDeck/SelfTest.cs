namespace WordDeck;

internal static class SelfTest
{
    private static readonly IReadOnlyDictionary<string, int> ExpectedLevelCounts =
        new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase)
        {
            ["A1"] = 900,
            ["A2"] = 872,
            ["B1"] = 809,
            ["B2"] = 727
        };

    public static int Run()
    {
        try
        {
            TestEmbeddedOxford();
            TestImportParserFailsClosed();
            TestLegacyDeckMigrationAndDynamicDeckOperations();
            TestShuffleBagForCoreAndUserDecks();
            TestShortcutRegistryAndRebinding();
            TestPronunciationAudioLayer();
            TestStatePersistenceAndRecovery();
            Console.WriteLine("WordDeck self-test passed: Oxford dictionary, strict imports, lossless dynamic-deck migration, random shuffle bags, per-deck shortcuts, optional pronunciation controls, and persistent recovery state validated.");
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
        DictionaryPackage package = DictionaryLoader.LoadEmbeddedOxford();
        Require(package.Id == "oxford-3000-en-uk", $"Unexpected dictionary id: {package.Id}");
        Require(package.SourceLanguage.Equals("en", StringComparison.OrdinalIgnoreCase), "Source language must be en.");
        Require(package.TargetLanguage.Equals("uk", StringComparison.OrdinalIgnoreCase), "Target language must be uk.");
        Require(package.Entries.Count == 3308, $"Expected 3308 entries, got {package.Entries.Count}.");

        var actualCounts = package.Entries
            .GroupBy(entry => entry.Level, StringComparer.OrdinalIgnoreCase)
            .ToDictionary(group => group.Key, group => group.Count(), StringComparer.OrdinalIgnoreCase);

        foreach ((string level, int expected) in ExpectedLevelCounts)
        {
            int actual = actualCounts.GetValueOrDefault(level);
            Require(actual == expected, $"Expected {expected} {level} entries, got {actual}.");
        }

        Require(actualCounts.Count == ExpectedLevelCounts.Count, "Unexpected CEFR levels found in embedded dictionary.");
        Require(package.Entries.Select(entry => entry.Id).Distinct(StringComparer.OrdinalIgnoreCase).Count() == package.Entries.Count,
            "Duplicate entry IDs found.");
        Require(package.Entries.All(entry => !string.IsNullOrWhiteSpace(entry.Source) && !string.IsNullOrWhiteSpace(entry.Target)),
            "Blank source or translation found.");

        DictionaryEntry first = package.Entries[0];
        DictionaryEntry last = package.Entries[^1];
        Require(first.Id == "oxford-a1-0001" && first.Source == "a, an", "Unexpected first Oxford entry.");
        Require(last.Id == "oxford-b2-0727" && last.Source == "zone", "Unexpected last Oxford entry.");
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

    private static void TestLegacyDeckMigrationAndDynamicDeckOperations()
    {
        const string dictionaryId = "oxford-3000-en-uk";
        var legacy = new AppState
        {
            ActiveDeck = 4
        };
        legacy.DecksByDictionary[dictionaryId] = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase)
        {
            ["word-1"] = 3,
            ["word-2"] = 5
        };
        legacy.Shortcuts[ActionIds.LegacySwitchDeck(3)] = (Keys.Control | Keys.Shift | Keys.D3).ToString();
        legacy.Shortcuts[ActionIds.LegacyMoveToDeck(5)] = (Keys.Alt | Keys.Shift | Keys.D5).ToString();

        AppState migrated = AppStateStore.Normalize(legacy);
        Require(migrated.Decks.Count == 5, $"Expected five permanent core decks after migration, got {migrated.Decks.Count}.");
        Require(migrated.Decks.All(deck => deck.IsCore), "Migrated default decks must be permanent core decks.");
        Require(migrated.ActiveDeckId == DeckIds.Core(4), "Legacy active deck did not migrate to its stable core ID.");
        Require(migrated.DeckIdsByDictionary[dictionaryId]["word-1"] == DeckIds.Core(3), "Legacy deck 3 assignment was lost during migration.");
        Require(migrated.DeckIdsByDictionary[dictionaryId]["word-2"] == DeckIds.Core(5), "Legacy deck 5 assignment was lost during migration.");
        Require(migrated.Shortcuts[ActionIds.SwitchDeck(DeckIds.Core(3))] == (Keys.Control | Keys.Shift | Keys.D3).ToString(),
            "Legacy customized switch shortcut did not migrate to stable deck ID ownership.");
        Require(migrated.Shortcuts[ActionIds.MoveToDeck(DeckIds.Core(5))] == (Keys.Alt | Keys.Shift | Keys.D5).ToString(),
            "Legacy customized move shortcut did not migrate to stable deck ID ownership.");

        var service = new DeckService(migrated);
        service.Rename(DeckIds.Core(1), "New words");
        Require(service.Find(DeckIds.Core(1))?.Name == "New words", "Permanent core deck could not be renamed.");

        DeckDefinition custom = service.Create("Phrasal verbs");
        Require(!custom.IsCore, "User-created deck was incorrectly marked core.");
        Require(service.CountEverywhere(custom.Id) == 0, "A newly created deck must start empty.");

        Dictionary<string, string> map = service.EnsureDictionaryAssignments(dictionaryId, new[] { "word-1", "word-2", "word-3" });
        Require(map["word-1"] == DeckIds.Core(3) && map["word-2"] == DeckIds.Core(5), "Existing migrated assignments changed while reconciling dictionary entries.");
        Require(map["word-3"] == DeckIds.Core(1), "A new dictionary entry did not start in the first/default deck.");

        map["word-3"] = custom.Id;
        Require(service.CountInDictionary(dictionaryId, custom.Id) == 1, "User deck membership count is incorrect.");
        service.Rename(custom.Id, "Review later");
        string stableId = custom.Id;
        Require(service.Move(custom.Id, -1), "User deck could not be reordered.");
        Require(service.Find(stableId)?.Name == "Review later", "Deck rename/reorder changed its stable ID.");

        bool rejectedUnsafeDelete = false;
        try
        {
            service.DeleteUserDeck(custom.Id, null);
        }
        catch (InvalidOperationException)
        {
            rejectedUnsafeDelete = true;
        }
        Require(rejectedUnsafeDelete, "Deleting a non-empty user deck without a destination was allowed.");
        Require(service.Find(custom.Id) is not null && map["word-3"] == custom.Id,
            "Cancelled/rejected non-empty deletion lost the deck or its word.");

        service.DeleteUserDeck(custom.Id, DeckIds.Core(2));
        Require(service.Find(custom.Id) is null, "User-created deck was not deleted after a valid destination was provided.");
        Require(map["word-3"] == DeckIds.Core(2), "Deleting a non-empty deck did not move all words to the selected destination.");

        bool coreDeleteRejected = false;
        try
        {
            service.DeleteUserDeck(DeckIds.Core(1), DeckIds.Core(2));
        }
        catch (InvalidOperationException)
        {
            coreDeleteRejected = true;
        }
        Require(coreDeleteRejected, "A permanent core deck was allowed to be deleted.");
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
            Require(drawn.Length == ids.Length, $"Shuffle bag length changed for {deckId}.");
            Require(drawn.Distinct(StringComparer.OrdinalIgnoreCase).Count() == ids.Length,
                $"Shuffle bag repeated a word before exhaustion for {deckId}.");
            Require(new HashSet<string>(drawn, StringComparer.OrdinalIgnoreCase).SetEquals(ids),
                $"Shuffle bag lost or invented a word for {deckId}.");
            if (ids.Length > 1)
                Require(!string.Equals(drawn[0], ids[0], StringComparison.OrdinalIgnoreCase),
                    $"Shuffle-bag refill immediately repeated the just-shown card in {deckId}.");
        }

        Queue<string> single = ShuffleBag.Create(new[] { "only" }, new Random(1), "only");
        Require(single.Count == 1 && single.Peek() == "only", "Single-word deck did not preserve its unavoidable repeat behavior.");
    }

    private static void TestShortcutRegistryAndRebinding()
    {
        var state = AppStateStore.Normalize(new AppState());
        var manager = new ShortcutManager(state);
        IReadOnlyList<ShortcutDefinition> definitions = manager.Definitions;
        Require(definitions.Count == 19, $"Expected 19 actions with five core deck switch/move pairs, got {definitions.Count}.");
        Require(definitions.Any(def => def.Id == ActionIds.UndoMove), "Undo last deck move is missing from configurable shortcuts.");
        Require(definitions.Any(def => def.Id == ActionIds.PlayPronunciation), "Manual generated pronunciation is missing from configurable shortcuts.");
        Require(definitions.Any(def => def.Id == ActionIds.ToggleAutoPronunciation), "Automatic pronunciation toggle is missing from configurable shortcuts.");
        Require(definitions.Select(def => def.Id).Distinct(StringComparer.OrdinalIgnoreCase).Count() == definitions.Count,
            "Shortcut action IDs must be unique.");
        Require(definitions.Where(def => def.DefaultKeys != Keys.None).Select(def => def.DefaultKeys).Distinct().Count() == definitions.Count(def => def.DefaultKeys != Keys.None),
            "Assigned default shortcuts must be unique.");

        Keys[] replacementKeys = Enumerable.Range(0, definitions.Count)
            .Select(index => Keys.Control | Keys.Shift | (Keys)((int)Keys.A + index))
            .ToArray();

        for (int i = 0; i < definitions.Count; i++)
        {
            ShortcutDefinition definition = definitions[i];
            Keys replacement = replacementKeys[i];
            Require(manager.TrySet(definition.Id, replacement, out string? error),
                $"Could not rebind '{definition.Description}' to {replacement}: {error}");
            Require(manager.Get(definition.Id) == replacement,
                $"Rebound shortcut was not returned for '{definition.Description}'.");

            string expectedDispatch = definition.Id == ActionIds.PreviousWord ? ActionIds.NextWord : definition.Id;
            Require(manager.FindAction(replacement) == expectedDispatch,
                $"Rebound shortcut did not dispatch correctly for '{definition.Description}'.");
        }

        Require(!manager.TrySet(definitions[1].Id, replacementKeys[0], out string? conflict) && !string.IsNullOrWhiteSpace(conflict),
            "Shortcut conflict was not rejected.");

        Keys[] unsafeKeys =
        {
            Keys.Tab,
            Keys.Escape,
            Keys.Enter,
            Keys.Alt | Keys.F4,
            Keys.Left,
            Keys.Right,
            Keys.Up,
            Keys.Down,
            Keys.Home,
            Keys.End,
            Keys.PageUp,
            Keys.PageDown
        };
        foreach (Keys unsafeKey in unsafeKeys)
        {
            Require(!manager.TrySet(definitions[0].Id, unsafeKey, out string? unsafeError) && !string.IsNullOrWhiteSpace(unsafeError),
                $"Unsafe shortcut {unsafeKey} was accepted.");
        }

        manager.ResetDefaults();
        foreach (ShortcutDefinition definition in definitions)
        {
            Require(manager.Get(definition.Id) == definition.DefaultKeys,
                $"Reset defaults failed for '{definition.Description}'.");
            if (definition.DefaultKeys != Keys.None)
            {
                string expectedDispatch = definition.Id == ActionIds.PreviousWord ? ActionIds.NextWord : definition.Id;
                Require(manager.FindAction(definition.DefaultKeys) == expectedDispatch,
                    $"Default shortcut does not dispatch correctly for '{definition.Description}' after reset.");
            }
        }

        var service = new DeckService(state);
        DeckDefinition userDeck = service.Create("Custom study");
        manager.RefreshDeckDefinitions();
        string switchAction = ActionIds.SwitchDeck(userDeck.Id);
        string moveAction = ActionIds.MoveToDeck(userDeck.Id);
        Require(manager.Definitions.Count == 21, "Creating a user deck did not add its switch and move shortcut actions.");
        Require(manager.Get(switchAction) == Keys.None && manager.Get(moveAction) == Keys.None,
            "User-created deck shortcuts must start unassigned.");

        Keys customSwitch = Keys.Control | Keys.Alt | Keys.F8;
        Keys customMove = Keys.Control | Keys.Alt | Keys.F9;
        Require(manager.TrySet(switchAction, customSwitch, out string? switchError), $"Could not bind user-deck switch shortcut: {switchError}");
        Require(manager.TrySet(moveAction, customMove, out string? moveError), $"Could not bind user-deck move shortcut: {moveError}");
        service.Rename(userDeck.Id, "Renamed custom study");
        service.Move(userDeck.Id, -1);
        manager.RefreshDeckDefinitions();
        Require(manager.Get(switchAction) == customSwitch && manager.Get(moveAction) == customMove,
            "Renaming/reordering a deck broke shortcuts that should follow its stable ID.");
        Require(manager.FindAction(customSwitch) == switchAction && manager.FindAction(customMove) == moveAction,
            "User-created deck shortcut did not dispatch to its stable deck ID action.");
        Require(!manager.TrySet(moveAction, customSwitch, out string? userConflict) && !string.IsNullOrWhiteSpace(userConflict),
            "Conflict between a user deck's switch and move shortcuts was not rejected.");
        manager.Clear(switchAction);
        Require(manager.Get(switchAction) == Keys.None, "Clearing an assigned user-deck shortcut failed.");

        service.DeleteUserDeck(userDeck.Id, null);
        manager.RefreshDeckDefinitions();
        Require(!manager.Definitions.Any(def => def.Id == switchAction || def.Id == moveAction),
            "Deleted user deck left orphaned shortcut actions in the settings UI.");
    }

    private static void TestPronunciationAudioLayer()
    {
        IReadOnlyList<string> paths = PronunciationAudio.CandidatePaths("oxford-3000-en-uk", "oxford-a1-0001");
        Require(paths.Count == 2, $"Expected portable and local audio-pack paths, got {paths.Count}.");
        string expectedTail = Path.Combine("oxford-3000-en-uk", "oxford-a1-0001.mp3");
        Require(paths.All(path => path.EndsWith(expectedTail, StringComparison.OrdinalIgnoreCase)),
            "Pronunciation paths are not keyed by stable dictionary and entry IDs.");

        IReadOnlyList<string> sanitized = PronunciationAudio.CandidatePaths("custom dictionary/uk", "entry 1");
        Require(sanitized.All(path => path.Contains("custom_dictionary_uk", StringComparison.OrdinalIgnoreCase)),
            "Unsafe dictionary ID characters were not sanitized for audio-pack paths.");
        Require(sanitized.All(path => path.EndsWith(Path.Combine("custom_dictionary_uk", "entry_1.mp3"), StringComparison.OrdinalIgnoreCase)),
            "Unsafe entry ID characters were not sanitized for audio file names.");
    }

    private static void TestStatePersistenceAndRecovery()
    {
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck-self-test-{Guid.NewGuid():N}");
        try
        {
            var store = new AppStateStore(root);
            var state = AppStateStore.Normalize(new AppState
            {
                ActiveDictionaryId = "oxford-3000-en-uk",
                AutoPlayPronunciationOnCardChange = true
            });
            var service = new DeckService(state);
            service.Rename(DeckIds.Core(1), "Inbox words");
            DeckDefinition custom = service.Create("Persistent custom");
            state.ActiveDeckId = custom.Id;
            state.DeckIdsByDictionary["oxford-3000-en-uk"] = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                ["oxford-a1-0001"] = DeckIds.Core(3),
                ["oxford-a1-0002"] = custom.Id
            };

            var shortcuts = new ShortcutManager(state);
            Keys persistedShortcut = Keys.Control | Keys.Shift | Keys.Z;
            Require(shortcuts.TrySet(ActionIds.RevealTranslation, persistedShortcut, out string? shortcutError),
                $"Could not prepare persisted shortcut: {shortcutError}");
            Keys persistedAudioShortcut = Keys.Control | Keys.Alt | Keys.F10;
            Require(shortcuts.TrySet(ActionIds.PlayPronunciation, persistedAudioShortcut, out string? audioShortcutError),
                $"Could not prepare persisted pronunciation shortcut: {audioShortcutError}");
            Keys persistedDeckShortcut = Keys.Control | Keys.Alt | Keys.F11;
            Require(shortcuts.TrySet(ActionIds.SwitchDeck(custom.Id), persistedDeckShortcut, out string? deckShortcutError),
                $"Could not prepare persisted custom-deck shortcut: {deckShortcutError}");
            store.Save(state);

            AppState reloaded = new AppStateStore(root).Load();
            Require(reloaded.ActiveDictionaryId == "oxford-3000-en-uk", "Active dictionary did not survive restart.");
            Require(reloaded.ActiveDeckId == custom.Id, "Active user-created deck did not survive restart.");
            Require(reloaded.AutoPlayPronunciationOnCardChange, "Automatic pronunciation preference did not survive restart.");
            Require(reloaded.Decks.First(deck => deck.Id == DeckIds.Core(1)).Name == "Inbox words", "Renamed default deck did not survive restart.");
            Require(reloaded.Decks.Any(deck => deck.Id == custom.Id && deck.Name == "Persistent custom" && !deck.IsCore),
                "User-created deck definition did not survive restart.");
            Require(reloaded.DeckIdsByDictionary["oxford-3000-en-uk"]["oxford-a1-0001"] == DeckIds.Core(3),
                "Stable core deck assignment did not survive restart.");
            Require(reloaded.DeckIdsByDictionary["oxford-3000-en-uk"]["oxford-a1-0002"] == custom.Id,
                "User-created deck assignment did not survive restart.");
            var reloadedShortcuts = new ShortcutManager(reloaded);
            Require(reloadedShortcuts.Get(ActionIds.RevealTranslation) == persistedShortcut,
                "Rebound shortcut did not survive restart.");
            Require(reloadedShortcuts.Get(ActionIds.PlayPronunciation) == persistedAudioShortcut,
                "Rebound pronunciation shortcut did not survive restart.");
            Require(reloadedShortcuts.Get(ActionIds.SwitchDeck(custom.Id)) == persistedDeckShortcut,
                "Custom-deck switch shortcut did not survive restart.");

            // A second valid save creates a recovery snapshot of the first state.
            reloaded.ActiveDeckId = DeckIds.Core(2);
            reloaded.AutoPlayPronunciationOnCardChange = false;
            reloaded.DeckIdsByDictionary["oxford-3000-en-uk"]["oxford-a1-0001"] = DeckIds.Core(5);
            store.Save(reloaded);

            string primaryPath = Path.Combine(root, "state.json");
            File.WriteAllText(primaryPath, "{ definitely not valid json");
            AppState recovered = new AppStateStore(root).Load();
            Require(recovered.ActiveDeckId == custom.Id, "Backup recovery did not restore the last known-good active custom deck.");
            Require(recovered.AutoPlayPronunciationOnCardChange, "Backup recovery did not restore automatic pronunciation preference.");
            Require(recovered.DeckIdsByDictionary["oxford-3000-en-uk"]["oxford-a1-0001"] == DeckIds.Core(3),
                "Backup recovery did not restore the last known-good deck assignment.");
            var recoveredShortcuts = new ShortcutManager(recovered);
            Require(recoveredShortcuts.Get(ActionIds.RevealTranslation) == persistedShortcut,
                "Backup recovery did not restore the rebound shortcut.");
            Require(recoveredShortcuts.Get(ActionIds.PlayPronunciation) == persistedAudioShortcut,
                "Backup recovery did not restore the pronunciation shortcut.");
            Require(recoveredShortcuts.Get(ActionIds.SwitchDeck(custom.Id)) == persistedDeckShortcut,
                "Backup recovery did not restore the custom-deck shortcut.");
        }
        finally
        {
            try
            {
                if (Directory.Exists(root))
                    Directory.Delete(root, true);
            }
            catch
            {
                // A failed cleanup must not hide the actual self-test result.
            }
        }
    }

    private static void ExpectInvalid(string text, string description)
    {
        try
        {
            DictionaryLoader.Parse(text);
        }
        catch (InvalidDataException)
        {
            return;
        }

        throw new InvalidDataException($"Parser accepted invalid dictionary: {description}.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidDataException(message);
    }
}
