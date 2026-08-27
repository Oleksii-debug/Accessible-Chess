using System.Text.RegularExpressions;

namespace WordDeck;

internal enum StoryCourseCurriculumAuthority
{
    TechnicalFixture,
    PedagogicalDraft,
    ApprovedCurriculum
}

internal enum StoryCourseContentOrigin
{
    WordDeckAuthored,
    LicensedSource,
    LearnerLocal,
    GeneratedFixture
}

internal enum StoryCourseNarrativeKind
{
    Dialogue,
    Story
}

internal enum StoryCourseComprehensionKind
{
    BoundedResponse,
    FreeResponse
}

internal enum StoryCourseProductiveChannel
{
    Speaking,
    Writing,
    Mixed
}

internal enum StoryCourseMasteryDecision
{
    Unknown,
    NotYet,
    Mastered
}

internal sealed record StoryCourseProvenanceContract(
    StoryCourseContentOrigin Origin,
    string SourceId,
    string Version,
    string LicenseOrRights,
    string Attribution)
{
    public void Validate(string ownerId)
    {
        StoryCourseContractId.Require(ownerId, "provenance owner id");
        StoryCourseContractText.Require(SourceId, $"{ownerId} provenance source id");
        StoryCourseContractText.Require(Version, $"{ownerId} provenance version");
        StoryCourseContractText.Require(LicenseOrRights, $"{ownerId} provenance license/rights");

        if (Origin == StoryCourseContentOrigin.LicensedSource && string.IsNullOrWhiteSpace(Attribution))
            throw new InvalidDataException($"{ownerId} licensed content requires attribution.");
        if (Origin == StoryCourseContentOrigin.GeneratedFixture &&
            LicenseOrRights.Contains("approved curriculum", StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException($"{ownerId} generated fixture must not masquerade as approved curriculum.");
    }
}

internal sealed record StoryCourseObjectiveContract(
    string ObjectiveId,
    string Description,
    IReadOnlyList<string> EvidenceChannels)
{
    public void Validate(string moduleId)
    {
        StoryCourseContractId.Require(ObjectiveId, $"{moduleId} objective id");
        StoryCourseContractText.Require(Description, $"{ObjectiveId} objective description");
        if (EvidenceChannels is null || EvidenceChannels.Count == 0 || EvidenceChannels.Any(string.IsNullOrWhiteSpace))
            throw new InvalidDataException($"{ObjectiveId} requires at least one explicit evidence channel.");
    }
}

/// <summary>
/// Targets carry canonical identities only. Story/Course content must never
/// identify lexical targets by a surface form or own a parallel Grammar registry.
/// </summary>
internal sealed record StoryCourseTargetsContract(
    IReadOnlyList<string> LexicalEntryIds,
    IReadOnlyList<string> GrammarSkillIds)
{
    public void ValidateShape(string unitId)
    {
        if (LexicalEntryIds is null || GrammarSkillIds is null)
            throw new InvalidDataException($"{unitId} target collections are required.");
        if (LexicalEntryIds.Any(string.IsNullOrWhiteSpace))
            throw new InvalidDataException($"{unitId} contains a blank stable lexical entry id.");
        if (GrammarSkillIds.Any(string.IsNullOrWhiteSpace))
            throw new InvalidDataException($"{unitId} contains a blank Grammar skill reference.");
        if (LexicalEntryIds.Count == 0 && GrammarSkillIds.Count == 0)
            throw new InvalidDataException($"{unitId} requires at least one lexical or Grammar target.");
        if (LexicalEntryIds.Distinct(StringComparer.OrdinalIgnoreCase).Count() != LexicalEntryIds.Count)
            throw new InvalidDataException($"{unitId} contains duplicate stable lexical entry ids.");
    }
}

internal sealed record ResolvedStoryCourseTargets(
    IReadOnlyList<DictionaryEntry> LexicalEntries,
    IReadOnlyList<string> GrammarSkillIds);

internal static class StoryCourseIdentityResolver
{
    public static ResolvedStoryCourseTargets Resolve(DictionaryPackage dictionary, StoryCourseTargetsContract targets, string unitId)
    {
        ArgumentNullException.ThrowIfNull(dictionary);
        ArgumentNullException.ThrowIfNull(targets);
        targets.ValidateShape(unitId);

        var duplicateDictionaryIds = dictionary.Entries
            .GroupBy(entry => entry.Id, StringComparer.OrdinalIgnoreCase)
            .Where(group => group.Count() != 1)
            .Select(group => group.Key)
            .ToArray();
        if (duplicateDictionaryIds.Length != 0)
            throw new InvalidDataException("Active dictionary contains duplicate stable entry ids and cannot safely resolve Story/Course targets.");

        IReadOnlyDictionary<string, DictionaryEntry> byId = dictionary.Entries
            .ToDictionary(entry => entry.Id, StringComparer.OrdinalIgnoreCase);

        var lexical = new List<DictionaryEntry>(targets.LexicalEntryIds.Count);
        foreach (string rawId in targets.LexicalEntryIds)
        {
            string id = rawId.Trim();
            if (!byId.TryGetValue(id, out DictionaryEntry? entry))
                throw new InvalidDataException($"{unitId} references unknown stable lexical entry id '{rawId}'.");
            lexical.Add(entry);
        }

        // Canonical resolver owns aliases, validation and fail-closed behavior.
        // No Story/Course Grammar alias map or known-ID snapshot is permitted here.
        IReadOnlyList<string> grammar = GrammarSkillReferenceResolver.Normalize(targets.GrammarSkillIds);
        return new ResolvedStoryCourseTargets(lexical, grammar);
    }
}

internal sealed record StoryCourseNarrativeContract(
    string ContentId,
    StoryCourseNarrativeKind Kind,
    string Text,
    IReadOnlyList<string> SpeakerIds,
    StoryCourseProvenanceContract Provenance)
{
    public void Validate(string unitId)
    {
        StoryCourseContractId.Require(ContentId, $"{unitId} dialogue/story id");
        StoryCourseContractText.Require(Text, $"{ContentId} dialogue/story text");
        if (SpeakerIds is null || SpeakerIds.Any(string.IsNullOrWhiteSpace))
            throw new InvalidDataException($"{ContentId} speaker metadata is invalid.");
        if (Kind == StoryCourseNarrativeKind.Dialogue && SpeakerIds.Distinct(StringComparer.OrdinalIgnoreCase).Count() < 2)
            throw new InvalidDataException($"{ContentId} dialogue requires at least two distinct speaker ids.");
        Provenance?.Validate(ContentId);
        if (Provenance is null) throw new InvalidDataException($"{ContentId} provenance is required.");
    }
}

internal sealed record StoryCourseComprehensionTaskContract(
    string TaskId,
    StoryCourseComprehensionKind Kind,
    string Prompt,
    IReadOnlyList<string> ObjectiveIds,
    IReadOnlyList<string> AcceptedBoundedResponses)
{
    public void Validate(string unitId, ISet<string> objectiveIds)
    {
        StoryCourseContractId.Require(TaskId, $"{unitId} comprehension task id");
        StoryCourseContractText.Require(Prompt, $"{TaskId} comprehension prompt");
        StoryCourseContractReferences.RequireOwned(ObjectiveIds, objectiveIds, TaskId, "objective");
        if (AcceptedBoundedResponses is null || AcceptedBoundedResponses.Any(string.IsNullOrWhiteSpace))
            throw new InvalidDataException($"{TaskId} bounded response collection is invalid.");
        if (Kind == StoryCourseComprehensionKind.BoundedResponse && AcceptedBoundedResponses.Count == 0)
            throw new InvalidDataException($"{TaskId} bounded comprehension requires at least one accepted response.");
        if (Kind == StoryCourseComprehensionKind.FreeResponse && AcceptedBoundedResponses.Count != 0)
            throw new InvalidDataException($"{TaskId} free-response comprehension must be evaluated by an external evidence policy, not a hidden fixed-answer list.");
    }
}

internal sealed record StoryCourseProductiveTaskContract(
    string TaskId,
    StoryCourseProductiveChannel Channel,
    string Prompt,
    IReadOnlyList<string> ObjectiveIds,
    string EvaluationPolicyId)
{
    public void Validate(string unitId, ISet<string> objectiveIds)
    {
        StoryCourseContractId.Require(TaskId, $"{unitId} productive task id");
        StoryCourseContractText.Require(Prompt, $"{TaskId} productive prompt");
        StoryCourseContractReferences.RequireOwned(ObjectiveIds, objectiveIds, TaskId, "objective");
        StoryCourseContractId.Require(EvaluationPolicyId, $"{TaskId} evaluation policy id");
    }
}

internal sealed record StoryCourseCheckpointContract(
    string CheckpointId,
    IReadOnlyList<string> ObjectiveIds,
    string EvidencePolicyId,
    bool UsesUnseenMaterial)
{
    public void Validate(string unitId, ISet<string> objectiveIds)
    {
        StoryCourseContractId.Require(CheckpointId, $"{unitId} checkpoint id");
        StoryCourseContractReferences.RequireOwned(ObjectiveIds, objectiveIds, CheckpointId, "objective");
        StoryCourseContractId.Require(EvidencePolicyId, $"{CheckpointId} evidence policy id");
    }
}

internal sealed record StoryCourseUnitContract(
    string UnitId,
    string ModuleId,
    string Title,
    IReadOnlyList<string> ObjectiveIds,
    StoryCourseTargetsContract Targets,
    IReadOnlyList<StoryCourseNarrativeContract> DialogueOrStory,
    IReadOnlyList<StoryCourseComprehensionTaskContract> ComprehensionTasks,
    IReadOnlyList<StoryCourseProductiveTaskContract> ProductiveTasks,
    StoryCourseCheckpointContract? Checkpoint,
    StoryCourseProvenanceContract Provenance);

internal sealed record StoryCourseModuleContract(
    string ModuleId,
    string LevelId,
    string Title,
    IReadOnlyList<StoryCourseObjectiveContract> Objectives,
    IReadOnlyList<StoryCourseUnitContract> Units);

internal sealed record StoryCourseLevelContract(
    string LevelId,
    string FrameworkLevel,
    string Title,
    int Sequence,
    IReadOnlyList<StoryCourseModuleContract> Modules);

internal sealed record StoryCourseManifestContract(
    string CourseId,
    string Title,
    StoryCourseCurriculumAuthority CurriculumAuthority,
    bool ClaimsCompleteEnglishCourse,
    IReadOnlyList<StoryCourseLevelContract> Levels,
    StoryCourseProvenanceContract Provenance);

internal static class StoryCourseContractValidator
{
    private static readonly HashSet<string> SupportedFrameworkLevels = new(StringComparer.OrdinalIgnoreCase)
    {
        "Pre-A1", "A1", "A2", "B1", "B2", "C1"
    };

    public static void Validate(StoryCourseManifestContract manifest, DictionaryPackage dictionary)
    {
        ArgumentNullException.ThrowIfNull(manifest);
        ArgumentNullException.ThrowIfNull(dictionary);
        StoryCourseContractId.Require(manifest.CourseId, "course id");
        StoryCourseContractText.Require(manifest.Title, $"{manifest.CourseId} title");
        manifest.Provenance?.Validate(manifest.CourseId);
        if (manifest.Provenance is null) throw new InvalidDataException($"{manifest.CourseId} provenance is required.");
        if (manifest.ClaimsCompleteEnglishCourse && manifest.CurriculumAuthority != StoryCourseCurriculumAuthority.ApprovedCurriculum)
            throw new InvalidDataException("A technical fixture or pedagogical draft cannot claim to be a Complete English course.");
        if (manifest.Levels is null || manifest.Levels.Count == 0)
            throw new InvalidDataException($"{manifest.CourseId} requires at least one level contract.");
        RequireUnique(manifest.Levels.Select(level => level.LevelId), "level");

        var globalModuleIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var globalUnitIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var globalTaskIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var globalCheckpointIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (StoryCourseLevelContract level in manifest.Levels)
        {
            StoryCourseContractId.Require(level.LevelId, "level id");
            StoryCourseContractText.Require(level.Title, $"{level.LevelId} title");
            if (!SupportedFrameworkLevels.Contains(level.FrameworkLevel))
                throw new InvalidDataException($"{level.LevelId} has unsupported framework level '{level.FrameworkLevel}'.");
            if (level.Sequence < 0) throw new InvalidDataException($"{level.LevelId} sequence must be non-negative.");
            if (level.Modules is null || level.Modules.Count == 0)
                throw new InvalidDataException($"{level.LevelId} requires at least one module contract.");

            foreach (StoryCourseModuleContract module in level.Modules)
            {
                StoryCourseContractId.Require(module.ModuleId, $"{level.LevelId} module id");
                if (!globalModuleIds.Add(module.ModuleId)) throw new InvalidDataException($"Duplicate module id '{module.ModuleId}'.");
                if (!module.LevelId.Equals(level.LevelId, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException($"Module {module.ModuleId} is attached to the wrong level.");
                StoryCourseContractText.Require(module.Title, $"{module.ModuleId} title");
                if (module.Objectives is null || module.Objectives.Count == 0)
                    throw new InvalidDataException($"{module.ModuleId} requires at least one objective.");
                RequireUnique(module.Objectives.Select(objective => objective.ObjectiveId), $"{module.ModuleId} objective");
                foreach (StoryCourseObjectiveContract objective in module.Objectives) objective.Validate(module.ModuleId);
                var objectiveIds = new HashSet<string>(module.Objectives.Select(objective => objective.ObjectiveId), StringComparer.OrdinalIgnoreCase);

                if (module.Units is null || module.Units.Count == 0)
                    throw new InvalidDataException($"{module.ModuleId} requires at least one unit contract.");
                foreach (StoryCourseUnitContract unit in module.Units)
                    ValidateUnit(unit, module.ModuleId, objectiveIds, dictionary, globalUnitIds, globalTaskIds, globalCheckpointIds);
            }
        }
    }

    private static void ValidateUnit(
        StoryCourseUnitContract unit,
        string moduleId,
        ISet<string> moduleObjectiveIds,
        DictionaryPackage dictionary,
        ISet<string> globalUnitIds,
        ISet<string> globalTaskIds,
        ISet<string> globalCheckpointIds)
    {
        StoryCourseContractId.Require(unit.UnitId, $"{moduleId} unit id");
        if (!globalUnitIds.Add(unit.UnitId)) throw new InvalidDataException($"Duplicate unit id '{unit.UnitId}'.");
        if (!unit.ModuleId.Equals(moduleId, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException($"Unit {unit.UnitId} is attached to the wrong module.");
        StoryCourseContractText.Require(unit.Title, $"{unit.UnitId} title");
        StoryCourseContractReferences.RequireOwned(unit.ObjectiveIds, moduleObjectiveIds, unit.UnitId, "objective");
        unit.Provenance?.Validate(unit.UnitId);
        if (unit.Provenance is null) throw new InvalidDataException($"{unit.UnitId} provenance is required.");

        _ = StoryCourseIdentityResolver.Resolve(dictionary, unit.Targets, unit.UnitId);

        if (unit.DialogueOrStory is null || unit.DialogueOrStory.Count == 0)
            throw new InvalidDataException($"{unit.UnitId} requires at least one dialogue/story context.");
        RequireUnique(unit.DialogueOrStory.Select(context => context.ContentId), $"{unit.UnitId} dialogue/story");
        foreach (StoryCourseNarrativeContract context in unit.DialogueOrStory) context.Validate(unit.UnitId);

        if (unit.ComprehensionTasks is null || unit.ProductiveTasks is null)
            throw new InvalidDataException($"{unit.UnitId} task collections are required.");
        if (unit.ComprehensionTasks.Count == 0)
            throw new InvalidDataException($"{unit.UnitId} requires comprehension evidence.");
        if (unit.ProductiveTasks.Count == 0)
            throw new InvalidDataException($"{unit.UnitId} requires a learner-generated productive task.");

        foreach (StoryCourseComprehensionTaskContract task in unit.ComprehensionTasks)
        {
            if (!globalTaskIds.Add(task.TaskId)) throw new InvalidDataException($"Duplicate task id '{task.TaskId}'.");
            task.Validate(unit.UnitId, moduleObjectiveIds);
        }
        foreach (StoryCourseProductiveTaskContract task in unit.ProductiveTasks)
        {
            if (!globalTaskIds.Add(task.TaskId)) throw new InvalidDataException($"Duplicate task id '{task.TaskId}'.");
            task.Validate(unit.UnitId, moduleObjectiveIds);
        }

        if (unit.Checkpoint is not null)
        {
            if (!globalCheckpointIds.Add(unit.Checkpoint.CheckpointId))
                throw new InvalidDataException($"Duplicate checkpoint id '{unit.Checkpoint.CheckpointId}'.");
            unit.Checkpoint.Validate(unit.UnitId, moduleObjectiveIds);
        }
    }

    private static void RequireUnique(IEnumerable<string> values, string label)
    {
        string[] ids = values?.ToArray() ?? throw new InvalidDataException($"{label} collection is required.");
        if (ids.Any(string.IsNullOrWhiteSpace) || ids.Distinct(StringComparer.OrdinalIgnoreCase).Count() != ids.Length)
            throw new InvalidDataException($"{label} ids must be nonblank and unique.");
    }
}

internal sealed record StoryCourseObjectiveProgressContract(
    string ObjectiveId,
    int ExposureCount,
    int ComprehensionEvidenceCount,
    int ProductiveEvidenceCount,
    int CheckpointEvidenceCount,
    StoryCourseMasteryDecision MasteryDecision,
    string? DecisionAuthority)
{
    public void Validate()
    {
        StoryCourseContractId.Require(ObjectiveId, "progress objective id");
        if (ExposureCount < 0 || ComprehensionEvidenceCount < 0 || ProductiveEvidenceCount < 0 || CheckpointEvidenceCount < 0)
            throw new InvalidDataException($"{ObjectiveId} progress counters cannot be negative.");
        if (MasteryDecision != StoryCourseMasteryDecision.Unknown && string.IsNullOrWhiteSpace(DecisionAuthority))
            throw new InvalidDataException($"{ObjectiveId} mastery decision requires an explicit external decision authority/policy.");
        if (MasteryDecision == StoryCourseMasteryDecision.Unknown && !string.IsNullOrWhiteSpace(DecisionAuthority))
            throw new InvalidDataException($"{ObjectiveId} unknown mastery state must not carry a decision authority.");
    }
}

/// <summary>
/// Runtime progress stores evidence separately from mastery. Exposure, story
/// completion, or reveal events are never promoted to mastery by this contract.
/// A mastery decision must come from an explicit assessment/adaptive policy.
/// </summary>
internal sealed record StoryCourseProgressContract(
    int SchemaVersion,
    string CourseId,
    string? ActiveLevelId,
    string? ActiveModuleId,
    string? ActiveUnitId,
    IReadOnlyList<string> CompletedContentIds,
    IReadOnlyList<string> CompletedTaskIds,
    IReadOnlyDictionary<string, StoryCourseObjectiveProgressContract> ObjectiveProgress)
{
    public void Validate()
    {
        if (SchemaVersion < 1) throw new InvalidDataException("Story/Course progress schema version must be positive.");
        StoryCourseContractId.Require(CourseId, "progress course id");
        ValidateOptionalId(ActiveLevelId, "active level id");
        ValidateOptionalId(ActiveModuleId, "active module id");
        ValidateOptionalId(ActiveUnitId, "active unit id");
        ValidateIdCollection(CompletedContentIds, "completed content ids");
        ValidateIdCollection(CompletedTaskIds, "completed task ids");
        if (ObjectiveProgress is null) throw new InvalidDataException("Objective progress collection is required.");
        foreach ((string key, StoryCourseObjectiveProgressContract value) in ObjectiveProgress)
        {
            StoryCourseContractId.Require(key, "objective progress key");
            if (value is null || !key.Equals(value.ObjectiveId, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Objective progress key does not match its stable objective id.");
            value.Validate();
        }
    }

    private static void ValidateOptionalId(string? value, string label)
    {
        if (value is not null) StoryCourseContractId.Require(value, label);
    }

    private static void ValidateIdCollection(IReadOnlyList<string>? values, string label)
    {
        if (values is null || values.Any(string.IsNullOrWhiteSpace) || values.Distinct(StringComparer.OrdinalIgnoreCase).Count() != values.Count)
            throw new InvalidDataException($"{label} must be a unique stable-id collection.");
    }
}

internal static class StoryCourseContractReferences
{
    public static void RequireOwned(IReadOnlyList<string>? references, ISet<string> ownedIds, string ownerId, string label)
    {
        if (references is null || references.Count == 0 || references.Any(string.IsNullOrWhiteSpace))
            throw new InvalidDataException($"{ownerId} requires at least one valid {label} reference.");
        if (references.Distinct(StringComparer.OrdinalIgnoreCase).Count() != references.Count)
            throw new InvalidDataException($"{ownerId} contains duplicate {label} references.");
        foreach (string reference in references)
            if (!ownedIds.Contains(reference)) throw new InvalidDataException($"{ownerId} references unknown {label} '{reference}'.");
    }
}

internal static class StoryCourseContractId
{
    private static readonly Regex Pattern = new("^[a-z0-9][a-z0-9._-]*$", RegexOptions.Compiled | RegexOptions.CultureInvariant);

    public static void Require(string? value, string label)
    {
        if (string.IsNullOrWhiteSpace(value) || !Pattern.IsMatch(value))
            throw new InvalidDataException($"{label} must be a stable lower-case identifier.");
    }
}

internal static class StoryCourseContractText
{
    public static void Require(string? value, string label)
    {
        if (string.IsNullOrWhiteSpace(value)) throw new InvalidDataException($"{label} is required.");
    }
}
