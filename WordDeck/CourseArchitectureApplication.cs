using System.Text.Json;
using WordDeck.Core.Courses;
using CourseModule = WordDeck.Core.Courses.Module;

namespace WordDeck.ApplicationLayer.Courses;

/// <summary>
/// Resolves declarative course capability references into the existing WordDeck learning engine.
/// The course layer never executes or reimplements learning behavior itself.
/// </summary>
public interface ILearningCapabilityRegistry
{
    bool CanResolve(string capabilityId);
}

/// <summary>
/// Resolves stable targets against their owning existing subsystem (lexical, grammar, etc.).
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
/// Pure structural/reference validation. No answer evaluation, progress transition, persistence,
/// WinForms behavior, or course-completion algorithm belongs here.
/// </summary>
public static class CourseContractValidator
{
    public static CourseValidationResult Validate(Course course, ILearningCapabilityRegistry capabilities, ISkillTargetRegistry skills)
    {
        ArgumentNullException.ThrowIfNull(course);
        ArgumentNullException.ThrowIfNull(capabilities);
        ArgumentNullException.ThrowIfNull(skills);
        var issues = new List<CourseValidationIssue>();

        Id(course.Id, "course.id", issues);
        Text(course.Version, "course.version", issues);
        Resource(course.TitleResourceKey, "course.titleResourceKey", issues);

        Level[] levels = Items(course.Levels, "course.levels", issues);
        SkillTarget[] targets = Items(course.SkillTargets, "course.skillTargets", issues);
        AudioAsset[] audio = Items(course.AudioAssets, "course.audioAssets", issues);
        Assessment[] assessments = Items(course.Assessments, "course.assessments", issues);

        var targetById = Index(targets, x => x.Id, "skillTarget", issues);
        var audioById = Index(audio, x => x.Id, "audioAsset", issues);
        var assessmentById = Index(assessments, x => x.Id, "assessment", issues);
        _ = Index(levels, x => x.Id, "level", issues);

        foreach (SkillTarget target in targets)
        {
            string at = $"skillTarget[{target.Id}]";
            Id(target.Id, at + ".id", issues);
            Id(target.Domain, at + ".domain", issues);
            Text(target.TargetRef, at + ".targetRef", issues);
            if (CourseContractIdentifiers.IsStableId(target.Domain) && !string.IsNullOrWhiteSpace(target.TargetRef) && !skills.CanResolve(target.Domain, target.TargetRef))
                Add(issues, "skill_target_unresolved", at + ".targetRef", "Target is not resolved by its owning existing subsystem registry.");
        }

        foreach (AudioAsset asset in audio)
        {
            string at = $"audioAsset[{asset.Id}]";
            Id(asset.Id, at + ".id", issues);
            Resource(asset.AssetKey, at + ".assetKey", issues);
            Text(asset.LanguageTag, at + ".languageTag", issues);
            if (asset.TranscriptResourceKey is not null) Resource(asset.TranscriptResourceKey, at + ".transcriptResourceKey", issues);
        }

        foreach (Assessment assessment in assessments)
        {
            string at = $"assessment[{assessment.Id}]";
            Id(assessment.Id, at + ".id", issues);
            Id(assessment.EvaluatorCapabilityId, at + ".evaluatorCapabilityId", issues);
            Id(assessment.PolicyId, at + ".policyId", issues);
            Refs(assessment.SkillTargetIds, targetById, at + ".skillTargetIds", "skill target", issues);
            if (CourseContractIdentifiers.IsStableId(assessment.EvaluatorCapabilityId) && !capabilities.CanResolve(assessment.EvaluatorCapabilityId))
                Add(issues, "capability_unresolved", at + ".evaluatorCapabilityId", "Evaluator is not resolved by the existing application capability registry.");
        }

        var modules = new Dictionary<string, CourseModule>(StringComparer.OrdinalIgnoreCase);
        var units = new Dictionary<string, Unit>(StringComparer.OrdinalIgnoreCase);
        var lessons = new Dictionary<string, Lesson>(StringComparer.OrdinalIgnoreCase);
        var activities = new Dictionary<string, Activity>(StringComparer.OrdinalIgnoreCase);
        var explanations = new Dictionary<string, Explanation>(StringComparer.OrdinalIgnoreCase);
        var checkpoints = new Dictionary<string, Checkpoint>(StringComparer.OrdinalIgnoreCase);

        foreach (Level level in levels)
        {
            string levelAt = $"level[{level.Id}]";
            Id(level.Id, levelAt + ".id", issues);
            Id(level.Code, levelAt + ".code", issues);
            Resource(level.TitleResourceKey, levelAt + ".titleResourceKey", issues);
            CourseModule[] levelModules = Items(level.Modules, levelAt + ".modules", issues);
            AddIndex(levelModules, x => x.Id, "module", modules, issues);
            AddIndex(Items(level.Checkpoints, levelAt + ".checkpoints", issues), x => x.Id, "checkpoint", checkpoints, issues);

            foreach (CourseModule module in levelModules)
            {
                string moduleAt = $"module[{module.Id}]";
                Id(module.Id, moduleAt + ".id", issues);
                Resource(module.TitleResourceKey, moduleAt + ".titleResourceKey", issues);
                Unit[] moduleUnits = Items(module.Units, moduleAt + ".units", issues);
                AddIndex(moduleUnits, x => x.Id, "unit", units, issues);
                AddIndex(Items(module.Checkpoints, moduleAt + ".checkpoints", issues), x => x.Id, "checkpoint", checkpoints, issues);

                foreach (Unit unit in moduleUnits)
                {
                    string unitAt = $"unit[{unit.Id}]";
                    Id(unit.Id, unitAt + ".id", issues);
                    Resource(unit.TitleResourceKey, unitAt + ".titleResourceKey", issues);
                    Lesson[] unitLessons = Items(unit.Lessons, unitAt + ".lessons", issues);
                    AddIndex(unitLessons, x => x.Id, "lesson", lessons, issues);
                    AddIndex(Items(unit.Checkpoints, unitAt + ".checkpoints", issues), x => x.Id, "checkpoint", checkpoints, issues);

                    foreach (Lesson lesson in unitLessons)
                    {
                        string lessonAt = $"lesson[{lesson.Id}]";
                        Id(lesson.Id, lessonAt + ".id", issues);
                        Resource(lesson.TitleResourceKey, lessonAt + ".titleResourceKey", issues);
                        AddIndex(Items(lesson.Activities, lessonAt + ".activities", issues), x => x.Id, "activity", activities, issues);
                        Explanation[] lessonExplanations = Items(lesson.Explanations, lessonAt + ".explanations", issues);
                        AddIndex(lessonExplanations, x => x.Id, "explanation", explanations, issues);
                        AddIndex(Items(lesson.Checkpoints, lessonAt + ".checkpoints", issues), x => x.Id, "checkpoint", checkpoints, issues);
                        foreach (Explanation explanation in lessonExplanations)
                        {
                            string at = $"explanation[{explanation.Id}]";
                            Id(explanation.Id, at + ".id", issues);
                            Resource(explanation.ContentResourceKey, at + ".contentResourceKey", issues);
                        }
                    }
                }
            }
        }

        foreach (Activity activity in activities.Values)
        {
            string at = $"activity[{activity.Id}]";
            Id(activity.Id, at + ".id", issues);
            Id(activity.CapabilityId, at + ".capabilityId", issues);
            Refs(activity.SkillTargetIds, targetById, at + ".skillTargetIds", "skill target", issues);
            Refs(activity.AudioAssetIds, audioById, at + ".audioAssetIds", "audio asset", issues);
            Refs(activity.ExplanationIds, explanations, at + ".explanationIds", "explanation", issues);
            OptionalRef(activity.AssessmentId, assessmentById, at + ".assessmentId", "assessment", issues);
            if (CourseContractIdentifiers.IsStableId(activity.CapabilityId) && !capabilities.CanResolve(activity.CapabilityId))
                Add(issues, "capability_unresolved", at + ".capabilityId", "Activity is not resolved by the existing application capability registry.");
        }

        foreach (Checkpoint checkpoint in checkpoints.Values)
        {
            string at = $"checkpoint[{checkpoint.Id}]";
            Id(checkpoint.Id, at + ".id", issues);
            Refs(checkpoint.SkillTargetIds, targetById, at + ".skillTargetIds", "skill target", issues);
            Refs(checkpoint.ActivityIds, activities, at + ".activityIds", "activity", issues);
            OptionalRef(checkpoint.AssessmentId, assessmentById, at + ".assessmentId", "assessment", issues);
        }

        if (course.FastTrack is { } fast)
        {
            string at = $"fastTrack[{fast.Id}]";
            Id(fast.Id, at + ".id", issues);
            Id(fast.PolicyId, at + ".policyId", issues);
            Refs(fast.LessonIds, lessons, at + ".lessonIds", "lesson", issues);
            Refs(fast.CheckpointIds, checkpoints, at + ".checkpointIds", "checkpoint", issues);
        }

        if (course.DeepPractice is { } deep)
        {
            string at = $"deepPractice[{deep.Id}]";
            Id(deep.Id, at + ".id", issues);
            Id(deep.PolicyId, at + ".policyId", issues);
            Refs(deep.ActivityIds, activities, at + ".activityIds", "activity", issues);
            Refs(deep.SkillTargetIds, targetById, at + ".skillTargetIds", "skill target", issues);
        }

        return new CourseValidationResult(issues);
    }

