namespace WordDeck;

internal enum StoryCourseProductiveSubmissionKind
{
    RequiredChannelPerformance,
    TypedFallback
}

/// <summary>
/// Binds learner-facing Story/Course activity to the versioned course-learning
/// sidecar without inventing a second progress model. This layer records facts
/// only: position, exposure and practice. It never derives mastery, adaptive
/// routing or level estimates from ordinary course activity.
/// </summary>
internal sealed class StoryCourseLearnerStateBridge
{
    private readonly LearnerCourseStateStore _store;
    private readonly Func<string> _eventIdFactory;
    private readonly Func<DateTimeOffset> _clock;

    public StoryCourseLearnerStateBridge(LearnerCourseStateStore store)
        : this(store, CreateEventId, () => DateTimeOffset.UtcNow)
    {
    }

    internal StoryCourseLearnerStateBridge(
        LearnerCourseStateStore store,
        Func<string> eventIdFactory,
        Func<DateTimeOffset> clock)
    {
        _store = store ?? throw new ArgumentNullException(nameof(store));
        _eventIdFactory = eventIdFactory ?? throw new ArgumentNullException(nameof(eventIdFactory));
        _clock = clock ?? throw new ArgumentNullException(nameof(clock));
    }

    public LearnerCourseState RecordUnitSelection(
        StoryCourseManifestContract manifest,
        string moduleId,
        string unitId,
        string? activityId = null)
    {
        OwnedUnit owned = ResolveOwnedUnit(manifest, moduleId, unitId);
        if (!string.IsNullOrWhiteSpace(activityId) && !OwnsActivity(owned.Unit, activityId))
            throw new InvalidDataException($"Story/Course activity '{activityId}' is not owned by unit '{unitId}'.");

        LearnerCourseState state = _store.Load();
        string pathId = BuildPathId(manifest);
        state.CoursePositionsByPathId[pathId] = new CoursePositionBookmark
        {
            PathId = pathId,
            CourseId = manifest.CourseId,
            ModuleId = owned.Module.ModuleId,
            UnitId = owned.Unit.UnitId,
            ActivityId = string.IsNullOrWhiteSpace(activityId) ? null : activityId.Trim(),
            UpdatedAtUtc = _clock()
        };
        _store.Save(state);
        return state;
    }

    public LearnerCourseState RecordNarrativeExposure(
        StoryCourseManifestContract manifest,
        string moduleId,
        string unitId,
        string contentId)
    {
        OwnedUnit owned = ResolveOwnedUnit(manifest, moduleId, unitId);
        StoryCourseNarrativeContract narrative = owned.Unit.DialogueOrStory
            .SingleOrDefault(item => item.ContentId.Equals(contentId, StringComparison.OrdinalIgnoreCase))
            ?? throw new InvalidDataException($"Story/Course narrative '{contentId}' is not owned by unit '{unitId}'.");

        LearnerCourseState state = _store.Load();
        string pathId = BuildPathId(manifest);
        DateTimeOffset now = _clock();
        SetPosition(state, pathId, manifest.CourseId, owned.Module.ModuleId, owned.Unit.UnitId, narrative.ContentId, now);
        AddEvidence(state, new LearnerEvidenceEvent
        {
            EventId = NextEventId(),
            ActivityKind = LearnerActivityKind.Exposure,
            PathId = pathId,
            CourseId = manifest.CourseId,
            ModuleId = owned.Module.ModuleId,
            UnitId = owned.Unit.UnitId,
            ItemId = narrative.ContentId,
            LexicalEntryIds = CopyLexicalIds(owned.Unit),
            Completed = true,
            Correct = null,
            IsUnseenMaterial = false,
            IsProductivePerformance = false,
            IsTransferPerformance = false,
            AttemptNumber = 1,
            OccurredAtUtc = now
        });
        _store.Save(state);
        return state;
    }

