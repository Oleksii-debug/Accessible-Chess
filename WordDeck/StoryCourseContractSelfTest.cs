using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class StoryCourseContractSelfTest
{
    public static void Run()
    {
        DictionaryPackage dictionary = BuildDictionary();
        StoryCourseManifestContract fixture = BuildFixture();

        StoryCourseContractValidator.Validate(fixture, dictionary);

        StoryCourseUnitContract unit = fixture.Levels[0].Modules[0].Units[0];
        ResolvedStoryCourseTargets resolved = StoryCourseIdentityResolver.Resolve(dictionary, unit.Targets, unit.UnitId);
        Require(resolved.LexicalEntries.Count == 2, "Stable lexical targets were not resolved by entry ID.");
        Require(resolved.LexicalEntries[0].Id == "lex.light.n" && resolved.LexicalEntries[1].Id == "lex.light.v",
            "Same-surface lexical entries lost their distinct canonical IDs.");
        Require(resolved.GrammarSkillIds.Count == 1 && resolved.GrammarSkillIds[0] == "present.simple.core",
            "Story/Course did not delegate Grammar alias normalization and deduplication to the canonical resolver.");

        ExpectInvalid(
            () => StoryCourseIdentityResolver.Resolve(
                dictionary,
                unit.Targets with { LexicalEntryIds = new[] { "lex.unknown" } },
                unit.UnitId),
            "Unknown stable lexical target did not fail closed.");

        ExpectInvalid(
            () => StoryCourseIdentityResolver.Resolve(
                dictionary,
                unit.Targets with { GrammarSkillIds = new[] { "grammar.nonexistent-skill" } },
                unit.UnitId),
            "Unknown canonical Grammar reference did not fail closed.");

        ExpectInvalid(
            () => StoryCourseContractValidator.Validate(
                fixture with { ClaimsCompleteEnglishCourse = true },
                dictionary),
            "Technical fixture was allowed to claim Complete English authority.");

        ExpectInvalid(
            () => StoryCourseContractValidator.Validate(
                fixture with
                {
                    CurriculumAuthority = StoryCourseCurriculumAuthority.ApprovedCurriculum,
                    ClaimsCompleteEnglishCourse = true
                },
                dictionary),
            "Generated fixture provenance bypassed Complete English authority by setting ApprovedCurriculum.");

        StoryCourseProvenanceContract approvedProvenance = new(
            StoryCourseContentOrigin.WordDeckAuthored,
            "approved.curriculum.test",
            "1",
            "WordDeck-owned approved curriculum test provenance",
            "");
        StoryCourseManifestContract topLevelApprovedClaim = fixture with
        {
            CurriculumAuthority = StoryCourseCurriculumAuthority.ApprovedCurriculum,
            ClaimsCompleteEnglishCourse = true,
            Provenance = approvedProvenance
        };
        ExpectInvalid(
            () => StoryCourseContractValidator.Validate(topLevelApprovedClaim, dictionary),
            "Nested generated-fixture provenance was allowed to ride inside a Complete English course claim.");

        StoryCourseObjectiveContract moduleOnlyObjective = new(
            "objective.module-only",
            "Module objective intentionally not owned by the fixture unit.",
            new[] { "comprehension" });
        StoryCourseModuleContract sourceModule = fixture.Levels[0].Modules[0];

        StoryCourseNarrativeContract approvedContext = unit.DialogueOrStory[0] with
        {
            Provenance = approvedProvenance
        };
        StoryCourseProvenanceContract learnerLocalProvenance = new(
            StoryCourseContentOrigin.LearnerLocal,
            "learner.local.story.test",
            "1",
            "Private learner-local content; never curriculum authority",
            "");
        StoryCourseUnitContract learnerLocalUnit = unit with
        {
            Provenance = learnerLocalProvenance,
            DialogueOrStory = new[] { approvedContext }
        };
        StoryCourseModuleContract learnerLocalModule = sourceModule with
        {
            Units = new[] { learnerLocalUnit }
        };
        StoryCourseLevelContract learnerLocalLevel = fixture.Levels[0] with
        {
            Modules = new[] { learnerLocalModule }
        };
        ExpectInvalid(
            () => StoryCourseContractValidator.Validate(
                topLevelApprovedClaim with { Levels = new[] { learnerLocalLevel } },
                dictionary),
            "Nested learner-local unit provenance was allowed inside a Complete English course claim.");

        StoryCourseUnitContract approvedUnitWithGeneratedNarrative = unit with
        {
            Provenance = approvedProvenance
        };
        StoryCourseModuleContract generatedNarrativeModule = sourceModule with
        {
            Units = new[] { approvedUnitWithGeneratedNarrative }
        };
        StoryCourseLevelContract generatedNarrativeLevel = fixture.Levels[0] with
        {
            Modules = new[] { generatedNarrativeModule }
        };
        ExpectInvalid(
            () => StoryCourseContractValidator.Validate(
                topLevelApprovedClaim with { Levels = new[] { generatedNarrativeLevel } },
                dictionary),
            "Nested generated narrative provenance was allowed inside a Complete English course claim.");

        StoryCourseComprehensionTaskContract crossUnitTask = unit.ComprehensionTasks[0] with
        {
            ObjectiveIds = new[] { moduleOnlyObjective.ObjectiveId }
        };
        StoryCourseUnitContract crossUnitEvidence = unit with
        {
            ComprehensionTasks = new[] { crossUnitTask }
        };
        StoryCourseModuleContract crossUnitModule = sourceModule with
        {
            Objectives = new[] { sourceModule.Objectives[0], moduleOnlyObjective },
            Units = new[] { crossUnitEvidence }
        };
        StoryCourseLevelContract crossUnitLevel = fixture.Levels[0] with
        {
            Modules = new[] { crossUnitModule }
        };
        ExpectInvalid(
            () => StoryCourseContractValidator.Validate(fixture with { Levels = new[] { crossUnitLevel } }, dictionary),
            "A task was allowed to claim evidence for a module objective that its unit did not own.");

        var exposureOnly = new StoryCourseObjectiveProgressContract(
            "objective.describe-light",
            ExposureCount: 12,
            ComprehensionEvidenceCount: 0,
            ProductiveEvidenceCount: 0,
            CheckpointEvidenceCount: 0,
            MasteryDecision: StoryCourseMasteryDecision.Unknown,
            DecisionAuthority: null);
        exposureOnly.Validate();
        Require(exposureOnly.MasteryDecision == StoryCourseMasteryDecision.Unknown,
            "Exposure-only progress was silently promoted to mastery.");

        ExpectInvalid(
            () => new StoryCourseObjectiveProgressContract(
                "objective.describe-light", 12, 4, 1, 0,
                StoryCourseMasteryDecision.Mastered, null).Validate(),
            "Mastery without an explicit decision authority was accepted.");

        ExpectInvalid(
            () => (exposureOnly with
            {
                MasteryDecision = (StoryCourseMasteryDecision)999,
                DecisionAuthority = "assessment.invalid-enum"
            }).Validate(),
            "Unknown mastery enum value was accepted.");

        var assessed = new StoryCourseObjectiveProgressContract(
            "objective.describe-light", 12, 4, 2, 1,
            StoryCourseMasteryDecision.Mastered, "assessment.unit-checkpoint.v1");
        var progress = new StoryCourseProgressContract(
            SchemaVersion: 1,
            CourseId: fixture.CourseId,
            ActiveLevelId: "level.a1",
            ActiveModuleId: "module.a1.fixture",
            ActiveUnitId: "unit.a1.fixture-01",
            CompletedContentIds: new[] { "context.a1.fixture-dialogue" },
            CompletedTaskIds: new[] { "task.a1.comprehension", "task.a1.production" },
            ObjectiveProgress: new Dictionary<string, StoryCourseObjectiveProgressContract>(StringComparer.OrdinalIgnoreCase)
            {
                [assessed.ObjectiveId] = assessed
            });
        progress.Validate();

        ExpectInvalid(
            () => (progress with { CompletedTaskIds = new[] { "task id with spaces" } }).Validate(),
            "Progress completed-task collection accepted a non-stable identifier.");

        Console.WriteLine("WordDeck Story/Course contract self-test PASS.");
    }

    private static DictionaryPackage BuildDictionary() => new()
    {
        Id = "dictionary.test",
        Name = "Story contract fixture dictionary",
        SourceLanguage = "en",
        TargetLanguage = "uk",
        Entries = new[]
        {
            // Deliberately identical surface form: the contract must keep stable IDs distinct.
            new DictionaryEntry("lex.light.n", "A1", "light", "світло"),
            new DictionaryEntry("lex.light.v", "A1", "light", "запалювати")
        }
    };

    private static StoryCourseManifestContract BuildFixture()
    {
        StoryCourseProvenanceContract fixtureProvenance = new(
            StoryCourseContentOrigin.GeneratedFixture,
            "story-contract-self-test",
            "1",
            "Test-only generated fixture; not curriculum",
            "");

        StoryCourseObjectiveContract objective = new(
            "objective.describe-light",
            "Produce and understand a short utterance using the assigned canonical lexical targets.",
            new[] { "comprehension", "production" });

        StoryCourseTargetsContract targets = new(
            new[] { "lex.light.n", "lex.light.v" },
            new[] { "grammar.present-simple.statement", "present.simple.core" });

        StoryCourseNarrativeContract context = new(
            "context.a1.fixture-dialogue",
            StoryCourseNarrativeKind.Dialogue,
            "A: I see the light. B: I light the lamp.",
            new[] { "speaker.a", "speaker.b" },
            fixtureProvenance);

        StoryCourseComprehensionTaskContract comprehension = new(
            "task.a1.comprehension",
            StoryCourseComprehensionKind.BoundedResponse,
            "Which canonical target is used as a noun?",
            new[] { objective.ObjectiveId },
            new[] { "light" });

        StoryCourseProductiveTaskContract production = new(
            "task.a1.production",
            StoryCourseProductiveChannel.Speaking,
            "Produce a new short sentence using one assigned target.",
            new[] { objective.ObjectiveId },
            "assessment.productive.fixture");

        StoryCourseCheckpointContract checkpoint = new(
            "checkpoint.a1.fixture",
            new[] { objective.ObjectiveId },
            "assessment.unit-checkpoint.fixture",
            UsesUnseenMaterial: true);

        StoryCourseUnitContract unit = new(
            "unit.a1.fixture-01",
            "module.a1.fixture",
            "Technical fixture unit",
            new[] { objective.ObjectiveId },
            targets,
            new[] { context },
            new[] { comprehension },
            new[] { production },
            checkpoint,
            fixtureProvenance);

        StoryCourseModuleContract module = new(
            "module.a1.fixture",
            "level.a1",
            "Technical fixture module",
            new[] { objective },
            new[] { unit });

        StoryCourseLevelContract level = new(
            "level.a1",
            "A1",
            "Technical A1 fixture",
            Sequence: 1,
            Modules: new[] { module });

        return new StoryCourseManifestContract(
            "course.story-runtime-fixture",
            "Story/Course runtime contract fixture",
            StoryCourseCurriculumAuthority.TechnicalFixture,
            ClaimsCompleteEnglishCourse: false,
            Levels: new[] { level },
            Provenance: fixtureProvenance);
    }

    private static void ExpectInvalid(Action action, string message)
    {
        bool rejected = false;
        try { action(); }
        catch (InvalidDataException) { rejected = true; }
        Require(rejected, message);
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException("Story/Course contract self-test failed: " + message);
    }
}

internal static class StoryCourseContractSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            StoryCourseContractSelfTest.Run();
    }
}
