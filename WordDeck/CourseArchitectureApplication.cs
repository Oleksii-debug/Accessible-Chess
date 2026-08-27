using System.Text.Json;
using WordDeck.Core.Courses;
using CourseModule = WordDeck.Core.Courses.Module;

namespace WordDeck.Application.Courses;

/// <summary>
/// Resolves an Activity/Assessment capability into the existing WordDeck learning/application
/// engine. Adapters may implement this for WinForms today and semantic web presentation later.
/// </summary>
public interface ILearningCapabilityRegistry
{
    bool CanResolve(string capabilityId);
}

/// <summary>
/// Resolves stable target references against their owning existing subsystem (lexical,
/// grammar, morphology, etc.) without duplicating those registries in the course layer.
/// </summary>
public interface ISkillTargetRegistry
{
    bool CanResolve(string domain, string targetRef);
}

public sealed record CourseValidationIssue(string Code, string Location, string Message);

public sealed record CourseValidationResult(IReadOnlyList<CourseValidationIssue> Issues)
{
    public bool IsValid => Issues.Count == 0;
}

/// <summary>
/// Structural validation only. It verifies references and adapter boundaries; it neither
/// executes activities nor computes learning progress/mastery.
/// </summary>
public static class CourseContractValidator
{
    public static CourseValidationResult Validate(
        Course course,
        ILearningCapabilityRegistry capabilityRegistry,
        ISkillTargetRegistry skillTargetRegistry)
    {
        ArgumentNullException.ThrowIfNull(course);
        ArgumentNullException.ThrowIfNull(capabilityRegistry);
        ArgumentNullException.ThrowIfNull(skillTargetRegistry);

        var issues = new List<CourseValidationIssue>();
        RequireId(course.Id, "course", "course.id", issues);
        RequireText(course.Version, "course.version", issues);
        RequireResourceKey(course.TitleResourceKey, "course.titleResourceKey", issues);

        Level[] levels = Safe(course.Levels, "course.levels", issues);
        SkillTarget[] skillTargets = Safe(course.SkillTargets, "course.skillTargets", issues);
        AudioAsset[] audioAssets = Safe(course.AudioAssets, "course.audioAssets", issues);
        Assessment[] assessments = Safe(course.Assessments, "course.assessments", issues);

        var skillById = UniqueById(skillTargets, x => x.Id, "skillTarget", issues);
        var audioById = UniqueById(audioAssets, x => x.Id, "audioAsset", issues);
        var assessmentById = UniqueById(assessments, x => x.Id, "assessment", issues);
        var levelById = UniqueById(levels, x => x.Id, "level", issues);

        foreach (SkillTarget target in skillTargets)
        {
            string location = $"skillTarget[{target.Id}]";
            RequireId(target.Id, "skillTarget", location + ".id", issues);
            RequireId(target.Domain, "skillTarget domain", location + ".domain", issues);
            RequireText(target.TargetRef, location + ".targetRef", issues);
            if (CourseContractIdentifiers.IsStableId(target.Domain) && !string.IsNullOrWhiteSpace(target.TargetRef) &&
                !skillTargetRegistry.CanResolve(target.Domain, target.TargetRef))
            {
                Add(issues, "skill_target_unresolved", location + ".targetRef", "Target reference is not resolved by its owning application registry.");
            }
        }

        foreach (AudioAsset asset in audioAssets)
        {
            string location = $"audioAsset[{asset.Id}]";
            RequireId(asset.Id, "audioAsset", location + ".id", issues);
            RequireResourceKey(asset.AssetKey, location + ".assetKey", issues);
            RequireText(asset.LanguageTag, location + ".languageTag", issues);
            if (asset.TranscriptResourceKey is not null)
                RequireResourceKey(asset.TranscriptResourceKey, location + ".transcriptResourceKey", issues);
        }

        foreach (Assessment assessment in assessments)
        {
            string location = $"assessment[{assessment.Id}]";
            RequireId(assessment.Id, "assessment", location + ".id", issues);
            RequireId(assessment.EvaluatorCapabilityId, "assessment evaluator capability", location + ".evaluatorCapabilityId", issues);
            RequireId(assessment.PolicyId, "assessment policy", location + ".policyId", issues);
            ValidateReferenceList(assessment.SkillTargetIds, skillById, location + ".skillTargetIds", "skill target", issues);
            if (CourseContractIdentifiers.IsStableId(assessment.EvaluatorCapabilityId) && !capabilityRegistry.CanResolve(assessment.EvaluatorCapabilityId))
                Add(issues, "capability_unresolved", location + ".evaluatorCapabilityId", "Assessment evaluator is not resolved by the existing application capability registry.");
        }

        var moduleById = new Dictionary<string, CourseModule>(StringComparer.OrdinalIgnoreCase);
        var unitById = new Dictionary<string, Unit>(StringComparer.OrdinalIgnoreCase);
        var lessonById = new Dictionary<string, Lesson>(StringComparer.OrdinalIgnoreCase);
        var activityById = new Dictionary<string, Activity>(StringComparer.OrdinalIgnoreCase);
        var explanationById = new Dictionary<string, Explanation>(StringComparer.OrdinalIgnoreCase);
        var checkpointById = new Dictionary<string, Checkpoint>(StringComparer.OrdinalIgnoreCase);

        foreach (Level level in levels)
        {
            string levelLocation = $"level[{level.Id}]";
            RequireId(level.Id, "level", levelLocation + ".id", issues);
            RequireId(level.Code, "level code", levelLocation + ".code", issues);
            RequireResourceKey(level.TitleResourceKey, levelLocation + ".titleResourceKey", issues);
            CourseModule[] modules = Safe(level.Modules, levelLocation + ".modules", issues);
            Checkpoint[] levelCheckpoints = Safe(level.Checkpoints, levelLocation + ".checkpoints", issues);
            AddUnique(modules, x => x.Id, "module", moduleById, issues);
            AddUnique(levelCheckpoints, x => x.Id, "checkpoint", checkpointById, issues);

            foreach (CourseModule module in modules)
            {
                string moduleLocation = $"module[{module.Id}]";
                RequireId(module.Id, "module", moduleLocation + ".id", issues);
                RequireResourceKey(module.TitleResourceKey, moduleLocation + ".titleResourceKey", issues);
                Unit[] units = Safe(module.Units, moduleLocation + ".units", issues);
                Checkpoint[] moduleCheckpoints = Safe(module.Checkpoints, moduleLocation + ".checkpoints", issues);
                AddUnique(units, x => x.Id, "unit", unitById, issues);
                AddUnique(moduleCheckpoints, x => x.Id, "checkpoint", checkpointById, issues);

                foreach (Unit unit in units)
                {
                    string unitLocation = $"unit[{unit.Id}]";
                    RequireId(unit.Id, "unit", unitLocation + ".id", issues);
                    RequireResourceKey(unit.TitleResourceKey, unitLocation + ".titleResourceKey", issues);
                    Lesson[] lessons = Safe(unit.Lessons, unitLocation + ".lessons", issues);
                    Checkpoint[] unitCheckpoints = Safe(unit.Checkpoints, unitLocation + ".checkpoints", issues);
                    AddUnique(lessons, x => x.Id, "lesson", lessonById, issues);
                    AddUnique(unitCheckpoints, x => x.Id, "checkpoint", checkpointById, issues);

                    foreach (Lesson lesson in lessons)
                    {
                        string lessonLocation = $"lesson[{lesson.Id}]";
                        RequireId(lesson.Id, "lesson", lessonLocation + ".id", issues);
                        RequireResourceKey(lesson.TitleResourceKey, lessonLocation + ".titleResourceKey", issues);
                        Activity[] activities = Safe(lesson.Activities, lessonLocation + ".activities", issues);
                        Explanation[] explanations = Safe(lesson.Explanations, lessonLocation + ".explanations", issues);
                        Checkpoint[] lessonCheckpoints = Safe(lesson.Checkpoints, lessonLocation + ".checkpoints", issues);
                        AddUnique(activities, x => x.Id, "activity", activityById, issues);
                        AddUnique(explanations, x => x.Id, "explanation", explanationById, issues);
                        AddUnique(lessonCheckpoints, x => x.Id, "checkpoint", checkpointById, issues);

                        foreach (Explanation explanation in explanations)
                        {
                            string location = $"explanation[{explanation.Id}]";
                            RequireId(explanation.Id, "explanation", location + ".id", issues);
                            RequireResourceKey(explanation.ContentResourceKey, location + ".contentResourceKey", issues);
                        }
                    }
                }
            }
        }

        // Second pass: all graph indexes now exist, so forward references are safe.
        foreach (Activity activity in activityById.Values)
        {
            string location = $"activity[{activity.Id}]";
            RequireId(activity.Id, "activity", location + ".id", issues);
            RequireId(activity.CapabilityId, "activity capability", location + ".capabilityId", issues);
            ValidateReferenceList(activity.SkillTargetIds, skillById, location + ".skillTargetIds", "skill target", issues);
            ValidateReferenceList(activity.AudioAssetIds, audioById, location + ".audioAssetIds", "audio asset", issues);
            ValidateReferenceList(activity.ExplanationIds, explanationById, location + ".explanationIds", "explanation", issues);
            if (activity.AssessmentId is not null && !assessmentById.ContainsKey(activity.AssessmentId))
                Add(issues, "reference_missing", location + ".assessmentId", $"Unknown assessment id '{activity.AssessmentId}'.");
            if (CourseContractIdentifiers.IsStableId(activity.CapabilityId) && !capabilityRegistry.CanResolve(activity.CapabilityId))
                Add(issues, "capability_unresolved", location + ".capabilityId", "Activity capability is not resolved by the existing application capability registry.");
        }

        foreach (Checkpoint checkpoint in checkpointById.Values)
        {
            string location = $"checkpoint[{checkpoint.Id}]";
            RequireId(checkpoint.Id, "checkpoint", location + ".id", issues);
            ValidateReferenceList(checkpoint.SkillTargetIds, skillById, location + ".skillTargetIds", "skill target", issues);
            ValidateReferenceList(checkpoint.ActivityIds, activityById, location + ".activityIds", "activity", issues);
            if (checkpoint.AssessmentId is not null && !assessmentById.ContainsKey(checkpoint.AssessmentId))
                Add(issues, "reference_missing", location + ".assessmentId", $"Unknown assessment id '{checkpoint.AssessmentId}'.");
        }

        if (course.FastTrack is not null)
        {
            FastTrack route = course.FastTrack;
            string location = $"fastTrack[{route.Id}]";
            RequireId(route.Id, "fastTrack", location + ".id", issues);
            RequireId(route.PolicyId, "fastTrack policy", location + ".policyId", issues);
            ValidateReferenceList(route.LessonIds, lessonById, location + ".lessonIds", "lesson", issues);
            ValidateReferenceList(route.CheckpointIds, checkpointById, location + ".checkpointIds", "checkpoint", issues);
        }

        if (course.DeepPractice is not null)
        {
            DeepPractice route = course.DeepPractice;
            string location = $"deepPractice[{route.Id}]";
            RequireId(route.Id, "deepPractice", location + ".id", issues);
            RequireId(route.PolicyId, "deepPractice policy", location + ".policyId", issues);
            ValidateReferenceList(route.ActivityIds, activityById, location + ".activityIds", "activity", issues);
            ValidateReferenceList(route.SkillTargetIds, skillById, location + ".skillTargetIds", "skill target", issues);
        }

        _ = levelById; // retained intentionally for duplicate-level validation and future catalog lookup.
        return new CourseValidationResult(issues);
    }