    public LearnerCourseState RecordComprehensionPracticeAttempt(
        StoryCourseManifestContract manifest,
        string moduleId,
        string unitId,
        string taskId,
        bool correct,
        int attemptNumber,
        bool isTransfer = false)
    {
        RequireAttemptNumber(attemptNumber);
        OwnedUnit owned = ResolveOwnedUnit(manifest, moduleId, unitId);
        StoryCourseComprehensionTaskContract task = owned.Unit.ComprehensionTasks
            .SingleOrDefault(item => item.TaskId.Equals(taskId, StringComparison.OrdinalIgnoreCase))
            ?? throw new InvalidDataException($"Story/Course comprehension task '{taskId}' is not owned by unit '{unitId}'.");

        LearnerCourseState state = _store.Load();
        string pathId = BuildPathId(manifest);
        DateTimeOffset now = _clock();
        SetPosition(state, pathId, manifest.CourseId, owned.Module.ModuleId, owned.Unit.UnitId, task.TaskId, now);
        foreach (string objectiveId in RequireOwnedObjectives(owned, task.ObjectiveIds, task.TaskId))
        {
            AddEvidence(state, new LearnerEvidenceEvent
            {
                EventId = NextEventId(),
                ActivityKind = LearnerActivityKind.Practice,
                PathId = pathId,
                CourseId = manifest.CourseId,
                ModuleId = owned.Module.ModuleId,
                UnitId = owned.Unit.UnitId,
                ObjectiveId = objectiveId,
                SkillId = "comprehension",
                ItemId = task.TaskId,
                LexicalEntryIds = CopyLexicalIds(owned.Unit),
                Completed = true,
                Correct = correct,
                IsUnseenMaterial = false,
                IsProductivePerformance = false,
                IsTransferPerformance = isTransfer,
                AttemptNumber = attemptNumber,
                OccurredAtUtc = now
            });
        }
        _store.Save(state);
        return state;
    }

    public LearnerCourseState RecordProductivePracticeAttempt(
        StoryCourseManifestContract manifest,
        string moduleId,
        string unitId,
        string taskId,
        StoryCourseProductiveSubmissionKind submissionKind,
        int attemptNumber,
        bool isTransfer = false)
    {
        RequireAttemptNumber(attemptNumber);
        if (!Enum.IsDefined(submissionKind))
            throw new InvalidDataException("Story/Course productive submission kind is invalid.");

        OwnedUnit owned = ResolveOwnedUnit(manifest, moduleId, unitId);
        StoryCourseProductiveTaskContract task = owned.Unit.ProductiveTasks
            .SingleOrDefault(item => item.TaskId.Equals(taskId, StringComparison.OrdinalIgnoreCase))
            ?? throw new InvalidDataException($"Story/Course productive task '{taskId}' is not owned by unit '{unitId}'.");

        if (submissionKind == StoryCourseProductiveSubmissionKind.TypedFallback &&
            task.Channel == StoryCourseProductiveChannel.Writing)
        {
            throw new InvalidDataException(
                $"Writing task '{task.TaskId}' cannot label its required typed production as a fallback channel.");
        }

        LearnerCourseState state = _store.Load();
        string pathId = BuildPathId(manifest);
        DateTimeOffset now = _clock();
        SetPosition(state, pathId, manifest.CourseId, owned.Module.ModuleId, owned.Unit.UnitId, task.TaskId, now);
        bool requiredChannelPerformed = submissionKind == StoryCourseProductiveSubmissionKind.RequiredChannelPerformance;
        string skillId = task.Channel switch
        {
            StoryCourseProductiveChannel.Speaking => "speaking-pronunciation",
            StoryCourseProductiveChannel.Writing => "writing",
            StoryCourseProductiveChannel.Mixed => "integrated-production",
            _ => throw new InvalidDataException($"Productive task '{task.TaskId}' has invalid channel '{task.Channel}'.")
        };

        foreach (string objectiveId in RequireOwnedObjectives(owned, task.ObjectiveIds, task.TaskId))
        {
            AddEvidence(state, new LearnerEvidenceEvent
            {
                EventId = NextEventId(),
                ActivityKind = LearnerActivityKind.Practice,
                PathId = pathId,
                CourseId = manifest.CourseId,
                ModuleId = owned.Module.ModuleId,
                UnitId = owned.Unit.UnitId,
                ObjectiveId = objectiveId,
                SkillId = skillId,
                ItemId = task.TaskId,
                LexicalEntryIds = CopyLexicalIds(owned.Unit),
                Completed = true,
                // This bridge has no evaluator. A practice submission can be
                // recorded without fabricating correctness or mastery.
                Correct = null,
                IsUnseenMaterial = false,
                IsProductivePerformance = requiredChannelPerformed,
                IsTransferPerformance = isTransfer,
                AttemptNumber = attemptNumber,
                OccurredAtUtc = now
            });
        }
        _store.Save(state);
        return state;
    }