    private static T[] Items<T>(IReadOnlyList<T>? source, string at, List<CourseValidationIssue> issues)
    {
        if (source is null) { Add(issues, "collection_null", at, "Use an empty array instead of null."); return Array.Empty<T>(); }
        if (source.Any(x => x is null)) Add(issues, "collection_null_item", at, "Collection contains a null item.");
        return source.Where(x => x is not null).ToArray()!;
    }

    private static Dictionary<string, T> Index<T>(IEnumerable<T> source, Func<T, string> id, string kind, List<CourseValidationIssue> issues)
    {
        var result = new Dictionary<string, T>(StringComparer.OrdinalIgnoreCase);
        AddIndex(source, id, kind, result, issues);
        return result;
    }

    private static void AddIndex<T>(IEnumerable<T> source, Func<T, string> id, string kind, Dictionary<string, T> index, List<CourseValidationIssue> issues)
    {
        foreach (T item in source)
        {
            string key = id(item) ?? string.Empty;
            if (!index.TryAdd(key, item)) Add(issues, "duplicate_id", $"{kind}[{key}]", $"Duplicate {kind} id '{key}'.");
        }
    }

    private static void Refs<T>(IReadOnlyList<string>? ids, IReadOnlyDictionary<string, T> index, string at, string kind, List<CourseValidationIssue> issues)
    {
        string[] values = Items(ids, at, issues);
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (string value in values)
        {
            if (!CourseContractIdentifiers.IsStableId(value)) { Add(issues, "id_invalid", at, $"Reference '{value}' is not a stable lower-case identifier."); continue; }
            if (!seen.Add(value)) Add(issues, "reference_duplicate", at, $"Duplicate {kind} reference '{value}'.");
            if (!index.ContainsKey(value)) Add(issues, "reference_missing", at, $"Unknown {kind} id '{value}'.");
        }
    }

