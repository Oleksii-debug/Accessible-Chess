using System.Reflection;
using WordDeck.ApplicationLayer.Courses;
using WordDeck.Core.Courses;
using CourseModule = WordDeck.Core.Courses.Module;

namespace WordDeckCourseContractsHarness;

internal static class Program
{
    private static int Main()
    {
        try
        {
            Run();
            Console.WriteLine("Course architecture contracts passed: graph validation, registry delegation, path-neutral assets, JSON round-trip, and presentation-neutral public surfaces verified.");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("Course architecture contracts FAILED: " + ex);
            return 1;
        }
    }

    private static void Run()
    {
        Course valid = BuildFixture();
        var capabilities = new TestCapabilities("test.practice", "test.assess");
        var skills = new TestSkills(("lexical", "ox-test-1"));

        CourseValidationResult result = CourseContractValidator.Validate(valid, capabilities, skills);
        Require(result.IsValid, "Valid neutral course fixture failed: " + string.Join(" | ", result.Issues.Select(x => x.Message)));

        string json = CourseContractJson.Serialize(valid);
        Course roundTrip = CourseContractJson.DeserializeAndValidate(json, capabilities, skills);
        Require(roundTrip.Id == valid.Id && roundTrip.Levels[0].Modules[0].Units[0].Lessons[0].Activities[0].CapabilityId == "test.practice",
            "JSON round-trip changed the declarative graph.");

        Course badReference = valid with { FastTrack = valid.FastTrack! with { LessonIds = new[] { "lesson.missing" } } };
        CourseValidationResult badReferenceResult = CourseContractValidator.Validate(badReference, capabilities, skills);
        Require(!badReferenceResult.IsValid && badReferenceResult.Issues.Any(x => x.Code == "reference_missing"),
            "Missing FastTrack lesson did not fail closed.");

        Course badCapability = ReplaceActivity(valid, valid.Levels[0].Modules[0].Units[0].Lessons[0].Activities[0] with { CapabilityId = "test.unknown" });
        CourseValidationResult badCapabilityResult = CourseContractValidator.Validate(badCapability, capabilities, skills);
        Require(!badCapabilityResult.IsValid && badCapabilityResult.Issues.Any(x => x.Code == "capability_unresolved"),
            "Unknown activity capability was accepted instead of delegating to the existing engine registry.");

        Course badSkill = valid with { SkillTargets = new[] { valid.SkillTargets[0] with { TargetRef = "missing-target" } } };
        CourseValidationResult badSkillResult = CourseContractValidator.Validate(badSkill, capabilities, skills);
        Require(!badSkillResult.IsValid && badSkillResult.Issues.Any(x => x.Code == "skill_target_unresolved"),
            "Unknown skill target was accepted instead of delegating to the owning subsystem registry.");

        Course physicalAsset = valid with { AudioAssets = new[] { valid.AudioAssets[0] with { AssetKey = @"C:\WordDeck\audio.wav" } } };
        CourseValidationResult physicalAssetResult = CourseContractValidator.Validate(physicalAsset, capabilities, skills);
        Require(!physicalAssetResult.IsValid && physicalAssetResult.Issues.Any(x => x.Code == "resource_key_invalid"),
            "Core accepted a Windows-specific physical audio path.");

        AssertPresentationNeutralSurface();
    }

