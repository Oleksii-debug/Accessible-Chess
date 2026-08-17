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
            TestShortcutRegistryAndRebinding();
            TestPronunciationAudioLayer();
            TestStatePersistenceAndRecovery();
            Console.WriteLine("WordDeck self-test passed: Oxford dictionary, strict imports, random navigation shortcuts, optional pronunciation controls, and persistent recovery state validated.");
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

    private static void TestShortcutRegistryAndRebinding()
    {
        IReadOnlyList<ShortcutDefinition> definitions = ShortcutManager.Definitions;
        Require(definitions.Count == 19, $"Expected 19 configurable actions including pronunciation controls, got {definitions.Count}.");
        Require(definitions.Any(def => def.Id == ActionIds.UndoMove), "Undo last deck move is missing from configurable shortcuts.");
        Require(definitions.Any(def => def.Id == ActionIds.PlayPronunciation), "Manual generated pronunciation is missing from configurable shortcuts.");
        Require(definitions.Any(def => def.Id == ActionIds.ToggleAutoPronunciation), "Automatic pronunciation toggle is missing from configurable shortcuts.");
        Require(definitions.Select(def => def.Id).Distinct(StringComparer.OrdinalIgnoreCase).Count() == definitions.Count,
            "Shortcut action IDs must be unique.");
        Require(definitions.Select(def => def.DefaultKeys).Distinct().Count() == definitions.Count,
            "Default shortcuts must be unique.");

        var state = new AppState();
        var manager = new ShortcutManager(state);

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

            // Both navigation directions are intentionally separate rebindable
            // bindings that dispatch to the same random-card action. All other
            // definitions dispatch to their own action IDs.
            string expectedDispatch = definition.Id == ActionIds.PreviousWord
                ? ActionIds.NextWord
                : definition.Id;
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
            string expectedDispatch = definition.Id == ActionIds.PreviousWord
                ? ActionIds.NextWord
                : definition.Id;
            Require(manager.FindAction(definition.DefaultKeys) == expectedDispatch,
                $"Default shortcut does not dispatch correctly for '{definition.Description}' after reset.");
        }
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
            var state = new AppState
            {
                ActiveDictionaryId = "oxford-3000-en-uk",
                ActiveDeck = 4,
                AutoPlayPronunciationOnCardChange = true
            };
            state.DecksByDictionary["oxford-3000-en-uk"] = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase)
            {
                ["oxford-a1-0001"] = 3,
                ["oxford-a1-0002"] = 5
            };

            var shortcuts = new ShortcutManager(state);
            Keys persistedShortcut = Keys.Control | Keys.Shift | Keys.Z;
            Require(shortcuts.TrySet(ActionIds.RevealTranslation, persistedShortcut, out string? shortcutError),
                $"Could not prepare persisted shortcut: {shortcutError}");
            Keys persistedAudioShortcut = Keys.Control | Keys.Shift | Keys.B;
            Require(shortcuts.TrySet(ActionIds.PlayPronunciation, persistedAudioShortcut, out string? audioShortcutError),
                $"Could not prepare persisted pronunciation shortcut: {audioShortcutError}");
            store.Save(state);

            AppState reloaded = new AppStateStore(root).Load();
            Require(reloaded.ActiveDictionaryId == "oxford-3000-en-uk", "Active dictionary did not survive restart.");
            Require(reloaded.ActiveDeck == 4, "Active deck did not survive restart.");
            Require(reloaded.AutoPlayPronunciationOnCardChange, "Automatic pronunciation preference did not survive restart.");
            Require(reloaded.DecksByDictionary["oxford-3000-en-uk"]["oxford-a1-0001"] == 3,
                "Deck assignment did not survive restart.");
            var reloadedShortcuts = new ShortcutManager(reloaded);
            Require(reloadedShortcuts.Get(ActionIds.RevealTranslation) == persistedShortcut,
                "Rebound shortcut did not survive restart.");
            Require(reloadedShortcuts.FindAction(persistedShortcut) == ActionIds.RevealTranslation,
                "Persisted shortcut did not dispatch after restart.");
            Require(reloadedShortcuts.Get(ActionIds.PlayPronunciation) == persistedAudioShortcut,
                "Rebound pronunciation shortcut did not survive restart.");

            // A second valid save creates a recovery snapshot of the first state.
            reloaded.ActiveDeck = 2;
            reloaded.AutoPlayPronunciationOnCardChange = false;
            reloaded.DecksByDictionary["oxford-3000-en-uk"]["oxford-a1-0001"] = 5;
            store.Save(reloaded);

            string primaryPath = Path.Combine(root, "state.json");
            File.WriteAllText(primaryPath, "{ definitely not valid json");
            AppState recovered = new AppStateStore(root).Load();
            Require(recovered.ActiveDeck == 4, "Backup recovery did not restore the last known-good active deck.");
            Require(recovered.AutoPlayPronunciationOnCardChange, "Backup recovery did not restore automatic pronunciation preference.");
            Require(recovered.DecksByDictionary["oxford-3000-en-uk"]["oxford-a1-0001"] == 3,
                "Backup recovery did not restore the last known-good deck assignment.");
            var recoveredShortcuts = new ShortcutManager(recovered);
            Require(recoveredShortcuts.Get(ActionIds.RevealTranslation) == persistedShortcut,
                "Backup recovery did not restore the rebound shortcut.");
            Require(recoveredShortcuts.Get(ActionIds.PlayPronunciation) == persistedAudioShortcut,
                "Backup recovery did not restore the pronunciation shortcut.");
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
