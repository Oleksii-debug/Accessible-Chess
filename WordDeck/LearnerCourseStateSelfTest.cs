using System.Runtime.CompilerServices;
using System.Text.Json;

namespace WordDeck;

internal static class LearnerCourseStateSelfTest
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
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck course state Київ {Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            const string hiddenEntryId = "lex-hidden-1";
            var appStore = new AppStateStore(root);
            AppState recall = AppStateStore.Normalize(new AppState { ActiveDictionaryId = "oxford-3000-en-uk" });
            recall.HiddenEntryIds.Add(hiddenEntryId);
            UserProgressService.RecordSeen(recall, hiddenEntryId, StudyScopeIds.A2, DeckIds.Core(2));
            appStore.Save(recall);

            var courseStore = new LearnerCourseStateStore(root);
            LearnerCourseState state = courseStore.Load();
            Require(state.EvidenceHistory.Count == 0 && state.MasteryByObjectiveId.Count == 0,
                "Fresh course state must not infer mastery from existing Recall history.");

            const string completeA2Path = "complete-english:a2";
            const string listeningA2Path = "deep:listening:a2";
            state.CatalogVersion = "contract-fixture-v1";
            state.CoursePositionsByPathId[completeA2Path] = new CoursePositionBookmark
            {
                PathId = completeA2Path,
                CourseId = "complete-english-a2",
                ModuleId = "travel-services",
                UnitId = "travel-problems",
                ActivityId = "dialogue-1"
            };
            state.CoursePositionsByPathId[listeningA2Path] = new CoursePositionBookmark
            {
                PathId = listeningA2Path,
                CourseId = "deep-listening-a2",
                ModuleId = "connected-speech",
                UnitId = "weak-forms",
                ActivityId = "listen-2"
            };

            state.EvidenceHistory.Add(new LearnerEvidenceEvent
            {
                EventId = "ev-exposure",
                ActivityKind = LearnerActivityKind.Exposure,
                PathId = completeA2Path,
                CourseId = "complete-english-a2",
                ModuleId = "travel-services",
                ObjectiveId = "obj-hotel-request",
                SkillId = "listening",
                ItemId = "dialogue-1",
                LexicalEntryIds = new List<string> { hiddenEntryId },
                Completed = true,
                RevealUses = 1,
                AttemptNumber = 1
            });
            Require(!state.MasteryByObjectiveId.ContainsKey("obj-hotel-request"),
                "Exposure must not automatically become mastery.");

            state.EvidenceHistory.Add(new LearnerEvidenceEvent
            {
                EventId = "ev-practice",
                ActivityKind = LearnerActivityKind.Practice,
                PathId = completeA2Path,
                CourseId = "complete-english-a2",
                ModuleId = "travel-services",
                ObjectiveId = "obj-hotel-request",
                SkillId = "speaking-pronunciation",
                ItemId = "roleplay-1",
                Completed = true,
                Correct = true,
                IsProductivePerformance = true,
                AttemptNumber = 2
            });
            Require(!state.MasteryByObjectiveId.ContainsKey("obj-hotel-request"),
                "Ordinary practice must not automatically become mastery.");

            state.EvidenceHistory.Add(new LearnerEvidenceEvent
            {
                EventId = "ev-assessment-transfer",
                ActivityKind = LearnerActivityKind.Assessment,
                PathId = completeA2Path,
                CourseId = "complete-english-a2",
                ObjectiveId = "obj-hotel-request",
                SkillId = "speaking-pronunciation",
                ItemId = "unseen-roleplay-7",
                AssessmentId = "a2-module-challenge-3",
                Completed = true,
                Correct = true,
                IsUnseenMaterial = true,
                IsProductivePerformance = true,
                IsTransferPerformance = true,
                AttemptNumber = 1
            });
            state.MasteryByObjectiveId["obj-hotel-request"] = new MasteryClaim
            {
                ObjectiveId = "obj-hotel-request",
                Demonstrated = true,
                RuleVersion = "approved-rule-placeholder-v1",
                EvidenceEventIds = new List<string> { "ev-assessment-transfer" }
            };
            state.AdaptiveRouteByPathId[completeA2Path] = new AdaptiveRouteDecision
            {
                PathId = completeA2Path,
                Route = AdaptivePracticeRoute.FastTrack,
                RuleVersion = "approved-router-placeholder-v1",
                ReasonCode = "productive-transfer-evidence",
                EvidenceEventIds = new List<string> { "ev-assessment-transfer" }
            };

            state.EvidenceHistory.Add(new LearnerEvidenceEvent
            {
                EventId = "ev-listening-weakness",
                ActivityKind = LearnerActivityKind.Assessment,
                PathId = listeningA2Path,
                CourseId = "deep-listening-a2",
                ObjectiveId = "obj-connected-speech-detail",
                SkillId = "listening",
                ItemId = "unseen-audio-4",
                AssessmentId = "skills-diagnostic-fixture",
                Completed = true,
                Correct = false,
                IsUnseenMaterial = true,
                AttemptNumber = 1
            });
            state.AdaptiveRouteByPathId[listeningA2Path] = new AdaptiveRouteDecision
            {
                PathId = listeningA2Path,
                Route = AdaptivePracticeRoute.DeepPractice,
                RuleVersion = "approved-router-placeholder-v1",
                ReasonCode = "skill-specific-weakness",
                EvidenceEventIds = new List<string> { "ev-listening-weakness" }
            };
            state.SkillLevelsBySkillId["listening"] = new SkillLevelEstimate
            {
                SkillId = "listening",
                LevelId = "a2",
                SourceAssessmentId = "skills-diagnostic-fixture",
                EvidenceEventIds = new List<string> { "ev-listening-weakness" }
            };
            state.SkillLevelsBySkillId["overall"] = new SkillLevelEstimate
            {
                SkillId = "overall",
                LevelId = "b1",
                SourceAssessmentId = "skills-diagnostic-fixture",
                EvidenceEventIds = new List<string> { "ev-assessment-transfer", "ev-listening-weakness" }
            };

            courseStore.Save(state);
            LearnerCourseState loaded = courseStore.Load();
            Require(loaded.EvidenceHistory.Select(x => x.ActivityKind).SequenceEqual(new[]
                {
                    LearnerActivityKind.Exposure,
                    LearnerActivityKind.Practice,
                    LearnerActivityKind.Assessment,
                    LearnerActivityKind.Assessment
                }), "Exposure/practice/assessment distinctions did not survive persistence.");
            Require(loaded.MasteryByObjectiveId["obj-hotel-request"].EvidenceEventIds.Single() == "ev-assessment-transfer",
                "Mastery provenance did not survive persistence.");
            Require(loaded.AdaptiveRouteByPathId[completeA2Path].Route == AdaptivePracticeRoute.FastTrack &&
                    loaded.AdaptiveRouteByPathId[listeningA2Path].Route == AdaptivePracticeRoute.DeepPractice,
                "Fast Track and Deep Practice routing did not remain independent.");
            Require(loaded.SkillLevelsBySkillId["listening"].LevelId == "a2" && loaded.SkillLevelsBySkillId["overall"].LevelId == "b1",
                "Independent skill-level estimates were collapsed into overall level.");
            Require(loaded.CoursePositionsByPathId.Count == 2,
                "Complete English and Deep Skill course positions did not remain independent.");

            // Writing the additive sidecar must not mutate or reinterpret current
            // Recall hidden-word/history state.
            AppState recallAfterCourseSave = appStore.Load();
            Require(recallAfterCourseSave.HiddenEntryIds.Contains(hiddenEntryId),
                "Course-state save changed existing hidden-word state.");
            Require(recallAfterCourseSave.StudyHistoryByEntryId[hiddenEntryId].SeenCount == 1,
                "Course-state save changed existing Recall study history.");

            // A second verified save must leave a fixed recovery copy.
            loaded.OrphanedStableIds.Add("future-objective-no-longer-in-catalog");
            courseStore.Save(loaded);
            Require(File.Exists(Path.Combine(root, LearnerCourseStateStore.BackupFileName)),
                "Course-state save did not retain a verified recovery backup.");

            // Export/import is self-contained for the future profile layer and the
            // destination is backed up before replacement.
            string export = Path.Combine(root, "course-state-export.json");
            courseStore.ExportSnapshot(loaded, export);
            loaded.CoursePositionsByPathId.Clear();
            courseStore.Save(loaded);
            LearnerCourseStateImportResult import = courseStore.ImportSnapshot(export);
            Require(!string.IsNullOrWhiteSpace(import.BackupPath) && File.Exists(import.BackupPath!),
                "Course-state import did not create a pre-import recovery backup.");
            Require(courseStore.Load().CoursePositionsByPathId.Count == 2,
                "Course-state import did not restore the exported course positions.");

            // A future schema must fail closed before replacing any existing state.
            string beforeNewerReject = File.ReadAllText(Path.Combine(root, LearnerCourseStateStore.FileName));
            string newer = Path.Combine(root, "course-state-newer.json");
            using (JsonDocument currentDoc = JsonDocument.Parse(beforeNewerReject))
            {
                var values = JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(currentDoc.RootElement.GetRawText())!;
                values["SchemaVersion"] = JsonDocument.Parse("999").RootElement.Clone();
                File.WriteAllText(newer, JsonSerializer.Serialize(values));
            }
            bool newerRejected = false;
            try { _ = courseStore.ImportSnapshot(newer); }
            catch (InvalidDataException) { newerRejected = true; }
            Require(newerRejected, "Newer incompatible course-state schema was accepted.");
            Require(File.ReadAllText(Path.Combine(root, LearnerCourseStateStore.FileName)) == beforeNewerReject,
                "Rejected newer course-state import mutated existing state.");

            // Schema-0 migration is intentionally semantic-free but still backed up.
            string migrationRoot = Path.Combine(root, "migration fixture");
            Directory.CreateDirectory(migrationRoot);
            string legacyPath = Path.Combine(migrationRoot, LearnerCourseStateStore.FileName);
            File.WriteAllText(legacyPath, "{\"SchemaVersion\":0,\"CoursePositionsByPathId\":{},\"EvidenceHistory\":[],\"MasteryByObjectiveId\":{},\"AdaptiveRouteByPathId\":{},\"SkillLevelsBySkillId\":{},\"OrphanedStableIds\":[]}");
            var migrationStore = new LearnerCourseStateStore(migrationRoot);
            LearnerCourseState migrated = migrationStore.Load();
            Require(migrated.SchemaVersion == LearnerCourseStateStore.CurrentSchemaVersion,
                "Course-state schema-0 migration did not reach the current schema.");
            Require(Directory.EnumerateFiles(Path.Combine(migrationRoot, "Backups"), "*pre-migration*.json").Any(),
                "Course-state migration occurred without a pre-migration backup.");
            Require(migrated.EvidenceHistory.Count == 0 && migrated.MasteryByObjectiveId.Count == 0,
                "Schema migration invented learning evidence or mastery.");

            // Unknown future fields must survive load/save so an older compatible
            // build does not erase data it does not understand.
            string extensionRoot = Path.Combine(root, "extension fixture");
            Directory.CreateDirectory(extensionRoot);
            string extensionPath = Path.Combine(extensionRoot, LearnerCourseStateStore.FileName);
            File.WriteAllText(extensionPath, "{\"SchemaVersion\":1,\"CatalogVersion\":\"x\",\"CoursePositionsByPathId\":{},\"EvidenceHistory\":[],\"MasteryByObjectiveId\":{},\"AdaptiveRouteByPathId\":{},\"SkillLevelsBySkillId\":{},\"OrphanedStableIds\":[],\"FutureOpaqueField\":{\"keep\":true}}");
            var extensionStore = new LearnerCourseStateStore(extensionRoot);
            LearnerCourseState extensionState = extensionStore.Load();
            extensionStore.Save(extensionState);
            using JsonDocument extensionDoc = JsonDocument.Parse(File.ReadAllText(extensionPath));
            Require(extensionDoc.RootElement.TryGetProperty("FutureOpaqueField", out JsonElement opaque) && opaque.GetProperty("keep").GetBoolean(),
                "Unknown future course-state data was lost during load/save.");

            Console.WriteLine("WordDeck learner course-state acceptance passed: exposure/practice/mastery/assessment separation, Fast Track/Deep Practice routing, independent course positions/skill estimates, LocalAppData sidecar continuity, backups, import/export, fail-closed newer schema, non-destructive migration and unknown-field preservation verified.");
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
