using System.Text.Json;

namespace WordDeck;

internal static class FullV1ProfileSelfTest
{
    public static void Run()
    {
        TestThreeModuleRoundTrip();
        TestIncompatibleCorpusFailsBeforeBackupOrMutation();
        TestInjectedPartialSaveRollsBackAllModules();
        TestLegacyRecallProfileDoesNotEraseNewerModules();
    }

    private static void TestThreeModuleRoundTrip()
    {
        string root = TempRoot("roundtrip");
        try
        {
            AppState sourceRecall = Recall("recall-hidden");
            sourceRecall.Shortcuts[ActionIds.OpenSpelling] = "Ctrl+Alt+S";
            SpellingState sourceSpelling = Spelling("spell-entry", coachEnabled: false);
            SentenceCoachState sourceSentence = Sentence("sentence-entry", "pack-one");
            string profile = Path.Combine(root, "full-profile.json");

            var service = new FullV1ProfileService(root);
            service.Export(sourceRecall, sourceSpelling, sourceSentence, profile);

            AppState destinationRecall = Recall("old-recall");
            SpellingState destinationSpelling = Spelling("old-spell", coachEnabled: true);
            SentenceCoachState destinationSentence = Sentence("old-sentence", "old-pack");

            FullV1ProfileImportResult result = service.Import(
                profile,
                destinationRecall,
                destinationSpelling,
                destinationSentence,
                new[] { "recall-hidden", "spell-entry", "sentence-entry" },
                new[] { "oxford-3000-en-uk" },
                new[] { "pack-one" });

            Require(!result.LegacyRecallOnlyProfile, "Full-v1 profile was misclassified as legacy.");
            Require(File.Exists(result.RecoveryBundlePath), "Full-v1 import did not create a pre-import three-module recovery bundle.");
            Require(destinationRecall.HiddenEntryIds.Contains("recall-hidden"), "Recall hidden state did not round-trip in full-v1 profile.");
            Require(destinationRecall.Shortcuts.GetValueOrDefault(ActionIds.OpenSpelling) == "Ctrl+Alt+S", "Shortcut state did not round-trip in full-v1 profile.");
            Require(!destinationSpelling.CoachEnabled && destinationSpelling.StatsByDictionary["oxford-3000-en-uk"].ContainsKey("spell-entry"),
                "Spelling stats/Coach state did not round-trip in full-v1 profile.");
            Require(destinationSentence.ActivePackId == "pack-one" && destinationSentence.CurrentTargetEntryIds.Contains("sentence-entry"),
                "Sentence pack/progress state did not round-trip in full-v1 profile.");
        }
        finally { DeleteTree(root); }
    }

    private static void TestIncompatibleCorpusFailsBeforeBackupOrMutation()
    {
        string root = TempRoot("incompatible");
        try
        {
            var service = new FullV1ProfileService(root);
            AppState currentRecall = Recall("keep-recall");
            SpellingState currentSpelling = Spelling("keep-spell", coachEnabled: false);
            SentenceCoachState currentSentence = Sentence("keep-sentence", "keep-pack");
            string beforeRecall = JsonSerializer.Serialize(currentRecall);
            string beforeSpelling = JsonSerializer.Serialize(currentSpelling);
            string beforeSentence = JsonSerializer.Serialize(currentSentence);

            string profilePath = Path.Combine(root, "bad-corpus.json");
            var profile = new WordDeckFullV1Profile
            {
                CorpusIdentity = "foreign-corpus:1",
                Recall = Recall("foreign-recall"),
                Spelling = Spelling("foreign-spell", true),
                Sentence = Sentence("foreign-sentence", "foreign-pack")
            };
            File.WriteAllText(profilePath, JsonSerializer.Serialize(profile));

            bool rejected = false;
            try
            {
                service.Import(profilePath, currentRecall, currentSpelling, currentSentence,
                    Array.Empty<string>(), Array.Empty<string>(), Array.Empty<string>());
            }
            catch (InvalidDataException ex)
            {
                rejected = ex.Message.Contains("corpus", StringComparison.OrdinalIgnoreCase);
            }

            Require(rejected, "Incompatible full-v1 corpus was accepted.");
            Require(JsonSerializer.Serialize(currentRecall) == beforeRecall, "Incompatible profile mutated in-memory Recall state.");
            Require(JsonSerializer.Serialize(currentSpelling) == beforeSpelling, "Incompatible profile mutated in-memory Spelling state.");
            Require(JsonSerializer.Serialize(currentSentence) == beforeSentence, "Incompatible profile mutated in-memory Sentence state.");
            Require(!Directory.EnumerateFiles(Path.Combine(root, "Backups"), "WordDeck-full-profile-*.json").Any(),
                "Incompatible profile created recovery metadata before compatibility was established.");
            Require(!File.Exists(Path.Combine(root, "state.json")) &&
                    !File.Exists(Path.Combine(root, "spelling-state.json")) &&
                    !File.Exists(Path.Combine(root, "sentence-coach-state.json")),
                "Incompatible profile caused persistent module state writes.");
        }
        finally { DeleteTree(root); }
    }

