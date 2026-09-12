using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class StoryCourseSkillTargetBridgeSelfTest
{
    public static void Run()
    {
        DictionaryPackage dictionary = BuildDictionary();
        StoryCourseManifestContract approved = BuildManifest(StoryCourseCurriculumAuthority.ApprovedCurriculum, "CE-ST-M08-TL001");

        StoryCourseContractValidator.Validate(approved, dictionary);
        StoryCourseUnitContract unit = approved.Levels[0].Modules[0].Units[0];
        ResolvedStoryCourseTargets resolved = StoryCourseIdentityResolver.Resolve(
            dictionary,
            unit.Targets,
            unit.UnitId,
            approved.CurriculumAuthority);

        Require(resolved.LexicalEntries.Count == 1 && resolved.LexicalEntries[0].Id == "lex.bus.n",
            "Existing lexical stable-ID resolution changed.");
        Require(resolved.GrammarSkillIds.Count == 1,
            "Existing Grammar target resolution changed.");
        Require(resolved.SkillTargets.Count == 1,
            "Approved governed course target was not preserved.");
        Require(resolved.SkillTargets[0].Domain == StoryCourseSkillTargetReferenceContract.CourseTargetDomain,
            "Governed course target domain changed.");
        Require(resolved.SkillTargets[0].TargetRef == "CE-ST-M08-TL001",
            "Exact externally governed target identity/case was not preserved.");

        string json = StoryCoursePackageLoader.Serialize(approved);
        StoryCourseManifestContract roundTrip = StoryCoursePackageLoader.Deserialize(json);
        string roundTripRef = roundTrip.Levels[0].Modules[0].Units[0].Targets.SkillTargets.Single().TargetRef;
        Require(roundTripRef == "CE-ST-M08-TL001",
            "Story/Course package JSON round-trip lost the governed target identity.");

        string tempRoot = Path.Combine(Path.GetTempPath(), "worddeck-course-target-bridge-" + Guid.NewGuid().ToString("N"));
        try
        {
            Directory.CreateDirectory(tempRoot);
            File.WriteAllText(Path.Combine(tempRoot, "approved.story-course.json"), json);
            StoryCoursePackageDiscoveryResult discovery = StoryCoursePackageLoader.Discover(dictionary, new[] { tempRoot });
            Require(discovery.Errors.Count == 0 && discovery.Courses.Count == 1,
                "Learner-facing package loader rejected an approved package carrying a governed course target.");
        }
        finally
        {
            if (Directory.Exists(tempRoot)) Directory.Delete(tempRoot, recursive: true);
        }

        StoryCourseManifestContract technicalFixture = BuildManifest(
            StoryCourseCurriculumAuthority.TechnicalFixture,
            "CE-ST-M08-TL001");
        ExpectInvalid(
            () => StoryCourseContractValidator.Validate(technicalFixture, dictionary),
            "Non-approved curriculum was allowed to self-authorize a governed course target.");

        ExpectInvalid(
            () => StoryCourseIdentityResolver.Resolve(dictionary, unit.Targets, unit.UnitId),
            "Legacy/default resolver silently authorized governed course targets without approved curriculum authority.");

        ExpectInvalid(
            () => StoryCourseContractValidator.Validate(
                BuildManifest(StoryCourseCurriculumAuthority.ApprovedCurriculum, "../CE-ST-M08-TL001"),
                dictionary),
            "Path-like governed course target reference was accepted.");

        ExpectInvalid(
            () => StoryCourseContractValidator.Validate(
                BuildManifest(StoryCourseCurriculumAuthority.ApprovedCurriculum, "https://example.invalid/target"),
                dictionary),
            "URI-like governed course target reference was accepted.");

        StoryCourseManifestContract unknownDomain = approved with
        {
            Levels = approved.Levels.Select(level => level with
            {
                Modules = level.Modules.Select(module => module with
                {
                    Units = module.Units.Select(sourceUnit => sourceUnit with
                    {
                        Targets = sourceUnit.Targets with
                        {
                            SkillTargets = new[]
                            {
                                new StoryCourseSkillTargetReferenceContract("lexical", "CE-ST-M08-TL001")
                            }
                        }
                    }).ToArray()
                }).ToArray()
            }).ToArray()
        };
        ExpectInvalid(
            () => StoryCourseContractValidator.Validate(unknownDomain, dictionary),
            "Story/Course accepted a parallel lexical target path instead of the canonical dictionary resolver.");

        StoryCourseManifestContract duplicate = approved with
        {
            Levels = approved.Levels.Select(level => level with
            {
                Modules = level.Modules.Select(module => module with
                {
                    Units = module.Units.Select(sourceUnit => sourceUnit with
                    {
                        Targets = sourceUnit.Targets with
                        {
                            SkillTargets = new[]
                            {
                                new StoryCourseSkillTargetReferenceContract("course-target", "CE-ST-M08-TL001"),
                                new StoryCourseSkillTargetReferenceContract("course-target", "ce-st-m08-tl001")
                            }
                        }
                    }).ToArray()
                }).ToArray()
            }).ToArray()
        };
        ExpectInvalid(
            () => StoryCourseContractValidator.Validate(duplicate, dictionary),
            "Case-variant duplicate governed course targets were accepted.");

        StoryCourseTargetsContract legacyTargets = new(
            new[] { "lex.bus.n" },
            new[] { "present.simple.core" });
        ResolvedStoryCourseTargets legacyResolved = StoryCourseIdentityResolver.Resolve(dictionary, legacyTargets, "unit.legacy");
        Require(legacyResolved.SkillTargets.Count == 0,
            "Backward-compatible Story/Course target construction unexpectedly gained governed course targets.");

        Console.WriteLine("WordDeck Story/Course governed target bridge self-test PASS.");
    }

    private static DictionaryPackage BuildDictionary() => new()
    {
        Id = "dictionary.course-target-bridge",
        Name = "Course target bridge fixture dictionary",
        SourceLanguage = "en",
        TargetLanguage = "uk",
        Entries = new[]
        {
            new DictionaryEntry("lex.bus.n", "A1", "bus", "автобус")
        }
    };

    private static StoryCourseManifestContract BuildManifest(
        StoryCourseCurriculumAuthority authority,
        string governedTargetRef)
    {
        StoryCourseProvenanceContract provenance = new(
            StoryCourseContentOrigin.WordDeckAuthored,
            "worddeck.course-target-bridge.self-test",
            "1",
            "WordDeck-owned self-test content; no release claim",
            "");

        StoryCourseObjectiveContract objective = new(
            "objective.course-target-bridge",
            "Exercise an approved governed course target without treating target metadata itself as mastery.",
            new[] { "comprehension", "production" });

        StoryCourseTargetsContract targets = new(
            new[] { "lex.bus.n" },
            new[] { "present.simple.core" })
        {
            SkillTargets = new[]
            {
                new StoryCourseSkillTargetReferenceContract(
                    StoryCourseSkillTargetReferenceContract.CourseTargetDomain,
                    governedTargetRef)
            }
        };

        StoryCourseNarrativeContract narrative = new(
            "context.course-target-bridge",
            StoryCourseNarrativeKind.Dialogue,
            "A: Bus? B: Yes, the bus.",
            new[] { "speaker.a", "speaker.b" },
            provenance);

        StoryCourseComprehensionTaskContract comprehension = new(
            "task.course-target-bridge.comprehension",
            StoryCourseComprehensionKind.BoundedResponse,
            "Which transport word did you hear?",
            new[] { objective.ObjectiveId },
            new[] { "bus" });

        StoryCourseProductiveTaskContract production = new(
            "task.course-target-bridge.production",
            StoryCourseProductiveChannel.Speaking,
            "Say the assigned transport word.",
            new[] { objective.ObjectiveId },
            "assessment.course-target-bridge");

        StoryCourseUnitContract unit = new(
            "unit.course-target-bridge",
            "module.course-target-bridge",
            "Course target bridge fixture",
            new[] { objective.ObjectiveId },
            targets,
            new[] { narrative },
            new[] { comprehension },
            new[] { production },
            Checkpoint: null,
            provenance);

        StoryCourseModuleContract module = new(
            "module.course-target-bridge",
            "level.course-target-bridge",
            "Course target bridge module",
            new[] { objective },
            new[] { unit });

        StoryCourseLevelContract level = new(
            "level.course-target-bridge",
            "Pre-A1",
            "Course target bridge level",
            Sequence: 1,
            Modules: new[] { module });

        return new StoryCourseManifestContract(
            "course.course-target-bridge",
            "Course target bridge self-test",
            authority,
            ClaimsCompleteEnglishCourse: false,
            Levels: new[] { level },
            Provenance: provenance);
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

        throw new InvalidOperationException("Story/Course governed target bridge self-test failed: " + message);
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException("Story/Course governed target bridge self-test failed: " + message);
    }
}

internal static class StoryCourseSkillTargetBridgeSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            StoryCourseSkillTargetBridgeSelfTest.Run();
    }
}
