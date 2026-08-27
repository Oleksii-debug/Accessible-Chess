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
