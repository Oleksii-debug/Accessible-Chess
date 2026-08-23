using System.Runtime.CompilerServices;
using System.Text.Json;

namespace WordDeck;

internal static class UnifiedProfileSelfTest
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (!Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            return;
        Run();
    }

    internal static void Run()
    {
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck unified profile Київ {Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            const string dictionaryId = "oxford-3000-en-uk";
            const string knownId = "word-a";
            var appStore = new AppStateStore(root);
            var spellingStore = new SpellingStateStore(root);
            var sentenceStore = new SentenceCoachStateStore(root);
            var storyStore = new StoryCourseStateStore(root);
            AppState app = AppStateStore.Normalize(new AppState { ActiveDictionaryId = dictionaryId });
            app.HiddenEntryIds.Add(knownId);
            appStore.Save(app);

            SpellingState spelling = SpellingStateStore.Normalize(new SpellingState());
            spelling.StatsByDictionary[dictionaryId] = new Dictionary<string, SpellingEntryStats>(StringComparer.OrdinalIgnoreCase)
            {
                [knownId] = new SpellingEntryStats { CompletedReviews = 4, FirstTrySuccesses = 3, CurrentStreak = 2 }
            };
            spellingStore.Save(spelling);

            SentenceCoachState sentence = SentenceCoachStateStore.Normalize(new SentenceCoachState { TargetCount = 1 });
            sentence.StatsByDictionary[dictionaryId] = new Dictionary<string, SentenceTargetStats>(StringComparer.OrdinalIgnoreCase)
            {
                [knownId] = new SentenceTargetStats { CompletedReviews = 2, FirstTrySuccesses = 1 }
            };
            sentenceStore.Save(sentence);

            StoryCourseState story = StoryCourseStateStore.Normalize(new StoryCourseState
            {
                ActiveDictionaryId = dictionaryId,
                ActiveUnitId = "test-unit",
                ActiveChapterId = "test-chapter"
            });
            story.ChapterProgress["test-chapter"] = new StoryChapterProgress { Opens = 3, Completions = 1, TaskAttempts = 2, TaskFirstTrySuccesses = 1 };
            story.TargetEvidenceByEntryId[knownId] = new StoryTargetEvidence { NarrativeEncounters = 3, CompletedNarrativeEncounters = 1 };
            story.PendingPracticeRoutes.Add(new StoryPracticeRoute(
                StoryPracticeMode.Sentence,
                "test-chapter",
                dictionaryId,
                new[] { knownId },
                new[] { "grammar.test" },
                "self-test route",
                DateTimeOffset.UtcNow));
            storyStore.Save(story);

            var service = new UnifiedProfileService(appStore, root);
            string profile = Path.Combine(root, "WordDeck-profile-v4.json");
            service.Export(app, profile);
            using (JsonDocument exported = JsonDocument.Parse(File.ReadAllText(profile)))
            {
                Require(exported.RootElement.GetProperty("ProfileSchemaVersion").GetInt32() == 4, "Unified export did not use schema 4.");
                Require(exported.RootElement.TryGetProperty("SpellingState", out _), "Unified export lost Spelling state.");
                Require(exported.RootElement.TryGetProperty("SentenceState", out _), "Unified export lost Sentence state.");
                Require(exported.RootElement.TryGetProperty("StoryState", out _), "Unified export lost Story/Narrative Course state.");
            }

            app.HiddenEntryIds.Clear();
            appStore.Save(app);
            spellingStore.Save(SpellingStateStore.Normalize(new SpellingState()));
            sentenceStore.Save(SentenceCoachStateStore.Normalize(new SentenceCoachState()));
            storyStore.Save(StoryCourseStateStore.Normalize(new StoryCourseState()));

            UnifiedProfileImportResult result = service.Import(profile, app, new[] { knownId }, new[] { dictionaryId });
            Require(result.SpellingImported && result.SentenceImported && result.StoryImported && result.SourceProfileSchemaVersion == 4,
                "Unified profile did not report Recall+Spelling+Sentence+Story import.");
            Require(app.HiddenEntryIds.Contains(knownId), "Unified profile lost Recall hidden state.");
            Require(spellingStore.Load().StatsByDictionary[dictionaryId][knownId].CompletedReviews == 4,
                "Unified profile lost Spelling statistics.");
            Require(sentenceStore.Load().StatsByDictionary[dictionaryId][knownId].CompletedReviews == 2,
                "Unified profile lost Sentence statistics.");
            Require(storyStore.Load().ChapterProgress["test-chapter"].Completions == 1,
                "Unified profile lost Story/Narrative Course progress.");
            Require(storyStore.Load().PendingPracticeRoutes.Count == 1,
                "Unified profile lost queued post-story practice routing.");
            Require(File.Exists(result.RecallBackupPath) && File.Exists(result.SpellingBackupPath!) &&
                    File.Exists(result.SentenceBackupPath!) && File.Exists(result.StoryBackupPath!),
                "Unified profile import did not create recovery evidence for all four states.");

            // Schema-3 profiles predate Story. Importing one must preserve current
            // Story/Course progress rather than silently resetting a newer mode.
            StoryCourseState beforeV3 = storyStore.Load();
            beforeV3.ChapterProgress["story-must-survive-v3"] = new StoryChapterProgress { Opens = 2, Completions = 2 };
            storyStore.Save(beforeV3);
            string v3 = Path.Combine(root, "WordDeck-profile-v3.json");
            var legacyV3 = new WordDeckUnifiedProfileV3
            {
                ProfileSchemaVersion = 3,
                StateSchemaVersion = AppStateStore.CurrentSchemaVersion,
                SpellingSchemaVersion = SpellingStateStore.CurrentSchemaVersion,
                SourceAppVersion = AppStateStore.SourceAppVersion,
                CorpusIdentity = AppStateStore.CorpusIdentity,
                State = app,
                SpellingState = spellingStore.Load(),
                SentenceState = sentenceStore.Load()
            };
            File.WriteAllText(v3, JsonSerializer.Serialize(legacyV3, new JsonSerializerOptions { WriteIndented = true }));
            UnifiedProfileImportResult v3Result = service.Import(v3, app, new[] { knownId }, new[] { dictionaryId });
            Require(v3Result.SourceProfileSchemaVersion == 3 && v3Result.SpellingImported && v3Result.SentenceImported && !v3Result.StoryImported,
                "Schema-3 compatibility path was not preserved.");
            Require(storyStore.Load().ChapterProgress.ContainsKey("story-must-survive-v3"),
                "Importing a schema-3 profile unexpectedly replaced Story state.");

            SentenceCoachState sentenceBeforeLegacy = sentenceStore.Load();
            sentenceBeforeLegacy.RecentSentenceIds.Add("sentinel-sentence");
            sentenceStore.Save(sentenceBeforeLegacy);
            StoryCourseState storyBeforeLegacy = storyStore.Load();
            storyBeforeLegacy.ChapterProgress["story-must-survive-v2"] = new StoryChapterProgress { Opens = 1, Completions = 1 };
            storyStore.Save(storyBeforeLegacy);
            string v2 = Path.Combine(root, "WordDeck-profile-v2.json");
            new SpellingProfileService(appStore, spellingStore).Export(app, spellingStore.Load(), v2);
            UnifiedProfileImportResult v2Result = service.Import(v2, app, new[] { knownId }, new[] { dictionaryId });
            Require(v2Result.SourceProfileSchemaVersion == 2 && v2Result.SpellingImported && !v2Result.SentenceImported && !v2Result.StoryImported,
                "Schema-2 compatibility path was not preserved.");
            Require(sentenceStore.Load().RecentSentenceIds.Contains("sentinel-sentence"),
                "Importing a schema-2 profile unexpectedly replaced Sentence state.");
            Require(storyStore.Load().ChapterProgress.ContainsKey("story-must-survive-v2"),
                "Importing a schema-2 profile unexpectedly replaced Story state.");

            WordDeckUnifiedProfile incompatibleProfile = JsonSerializer.Deserialize<WordDeckUnifiedProfile>(File.ReadAllText(profile))
                ?? throw new InvalidDataException("Could not construct incompatible-profile test fixture.");
            incompatibleProfile.CorpusIdentity = "different-corpus:1";
            string bad = Path.Combine(root, "incompatible-v4.json");
            File.WriteAllText(bad, JsonSerializer.Serialize(incompatibleProfile, new JsonSerializerOptions { WriteIndented = true }));
            string appBefore = JsonSerializer.Serialize(app);
            string spellingBefore = JsonSerializer.Serialize(spellingStore.Load());
            string sentenceBefore = JsonSerializer.Serialize(sentenceStore.Load());
            string storyBefore = JsonSerializer.Serialize(storyStore.Load());
            bool rejected = false;
            try { _ = service.Import(bad, app, new[] { knownId }, new[] { dictionaryId }); }
            catch (InvalidDataException) { rejected = true; }
            Require(rejected, "Incompatible-corpus unified profile was accepted.");
            Require(JsonSerializer.Serialize(app) == appBefore &&
                    JsonSerializer.Serialize(spellingStore.Load()) == spellingBefore &&
                    JsonSerializer.Serialize(sentenceStore.Load()) == sentenceBefore &&
                    JsonSerializer.Serialize(storyStore.Load()) == storyBefore,
                "Rejected unified profile mutated existing personal state.");

            Console.WriteLine("WordDeck unified profile acceptance passed: schema-4 Recall+Spelling+Sentence+Story export/import/recovery, schema-3/schema-2 compatibility and incompatible-corpus fail-closed behavior verified.");
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