    private static void TestInjectedPartialSaveRollsBackAllModules()
    {
        string root = TempRoot("rollback");
        try
        {
            AppState beforeRecall = Recall("before-recall");
            SpellingState beforeSpelling = Spelling("before-spell", coachEnabled: false);
            SentenceCoachState beforeSentence = Sentence("before-sentence", "before-pack");

            string source = Path.Combine(root, "incoming.json");
            new FullV1ProfileService(root).Export(
                Recall("incoming-recall"),
                Spelling("incoming-spell", coachEnabled: true),
                Sentence("incoming-sentence", "incoming-pack"),
                source);

            bool injected = false;
            var service = new FullV1ProfileService(root, checkpoint =>
            {
                if (checkpoint == "spelling-saved")
                {
                    injected = true;
                    throw new IOException("Injected failure after Recall and Spelling persistence.");
                }
            });

            bool failed = false;
            try
            {
                service.Import(source, beforeRecall, beforeSpelling, beforeSentence,
                    new[] { "incoming-recall", "incoming-spell", "incoming-sentence" },
                    new[] { "oxford-3000-en-uk" },
                    new[] { "incoming-pack" });
            }
            catch (IOException) { failed = true; }

            Require(injected && failed, "Profile failure injection did not execute at the expected partial-save boundary.");
            Require(beforeRecall.HiddenEntryIds.Contains("before-recall") && !beforeRecall.HiddenEntryIds.Contains("incoming-recall"),
                "Rollback did not restore in-memory Recall state.");
            Require(beforeSpelling.StatsByDictionary["oxford-3000-en-uk"].ContainsKey("before-spell") && !beforeSpelling.StatsByDictionary["oxford-3000-en-uk"].ContainsKey("incoming-spell"),
                "Rollback did not restore in-memory Spelling state.");
            Require(beforeSentence.ActivePackId == "before-pack" && beforeSentence.CurrentTargetEntryIds.Contains("before-sentence"),
                "Rollback did not restore in-memory Sentence state.");

            AppState diskRecall = new AppStateStore(root).Load();
            SpellingState diskSpelling = TrainingStateContinuityGuard.LoadSpelling(root).State;
            SentenceCoachState diskSentence = TrainingStateContinuityGuard.LoadSentence(root).State;
            Require(diskRecall.HiddenEntryIds.Contains("before-recall"), "Rollback did not restore persisted Recall state.");
            Require(diskSpelling.StatsByDictionary["oxford-3000-en-uk"].ContainsKey("before-spell"), "Rollback did not restore persisted Spelling state.");
            Require(diskSentence.ActivePackId == "before-pack", "Rollback did not restore persisted Sentence state.");
            Require(Directory.EnumerateFiles(Path.Combine(root, "Backups"), "WordDeck-full-profile-*.json").Any(),
                "Injected failure did not leave a pre-import three-module recovery bundle.");
        }
        finally { DeleteTree(root); }
    }

