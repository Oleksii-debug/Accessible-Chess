using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class LearnerCourseStateRecoverySelfTest
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
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck course recovery Київ {Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            ValidateSemanticPrimaryFallbackAndBackupPreservation(Path.Combine(root, "semantic recovery"));
            ValidateOpaqueNewerSchemaFailClosed(Path.Combine(root, "future schema"));
            ValidateDirectLegacyWriteRequiresMigration(Path.Combine(root, "legacy write"));
            ValidateCaseInsensitiveStableIdentity(Path.Combine(root, "stable identity"));
            ValidateUndefinedEnumValuesFailClosed(Path.Combine(root, "undefined enum"));
            Console.WriteLine("WordDeck learner course-state recovery acceptance passed: semantic corruption falls back to a validated fixed backup, invalid primary bytes cannot replace that backup, opaque newer schemas fail closed before downgrade overwrite, legacy writes require explicit migration, stable-ID maps remain case-insensitive across persistence, case-colliding identities fail closed, and undefined persisted enum values are rejected.");
        }
        finally
        {
            try { if (Directory.Exists(root)) Directory.Delete(root, true); } catch { }
        }
    }

    private static void ValidateSemanticPrimaryFallbackAndBackupPreservation(string root)
    {
        Directory.CreateDirectory(root);
        var store = new LearnerCourseStateStore(root);
        LearnerCourseState state = LearnerCourseStateStore.NewEmpty();
        state.EvidenceHistory.Add(new LearnerEvidenceEvent
        {
            EventId = "ev-good",
            ActivityKind = LearnerActivityKind.Exposure,
            PathId = "complete-english:a1",
            CourseId = "complete-english-a1",
            LexicalEntryIds = new List<string>(),
            AttemptNumber = 1
        });

        store.Save(state);
        state.OrphanedStableIds.Add("old-objective-kept-for-continuity");
        store.Save(state);

        string primaryPath = Path.Combine(root, LearnerCourseStateStore.FileName);
        string backupPath = Path.Combine(root, LearnerCourseStateStore.BackupFileName);
        Require(File.Exists(backupPath), "Recovery fixture did not create a fixed backup.");
        string goodBackupBytes = File.ReadAllText(backupPath);

        // The primary remains syntactically valid JSON and deserializes into the
        // model, but violates semantic state invariants via a duplicate event ID.
        string semanticallyInvalidPrimary = """
        {
          "SchemaVersion": 1,
          "CoursePositionsByPathId": {},
          "EvidenceHistory": [
            {
              "EventId": "dup",
              "ActivityKind": "Exposure",
              "PathId": "complete-english:a1",
              "CourseId": "complete-english-a1",
              "LexicalEntryIds": [],
              "AttemptNumber": 1
            },
            {
              "EventId": "dup",
              "ActivityKind": "Exposure",
              "PathId": "complete-english:a1",
              "CourseId": "complete-english:a1",
              "LexicalEntryIds": [],
              "AttemptNumber": 1
            }
          ],
          "MasteryByObjectiveId": {},
          "AdaptiveRouteByPathId": {},
          "SkillLevelsBySkillId": {},
          "OrphanedStableIds": []
        }
        """;
        File.WriteAllText(primaryPath, semanticallyInvalidPrimary);

        LearnerCourseState recovered = store.Load();
        Require(recovered.EvidenceHistory.Count == 1 && recovered.EvidenceHistory[0].EventId == "ev-good",
            "Semantically invalid primary did not recover from the fixed validated backup.");

        // A subsequent valid save must replace the bad primary without first
        // copying those corrupt-but-parseable bytes over the good fixed backup.
        store.Save(recovered);
        Require(File.ReadAllText(backupPath) == goodBackupBytes,
            "Semantically invalid primary overwrote the last known-good fixed backup.");
        Require(store.Load().EvidenceHistory.Single().EventId == "ev-good",
            "State was not readable after recovery save.");
    }

    private static void ValidateOpaqueNewerSchemaFailClosed(string root)
    {
        Directory.CreateDirectory(root);
        var store = new LearnerCourseStateStore(root);
        LearnerCourseState current = LearnerCourseStateStore.NewEmpty();
        current.EvidenceHistory.Add(new LearnerEvidenceEvent
        {
            EventId = "ev-current",
            ActivityKind = LearnerActivityKind.Assessment,
            PathId = "complete-english:b1",
            CourseId = "complete-english-b1",
            AssessmentId = "checkpoint-b1",
            LexicalEntryIds = new List<string>(),
            AttemptNumber = 1
        });
        store.Save(current);

        string importPath = Path.Combine(root, "compatible-import.json");
        store.ExportSnapshot(current, importPath);
        string primaryPath = Path.Combine(root, LearnerCourseStateStore.FileName);

        // Future schema deliberately contains an unknown enum value so full model
        // deserialization by this build can fail. The top-level schema envelope
        // must still be recognized and protected from downgrade writes.
        string opaqueFutureBytes = """
        {
          "SchemaVersion": 999,
          "CoursePositionsByPathId": {},
          "EvidenceHistory": [
            {
              "EventId": "future-event",
              "ActivityKind": "FutureImmersiveAssessment",
              "PathId": "future:path",
              "CourseId": "future-course",
              "LexicalEntryIds": [],
              "AttemptNumber": 1
            }
          ],
          "MasteryByObjectiveId": {},
          "AdaptiveRouteByPathId": {},
          "SkillLevelsBySkillId": {},
          "OrphanedStableIds": []
        }
        """;
        File.WriteAllText(primaryPath, opaqueFutureBytes);

        RequireThrowsInvalidData(() => _ = store.Load(),
            "Opaque newer primary schema fell back to older data instead of failing closed.");
        Require(File.ReadAllText(primaryPath) == opaqueFutureBytes,
            "Rejected newer state was mutated by Load.");

        RequireThrowsInvalidData(() => store.Save(current),
            "Older build overwrote a persisted newer schema during Save.");
        Require(File.ReadAllText(primaryPath) == opaqueFutureBytes,
            "Rejected newer state was mutated by Save.");

        RequireThrowsInvalidData(() => _ = store.ImportSnapshot(importPath),
            "Compatible import was allowed to overwrite a persisted newer local schema.");
        Require(File.ReadAllText(primaryPath) == opaqueFutureBytes,
            "Rejected import mutated persisted newer local state.");
    }

    private static void ValidateDirectLegacyWriteRequiresMigration(string root)
    {
        Directory.CreateDirectory(root);
        var store = new LearnerCourseStateStore(root);
        LearnerCourseState legacy = LearnerCourseStateStore.NewEmpty();
        legacy.SchemaVersion = 0;

        RequireThrowsInvalidData(() => store.Save(legacy),
            "Direct legacy-schema save silently upgraded state without an explicit backed-up migration path.");
        Require(!File.Exists(Path.Combine(root, LearnerCourseStateStore.FileName)),
            "Rejected legacy direct write still created course state.");
    }

    private static void ValidateCaseInsensitiveStableIdentity(string root)
    {
        Directory.CreateDirectory(root);
        string primaryPath = Path.Combine(root, LearnerCourseStateStore.FileName);
        string oneLogicalPath = """
        {
          "SchemaVersion": 1,
          "CoursePositionsByPathId": {
            "complete-english:a1": {
              "PathId": "complete-english:a1",
              "CourseId": "complete-english-a1"
            }
          },
          "EvidenceHistory": [],
          "MasteryByObjectiveId": {},
          "AdaptiveRouteByPathId": {},
          "SkillLevelsBySkillId": {},
          "OrphanedStableIds": []
        }
        """;
        File.WriteAllText(primaryPath, oneLogicalPath);

        var store = new LearnerCourseStateStore(root);
        LearnerCourseState loaded = store.Load();
        Require(loaded.CoursePositionsByPathId.ContainsKey("COMPLETE-ENGLISH:A1"),
            "Deserialized course-position stable IDs lost case-insensitive lookup semantics.");
        loaded.CoursePositionsByPathId["COMPLETE-ENGLISH:A1"] = new CoursePositionBookmark
        {
            PathId = "COMPLETE-ENGLISH:A1",
            CourseId = "complete-english-a1"
        };
        Require(loaded.CoursePositionsByPathId.Count == 1,
            "Case-only stable-ID update created a second logical course position after load.");

        string duplicateLogicalPaths = """
        {
          "SchemaVersion": 1,
          "CoursePositionsByPathId": {
            "complete-english:a1": {
              "PathId": "complete-english:a1",
              "CourseId": "complete-english-a1"
            },
            "COMPLETE-ENGLISH:A1": {
              "PathId": "COMPLETE-ENGLISH:A1",
              "CourseId": "complete-english-a1"
            }
          },
          "EvidenceHistory": [],
          "MasteryByObjectiveId": {},
          "AdaptiveRouteByPathId": {},
          "SkillLevelsBySkillId": {},
          "OrphanedStableIds": []
        }
        """;
        File.WriteAllText(primaryPath, duplicateLogicalPaths);
        RequireThrowsInvalidData(() => _ = store.Load(),
            "Case-colliding course-position stable IDs were accepted as separate identities.");
    }

    private static void ValidateUndefinedEnumValuesFailClosed(string root)
    {
        Directory.CreateDirectory(root);
        string primaryPath = Path.Combine(root, LearnerCourseStateStore.FileName);
        string undefinedActivityKind = """
        {
          "SchemaVersion": 1,
          "CoursePositionsByPathId": {},
          "EvidenceHistory": [
            {
              "EventId": "ev-undefined-kind",
              "ActivityKind": 999,
              "PathId": "complete-english:a1",
              "CourseId": "complete-english-a1",
              "LexicalEntryIds": [],
              "AttemptNumber": 1
            }
          ],
          "MasteryByObjectiveId": {},
          "AdaptiveRouteByPathId": {},
          "SkillLevelsBySkillId": {},
          "OrphanedStableIds": []
        }
        """;
        File.WriteAllText(primaryPath, undefinedActivityKind);
        var store = new LearnerCourseStateStore(root);
        RequireThrowsInvalidData(() => _ = store.Load(),
            "Undefined numeric LearnerActivityKind was accepted as valid current-schema state.");

        string undefinedAdaptiveRoute = """
        {
          "SchemaVersion": 1,
          "CoursePositionsByPathId": {},
          "EvidenceHistory": [],
          "MasteryByObjectiveId": {},
          "AdaptiveRouteByPathId": {
            "complete-english:a1": {
              "PathId": "complete-english:a1",
              "Route": 999,
              "RuleVersion": "fixture-rule-v1",
              "ReasonCode": "fixture",
              "EvidenceEventIds": []
            }
          },
          "SkillLevelsBySkillId": {},
          "OrphanedStableIds": []
        }
        """;
        File.WriteAllText(primaryPath, undefinedAdaptiveRoute);
        RequireThrowsInvalidData(() => _ = store.Load(),
            "Undefined numeric AdaptivePracticeRoute was accepted as valid current-schema state.");
    }

    private static void RequireThrowsInvalidData(Action action, string message)
    {
        bool rejected = false;
        try { action(); }
        catch (InvalidDataException) { rejected = true; }
        Require(rejected, message);
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }
}