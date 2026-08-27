using System.Text.Json;
using System.Text.Json.Serialization;

namespace WordDeck;

/// <summary>
/// Course activity is descriptive evidence, not a mastery judgment.
/// Exposure, practice and assessment therefore remain distinct persisted facts.
/// </summary>
internal enum LearnerActivityKind
{
    Exposure = 0,
    Practice = 1,
    Assessment = 2
}

/// <summary>
/// Adaptive routing is orthogonal to mastery and course position. A route says
/// what the learner should do next; it never proves competence by itself.
/// </summary>
internal enum AdaptivePracticeRoute
{
    Standard = 0,
    FastTrack = 1,
    DeepPractice = 2
}

internal sealed class LearnerEvidenceEvent
{
    public required string EventId { get; set; }
    public LearnerActivityKind ActivityKind { get; set; }
    public required string PathId { get; set; }
    public required string CourseId { get; set; }
    public string? ModuleId { get; set; }
    public string? UnitId { get; set; }
    public string? ObjectiveId { get; set; }
    public string? SkillId { get; set; }
    public string? ItemId { get; set; }
    public string? AssessmentId { get; set; }
    public List<string> LexicalEntryIds { get; set; } = new();
    public bool Completed { get; set; }
    public bool? Correct { get; set; }
    public bool IsUnseenMaterial { get; set; }
    public bool IsProductivePerformance { get; set; }
    public bool IsTransferPerformance { get; set; }
    public int HintUses { get; set; }
    public int RevealUses { get; set; }
    public int AttemptNumber { get; set; } = 1;
    public DateTimeOffset OccurredAtUtc { get; set; } = DateTimeOffset.UtcNow;

    [JsonExtensionData]
    public Dictionary<string, JsonElement>? ExtensionData { get; set; }
}

/// <summary>
/// A mastery claim is a derived, attributable statement. No activity event,
/// lesson completion, reveal, streak or course position automatically creates it.
/// Thresholds and derivation rules are supplied by an approved assessment/router
/// contract and identified by RuleVersion rather than hard-coded here.
/// </summary>
internal sealed class MasteryClaim
{
    public required string ObjectiveId { get; set; }
    public bool Demonstrated { get; set; }
    public bool RequiresRevalidation { get; set; }
    public required string RuleVersion { get; set; }
    public List<string> EvidenceEventIds { get; set; } = new();
    public DateTimeOffset DerivedAtUtc { get; set; } = DateTimeOffset.UtcNow;

    [JsonExtensionData]
    public Dictionary<string, JsonElement>? ExtensionData { get; set; }
}

/// <summary>
/// A bookmark is navigation state only. It is deliberately not named progress or
/// completion so resuming a course can never be confused with proving a skill.
/// </summary>
internal sealed class CoursePositionBookmark
{
    public required string PathId { get; set; }
    public required string CourseId { get; set; }
    public string? ModuleId { get; set; }
    public string? UnitId { get; set; }
    public string? ActivityId { get; set; }
    public DateTimeOffset UpdatedAtUtc { get; set; } = DateTimeOffset.UtcNow;

    [JsonExtensionData]
    public Dictionary<string, JsonElement>? ExtensionData { get; set; }
}

internal sealed class AdaptiveRouteDecision
{
    public required string PathId { get; set; }
    public AdaptivePracticeRoute Route { get; set; }
    public required string RuleVersion { get; set; }
    public required string ReasonCode { get; set; }
    public List<string> EvidenceEventIds { get; set; } = new();
    public DateTimeOffset AssignedAtUtc { get; set; } = DateTimeOffset.UtcNow;

    [JsonExtensionData]
    public Dictionary<string, JsonElement>? ExtensionData { get; set; }
}

/// <summary>
/// Skill estimates remain independent. LevelId is intentionally a stable string
/// supplied by the assessment layer (for example pre-a1/a1/.../c1), not an enum
/// whose ordering could accidentally become an averaging or promotion rule.
/// </summary>
internal sealed class SkillLevelEstimate
{
    public required string SkillId { get; set; }
    public required string LevelId { get; set; }
    public string? SourceAssessmentId { get; set; }
    public double? Confidence { get; set; }
    public List<string> EvidenceEventIds { get; set; } = new();
    public DateTimeOffset MeasuredAtUtc { get; set; } = DateTimeOffset.UtcNow;

