using System.Text.RegularExpressions;

namespace WordDeck.Core.Courses;

/// <summary>
/// Platform-neutral declarative course graph. It contains structure and references only;
/// learning behavior remains in existing WordDeck application capabilities.
/// </summary>
public sealed record Course(
    string Id,
    string Version,
    string TitleResourceKey,
    IReadOnlyList<Level> Levels,
    IReadOnlyList<SkillTarget> SkillTargets,
    IReadOnlyList<AudioAsset> AudioAssets,
    IReadOnlyList<Assessment> Assessments,
    FastTrack? FastTrack = null,
    DeepPractice? DeepPractice = null);

public sealed record Level(
    string Id,
    string Code,
    string TitleResourceKey,
    IReadOnlyList<Module> Modules,
    IReadOnlyList<Checkpoint> Checkpoints);

public sealed record Module(
    string Id,
    string TitleResourceKey,
    IReadOnlyList<Unit> Units,
    IReadOnlyList<Checkpoint> Checkpoints);

public sealed record Unit(
    string Id,
    string TitleResourceKey,
    IReadOnlyList<Lesson> Lessons,
    IReadOnlyList<Checkpoint> Checkpoints);

public sealed record Lesson(
    string Id,
    string TitleResourceKey,
    IReadOnlyList<Activity> Activities,
    IReadOnlyList<Explanation> Explanations,
    IReadOnlyList<Checkpoint> Checkpoints);

/// <summary>
/// A declarative request to invoke an existing learning capability. The contract deliberately
/// contains no answer evaluator, mastery transition, WinForms command, or persistence logic.
/// </summary>
public sealed record Activity(
    string Id,
    string CapabilityId,
    IReadOnlyList<string> SkillTargetIds,
    IReadOnlyList<string> AudioAssetIds,
    IReadOnlyList<string> ExplanationIds,
    string? AssessmentId = null);

/// <summary>
/// Reference to explanation content supplied by an approved curriculum/content source.
/// Text itself is not authored by the architecture layer.
/// </summary>
public sealed record Explanation(
    string Id,
    string ContentResourceKey);

/// <summary>
/// Stable cross-engine target reference. Domain identifies the owner (for example lexical or
/// grammar); TargetRef is resolved by the owning existing application subsystem.
/// </summary>
public sealed record SkillTarget(
    string Id,
    string Domain,
    string TargetRef);

/// <summary>
/// Logical audio reference only. Infrastructure adapters resolve AssetKey to local files,
/// packaged assets, or future web delivery without changing the course graph.
/// </summary>
public sealed record AudioAsset(
    string Id,
    string AssetKey,
    string LanguageTag,
    string? TranscriptResourceKey = null);

public sealed record Checkpoint(
    string Id,
    IReadOnlyList<string> SkillTargetIds,
    IReadOnlyList<string> ActivityIds,
    string? AssessmentId = null);

/// <summary>
/// References an existing evaluator and externally defined scoring policy. The course contract
/// does not implement assessment scoring or mastery.
/// </summary>
public sealed record Assessment(
    string Id,
    string EvaluatorCapabilityId,
    string PolicyId,
    IReadOnlyList<string> SkillTargetIds);

/// <summary>
/// Declarative route through existing lessons/checkpoints. Selection logic belongs to the
/// application policy referenced by PolicyId, not this data model.
/// </summary>
public sealed record FastTrack(
    string Id,
    string PolicyId,
    IReadOnlyList<string> LessonIds,
    IReadOnlyList<string> CheckpointIds);

/// <summary>
/// Declarative extra-practice route. Existing learning capabilities execute the referenced
/// activities; this contract does not introduce a second practice engine.
/// </summary>
public sealed record DeepPractice(
    string Id,
    string PolicyId,
    IReadOnlyList<string> ActivityIds,
    IReadOnlyList<string> SkillTargetIds);

public static class CourseContractIdentifiers
{
    private static readonly Regex StableId = new("^[a-z0-9][a-z0-9._-]*$", RegexOptions.Compiled | RegexOptions.CultureInvariant);

    public static bool IsStableId(string? value) =>
        !string.IsNullOrWhiteSpace(value) &&
        string.Equals(value, value.Trim(), StringComparison.Ordinal) &&
        StableId.IsMatch(value);

    public static bool IsLogicalResourceKey(string? value)
    {
        if (string.IsNullOrWhiteSpace(value) || !string.Equals(value, value.Trim(), StringComparison.Ordinal))
            return false;
        if (value.Contains("://", StringComparison.Ordinal) || value.StartsWith('/') || value.StartsWith('\\'))
            return false;
        if (value.Length >= 3 && char.IsLetter(value[0]) && value[1] == ':' && (value[2] == '\\' || value[2] == '/'))
            return false;
        return true;
    }
}
