using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class StoryCourseLearnerStateBridgeSelfTest
{
    public static void Run()
    {
        string root = Path.Combine(Path.GetTempPath(), "worddeck-course-state-bridge-Київ-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            StoryCourseManifestContract manifest = BuildManifest();
            var store = new LearnerCourseStateStore(root);
            var eventIds = new Queue<string>(new[]
            {
                "bridge.ev.exposure",
                "bridge.ev.comp.1",
                "bridge.ev.comp.2",
                "bridge.ev.speaking.fallback",
                "bridge.ev.speaking.real",
                "bridge.ev.writing",
                "bridge.ev.duplicate",
                "bridge.ev.duplicate"
            });
            DateTimeOffset now = new(2026, 9, 12, 18, 0, 0, TimeSpan.Zero);
            var bridge = new StoryCourseLearnerStateBridge(
                store,
                () => eventIds.Dequeue(),
                () => now);

            LearnerCourseState selected = bridge.RecordUnitSelection(
                manifest,
                "module.bridge",
                "unit.bridge",
                "context.bridge");
            string pathId = StoryCourseLearnerStateBridge.BuildPathId(manifest);
            Require(selected.CoursePositionsByPathId[pathId].ActivityId == "context.bridge",
                "unit selection did not persist the exact manifest-owned activity id");
            Require(selected.EvidenceHistory.Count == 0 && selected.MasteryByObjectiveId.Count == 0,
                "navigation state manufactured learning evidence or mastery");

            StoryCourseManifestContract technicalFixture = manifest with
            {
                CurriculumAuthority = StoryCourseCurriculumAuthority.TechnicalFixture
            };
            ExpectInvalid(
                () => bridge.RecordUnitSelection(technicalFixture, "module.bridge", "unit.bridge", "context.bridge"),
                "technical fixture was allowed to write learner course state");
            StoryCourseManifestContract pedagogicalDraft = manifest with
            {
                CurriculumAuthority = StoryCourseCurriculumAuthority.PedagogicalDraft
            };
            ExpectInvalid(
                () => bridge.RecordUnitSelection(pedagogicalDraft, "module.bridge", "unit.bridge", "context.bridge"),
                "pedagogical draft was allowed to write learner course state");

            LearnerCourseState exposed = bridge.RecordNarrativeExposure(
                manifest,
                "module.bridge",
                "unit.bridge",
                "context.bridge");
            LearnerEvidenceEvent exposure = exposed.EvidenceHistory.Single();
            Require(exposure.ActivityKind == LearnerActivityKind.Exposure && exposure.ItemId == "context.bridge",
                "narrative exposure was not persisted as exposure evidence");
            Require(exposure.LexicalEntryIds.SequenceEqual(new[] { "lex.bus.n", "lex.stop.n" }),
                "narrative exposure lost stable lexical identities");
            Require(!exposure.IsProductivePerformance && exposure.Correct is null,
                "narrative exposure fabricated productive or correctness evidence");

            LearnerCourseState comprehension = bridge.RecordComprehensionPracticeAttempt(
                manifest,
                "module.bridge",
                "unit.bridge",
                "task.bridge.comprehension",
                correct: false,
                attemptNumber: 2,
                isTransfer: true);
            LearnerEvidenceEvent[] compEvents = comprehension.EvidenceHistory
                .Where(item => item.ItemId == "task.bridge.comprehension")
                .ToArray();
            Require(compEvents.Length == 2,
                "multi-objective comprehension did not retain one attributable evidence event per objective");
            Require(compEvents.Select(item => item.ObjectiveId).ToHashSet(StringComparer.OrdinalIgnoreCase)
                    .SetEquals(new[] { "objective.bridge.communication", "objective.bridge.accuracy" }),
                "multi-objective comprehension lost an objective binding");
            Require(compEvents.All(item => item.ActivityKind == LearnerActivityKind.Practice && item.Correct == false &&
                                           item.AttemptNumber == 2 && item.IsTransferPerformance),
                "comprehension practice attempt metadata changed during persistence");

            LearnerCourseState speakingFallback = bridge.RecordProductivePracticeAttempt(
                manifest,
                "module.bridge",
                "unit.bridge",
                "task.bridge.speaking",
                StoryCourseProductiveSubmissionKind.TypedFallback,
                attemptNumber: 1);
            LearnerEvidenceEvent fallback = speakingFallback.EvidenceHistory.Single(item => item.EventId == "bridge.ev.speaking.fallback");
            Require(fallback.SkillId == "typed-fallback" && !fallback.IsProductivePerformance && fallback.Correct is null,
                "typed fallback leaked into speaking evidence or fabricated judged correctness");

            LearnerCourseState speakingReal = bridge.RecordProductivePracticeAttempt(
                manifest,
                "module.bridge",
                "unit.bridge",
                "task.bridge.speaking",
                StoryCourseProductiveSubmissionKind.RequiredChannelPerformance,
                attemptNumber: 2,
                isTransfer: true);
            LearnerEvidenceEvent realSpeech = speakingReal.EvidenceHistory.Single(item => item.EventId == "bridge.ev.speaking.real");
            Require(realSpeech.IsProductivePerformance && realSpeech.SkillId == "speaking-pronunciation" && realSpeech.IsTransferPerformance,
                "explicit required-channel speaking performance was not recorded truthfully");
            Require(realSpeech.Correct is null,
                "course-state bridge fabricated a speech evaluator result");

            LearnerCourseState writing = bridge.RecordProductivePracticeAttempt(
                manifest,
                "module.bridge",
                "unit.bridge",
                "task.bridge.writing",
                StoryCourseProductiveSubmissionKind.RequiredChannelPerformance,
                attemptNumber: 1);
            LearnerEvidenceEvent written = writing.EvidenceHistory.Single(item => item.EventId == "bridge.ev.writing");
            Require(written.IsProductivePerformance && written.SkillId == "writing" && written.Correct is null,
                "writing practice was not recorded as unjudged productive evidence");

            ExpectInvalid(
                () => bridge.RecordProductivePracticeAttempt(
                    manifest,
                    "module.bridge",
                    "unit.bridge",
                    "task.bridge.writing",
                    StoryCourseProductiveSubmissionKind.TypedFallback,
                    attemptNumber: 1),
                "required writing production was allowed to masquerade as a fallback channel");
            ExpectInvalid(
                () => bridge.RecordComprehensionPracticeAttempt(
                    manifest,
                    "module.bridge",
                    "unit.bridge",
                    "task.bridge.comprehension",
                    correct: true,
                    attemptNumber: 0),
                "attempt number zero was accepted");
            ExpectInvalid(
                () => bridge.RecordUnitSelection(manifest, "module.bridge", "unit.bridge", "foreign.activity"),
                "foreign activity id was accepted under a manifest-owned unit");
            ExpectInvalid(
                () => bridge.RecordNarrativeExposure(manifest, "foreign.module", "unit.bridge", "context.bridge"),
                "foreign module id was accepted");

            StoryCourseManifestContract foreignObjective = BuildManifestWithForeignTaskObjective();
            ExpectInvalid(
                () => bridge.RecordComprehensionPracticeAttempt(
                    foreignObjective,
                    "module.bridge",
                    "unit.bridge",
                    "task.bridge.comprehension",
                    correct: true,
                    attemptNumber: 1),
                "task objective not owned by module/unit was accepted into learner evidence");

            // Duplicate event ids must fail before a new state snapshot is saved.
            LearnerCourseState beforeDuplicate = store.Load();
            int beforeDuplicateCount = beforeDuplicate.EvidenceHistory.Count;
            _ = bridge.RecordNarrativeExposure(manifest, "module.bridge", "unit.bridge", "context.bridge");
            ExpectInvalid(
                () => bridge.RecordNarrativeExposure(manifest, "module.bridge", "unit.bridge", "context.bridge"),
                "duplicate learner evidence event id was accepted");
            Require(store.Load().EvidenceHistory.Count == beforeDuplicateCount + 1,
                "failed duplicate event attempt mutated the persisted learner evidence history");

            LearnerCourseState reloaded = store.Load();
            Require(reloaded.CoursePositionsByPathId[pathId].CourseId == manifest.CourseId &&
                    reloaded.CoursePositionsByPathId[pathId].UnitId == "unit.bridge",
                "course bookmark did not survive save/reload");
            Require(reloaded.EvidenceHistory.Any(item => item.ActivityKind == LearnerActivityKind.Exposure) &&
                    reloaded.EvidenceHistory.Any(item => item.ActivityKind == LearnerActivityKind.Practice),
                "exposure/practice separation did not survive save/reload");
            Require(reloaded.MasteryByObjectiveId.Count == 0 && reloaded.AdaptiveRouteByPathId.Count == 0 &&
                    reloaded.SkillLevelsBySkillId.Count == 0,
                "ordinary course runtime events fabricated mastery, adaptive routing or skill levels");

            Console.WriteLine("WordDeck Story/Course learner-state bridge self-test PASS.");
        }
        finally
        {
            try { if (Directory.Exists(root)) Directory.Delete(root, recursive: true); } catch { }
        }
    }

    private static StoryCourseManifestContract BuildManifest()
    {
        var provenance = new StoryCourseProvenanceContract(
            StoryCourseContentOrigin.WordDeckAuthored,
            "course-state-bridge-self-test",
            "1",
            "WordDeck-owned self-test material; no release claim",
            string.Empty);
        var communication = new StoryCourseObjectiveContract(
            "objective.bridge.communication",
            "Use a simple transport exchange.",
            new[] { "comprehension", "speaking", "writing" });
        var accuracy = new StoryCourseObjectiveContract(
            "objective.bridge.accuracy",
            "Identify the correct transport detail.",
            new[] { "comprehension" });
        var targets = new StoryCourseTargetsContract(
            new[] { "lex.bus.n", "lex.stop.n" },
            new[] { "present.simple.core" });
        var narrative = new StoryCourseNarrativeContract(
            "context.bridge",
            StoryCourseNarrativeKind.Dialogue,
            "A: Is this the bus stop? B: Yes.",
            new[] { "speaker.a", "speaker.b" },
            provenance);
        var comprehension = new StoryCourseComprehensionTaskContract(
            "task.bridge.comprehension",
            StoryCourseComprehensionKind.BoundedResponse,
            "What place are they asking about?",
            new[] { communication.ObjectiveId, accuracy.ObjectiveId },
            new[] { "bus stop" });
        var speaking = new StoryCourseProductiveTaskContract(
            "task.bridge.speaking",
            StoryCourseProductiveChannel.Speaking,
            "Ask where the bus stop is.",
            new[] { communication.ObjectiveId },
            "policy.external.speaking");
        var writing = new StoryCourseProductiveTaskContract(
            "task.bridge.writing",
            StoryCourseProductiveChannel.Writing,
            "Write one sentence asking about the bus stop.",
            new[] { communication.ObjectiveId },
            "policy.external.writing");
        var unit = new StoryCourseUnitContract(
            "unit.bridge",
            "module.bridge",
            "Transport bridge fixture",
            new[] { communication.ObjectiveId, accuracy.ObjectiveId },
            targets,
            new[] { narrative },
            new[] { comprehension },
            new[] { speaking, writing },
            Checkpoint: null,
            provenance);
        var module = new StoryCourseModuleContract(
            "module.bridge",
            "level.bridge",
            "Transport",
            new[] { communication, accuracy },
            new[] { unit });
        var level = new StoryCourseLevelContract(
            "level.bridge",
            "Pre-A1",
            "Starter",
            Sequence: 1,
            Modules: new[] { module });
        return new StoryCourseManifestContract(
            "course.bridge",
            "Course learner-state bridge fixture",
            StoryCourseCurriculumAuthority.ApprovedCurriculum,
            ClaimsCompleteEnglishCourse: false,
            Levels: new[] { level },
            Provenance: provenance);
    }

    private static StoryCourseManifestContract BuildManifestWithForeignTaskObjective()
    {
        StoryCourseManifestContract manifest = BuildManifest();
        StoryCourseLevelContract level = manifest.Levels.Single();
        StoryCourseModuleContract module = level.Modules.Single();
        StoryCourseUnitContract unit = module.Units.Single();
        StoryCourseComprehensionTaskContract task = unit.ComprehensionTasks.Single();
        StoryCourseComprehensionTaskContract badTask = task with
        {
            ObjectiveIds = new[] { "objective.bridge.foreign" }
        };
        StoryCourseUnitContract badUnit = unit with
        {
            ComprehensionTasks = new[] { badTask }
        };
        StoryCourseModuleContract badModule = module with
        {
            Units = new[] { badUnit }
        };
        StoryCourseLevelContract badLevel = level with
        {
            Modules = new[] { badModule }
        };
        return manifest with { Levels = new[] { badLevel } };
    }

    private static void ExpectInvalid(Action action, string message)
    {
        try
        {
            action();
        }
        catch (InvalidDataException)
        {
            return;
        }
        throw new InvalidOperationException("Story/Course learner-state bridge self-test failed: " + message);
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException("Story/Course learner-state bridge self-test failed: " + message);
    }
}

internal static class StoryCourseLearnerStateBridgeSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            StoryCourseLearnerStateBridgeSelfTest.Run();
    }
}