    [JsonExtensionData]
    public Dictionary<string, JsonElement>? ExtensionData { get; set; }
}

/// <summary>
/// Versioned sidecar for future Complete English / Deep Skill state. Existing
/// Recall, hidden-word, Spelling and Sentence state remains owned by its current
/// stores and is never inferred into this model.
/// </summary>
internal sealed class LearnerCourseState
{
    public int SchemaVersion { get; set; } = LearnerCourseStateStore.CurrentSchemaVersion;
    public string? CatalogVersion { get; set; }
    public Dictionary<string, CoursePositionBookmark> CoursePositionsByPathId { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public List<LearnerEvidenceEvent> EvidenceHistory { get; set; } = new();
    public Dictionary<string, MasteryClaim> MasteryByObjectiveId { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public Dictionary<string, AdaptiveRouteDecision> AdaptiveRouteByPathId { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public Dictionary<string, SkillLevelEstimate> SkillLevelsBySkillId { get; set; } = new(StringComparer.OrdinalIgnoreCase);

    // IDs absent from the currently installed course/catalog may be surfaced here
    // by a future catalog reconciler. They are retained rather than silently lost.
    public List<string> OrphanedStableIds { get; set; } = new();

    [JsonExtensionData]
    public Dictionary<string, JsonElement>? ExtensionData { get; set; }
}

internal sealed record LearnerCourseStateImportResult(string? BackupPath, int SourceSchemaVersion);

/// <summary>
/// Safe sidecar persistence under the existing WordDeck LocalAppData root.
/// This store is not wired into the current UI yet: it establishes a migration-
/// safe contract without changing existing Recall/Spelling/Sentence semantics.
/// </summary>
internal sealed class LearnerCourseStateStore
{
    public const int CurrentSchemaVersion = 1;
    public const string FileName = "course-learning-state.json";
    public const string BackupFileName = "course-learning-state.backup.json";

    private static readonly JsonSerializerOptions JsonOptions = CreateJsonOptions();
    private readonly string _root;
    private readonly string _statePath;
    private readonly string _backupPath;
    private readonly string _backupsDirectory;

    public LearnerCourseStateStore()
        : this(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WordDeck"))
    {
    }

    internal LearnerCourseStateStore(string root)
    {
        if (string.IsNullOrWhiteSpace(root))
            throw new ArgumentException("Course-state root directory must not be blank.", nameof(root));
        _root = Path.GetFullPath(root);
        _statePath = Path.Combine(_root, FileName);
        _backupPath = Path.Combine(_root, BackupFileName);
        _backupsDirectory = Path.Combine(_root, "Backups");
        Directory.CreateDirectory(_root);
        Directory.CreateDirectory(_backupsDirectory);
    }

    public LearnerCourseState Load()
    {
        if (TryRead(_statePath, out LearnerCourseState? primary))
            return PrepareLoaded(primary!, _statePath);
        if (TryRead(_backupPath, out LearnerCourseState? backup))
            return PrepareLoaded(backup!, _backupPath);

        if (File.Exists(_statePath) || File.Exists(_backupPath))
            throw new InvalidDataException("WordDeck course learning state is unreadable and no verified backup can be loaded. Existing files were left untouched.");

        return NewEmpty();
    }

    public void Save(LearnerCourseState state)
    {
        ArgumentNullException.ThrowIfNull(state);
        LearnerCourseState snapshot = Clone(state);
        snapshot.SchemaVersion = CurrentSchemaVersion;
        Validate(snapshot);

        string temp = _statePath + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(snapshot, JsonOptions));
        if (!TryRead(temp, out LearnerCourseState? verified))
        {
            TryDelete(temp);
            throw new InvalidDataException("Course-state write verification failed; existing state was not replaced.");
        }
        Validate(verified!);

        // Only a parseable primary may become the fixed recovery backup. Corrupt
        // primary bytes are never allowed to overwrite a good backup.
        if (TryRead(_statePath, out LearnerCourseState? existing) && existing is not null)
            File.Copy(_statePath, _backupPath, true);

        File.Move(temp, _statePath, true);
        ReplaceInMemory(state, snapshot);
    }

    public string CreateTimestampedBackup(string reason)
    {
        string? source = TryRead(_statePath, out _) ? _statePath : TryRead(_backupPath, out _) ? _backupPath : null;
        if (source is null)
            throw new InvalidDataException("No parseable WordDeck course state exists to back up.");
        return CreateTimestampedFileBackup(source, reason);
    }

    public void ExportSnapshot(LearnerCourseState state, string destinationPath)
    {
        ArgumentNullException.ThrowIfNull(state);
        if (string.IsNullOrWhiteSpace(destinationPath))
            throw new ArgumentException("Course-state export destination is required.", nameof(destinationPath));

        LearnerCourseState snapshot = Clone(state);
        snapshot.SchemaVersion = CurrentSchemaVersion;
        Validate(snapshot);
        string fullPath = Path.GetFullPath(destinationPath);
        string? directory = Path.GetDirectoryName(fullPath);
        if (!string.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);
        string temp = fullPath + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(snapshot, JsonOptions));
        if (!TryRead(temp, out LearnerCourseState? verified) || verified is null)
        {
            TryDelete(temp);
            throw new InvalidDataException("Exported course-state snapshot could not be verified.");
        }
        Validate(verified);
        File.Move(temp, fullPath, true);
    }

    public LearnerCourseStateImportResult ImportSnapshot(string sourcePath)
    {
        if (!File.Exists(sourcePath))
            throw new FileNotFoundException("WordDeck course-state snapshot was not found.", sourcePath);
        if (!TryRead(sourcePath, out LearnerCourseState? imported) || imported is null)
            throw new InvalidDataException("The selected file is not a readable WordDeck course-state snapshot.");
        if (imported.SchemaVersion > CurrentSchemaVersion)
            throw new InvalidDataException($"Course-state schema {imported.SchemaVersion} is newer than supported schema {CurrentSchemaVersion}. No personal state was changed.");

        int sourceSchema = imported.SchemaVersion;
        LearnerCourseState prepared = imported.SchemaVersion < CurrentSchemaVersion
            ? Migrate(Clone(imported), imported.SchemaVersion)
            : Clone(imported);
        Validate(prepared);

        string? backup = null;
        if (TryRead(_statePath, out _) || TryRead(_backupPath, out _))
            backup = CreateTimestampedBackup("pre-import");

        Save(prepared);
        return new LearnerCourseStateImportResult(backup, sourceSchema);
    }

    internal static LearnerCourseState NewEmpty() => new()
    {
        SchemaVersion = CurrentSchemaVersion
    };

    internal static void Validate(LearnerCourseState state)
    {
        ArgumentNullException.ThrowIfNull(state);
        if (state.SchemaVersion > CurrentSchemaVersion)
            throw new InvalidDataException($"Course-state schema {state.SchemaVersion} is newer than supported schema {CurrentSchemaVersion}.");
        if (state.SchemaVersion < 0)
            throw new InvalidDataException("Course-state schema version cannot be negative.");

        state.CoursePositionsByPathId ??= new(StringComparer.OrdinalIgnoreCase);
        state.EvidenceHistory ??= new();
        state.MasteryByObjectiveId ??= new(StringComparer.OrdinalIgnoreCase);
        state.AdaptiveRouteByPathId ??= new(StringComparer.OrdinalIgnoreCase);
        state.SkillLevelsBySkillId ??= new(StringComparer.OrdinalIgnoreCase);
        state.OrphanedStableIds ??= new();

        var eventIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (LearnerEvidenceEvent evidence in state.EvidenceHistory)
        {
            if (evidence is null) throw new InvalidDataException("Course evidence history contains a null event.");
            RequireId(evidence.EventId, "evidence event");
            RequireId(evidence.PathId, "evidence path");
            RequireId(evidence.CourseId, "evidence course");
            if (!eventIds.Add(evidence.EventId)) throw new InvalidDataException($"Duplicate course evidence event id '{evidence.EventId}'.");
            if (evidence.HintUses < 0 || evidence.RevealUses < 0 || evidence.AttemptNumber < 1)
                throw new InvalidDataException($"Course evidence event '{evidence.EventId}' contains invalid counters.");
            evidence.LexicalEntryIds ??= new();
            if (evidence.LexicalEntryIds.Any(string.IsNullOrWhiteSpace))
                throw new InvalidDataException($"Course evidence event '{evidence.EventId}' contains a blank lexical stable ID.");
            if (evidence.LexicalEntryIds.Distinct(StringComparer.OrdinalIgnoreCase).Count() != evidence.LexicalEntryIds.Count)
                throw new InvalidDataException($"Course evidence event '{evidence.EventId}' contains duplicate lexical stable IDs.");
        }

        foreach ((string key, CoursePositionBookmark position) in state.CoursePositionsByPathId)
        {
            RequireId(key, "course-position map key");
            if (position is null) throw new InvalidDataException($"Course position '{key}' is null.");
            RequireId(position.PathId, "course-position path");
            RequireId(position.CourseId, "course-position course");
            if (!key.Equals(position.PathId, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException($"Course position map key '{key}' does not match path id '{position.PathId}'.");
        }

        foreach ((string key, MasteryClaim claim) in state.MasteryByObjectiveId)
        {
            RequireId(key, "mastery map key");
            if (claim is null) throw new InvalidDataException($"Mastery claim '{key}' is null.");
            RequireId(claim.ObjectiveId, "mastery objective");
            RequireId(claim.RuleVersion, "mastery rule version");
            if (!key.Equals(claim.ObjectiveId, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException($"Mastery map key '{key}' does not match objective id '{claim.ObjectiveId}'.");
            ValidateEvidenceReferences(claim.EvidenceEventIds, eventIds, $"mastery '{key}'");
        }

        foreach ((string key, AdaptiveRouteDecision route) in state.AdaptiveRouteByPathId)
        {
            RequireId(key, "adaptive-route map key");
            if (route is null) throw new InvalidDataException($"Adaptive route '{key}' is null.");
            RequireId(route.PathId, "adaptive-route path");
            RequireId(route.RuleVersion, "adaptive-route rule version");
            RequireId(route.ReasonCode, "adaptive-route reason");
            if (!key.Equals(route.PathId, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException($"Adaptive route map key '{key}' does not match path id '{route.PathId}'.");
            ValidateEvidenceReferences(route.EvidenceEventIds, eventIds, $"adaptive route '{key}'");
        }

        foreach ((string key, SkillLevelEstimate estimate) in state.SkillLevelsBySkillId)
        {
            RequireId(key, "skill-level map key");
            if (estimate is null) throw new InvalidDataException($"Skill estimate '{key}' is null.");
            RequireId(estimate.SkillId, "skill-level skill");
            RequireId(estimate.LevelId, "skill-level level");
            if (!key.Equals(estimate.SkillId, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException($"Skill-level map key '{key}' does not match skill id '{estimate.SkillId}'.");
            if (estimate.Confidence is < 0 or > 1)
                throw new InvalidDataException($"Skill estimate '{key}' confidence must be between 0 and 1 when supplied.");
            ValidateEvidenceReferences(estimate.EvidenceEventIds, eventIds, $"skill estimate '{key}'");
        }

        if (state.OrphanedStableIds.Any(string.IsNullOrWhiteSpace))
            throw new InvalidDataException("Course-state orphan ledger contains a blank stable ID.");
    }

    private LearnerCourseState PrepareLoaded(LearnerCourseState state, string sourcePath)
    {
        if (state.SchemaVersion > CurrentSchemaVersion)
            throw new InvalidDataException($"This WordDeck course state uses newer schema {state.SchemaVersion}; this build supports up to {CurrentSchemaVersion}. No state was changed.");
        if (state.SchemaVersion < CurrentSchemaVersion)
        {
            CreateTimestampedFileBackup(sourcePath, "pre-migration");
            LearnerCourseState migrated = Migrate(state, state.SchemaVersion);
            Save(migrated);
            return migrated;
        }
        Validate(state);
        return state;
    }

    private static LearnerCourseState Migrate(LearnerCourseState state, int fromVersion)
    {
        // Schema 0 was never a production course schema. It exists only as an
        // explicit additive migration seam: no old Recall/Spelling/Sentence data
        // is promoted into mastery or assessment evidence.
        if (fromVersion == 0)
        {
            state.SchemaVersion = 1;
            fromVersion = 1;
        }
        if (fromVersion != CurrentSchemaVersion)
            throw new InvalidDataException($"No safe course-state migration path exists from schema {fromVersion}.");
        Validate(state);
        return state;
    }

    private string CreateTimestampedFileBackup(string sourcePath, string reason)
    {
        Directory.CreateDirectory(_backupsDirectory);
        string safeReason = string.Concat((reason ?? "backup").Select(ch => char.IsLetterOrDigit(ch) || ch is '-' or '_' ? ch : '-'));
        if (string.IsNullOrWhiteSpace(safeReason)) safeReason = "backup";
        string destination = Path.Combine(_backupsDirectory, $"course-learning-state-{DateTime.UtcNow:yyyyMMdd-HHmmssfff}-{safeReason}.json");
        File.Copy(sourcePath, destination, false);
        foreach (FileInfo stale in new DirectoryInfo(_backupsDirectory).GetFiles("course-learning-state-*.json")
                     .OrderByDescending(file => file.LastWriteTimeUtc).Skip(20))
            TryDelete(stale.FullName);
        return destination;
    }

    private static bool TryRead(string path, out LearnerCourseState? state)
    {
        state = null;
        try
        {
            if (!File.Exists(path)) return false;
            state = JsonSerializer.Deserialize<LearnerCourseState>(File.ReadAllText(path), JsonOptions);
            return state is not null;
        }
        catch
        {
            return false;
        }
    }

    private static LearnerCourseState Clone(LearnerCourseState state) =>
        JsonSerializer.Deserialize<LearnerCourseState>(JsonSerializer.Serialize(state, JsonOptions), JsonOptions)
        ?? throw new InvalidDataException("Could not clone WordDeck course learning state.");

    private static void ReplaceInMemory(LearnerCourseState destination, LearnerCourseState source)
    {
        destination.SchemaVersion = source.SchemaVersion;
        destination.CatalogVersion = source.CatalogVersion;
        destination.CoursePositionsByPathId = source.CoursePositionsByPathId;
        destination.EvidenceHistory = source.EvidenceHistory;
        destination.MasteryByObjectiveId = source.MasteryByObjectiveId;
        destination.AdaptiveRouteByPathId = source.AdaptiveRouteByPathId;
        destination.SkillLevelsBySkillId = source.SkillLevelsBySkillId;
        destination.OrphanedStableIds = source.OrphanedStableIds;
        destination.ExtensionData = source.ExtensionData;
    }

    private static void ValidateEvidenceReferences(IEnumerable<string>? references, IReadOnlySet<string> eventIds, string owner)
    {
        if (references is null) throw new InvalidDataException($"{owner} has a null evidence reference list.");
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (string id in references)
        {
            RequireId(id, $"{owner} evidence reference");
            if (!seen.Add(id)) throw new InvalidDataException($"{owner} contains duplicate evidence event id '{id}'.");
            if (!eventIds.Contains(id)) throw new InvalidDataException($"{owner} references missing evidence event '{id}'.");
        }
    }

    private static void RequireId(string? value, string label)
    {
        if (string.IsNullOrWhiteSpace(value)) throw new InvalidDataException($"WordDeck {label} must have a stable non-blank id.");
    }

    private static void TryDelete(string path)
    {
        try { if (File.Exists(path)) File.Delete(path); } catch { }
    }

    private static JsonSerializerOptions CreateJsonOptions()
    {
        var options = new JsonSerializerOptions
        {
            WriteIndented = true,
            PropertyNameCaseInsensitive = true
        };
        options.Converters.Add(new JsonStringEnumConverter());
        return options;
    }
}
