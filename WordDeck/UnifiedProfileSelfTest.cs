using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Text.Json.Nodes;

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
            const string coursePathId = "complete-english:a1";
            var appStore = new AppStateStore(root);
            var spellingStore = new SpellingStateStore(root);
            var sentenceStore = new SentenceCoachStateStore(root);
            var listeningStore = new ListeningStateStore(root);
            var courseStore = new LearnerCourseStateStore(root);
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

            ListeningCoachState listening = ListeningStateStore.Normalize(new ListeningCoachState { ActiveScopeId = StudyScopeIds.B1 });
            listening.StatsByDictionary[dictionaryId] = new Dictionary<string, ListeningItemStats>(StringComparer.OrdinalIgnoreCase)
            {
                ["word:" + knownId] = new ListeningItemStats { CompletedReviews = 3, CorrectReviews = 2, WrongAttempts = 1 }
            };
            listeningStore.Save(listening);

            LearnerCourseState course = LearnerCourseStateStore.NewEmpty();
            course.CatalogVersion = "acceptance-catalog-v1";
            course.CoursePositionsByPathId[coursePathId] = new CoursePositionBookmark
            {
                PathId = coursePathId,
                CourseId = "ce-a1",
                ModuleId = "m05",
                UnitId = "u02",
                ActivityId = "reading-3"
            };
            course.EvidenceHistory.Add(new LearnerEvidenceEvent
            {
                EventId = "event-course-1",
                ActivityKind = LearnerActivityKind.Practice,
                PathId = coursePathId,
                CourseId = "ce-a1",
                ModuleId = "m05",
                UnitId = "u02",
                ObjectiveId = "objective-reading-1",
                SkillId = "reading",
                ItemId = "reading-3",
                Completed = true,
                Correct = false,
                HintUses = 1,
                AttemptNumber = 1
            });
            courseStore.Save(course);

            var service = new UnifiedProfileService(appStore, root);
            string profile = Path.Combine(root, "WordDeck-profile-v5.json");
            service.Export(app, profile);
            using (JsonDocument exported = JsonDocument.Parse(File.ReadAllText(profile)))
            {
                Require(exported.RootElement.GetProperty("ProfileSchemaVersion").GetInt32() == 5, "Unified export did not use schema 5.");
                Require(exported.RootElement.TryGetProperty("SpellingState", out _), "Unified export lost Spelling state.");
                Require(exported.RootElement.TryGetProperty("SentenceState", out _), "Unified export lost Sentence state.");
                Require(exported.RootElement.TryGetProperty("ListeningState", out _), "Unified export lost Listening state.");
                Require(exported.RootElement.TryGetProperty("CourseSchemaVersion", out JsonElement courseSchema) &&
                        courseSchema.GetInt32() == LearnerCourseStateStore.CurrentSchemaVersion,
                    "Unified export lost Course/Story schema metadata.");
                Require(exported.RootElement.TryGetProperty("CourseState", out JsonElement courseState) &&
                        courseState.ValueKind == JsonValueKind.Object,
                    "Unified export lost Course/Story learning state.");
            }

            app.HiddenEntryIds.Clear();
            appStore.Save(app);
            spellingStore.Save(SpellingStateStore.Normalize(new SpellingState()));
            sentenceStore.Save(SentenceCoachStateStore.Normalize(new SentenceCoachState()));
            listeningStore.Save(ListeningStateStore.Normalize(new ListeningCoachState()));
            courseStore.Save(LearnerCourseStateStore.NewEmpty());

            UnifiedProfileImportResult result = service.Import(profile, app, new[] { knownId }, new[] { dictionaryId });
            Require(result.SpellingImported && result.SentenceImported && result.ListeningImported && result.CourseImported && result.SourceProfileSchemaVersion == 5,
                "Unified profile did not report all five learning-state families imported.");
            Require(app.HiddenEntryIds.Contains(knownId), "Unified profile lost Recall hidden state.");
            Require(spellingStore.Load().StatsByDictionary[dictionaryId][knownId].CompletedReviews == 4,
                "Unified profile lost Spelling statistics.");
            Require(sentenceStore.Load().StatsByDictionary[dictionaryId][knownId].CompletedReviews == 2,
                "Unified profile lost Sentence statistics.");
            Require(listeningStore.Load().StatsByDictionary[dictionaryId]["word:" + knownId].CompletedReviews == 3,
                "Unified profile lost Listening statistics.");
            LearnerCourseState restoredCourse = courseStore.Load();
            Require(restoredCourse.CatalogVersion == "acceptance-catalog-v1" &&
                    restoredCourse.CoursePositionsByPathId.TryGetValue(coursePathId, out CoursePositionBookmark? restoredPosition) &&
                    restoredPosition.UnitId == "u02" && restoredPosition.ActivityId == "reading-3" &&
                    restoredCourse.EvidenceHistory.Any(item => item.EventId == "event-course-1" && item.HintUses == 1),
                "Unified profile lost Course/Story bookmark or learner evidence.");
            Require(File.Exists(result.RecallBackupPath) && File.Exists(result.SpellingBackupPath!) && File.Exists(result.SentenceBackupPath!) &&
                    File.Exists(result.ListeningBackupPath!) && File.Exists(result.CourseBackupPath!),
                "Unified profile import did not create recovery evidence for all five existing state families.");

            LearnerCourseState courseBeforeV4 = courseStore.Load();
            courseBeforeV4.CatalogVersion = "preserve-v4-course";
            courseBeforeV4.CoursePositionsByPathId[coursePathId].ActivityId = "local-after-v5";
            courseStore.Save(courseBeforeV4);
            JsonObject v4Json = JsonNode.Parse(File.ReadAllText(profile))?.AsObject()
                ?? throw new InvalidDataException("Could not construct schema-4 compatibility fixture.");
            v4Json["ProfileSchemaVersion"] = 4;
            v4Json.Remove("CourseSchemaVersion");
            v4Json.Remove("CourseState");
            string v4 = Path.Combine(root, "WordDeck-profile-v4.json");
            File.WriteAllText(v4, v4Json.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
            UnifiedProfileImportResult v4Result = service.Import(v4, app, new[] { knownId }, new[] { dictionaryId });
            Require(v4Result.SourceProfileSchemaVersion == 4 && v4Result.SentenceImported && v4Result.ListeningImported && !v4Result.CourseImported,
                "Schema-4 compatibility path did not preserve current Course/Story state.");
            LearnerCourseState afterV4 = courseStore.Load();
            Require(afterV4.CatalogVersion == "preserve-v4-course" && afterV4.CoursePositionsByPathId[coursePathId].ActivityId == "local-after-v5",
                "Importing schema-4 unexpectedly replaced Course/Story learning state.");

            ListeningCoachState listeningBeforeV3 = listeningStore.Load();
            listeningBeforeV3.ActiveScopeId = StudyScopeIds.C1;
            listeningBeforeV3.History.Add(new ListeningHistoryRecord { AtUtc = DateTimeOffset.UtcNow, DictionaryId = dictionaryId, ExerciseId = "word:" + knownId, Kind = ListeningExerciseKind.Word });
            listeningStore.Save(listeningBeforeV3);
            JsonObject v3Json = JsonNode.Parse(File.ReadAllText(profile))?.AsObject()
                ?? throw new InvalidDataException("Could not construct schema-3 compatibility fixture.");
            v3Json["ProfileSchemaVersion"] = 3;
            v3Json.Remove("ListeningSchemaVersion");
            v3Json.Remove("ListeningState");
            v3Json.Remove("CourseSchemaVersion");
            v3Json.Remove("CourseState");
            string v3 = Path.Combine(root, "WordDeck-profile-v3.json");
            File.WriteAllText(v3, v3Json.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
            UnifiedProfileImportResult v3Result = service.Import(v3, app, new[] { knownId }, new[] { dictionaryId });
            Require(v3Result.SourceProfileSchemaVersion == 3 && v3Result.SentenceImported && !v3Result.ListeningImported && !v3Result.CourseImported,
                "Schema-3 compatibility path did not preserve current Listening and Course/Story state.");
            Require(listeningStore.Load().ActiveScopeId == StudyScopeIds.C1 && listeningStore.Load().History.Any(item => item.ExerciseId == "word:" + knownId),
                "Importing schema-3 unexpectedly replaced Listening state.");
            Require(courseStore.Load().CatalogVersion == "preserve-v4-course",
                "Importing schema-3 unexpectedly replaced Course/Story state.");

            SentenceCoachState sentenceBeforeLegacy = sentenceStore.Load();
            sentenceBeforeLegacy.RecentSentenceIds.Add("sentinel-sentence");
            sentenceStore.Save(sentenceBeforeLegacy);
            ListeningCoachState listeningBeforeLegacy = listeningStore.Load();
            listeningBeforeLegacy.SelectionCounter = 77;
            listeningStore.Save(listeningBeforeLegacy);
            LearnerCourseState courseBeforeLegacy = courseStore.Load();
            courseBeforeLegacy.OrphanedStableIds.Add("sentinel-course-id");
            courseStore.Save(courseBeforeLegacy);
            string v2 = Path.Combine(root, "WordDeck-profile-v2.json");
            new SpellingProfileService(appStore, spellingStore).Export(app, spellingStore.Load(), v2);
            UnifiedProfileImportResult v2Result = service.Import(v2, app, new[] { knownId }, new[] { dictionaryId });
            Require(v2Result.SourceProfileSchemaVersion == 2 && v2Result.SpellingImported && !v2Result.SentenceImported && !v2Result.ListeningImported && !v2Result.CourseImported,
                "Schema-2 compatibility path was not preserved.");
            Require(sentenceStore.Load().RecentSentenceIds.Contains("sentinel-sentence"),
                "Importing a schema-2 profile unexpectedly replaced Sentence state.");
            Require(listeningStore.Load().SelectionCounter == 77,
                "Importing a schema-2 profile unexpectedly replaced Listening state.");
            Require(courseStore.Load().OrphanedStableIds.Contains("sentinel-course-id"),
                "Importing a schema-2 profile unexpectedly replaced Course/Story state.");

            WordDeckUnifiedProfile incompatibleProfile = JsonSerializer.Deserialize<WordDeckUnifiedProfile>(File.ReadAllText(profile))
                ?? throw new InvalidDataException("Could not construct incompatible-profile test fixture.");
            incompatibleProfile.CorpusIdentity = "different-corpus:1";
            string bad = Path.Combine(root, "incompatible-v5.json");
            File.WriteAllText(bad, JsonSerializer.Serialize(incompatibleProfile, new JsonSerializerOptions { WriteIndented = true }));
            string appBefore = JsonSerializer.Serialize(app);
            string spellingBefore = JsonSerializer.Serialize(spellingStore.Load());
            string sentenceBefore = JsonSerializer.Serialize(sentenceStore.Load());
            string listeningBefore = JsonSerializer.Serialize(listeningStore.Load());
            string courseBefore = JsonSerializer.Serialize(courseStore.Load());
            bool rejected = false;
            try { _ = service.Import(bad, app, new[] { knownId }, new[] { dictionaryId }); }
            catch (InvalidDataException) { rejected = true; }
            Require(rejected, "Incompatible-corpus unified profile was accepted.");
            Require(JsonSerializer.Serialize(app) == appBefore &&
                    JsonSerializer.Serialize(spellingStore.Load()) == spellingBefore &&
                    JsonSerializer.Serialize(sentenceStore.Load()) == sentenceBefore &&
                    JsonSerializer.Serialize(listeningStore.Load()) == listeningBefore &&
                    JsonSerializer.Serialize(courseStore.Load()) == courseBefore,
                "Rejected unified profile mutated existing personal state.");

            JsonObject futureCourseJson = JsonNode.Parse(File.ReadAllText(profile))?.AsObject()
                ?? throw new InvalidDataException("Could not construct future Course/Story schema fixture.");
            int futureCourseSchema = LearnerCourseStateStore.CurrentSchemaVersion + 1;
            futureCourseJson["CourseSchemaVersion"] = futureCourseSchema;
            JsonObject futureCourseState = futureCourseJson["CourseState"]?.AsObject()
                ?? throw new InvalidDataException("Exported v5 fixture has no CourseState object.");
            futureCourseState["SchemaVersion"] = futureCourseSchema;
            string future = Path.Combine(root, "future-course-schema-v5.json");
            File.WriteAllText(future, futureCourseJson.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
            appBefore = JsonSerializer.Serialize(app);
            spellingBefore = JsonSerializer.Serialize(spellingStore.Load());
            sentenceBefore = JsonSerializer.Serialize(sentenceStore.Load());
            listeningBefore = JsonSerializer.Serialize(listeningStore.Load());
            courseBefore = JsonSerializer.Serialize(courseStore.Load());
            rejected = false;
            try { _ = service.Import(future, app, new[] { knownId }, new[] { dictionaryId }); }
            catch (InvalidDataException) { rejected = true; }
            Require(rejected, "Future Course/Story state schema was accepted by an older unified-profile importer.");
            Require(JsonSerializer.Serialize(app) == appBefore &&
                    JsonSerializer.Serialize(spellingStore.Load()) == spellingBefore &&
                    JsonSerializer.Serialize(sentenceStore.Load()) == sentenceBefore &&
                    JsonSerializer.Serialize(listeningStore.Load()) == listeningBefore &&
                    JsonSerializer.Serialize(courseStore.Load()) == courseBefore,
                "Rejected future Course/Story schema mutated existing personal state.");

            Console.WriteLine("WordDeck unified profile acceptance passed: schema-5 Recall+Spelling+Sentence+Listening+Course/Story export/import/recovery, schema-4/3/2 non-destructive compatibility, and fail-closed corpus/future-course-schema behavior verified.");
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