    private static void OptionalRef<T>(string? id, IReadOnlyDictionary<string, T> index, string at, string kind, List<CourseValidationIssue> issues)
    {
        if (id is null) return;
        if (!CourseContractIdentifiers.IsStableId(id)) Add(issues, "id_invalid", at, "Optional reference is not a stable lower-case identifier.");
        else if (!index.ContainsKey(id)) Add(issues, "reference_missing", at, $"Unknown {kind} id '{id}'.");
    }

    private static void Id(string? value, string at, List<CourseValidationIssue> issues)
    {
        if (!CourseContractIdentifiers.IsStableId(value)) Add(issues, "id_invalid", at, "Value must be a stable lower-case identifier.");
    }

    private static void Text(string? value, string at, List<CourseValidationIssue> issues)
    {
        if (string.IsNullOrWhiteSpace(value) || !string.Equals(value, value.Trim(), StringComparison.Ordinal)) Add(issues, "text_invalid", at, "Value is required and must be trimmed.");
    }

    private static void Resource(string? value, string at, List<CourseValidationIssue> issues)
    {
        if (!CourseContractIdentifiers.IsLogicalResourceKey(value)) Add(issues, "resource_key_invalid", at, "Use a logical resource key, not an OS path or transport URL.");
    }

    private static void Add(List<CourseValidationIssue> issues, string code, string at, string message) => issues.Add(new(code, at, message));
}

/// <summary>Presentation-neutral interchange seam for future semantic web clients.</summary>
public static class CourseContractJson
{
    private static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web) { WriteIndented = true, PropertyNameCaseInsensitive = false };

    public static string Serialize(Course course) => JsonSerializer.Serialize(course ?? throw new ArgumentNullException(nameof(course)), Options);

    public static Course DeserializeAndValidate(string json, ILearningCapabilityRegistry capabilities, ISkillTargetRegistry skills)
    {
        if (string.IsNullOrWhiteSpace(json)) throw new InvalidDataException("Course contract JSON is empty.");
        Course course;
        try { course = JsonSerializer.Deserialize<Course>(json, Options) ?? throw new InvalidDataException("Course contract JSON did not contain a course."); }
        catch (JsonException ex) { throw new InvalidDataException("Course contract JSON is invalid.", ex); }
        CourseValidationResult result = CourseContractValidator.Validate(course, capabilities, skills);
        if (!result.IsValid) throw new InvalidDataException("Course contract validation failed: " + string.Join(" | ", result.Issues.Select(x => $"{x.Code}@{x.Location}: {x.Message}")));
        return course;
    }
}