    private static T[] Safe<T>(IReadOnlyList<T>? values, string location, List<CourseValidationIssue> issues)
    {
        if (values is null)
        {
            Add(issues, "collection_null", location, "Collection must be present; use an empty array when there are no items.");
            return Array.Empty<T>();
        }
        if (values.Any(item => item is null))
        {
            Add(issues, "collection_null_item", location, "Collection contains a null item.");
            return values.Where(item => item is not null).ToArray()!;
        }
        return values.ToArray();
    }

    private static Dictionary<string, T> UniqueById<T>(IEnumerable<T> items, Func<T, string> id, string kind, List<CourseValidationIssue> issues)
    {
        var result = new Dictionary<string, T>(StringComparer.OrdinalIgnoreCase);
        AddUnique(items, id, kind, result, issues);
        return result;
    }

    private static void AddUnique<T>(IEnumerable<T> items, Func<T, string> id, string kind, Dictionary<string, T> destination, List<CourseValidationIssue> issues)
    {
        foreach (T item in items)
        {
            string value = id(item) ?? string.Empty;
            if (!destination.TryAdd(value, item))
                Add(issues, "duplicate_id", $"{kind}[{value}]", $"Duplicate {kind} id '{value}'.");
        }
    }

    private static void ValidateReferenceList<T>(IReadOnlyList<string>? ids, IReadOnlyDictionary<string, T> target, string location, string kind, List<CourseValidationIssue> issues)
    {
        string[] values = Safe(ids, location, issues);
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (string value in values)
        {
            if (!CourseContractIdentifiers.IsStableId(value))
            {
                Add(issues, "id_invalid", location, $"Reference '{value}' is not a stable lower-case identifier.");
                continue;
            }
            if (!seen.Add(value))
                Add(issues, "reference_duplicate", location, $"Duplicate {kind} reference '{value}'.");
            if (!target.ContainsKey(value))
                Add(issues, "reference_missing", location, $"Unknown {kind} id '{value}'.");
        }
    }

