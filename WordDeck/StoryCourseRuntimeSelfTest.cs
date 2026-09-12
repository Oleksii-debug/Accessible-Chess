using System.Runtime.CompilerServices;
using System.Text.Json;

namespace WordDeck;

internal static class StoryCourseRuntimeSelfTest
{
    public static void Run()
    {
        string root = Path.Combine(Path.GetTempPath(), "worddeck-story-runtime-" + Guid.NewGuid().ToString("N"));
        string courseRoot = Path.Combine(root, "Courses");
        string stateRoot = Path.Combine(root, "State");
        Directory.CreateDirectory(courseRoot);

        try
        {
            DictionaryPackage dictionary = BuildDictionary();
            StoryCourseManifestContract approved = BuildManifest(StoryCourseCurriculumAuthority.ApprovedCurriculum, "course.runtime.approved");
            StoryCourseManifestContract draft = BuildManifest(StoryCourseCurriculumAuthority.PedagogicalDraft, "course.runtime.draft");

            File.WriteAllText(Path.Combine(courseRoot, "approved.story-course.json"), StoryCoursePackageLoader.Serialize(approved));
            File.WriteAllText(Path.Combine(courseRoot, "draft.story-course.json"), StoryCoursePackageLoader.Serialize(draft));

            StoryCoursePackageDiscoveryResult discovery = StoryCoursePackageLoader.Discover(dictionary, new[] { courseRoot });
            Require(discovery.Courses.Count == 1 && discovery.Courses[0].CourseId == approved.CourseId,
                "approved course discovery did not fail closed around a draft package");
            Require(discovery.Errors.Count == 1 && discovery.Errors[0].Contains("independently approved", StringComparison.OrdinalIgnoreCase),
                "draft course package was not reported as ineligible");

            StoryCourseContractValidator.Validate(approved, dictionary);
            StoryCourseUnitContract unit = approved.Levels[0].Modules[0].Units[0];
            StoryCourseNarrativeContract context = unit.DialogueOrStory[0];
            StoryCourseComprehensionTaskContract comprehension = unit.ComprehensionTasks[0];

            var store = new StoryCourseRuntimeStateStore(approved.CourseId, stateRoot);
            StoryCourseProgressContract progress = store.LoadOrCreate(approved);
            Require(progress.CompletedContentIds.Count == 0 && progress.CompletedTaskIds.Count == 0,
                "fresh runtime state contains manufactured completion evidence");
            Require(progress.ObjectiveProgress.Count == 0,
                "fresh runtime state contains manufactured objective evidence");

            progress = StoryCourseRuntimeStateStore.RecordNarrativeCompletion(progress, context);
            Require(progress.CompletedContentIds.Contains(context.ContentId, StringComparer.OrdinalIgnoreCase),
                "narrative completion was not recorded by stable content id");
            Require(progress.ObjectiveProgress.Count == 0,
                "story completion was silently converted into objective evidence or mastery");

            Require(!StoryCourseRuntimeStateStore.IsAcceptedBoundedAnswer(comprehension, "wrong"),
                "bounded task accepted an invalid response");
            Require(StoryCourseRuntimeStateStore.IsAcceptedBoundedAnswer(comprehension, "  MORNING   "),
                "bounded task did not apply deterministic whitespace/case normalization");

            progress = StoryCourseRuntimeStateStore.RecordBoundedComprehensionSuccess(progress, comprehension);
            StoryCourseObjectiveProgressContract evidence = progress.ObjectiveProgress["objective.greeting"];
            Require(evidence.ComprehensionEvidenceCount == 1,
                "successful bounded comprehension did not record objective evidence exactly once");
            Require(evidence.MasteryDecision == StoryCourseMasteryDecision.Unknown && evidence.DecisionAuthority is null,
                "comprehension success was silently promoted to mastery");

            StoryCourseProgressContract duplicate = StoryCourseRuntimeStateStore.RecordBoundedComprehensionSuccess(progress, comprehension);
            Require(duplicate.ObjectiveProgress["objective.greeting"].ComprehensionEvidenceCount == 1,
                "reopening/rechecking a completed task duplicated evidence");

            store.Save(duplicate);
            StoryCourseProgressContract reloaded = store.LoadOrCreate(approved);
            Require(reloaded.CompletedContentIds.Contains(context.ContentId, StringComparer.OrdinalIgnoreCase) &&
                    reloaded.CompletedTaskIds.Contains(comprehension.TaskId, StringComparer.OrdinalIgnoreCase),
                "Story/Course progress did not survive close/reopen persistence");
            Require(reloaded.ObjectiveProgress["objective.greeting"].MasteryDecision == StoryCourseMasteryDecision.Unknown,
                "close/reopen changed mastery truth");

            // A second successful save creates a last-known-good backup of the same valid evidence.
            store.Save(reloaded);
            string primaryPath = Path.Combine(stateRoot, approved.CourseId + ".progress.json");
            File.WriteAllText(primaryPath, "{ definitely-not-json");
            StoryCourseProgressContract recovered = store.LoadOrCreate(approved);
            Require(recovered.CompletedTaskIds.Contains(comprehension.TaskId, StringComparer.OrdinalIgnoreCase),
                "corrupt primary state did not recover from last-known-good backup");

            // Saving immediately after backup recovery must not rotate the corrupt primary over
            // the only known-good backup. Corrupt primary a second time and prove recovery still works.
            store.Save(recovered);
            File.WriteAllText(primaryPath, "{ corrupt-again");
            StoryCourseProgressContract recoveredAgain = store.LoadOrCreate(approved);
            Require(recoveredAgain.CompletedTaskIds.Contains(comprehension.TaskId, StringComparer.OrdinalIgnoreCase),
                "save after backup recovery destroyed the last-known-good Story/Course backup");

            // Restore a valid current primary, then place a deliberately newer-schema state at
            // the primary path. Save must reject it before mutating either primary or backup.
            store.Save(recoveredAgain);
            StoryCourseProgressContract newer = recoveredAgain with
            {
                SchemaVersion = StoryCourseRuntimeStateStore.CurrentSchemaVersion + 1
            };
            string newerBytes = JsonSerializer.Serialize(
                newer,
                new JsonSerializerOptions(JsonSerializerDefaults.Web) { WriteIndented = true });
            File.WriteAllText(primaryPath, newerBytes);
            bool newerRejected = false;
            try { store.Save(recoveredAgain); }
            catch (InvalidDataException) { newerRejected = true; }
            Require(newerRejected,
                "Story/Course save did not fail closed around an existing newer-schema primary");
            Require(File.ReadAllText(primaryPath) == newerBytes,
                "Story/Course save mutated an existing newer-schema primary before rejecting it");

            Console.WriteLine("WordDeck Story/Course runtime self-test PASS.");
        }
        finally
        {
            try { Directory.Delete(root, recursive: true); } catch { }
        }
    }

