using System.Text.Json;
using System.Text.Json.Nodes;

namespace WordDeck;

internal static class UserDataSelfTest
{
    public static void Run()
    {
        Require(RecallKeyboardFocusPolicy.IsFastCardArrow(Keys.Down, englishWordSurfaceFocused: true),
            "Down Arrow must remain fast Recall navigation on the English word surface.");
        Require(RecallKeyboardFocusPolicy.IsFastCardArrow(Keys.Up, englishWordSurfaceFocused: true),
            "Up Arrow must remain true-previous Recall navigation on the English word surface.");
        Require(!RecallKeyboardFocusPolicy.IsFastCardArrow(Keys.Down, englishWordSurfaceFocused: false) &&
                !RecallKeyboardFocusPolicy.IsFastCardArrow(Keys.Up, englishWordSurfaceFocused: false),
            "Unmodified Up/Down must remain native outside the English word surface, including the Ukrainian translation and selectors.");
        Require(!RecallKeyboardFocusPolicy.IsFastCardArrow(Keys.Left, englishWordSurfaceFocused: true) &&
                !RecallKeyboardFocusPolicy.IsFastCardArrow(Keys.Control | Keys.Down, englishWordSurfaceFocused: true),
            "Recall fast-card policy intercepted a non-contract key.");
        Require(!RecallKeyboardFocusPolicy.ShouldFocusCardAfterSelectorChange(selectorContainsFocus: true) &&
                RecallKeyboardFocusPolicy.ShouldFocusCardAfterSelectorChange(selectorContainsFocus: false),
            "Selector focus policy would steal focus from a focused Dictionary/Scope/Deck ComboBox.");

        const string dictionaryId = "oxford-3000-en-uk";
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck-userdata-self-test-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            var entries = new List<DictionaryEntry>
            {
                new("word-a", "A1", "alpha", "альфа"),
                new("word-b", "B2", "beta", "бета"),
                new("word-c", "C1", "gamma", "гамма")
            };

            AppState legacy = AppStateStore.Normalize(new AppState
            {
                ActiveDictionaryId = dictionaryId,
                AutoPlayPronunciationOnCardChange = true
            });
            var scopes = new RecallStudyScopeService(legacy, dictionaryId, entries);
            scopes.Move(StudyScopeIds.All, "word-a", DeckIds.Core(3));
            scopes.Move(StudyScopeIds.B2, "word-b", DeckIds.Core(5));
            scopes.ActiveScopeId = StudyScopeIds.B2;
            scopes.SetActiveDeck(StudyScopeIds.B2, DeckIds.Core(5));
            scopes.SetCurrentEntry(StudyScopeIds.B2, "word-b");
            scopes.SetRemainingShuffle(StudyScopeIds.B2, new[] { "word-b" });
            UserProgressService.Hide(legacy, "word-c");
            UserProgressService.RecordSeen(legacy, "word-a", StudyScopeIds.All, DeckIds.Core(3));
            UserProgressService.RecordTranslationReveal(legacy, "word-a");
            var shortcuts = new ShortcutManager(legacy);
            Require(shortcuts.TrySet(ActionIds.RevealTranslation, Keys.Control | Keys.Alt | Keys.F9, out _), "Could not prepare custom shortcut.");

            legacy.SchemaVersion = 0;
            string statePath = Path.Combine(root, "state.json");
            File.WriteAllText(statePath, JsonSerializer.Serialize(legacy, new JsonSerializerOptions { WriteIndented = true }));

            var store = new AppStateStore(root);
            AppState migrated = store.Load();
            Require(migrated.SchemaVersion == AppStateStore.CurrentSchemaVersion, "Legacy state did not migrate to current schema.");
            Require(migrated.HiddenEntryIds.Contains("word-c"), "Hidden stable ID was lost during migration.");
            Require(migrated.StudyHistoryByEntryId["word-a"].SeenCount == 1 && migrated.StudyHistoryByEntryId["word-a"].TranslationRevealCount == 1,
                "Study history was lost during migration.");
            Require(migrated.RecallStudyScopesByDictionary[dictionaryId].Scopes[StudyScopeIds.All].DeckIds["word-a"] == DeckIds.Core(3),
                "All-scope assignment was lost during migration.");
            Require(migrated.RecallStudyScopesByDictionary[dictionaryId].Scopes[StudyScopeIds.B2].DeckIds["word-b"] == DeckIds.Core(5),
                "B2 assignment was lost during migration.");
            Require(new ShortcutManager(migrated).Get(ActionIds.RevealTranslation) == (Keys.Control | Keys.Alt | Keys.F9),
                "Shortcut customization was lost during migration.");
            Require(migrated.AutoPlayPronunciationOnCardChange, "Pronunciation preference was lost during migration.");
            Require(Directory.GetFiles(Path.Combine(root, "Backups"), "state-*-pre-migration.json").Length >= 1,
                "Migration did not create a timestamped recovery backup.");

            string profile = Path.Combine(root, "WordDeck-profile-v1.json");
            store.ExportProfile(migrated, profile);
            Require(File.Exists(profile) && new FileInfo(profile).Length > 100, "Personal profile export was not created.");
            string exportedText = File.ReadAllText(profile);
            Require(exportedText.Contains("ProfileSchemaVersion", StringComparison.Ordinal) && !exportedText.Contains("ReviewedOxford5000Bootstrap", StringComparison.Ordinal),
                "Profile export does not look like user-state-only JSON.");

            string resetBackup = store.CreateRecoveryProfile(migrated, "pre-reset-test");
            UserProgressService.ResetLearningData(migrated);
            store.Save(migrated);
            Require(File.Exists(resetBackup), "Reset recovery profile was not created.");
            Require(migrated.HiddenEntryIds.Count == 0 && migrated.StudyHistoryByEntryId.Count == 0 && migrated.RecallStudyScopesByDictionary.Count == 0,
                "Learning reset did not clear only the learning overlays/progress maps.");

            ProfileImportResult roundTrip = store.ImportProfile(profile, migrated, entries.Select(entry => entry.Id), new[] { dictionaryId });
            Require(File.Exists(roundTrip.BackupPath), "Profile import did not create a pre-import backup.");
            Require(migrated.HiddenEntryIds.Contains("word-c"), "Profile round-trip did not restore hidden state.");
            Require(migrated.StudyHistoryByEntryId["word-a"].SeenCount == 1, "Profile round-trip did not restore study history.");
            Require(migrated.RecallStudyScopesByDictionary[dictionaryId].Scopes[StudyScopeIds.B2].DeckIds["word-b"] == DeckIds.Core(5),
                "Profile round-trip did not restore per-scope assignment.");

            // Repeated save and repeated import must be idempotent. They may create
            // fresh recovery artifacts, but must not accumulate duplicate progress,
            // increment history, duplicate hidden IDs or grow scope assignment maps.
            int hiddenCountBeforeRepeat = migrated.HiddenEntryIds.Count;
            int historyCountBeforeRepeat = migrated.StudyHistoryByEntryId.Count;
            int allAssignmentCountBeforeRepeat = migrated.RecallStudyScopesByDictionary[dictionaryId].Scopes[StudyScopeIds.All].DeckIds.Count;
            int b2AssignmentCountBeforeRepeat = migrated.RecallStudyScopesByDictionary[dictionaryId].Scopes[StudyScopeIds.B2].DeckIds.Count;
            store.Save(migrated);
            store.Save(migrated);
            AppState afterRepeatedSave = new AppStateStore(root).Load();
            Require(afterRepeatedSave.HiddenEntryIds.Count == hiddenCountBeforeRepeat &&
                    afterRepeatedSave.StudyHistoryByEntryId.Count == historyCountBeforeRepeat &&
                    afterRepeatedSave.StudyHistoryByEntryId["word-a"].SeenCount == 1 &&
                    afterRepeatedSave.StudyHistoryByEntryId["word-a"].TranslationRevealCount == 1,
                "Repeated saves duplicated or mutated Recall progress/history.");
            Require(afterRepeatedSave.RecallStudyScopesByDictionary[dictionaryId].Scopes[StudyScopeIds.All].DeckIds.Count == allAssignmentCountBeforeRepeat &&
                    afterRepeatedSave.RecallStudyScopesByDictionary[dictionaryId].Scopes[StudyScopeIds.B2].DeckIds.Count == b2AssignmentCountBeforeRepeat,
                "Repeated saves changed scope assignment cardinality.");

            ProfileImportResult repeatedImport = store.ImportProfile(profile, migrated, entries.Select(entry => entry.Id), new[] { dictionaryId });
            Require(File.Exists(repeatedImport.BackupPath), "Repeated profile import did not create its recovery point.");
            Require(migrated.HiddenEntryIds.Count == hiddenCountBeforeRepeat && migrated.HiddenEntryIds.Contains("word-c"),
                "Repeated profile import duplicated or lost hidden-word state.");
            Require(migrated.StudyHistoryByEntryId.Count == historyCountBeforeRepeat &&
                    migrated.StudyHistoryByEntryId["word-a"].SeenCount == 1 &&
                    migrated.StudyHistoryByEntryId["word-a"].TranslationRevealCount == 1,
                "Repeated profile import accumulated study history instead of replacing state idempotently.");
            Require(migrated.RecallStudyScopesByDictionary[dictionaryId].Scopes[StudyScopeIds.All].DeckIds.Count == allAssignmentCountBeforeRepeat &&
                    migrated.RecallStudyScopesByDictionary[dictionaryId].Scopes[StudyScopeIds.B2].DeckIds.Count == b2AssignmentCountBeforeRepeat &&
                    migrated.RecallStudyScopesByDictionary[dictionaryId].Scopes[StudyScopeIds.B2].DeckIds["word-b"] == DeckIds.Core(5),
                "Repeated profile import duplicated or changed per-scope assignments.");

            string incompatibleProfile = Path.Combine(root, "WordDeck-profile-incompatible-corpus.json");
            JsonObject incompatibleProfileJson = JsonNode.Parse(File.ReadAllText(profile))?.AsObject()
                ?? throw new InvalidDataException("Exported profile JSON could not be parsed for incompatible-corpus regression setup.");
            incompatibleProfileJson["CorpusIdentity"] = "incompatible-corpus:1";
            File.WriteAllText(incompatibleProfile,
                incompatibleProfileJson.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
            int incompatibleHiddenBefore = migrated.HiddenEntryIds.Count;
            bool incompatibleRejected = false;
            try { store.ImportProfile(incompatibleProfile, migrated, entries.Select(entry => entry.Id), new[] { dictionaryId }); }
            catch (InvalidDataException) { incompatibleRejected = true; }
            Require(incompatibleRejected && migrated.HiddenEntryIds.Count == incompatibleHiddenBefore,
                "Incompatible-corpus profile was accepted or mutated current state instead of failing closed.");

            migrated.HiddenEntryIds.Add("future-word-id");
            string futureProfile = Path.Combine(root, "WordDeck-profile-future-id.json");
            store.ExportProfile(migrated, futureProfile);
            migrated.HiddenEntryIds.Remove("future-word-id");
            ProfileImportResult futureResult = store.ImportProfile(futureProfile, migrated, entries.Select(entry => entry.Id), new[] { dictionaryId });
            Require(futureResult.QuarantinedIds.Contains("future-word-id", StringComparer.OrdinalIgnoreCase),
                "Unknown stable ID was silently discarded instead of quarantined.");
            ProfileImportResult futureRepeat = store.ImportProfile(futureProfile, migrated, entries.Select(entry => entry.Id), new[] { dictionaryId });
            Require(futureRepeat.QuarantinedIds.Count(id => id.Equals("future-word-id", StringComparison.OrdinalIgnoreCase)) == 1 &&
                    migrated.QuarantinedProfileEntryIds.Count(id => id.Equals("future-word-id", StringComparison.OrdinalIgnoreCase)) == 1,
                "Repeated import duplicated an unknown quarantined stable ID.");

            string badProfile = Path.Combine(root, "bad-profile.json");
            File.WriteAllText(badProfile, "{ this is not valid json");
            int hiddenBefore = migrated.HiddenEntryIds.Count;
            bool rejected = false;
            try { store.ImportProfile(badProfile, migrated, entries.Select(entry => entry.Id), new[] { dictionaryId }); }
            catch (InvalidDataException) { rejected = true; }
            Require(rejected && migrated.HiddenEntryIds.Count == hiddenBefore,
                "Failed profile import mutated current state.");

            var navigation = new RecallNavigationHistory();
            navigation.Visit("word-a");
            navigation.Visit("word-b");
            navigation.Visit("word-c");
            Require(navigation.TryPrevious(id => id != "word-b", out string? previous) && previous == "word-a",
                "Up/previous history did not skip an ineligible card and return a previously shown card.");
            Require(navigation.TryForward(_ => true, out string? forward) && forward == "word-b",
                "Down/forward history did not move forward through already shown cards.");
            navigation.Remove("word-b");
            Require(navigation.TryForward(_ => true, out string? newest) && newest == "word-c",
                "Navigation history did not remain valid after hiding/removing a card.");

            string missingDictionaryId = "worddeck-selftest-missing-" + Guid.NewGuid().ToString("N");
            var missingPackage = new DictionaryPackage
            {
                Id = missingDictionaryId,
                Name = "Missing audio self-test",
                SourceLanguage = "en",
                TargetLanguage = "uk",
                Entries = new[] { new DictionaryEntry("missing-entry", "A1", "missing audio", "відсутнє аудіо") }
            };
            using (var audio = new PronunciationAudio())
            {
                bool played = audio.TryPlay(missingPackage, missingPackage.Entries[0], out string? missingAudioError);
                Require(!played && !string.IsNullOrWhiteSpace(missingAudioError) && missingAudioError.Contains("not installed", StringComparison.OrdinalIgnoreCase),
                    "Missing pronunciation audio did not return a readable non-crashing status.");
            }

            Console.WriteLine("WordDeck user-data acceptance passed: selector/translation keyboard policy, schema migration+backup, LocalAppData continuity, profile export/reset/import rollback, repeated save/import idempotence, incompatible-corpus rejection, unique unknown-ID quarantine, hidden IDs, study history, true previous/forward Recall history and missing-audio non-crash status verified.");
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