    private static Course BuildFixture()
    {
        var skill = new SkillTarget("skill.test.lexical", "lexical", "ox-test-1");
        var audio = new AudioAsset("audio.test.prompt", "audio.test.prompt", "en-GB", "transcript.test.prompt");
        var assessment = new Assessment("assessment.test", "test.assess", "policy.test.assessment", new[] { skill.Id });
        var explanation = new Explanation("explanation.test", "explanation.test.resource");
        var activity = new Activity("activity.test", "test.practice", new[] { skill.Id }, new[] { audio.Id }, new[] { explanation.Id }, assessment.Id);
        var checkpoint = new Checkpoint("checkpoint.test", new[] { skill.Id }, new[] { activity.Id }, assessment.Id);
        var lesson = new Lesson("lesson.test", "lesson.test.title", new[] { activity }, new[] { explanation }, new[] { checkpoint });
        var unit = new Unit("unit.test", "unit.test.title", new[] { lesson }, Array.Empty<Checkpoint>());
        var module = new CourseModule("module.test", "module.test.title", new[] { unit }, Array.Empty<Checkpoint>());
        var level = new Level("level.test", "test", "level.test.title", new[] { module }, Array.Empty<Checkpoint>());
        return new Course(
            "course.test",
            "1",
            "course.test.title",
            new[] { level },
            new[] { skill },
            new[] { audio },
            new[] { assessment },
            new FastTrack("fasttrack.test", "policy.test.fasttrack", new[] { lesson.Id }, new[] { checkpoint.Id }),
            new DeepPractice("deeppractice.test", "policy.test.deeppractice", new[] { activity.Id }, new[] { skill.Id }));
    }

    private static Course ReplaceActivity(Course course, Activity replacement)
    {
        Level level = course.Levels[0];
        CourseModule module = level.Modules[0];
        Unit unit = module.Units[0];
        Lesson lesson = unit.Lessons[0] with { Activities = new[] { replacement } };
        unit = unit with { Lessons = new[] { lesson } };
        module = module with { Units = new[] { unit } };
        level = level with { Modules = new[] { module } };
        return course with { Levels = new[] { level } };
    }

    private static void AssertPresentationNeutralSurface()
    {
        Type[] types =
        {
            typeof(Course), typeof(Level), typeof(CourseModule), typeof(Unit), typeof(Lesson), typeof(Activity),
            typeof(Explanation), typeof(SkillTarget), typeof(AudioAsset), typeof(Checkpoint), typeof(Assessment),
            typeof(FastTrack), typeof(DeepPractice), typeof(ILearningCapabilityRegistry), typeof(ISkillTargetRegistry),
            typeof(CourseValidationIssue), typeof(CourseValidationResult)
        };

        foreach (Type type in types)
        {
            foreach (PropertyInfo property in type.GetProperties(BindingFlags.Instance | BindingFlags.Public))
                Require(!ContainsPresentationType(property.PropertyType), $"{type.FullName}.{property.Name} exposes {property.PropertyType}.");
            foreach (MethodInfo method in type.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.DeclaredOnly))
            {
                Require(!ContainsPresentationType(method.ReturnType), $"{type.FullName}.{method.Name} return type is presentation-specific.");
                foreach (ParameterInfo parameter in method.GetParameters())
                    Require(!ContainsPresentationType(parameter.ParameterType), $"{type.FullName}.{method.Name} parameter is presentation-specific.");
            }
        }
    }

    private static bool ContainsPresentationType(Type type)
    {
        Type candidate = Nullable.GetUnderlyingType(type) ?? type;
        string ns = candidate.Namespace ?? string.Empty;
        if (ns.StartsWith("System.Windows.Forms", StringComparison.Ordinal) ||
            ns.StartsWith("System.Drawing", StringComparison.Ordinal) ||
            ns.StartsWith("Microsoft.AspNetCore", StringComparison.Ordinal) ||
            ns.StartsWith("Microsoft.JSInterop", StringComparison.Ordinal))
            return true;
        if (candidate.IsArray) return ContainsPresentationType(candidate.GetElementType()!);
        return candidate.IsGenericType && candidate.GetGenericArguments().Any(ContainsPresentationType);
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }

    private sealed class TestCapabilities(params string[] ids) : ILearningCapabilityRegistry
    {
        private readonly HashSet<string> _ids = new(ids, StringComparer.OrdinalIgnoreCase);
        public bool CanResolve(string capabilityId) => _ids.Contains(capabilityId);
    }

    private sealed class TestSkills(params (string Domain, string TargetRef)[] targets) : ISkillTargetRegistry
    {
        private readonly HashSet<string> _targets = new(targets.Select(x => x.Domain + "\n" + x.TargetRef), StringComparer.OrdinalIgnoreCase);
        public bool CanResolve(string domain, string targetRef) => _targets.Contains(domain + "\n" + targetRef);
    }
}