    private static DictionaryPackage BuildDictionary() => new()
    {
        Id = "dictionary.story.runtime.test",
        Name = "Story runtime self-test dictionary",
        SourceLanguage = "en",
        TargetLanguage = "uk",
        Entries = new[]
        {
            new DictionaryEntry("lex.morning.n", "A1", "morning", "ранок"),
            new DictionaryEntry("lex.hello.interj", "A1", "hello", "привіт")
        }
    };

    private static StoryCourseManifestContract BuildManifest(StoryCourseCurriculumAuthority authority, string courseId)
    {
        var provenance = new StoryCourseProvenanceContract(
            StoryCourseContentOrigin.WordDeckAuthored,
            "runtime-self-test",
            "1",
            "WordDeck-owned runtime self-test material",
            string.Empty);
        var objective = new StoryCourseObjectiveContract(
            "objective.greeting",
            "Understand a simple morning greeting.",
            new[] { "comprehension", "production" });
        var targets = new StoryCourseTargetsContract(
            new[] { "lex.morning.n", "lex.hello.interj" },
            new[] { "present.simple.core" });
        var context = new StoryCourseNarrativeContract(
            "context.greeting.01",
            StoryCourseNarrativeKind.Dialogue,
            "A: Good morning. B: Hello!",
            new[] { "speaker.a", "speaker.b" },
            provenance);
        var comprehension = new StoryCourseComprehensionTaskContract(
            "task.greeting.reading.01",
            StoryCourseComprehensionKind.BoundedResponse,
            "Which time-of-day word appears in the greeting?",
            new[] { objective.ObjectiveId },
            new[] { "morning" });
        var production = new StoryCourseProductiveTaskContract(
            "task.greeting.production.01",
            StoryCourseProductiveChannel.Writing,
            "Write a new short greeting.",
            new[] { objective.ObjectiveId },
            "assessment.external.runtime-self-test");
        var checkpoint = new StoryCourseCheckpointContract(
            "checkpoint.greeting.01",
            new[] { objective.ObjectiveId },
            "assessment.external.runtime-self-test",
            UsesUnseenMaterial: true);
        var unit = new StoryCourseUnitContract(
            "unit.greeting.01",
            "module.greeting",
            "Morning greetings",
            new[] { objective.ObjectiveId },
            targets,
            new[] { context },
            new[] { comprehension },
            new[] { production },
            checkpoint,
            provenance);
        var module = new StoryCourseModuleContract(
            "module.greeting",
            "level.a1",
            "Greetings",
            new[] { objective },
            new[] { unit });
        var level = new StoryCourseLevelContract(
            "level.a1",
            "A1",
            "A1",
            1,
            new[] { module });
        return new StoryCourseManifestContract(
            courseId,
            "Runtime self-test course",
            authority,
            ClaimsCompleteEnglishCourse: false,
            new[] { level },
            provenance);
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException("Story/Course runtime self-test failed: " + message);
    }
}

internal static class StoryCourseRuntimeSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            StoryCourseRuntimeSelfTest.Run();
    }
}