    internal static string BuildPathId(StoryCourseManifestContract manifest)
    {
        ArgumentNullException.ThrowIfNull(manifest);
        StoryCourseContractId.Require(manifest.CourseId, "learner course id");
        return "story-course:" + manifest.CourseId;
    }

    private static OwnedUnit ResolveOwnedUnit(
        StoryCourseManifestContract manifest,
        string moduleId,
        string unitId)
    {
        ArgumentNullException.ThrowIfNull(manifest);
        StoryCourseContractId.Require(manifest.CourseId, "learner course id");
        StoryCourseContractId.Require(moduleId, "learner course module id");
        StoryCourseContractId.Require(unitId, "learner course unit id");
        if (manifest.Levels is null)
            throw new InvalidDataException("Story/Course manifest levels are required for learner-state binding.");

        OwnedUnit[] matches = manifest.Levels
            .Where(level => level is not null && level.Modules is not null)
            .SelectMany(level => level.Modules.Select(module => new { level, module }))
            .Where(pair => pair.module is not null && pair.module.ModuleId.Equals(moduleId, StringComparison.OrdinalIgnoreCase))
            .SelectMany(pair => (pair.module.Units ?? Array.Empty<StoryCourseUnitContract>())
                .Where(unit => unit is not null && unit.UnitId.Equals(unitId, StringComparison.OrdinalIgnoreCase))
                .Select(unit => new OwnedUnit(pair.level, pair.module, unit)))
            .ToArray();

        if (matches.Length != 1)
            throw new InvalidDataException(
                $"Story/Course learner-state bridge could not resolve exactly one manifest-owned unit '{moduleId}/{unitId}'.");

        OwnedUnit owned = matches[0];
        StoryCourseContractId.Require(owned.Level.LevelId, "learner course level id");
        StoryCourseContractId.Require(owned.Module.ModuleId, "learner course module id");
        StoryCourseContractId.Require(owned.Unit.UnitId, "learner course unit id");
        if (!owned.Module.LevelId.Equals(owned.Level.LevelId, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException($"Story/Course module '{owned.Module.ModuleId}' is attached to the wrong level.");
        if (!owned.Unit.ModuleId.Equals(owned.Module.ModuleId, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException($"Story/Course unit '{owned.Unit.UnitId}' is attached to the wrong module.");
        return owned;
    }

    private static bool OwnsActivity(StoryCourseUnitContract unit, string activityId) =>
        unit.DialogueOrStory.Any(item => item.ContentId.Equals(activityId, StringComparison.OrdinalIgnoreCase)) ||
        unit.ComprehensionTasks.Any(item => item.TaskId.Equals(activityId, StringComparison.OrdinalIgnoreCase)) ||
        unit.ProductiveTasks.Any(item => item.TaskId.Equals(activityId, StringComparison.OrdinalIgnoreCase)) ||
        (unit.Checkpoint?.CheckpointId.Equals(activityId, StringComparison.OrdinalIgnoreCase) ?? false);

    private static IReadOnlyList<string> RequireOwnedObjectives(
        OwnedUnit owned,
        IReadOnlyList<string> objectiveIds,
        string ownerId)
    {
        if (objectiveIds is null || objectiveIds.Count == 0 || objectiveIds.Any(string.IsNullOrWhiteSpace))
            throw new InvalidDataException($"Story/Course activity '{ownerId}' requires owned objective ids before learner evidence can be recorded.");
        if (objectiveIds.Distinct(StringComparer.OrdinalIgnoreCase).Count() != objectiveIds.Count)
            throw new InvalidDataException($"Story/Course activity '{ownerId}' contains duplicate objective ids.");
        if (owned.Module.Objectives is null)
            throw new InvalidDataException($"Story/Course module '{owned.Module.ModuleId}' has no objective collection.");

        var moduleObjectives = new HashSet<string>(
            owned.Module.Objectives.Where(objective => objective is not null).Select(objective => objective.ObjectiveId),
            StringComparer.OrdinalIgnoreCase);
        foreach (string objectiveId in objectiveIds)
        {
            StoryCourseContractId.Require(objectiveId, $"{ownerId} learner evidence objective id");
            if (!moduleObjectives.Contains(objectiveId))
                throw new InvalidDataException(
                    $"Story/Course activity '{ownerId}' references objective '{objectiveId}' that is not owned by module '{owned.Module.ModuleId}'.");
            if (!owned.Unit.ObjectiveIds.Contains(objectiveId, StringComparer.OrdinalIgnoreCase))
                throw new InvalidDataException(
                    $"Story/Course activity '{ownerId}' references objective '{objectiveId}' that is not assigned to unit '{owned.Unit.UnitId}'.");
        }
        return objectiveIds;
    }

    private static List<string> CopyLexicalIds(StoryCourseUnitContract unit)
    {
        if (unit.Targets?.LexicalEntryIds is null)
            throw new InvalidDataException($"Story/Course unit '{unit.UnitId}' has no lexical target collection.");
        if (unit.Targets.LexicalEntryIds.Any(string.IsNullOrWhiteSpace) ||
            unit.Targets.LexicalEntryIds.Distinct(StringComparer.OrdinalIgnoreCase).Count() != unit.Targets.LexicalEntryIds.Count)
        {
            throw new InvalidDataException($"Story/Course unit '{unit.UnitId}' has invalid lexical stable IDs.");
        }
        return unit.Targets.LexicalEntryIds.ToList();
    }

    private static void SetPosition(
        LearnerCourseState state,
        string pathId,
        string courseId,
        string moduleId,
        string unitId,
        string activityId,
        DateTimeOffset now)
    {
        state.CoursePositionsByPathId[pathId] = new CoursePositionBookmark
        {
            PathId = pathId,
            CourseId = courseId,
            ModuleId = moduleId,
            UnitId = unitId,
            ActivityId = activityId,
            UpdatedAtUtc = now
        };
    }

    private static void AddEvidence(LearnerCourseState state, LearnerEvidenceEvent evidence)
    {
        if (state.EvidenceHistory.Any(existing => existing.EventId.Equals(evidence.EventId, StringComparison.OrdinalIgnoreCase)))
            throw new InvalidDataException($"Duplicate Story/Course learner evidence event id '{evidence.EventId}'.");
        state.EvidenceHistory.Add(evidence);
    }

    private string NextEventId()
    {
        string id = _eventIdFactory()?.Trim() ?? string.Empty;
        if (string.IsNullOrWhiteSpace(id))
            throw new InvalidDataException("Story/Course learner evidence requires a non-blank event id.");
        return id;
    }

    private static void RequireAttemptNumber(int attemptNumber)
    {
        if (attemptNumber < 1)
            throw new InvalidDataException("Story/Course learner practice attempt number must be at least 1.");
    }

    private static string CreateEventId() => "course-event." + Guid.NewGuid().ToString("N");

    private sealed record OwnedUnit(
        StoryCourseLevelContract Level,
        StoryCourseModuleContract Module,
        StoryCourseUnitContract Unit);
}