    private static void RequireId(string? value, string label, string location, List<CourseValidationIssue> issues)
    {
        if (!CourseContractIdentifiers.IsStableId(value))
            Add(issues, "id_invalid", location, $"{label} must be a stable lower-case identifier.");
    }

    private static void RequireText(string? value, string location, List<CourseValidationIssue> issues)
    {
        if (string.IsNullOrWhiteSpace(value) || !string.Equals(value, value.Trim(), StringComparison.Ordinal))
            Add(issues, "text_invalid", location, "Value is required and must not contain leading/trailing whitespace.");
    }

    private static void RequireResourceKey(string? value, string location, List<CourseValidationIssue> issues)
    {
        if (!CourseContractIdentifiers.IsLogicalResourceKey(value))
            Add(issues, "resource_key_invalid", location, "Use a logical resource key, not an OS path or transport URL.");
    }

    private static void Add(List<CourseValidationIssue> issues, string code, string location, string message) =>
        issues.Add(new CourseValidationIssue(code, location, message));
}

/// <summary>
/// JSON is a presentation-neutral interchange boundary for future semantic web clients. The
/// deserialized graph is always validated before use.
/// </summary>
public static class CourseContractJson
{
    private static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = true,
        PropertyNameCaseInsensitive = false
    };

    public static string Serialize(Course course)
    {
        ArgumentNullException.ThrowIfNull(course);
        return JsonSerializer.Serialize(course, Options);
    }

    public static Course DeserializeAndValidate(
        string json,
        ILearningCapabilityRegistry capabilityRegistry,
        ISkillTargetRegistry skillTargetRegistry)
    {
        if (string.IsNullOrWhiteSpace(json)) throw new InvalidDataException("Course contract JSON is empty.");
        Course? course;
        try
        {
            course = JsonSerializer.Deserialize<Course>(json, Options);
        }
        catch (JsonException ex)
        {
            throw new InvalidDataException("Course contract JSON is invalid.", ex);
        }
        if (course is null) throw new InvalidDataException("Course contract JSON did not contain a course.");
        CourseValidationResult result = CourseContractValidator.Validate(course, capabilityRegistry, skillTargetRegistry);
        if (!result.IsValid)
            throw new InvalidDataException("Course contract validation failed: " + string.Join(" | ", result.Issues.Select(x => $"{x.Code}@{x.Location}: {x.Message}")));
        return course;
    }
}