    private static void TestLegacyRecallProfileDoesNotEraseNewerModules()
    {
        string root = TempRoot("legacy");
        try
        {
            var appStore = new AppStateStore(root);
            AppState legacyRecall = Recall("legacy-recall");
            string profile = Path.Combine(root, "legacy-v01.json");
            appStore.ExportProfile(legacyRecall, profile);

            AppState destinationRecall = Recall("current-recall");
            appStore.Save(destinationRecall);
            SpellingState destinationSpelling = Spelling("keep-spell", coachEnabled: false);
            new SpellingStateStore(root).Save(destinationSpelling);
            SentenceCoachState destinationSentence = Sentence("keep-sentence", "keep-pack");
            new SentenceCoachStateStore(root).Save(destinationSentence);

            FullV1ProfileImportResult result = new FullV1ProfileService(root).Import(
                profile, destinationRecall, destinationSpelling, destinationSentence,
                new[] { "legacy-recall", "keep-spell", "keep-sentence" },
                new[] { "oxford-3000-en-uk" },
                new[] { "keep-pack" });

            Require(result.LegacyRecallOnlyProfile, "V0.1 Recall-only profile was not recognized as legacy.");
            Require(destinationRecall.HiddenEntryIds.Contains("legacy-recall"), "Legacy Recall profile did not import Recall state.");
            Require(destinationSpelling.StatsByDictionary["oxford-3000-en-uk"].ContainsKey("keep-spell") && !destinationSpelling.CoachEnabled,
                "Legacy Recall-only import erased or replaced Spelling state.");
            Require(destinationSentence.ActivePackId == "keep-pack" && destinationSentence.CurrentTargetEntryIds.Contains("keep-sentence"),
                "Legacy Recall-only import erased or replaced Sentence state.");
        }
        finally { DeleteTree(root); }
    }

    private static AppState Recall(string hiddenId)
    {
        AppState state = AppStateStore.Normalize(new AppState());
        state.ActiveDictionaryId = "oxford-3000-en-uk";
        state.HiddenEntryIds.Add(hiddenId);
        return state;
    }

    private static SpellingState Spelling(string entryId, bool coachEnabled)
    {
        SpellingState state = SpellingStateStore.Normalize(new SpellingState { CoachEnabled = coachEnabled });
        state.StatsByDictionary["oxford-3000-en-uk"] = new Dictionary<string, SpellingEntryStats>(StringComparer.OrdinalIgnoreCase)
        {
            [entryId] = new SpellingEntryStats { CompletedReviews = 4, FirstTrySuccesses = 3 }
        };
        state.DeckIdsByDictionary["oxford-3000-en-uk"] = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            [entryId] = SpellingDeckIds.Core(2)
        };
        state.CurrentEntryIdByDictionary["oxford-3000-en-uk"] = entryId;
        return state;
    }

    private static SentenceCoachState Sentence(string entryId, string packId)
    {
        SentenceCoachState state = SentenceCoachStateStore.Normalize(new SentenceCoachState
        {
            ActivePackId = packId,
            TargetCount = 1,
            CurrentTargetEntryIds = new List<string> { entryId },
            CurrentTargetEntryId = entryId,
            CurrentSentenceId = "sentence-" + entryId
        });
        state.StatsByDictionary["oxford-3000-en-uk"] = new Dictionary<string, SentenceTargetStats>(StringComparer.OrdinalIgnoreCase)
        {
            [entryId] = new SentenceTargetStats { CompletedReviews = 2, FirstTrySuccesses = 1 }
        };
        return state;
    }

    private static string TempRoot(string suffix)
    {
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck-r3-profile-{suffix}-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        return root;
    }

    private static void DeleteTree(string root)
    {
        try { if (Directory.Exists(root)) Directory.Delete(root, true); } catch { }
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }
}
