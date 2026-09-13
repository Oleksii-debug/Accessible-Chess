using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class StoryCourseRuntimeBuiltInM07SelfTest
{
    internal static void Run()
    {
        string root = Path.Combine(Path.GetTempPath(), "worddeck-m07-runtime-" + Guid.NewGuid().ToString("N"));
        string courseRoot = Path.Combine(root, "Courses");
        string stateRoot = Path.Combine(root, "State");
        Directory.CreateDirectory(courseRoot);

        try
        {
            DictionaryPackage dictionary = new()
            {
                Id = "dictionary.m07.runtime.self-test",
                Name = "M07 runtime self-test dictionary",
                SourceLanguage = "en",
                TargetLanguage = "uk",
                Entries = Array.Empty<DictionaryEntry>()
            };

            IReadOnlyList<StoryCourseManifestContract> builtIns = StoryCourseRuntimeBuiltInCatalog.BuildApprovedManifests();
            Require(builtIns.Count == 2, "expected governed M07 and A1-M10 built-in packages in this lineage");
            StoryCourseManifestContract manifest = builtIns.Single(candidate =>
                candidate.CourseId == StoryCourseRuntimeBuiltInCatalog.M07MissionRuntimeCourseId);
            StoryCourseContractValidator.Validate(manifest, dictionary);

            Require(manifest.CourseId == StoryCourseRuntimeBuiltInCatalog.M07MissionRuntimeCourseId,
                "M07 runtime course identity changed");
            Require(manifest.CurriculumAuthority == StoryCourseCurriculumAuthority.ApprovedCurriculum,
                "governed M07 mission is not marked ApprovedCurriculum");
            Require(!manifest.ClaimsCompleteEnglishCourse,
                "single M07 mission slice falsely claims the whole Complete English course");
            Require(manifest.Levels.Count == 1 && manifest.Levels[0].FrameworkLevel == "Pre-A1",
                "M07 runtime binding lost its Starter / Pre-A1 ceiling");

            StoryCourseModuleContract module = manifest.Levels.Single().Modules.Single();
            StoryCourseUnitContract unit = module.Units.Single();
            Require(module.ModuleId == "ce-st-m07" && unit.UnitId == StoryCourseRuntimeBuiltInCatalog.M07MissionRuntimeUnitId,
                "M07 runtime module/unit mapping changed");
            Require(unit.Checkpoint is null,
                "exposed Study mission was silently converted into protected assessment/checkpoint content");
            Require(unit.Targets.LexicalEntryIds.Count == 0 && unit.Targets.GrammarSkillIds.Count == 0,
                "M07 mission reminted lexical or Grammar ownership instead of using governed course targets");

            string[] expectedTargets =
            {
                "CE-ST-M01-TL015", "CE-ST-M01-TL016", "CE-ST-M01-TL017", "CE-ST-M01-TL018",
                "CE-ST-M07-TL005", "CE-ST-M07-TL006", "CE-ST-M07-TL007", "CE-ST-M07-TL011",
                "CE-ST-M07-TL012", "CE-ST-M07-TL015", "CE-ST-M07-TL017", "CE-ST-M07-TL019",
                "CE-ST-M07-TL020", "CE-ST-M07-TL022"
            };
            string[] actualTargets = unit.Targets.SkillTargets.Select(target => target.TargetRef).Order(StringComparer.Ordinal).ToArray();
            Require(actualTargets.SequenceEqual(expectedTargets.Order(StringComparer.Ordinal), StringComparer.Ordinal),
                "governed M07/M01 target identity set drifted");
            Require(unit.Targets.SkillTargets.All(target => target.Domain == StoryCourseSkillTargetReferenceContract.CourseTargetDomain),
                "M07 target binding escaped the governed course-target domain");
            Require(actualTargets.Where(id => id.StartsWith("CE-ST-M07-TL", StringComparison.Ordinal))
                    .All(id => int.Parse(id[^3..]) <= 23),
                "runtime package introduced an unauthorized M07 TL024+ target");

            StoryCourseNarrativeContract context = unit.DialogueOrStory.Single();
            Require(context.Text.Contains("Start: pharmacy", StringComparison.Ordinal) &&
                    context.Text.Contains("Destination: hotel", StringComparison.Ordinal) &&
                    context.Text.Contains("GO STRAIGHT", StringComparison.Ordinal) &&
                    context.Text.Contains("TURN RIGHT at the bus stop", StringComparison.Ordinal) &&
                    context.Text.Contains("hotel is NEAR the bus stop", StringComparison.Ordinal),
                "changed v1.1 transfer facts were not bound exactly enough for learner runtime");
            Require(context.Text.Contains("no Listening evidence", StringComparison.OrdinalIgnoreCase),
                "no-audio/no-Listening-credit truth disappeared from learner-facing mission context");

            Require(manifest.Provenance.SourceId.Contains(StoryCourseRuntimeBuiltInCatalog.M07MissionSourceId, StringComparison.Ordinal) &&
                    manifest.Provenance.SourceId.Contains(StoryCourseRuntimeBuiltInCatalog.M07MissionSourceRevision, StringComparison.Ordinal),
                "exact governed M07 source/revision is not pinned in runtime provenance");
            Require(manifest.Provenance.Attribution.Contains(StoryCourseRuntimeBuiltInCatalog.M07MissionQaId, StringComparison.Ordinal) &&
                    manifest.Provenance.Attribution.Contains(StoryCourseRuntimeBuiltInCatalog.M07MissionQaRevision, StringComparison.Ordinal) &&
                    manifest.Provenance.Attribution.Contains(StoryCourseRuntimeBuiltInCatalog.M07MissionIntegrationId, StringComparison.Ordinal) &&
                    manifest.Provenance.Attribution.Contains(StoryCourseRuntimeBuiltInCatalog.M07MissionIntegrationRevision, StringComparison.Ordinal),
                "runtime provenance lost independent QA or governed integration pins");
            Require(manifest.Provenance.LicenseOrRights.Contains("HOLD", StringComparison.OrdinalIgnoreCase),
                "commercial/public rights HOLD was silently removed");

            StoryCourseComprehensionTaskContract[] comprehension = unit.ComprehensionTasks.ToArray();
            Require(comprehension.Length == 5,
                "M07 runtime did not preserve atomic S02 facts plus S04 relation comprehension");
            Require(Accepts(comprehension, "ce-st-m07-msn-001-s02-step1", "go straight"),
                "S02 Step 1 STRAIGHT fact is not deterministically checkable");
            Require(Accepts(comprehension, "ce-st-m07-msn-001-s02-step2-direction", "right"),
                "S02 Step 2 RIGHT fact is not deterministically checkable");
            Require(Accepts(comprehension, "ce-st-m07-msn-001-s02-step2-landmark", "bus stop"),
                "S02 bus-stop landmark is not deterministically checkable");
            Require(Accepts(comprehension, "ce-st-m07-msn-001-s02-order", "straight then right"),
                "S02 route order is not deterministically checkable");
            Require(Accepts(comprehension, "ce-st-m07-msn-001-s04-relation", "near"),
                "S04 NEAR relation is not deterministically checkable");

            IReadOnlyDictionary<string, StoryCourseProductiveTaskContract> productive = unit.ProductiveTasks
                .ToDictionary(task => task.TaskId, StringComparer.OrdinalIgnoreCase);
            Require(productive.Count == 4,
                "M07 runtime lost one of S01/S03/S04/S05 productive stages");
            Require(productive["ce-st-m07-msn-001-s01-speaking"].Channel == StoryCourseProductiveChannel.Speaking,
                "S01 location question no longer requests the governed spoken channel");
            Require(productive["ce-st-m07-msn-001-s03-speaking"].Channel == StoryCourseProductiveChannel.Speaking,
                "S03 required spoken route channel was weakened");
            Require(productive["ce-st-m07-msn-001-s04-writing"].Channel == StoryCourseProductiveChannel.Writing,
                "S04 original short route message lost Writing ownership");
            Require(productive["ce-st-m07-msn-001-s05-speaking"].Channel == StoryCourseProductiveChannel.Speaking,
                "S05 communication-repair interaction lost its spoken-channel requirement");
            Require(productive.Values.All(task => StoryCourseProductiveRevealPolicy.RequiredPriorTaskId(task) is null),
                "M07 regression acquired an unintended staged-reveal prerequisite");
            Require(StoryCourseRuntimeForm.SubmissionKindForCurrentUi(StoryCourseProductiveChannel.Speaking) ==
                    StoryCourseProductiveSubmissionKind.TypedFallback,
                "current UI would fabricate Speaking evidence from typed fallback");
            Require(StoryCourseRuntimeForm.SubmissionKindForCurrentUi(StoryCourseProductiveChannel.Writing) ==
                    StoryCourseProductiveSubmissionKind.RequiredChannelPerformance,
                "current UI stopped treating real typed Writing as its required channel");

            StoryCoursePackageDiscoveryResult discovery =
                StoryCoursePackageLoader.DiscoverIncludingBuiltIns(dictionary, new[] { courseRoot });
            Require(discovery.Courses.Count == builtIns.Count &&
                    discovery.Courses.Any(course => course.CourseId == manifest.CourseId),
                "governed M07 built-in package is not reachable through learner runtime discovery");
            Require(discovery.Errors.Count == 0,
                "clean built-in discovery reported an unexpected error");

            File.WriteAllText(
                Path.Combine(courseRoot, "duplicate.story-course.json"),
                StoryCoursePackageLoader.Serialize(manifest));
            StoryCoursePackageDiscoveryResult duplicateDiscovery =
                StoryCoursePackageLoader.DiscoverIncludingBuiltIns(dictionary, new[] { courseRoot });
            Require(duplicateDiscovery.Courses.Count == builtIns.Count &&
                    duplicateDiscovery.Courses.Any(course => course.CourseId == manifest.CourseId),
                "external duplicate displaced the governed built-in package");
            Require(duplicateDiscovery.Errors.Any(error => error.Contains("duplicates governed built-in", StringComparison.OrdinalIgnoreCase)),
                "external duplicate built-in course id did not fail closed with a deterministic diagnostic");

            var store = new StoryCourseRuntimeStateStore(manifest.CourseId, stateRoot);
            StoryCourseProgressContract progress = store.LoadOrCreate(manifest);
            Require(progress.ActiveModuleId == module.ModuleId && progress.ActiveUnitId == unit.UnitId,
                "fresh runtime state does not reopen at the governed M07 mission");
            Require(progress.ObjectiveProgress.Count == 0,
                "fresh governed mission manufactured evidence/mastery");

            StoryCourseComprehensionTaskContract step1 = comprehension.Single(task => task.TaskId == "ce-st-m07-msn-001-s02-step1");
            progress = StoryCourseRuntimeStateStore.RecordBoundedComprehensionSuccess(progress, step1);
            StoryCourseObjectiveProgressContract objectiveEvidence = progress.ObjectiveProgress[step1.ObjectiveIds.Single()];
            Require(objectiveEvidence.ComprehensionEvidenceCount == 1 &&
                    objectiveEvidence.MasteryDecision == StoryCourseMasteryDecision.Unknown &&
                    objectiveEvidence.DecisionAuthority is null,
                "exposed mission practice was silently promoted to mastery");
            store.Save(progress);
            StoryCourseProgressContract reopened = store.LoadOrCreate(manifest);
            Require(reopened.CompletedTaskIds.Contains(step1.TaskId, StringComparer.OrdinalIgnoreCase) &&
                    reopened.ObjectiveProgress[step1.ObjectiveIds.Single()].MasteryDecision == StoryCourseMasteryDecision.Unknown,
                "M07 mission state/recovery lost practice or changed mastery truth after reopen");

            Console.WriteLine("WordDeck governed M07 built-in runtime package self-test PASS.");
        }
        finally
        {
            try { Directory.Delete(root, recursive: true); } catch { }
        }
    }

    private static bool Accepts(
        IEnumerable<StoryCourseComprehensionTaskContract> tasks,
        string taskId,
        string response)
    {
        StoryCourseComprehensionTaskContract task = tasks.Single(candidate => candidate.TaskId == taskId);
        return StoryCourseRuntimeStateStore.IsAcceptedBoundedAnswer(task, response);
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException("Governed M07 runtime self-test failed: " + message);
    }
}

internal static class StoryCourseRuntimeBuiltInM07SelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            StoryCourseRuntimeBuiltInM07SelfTest.Run();
    }
}
