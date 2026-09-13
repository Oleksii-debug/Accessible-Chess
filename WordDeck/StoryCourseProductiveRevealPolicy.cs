namespace WordDeck;

/// <summary>
/// Content-neutral staged reveal for productive Story/Course practice.
/// An evaluation-policy id may append `.after.<task-id>` to require a real
/// required-channel submission of that earlier productive task before this task
/// becomes learner-visible. The gate is backed by durable learner evidence, not
/// by UI-only state, and never implies correctness or mastery.
/// </summary>
internal static class StoryCourseProductiveRevealPolicy
{
    internal const string AfterToken = ".after.";

    internal static string? RequiredPriorTaskId(StoryCourseProductiveTaskContract task)
    {
        ArgumentNullException.ThrowIfNull(task);
        string policyId = task.EvaluationPolicyId ?? string.Empty;
        int first = policyId.IndexOf(AfterToken, StringComparison.Ordinal);
        if (first < 0) return null;
        int last = policyId.LastIndexOf(AfterToken, StringComparison.Ordinal);
        if (first != last)
            throw new InvalidDataException($"Productive task '{task.TaskId}' has more than one staged-reveal prerequisite token.");

        string priorTaskId = policyId[(first + AfterToken.Length)..];
        StoryCourseContractId.Require(priorTaskId, $"{task.TaskId} staged-reveal prerequisite task id");
        return priorTaskId;
    }

    internal static void ValidateUnit(StoryCourseUnitContract unit)
    {
        ArgumentNullException.ThrowIfNull(unit);
        if (unit.ProductiveTasks is null)
            throw new InvalidDataException($"{unit.UnitId} productive task collection is required for staged-reveal validation.");

        var byId = unit.ProductiveTasks.ToDictionary(task => task.TaskId, StringComparer.OrdinalIgnoreCase);
        foreach (StoryCourseProductiveTaskContract task in unit.ProductiveTasks)
        {
            string? prior = RequiredPriorTaskId(task);
            if (prior is null) continue;
            if (prior.Equals(task.TaskId, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException($"Productive task '{task.TaskId}' cannot reveal itself.");
            if (!byId.ContainsKey(prior))
                throw new InvalidDataException($"Productive task '{task.TaskId}' requires unknown prior task '{prior}'.");
        }

        foreach (StoryCourseProductiveTaskContract task in unit.ProductiveTasks)
        {
            var visited = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { task.TaskId };
            StoryCourseProductiveTaskContract cursor = task;
            while (RequiredPriorTaskId(cursor) is string prior)
            {
                if (!visited.Add(prior))
                    throw new InvalidDataException($"Productive staged-reveal cycle detected at '{task.TaskId}'.");
                cursor = byId[prior];
            }
        }
    }

    internal static IReadOnlyList<StoryCourseProductiveTaskContract> VisibleTasks(
        StoryCourseManifestContract manifest,
        StoryCourseUnitContract unit,
        LearnerCourseState state)
    {
        ArgumentNullException.ThrowIfNull(manifest);
        ArgumentNullException.ThrowIfNull(unit);
        ArgumentNullException.ThrowIfNull(state);
        ValidateUnit(unit);

        string pathId = StoryCourseLearnerStateBridge.BuildPathId(manifest);
        var completedRequiredChannelSubmissions = new HashSet<string>(
            state.EvidenceHistory
                .Where(item =>
                    item.ActivityKind == LearnerActivityKind.Practice &&
                    item.PathId.Equals(pathId, StringComparison.OrdinalIgnoreCase) &&
                    item.CourseId.Equals(manifest.CourseId, StringComparison.OrdinalIgnoreCase) &&
                    item.UnitId.Equals(unit.UnitId, StringComparison.OrdinalIgnoreCase) &&
                    item.IsProductivePerformance &&
                    !string.IsNullOrWhiteSpace(item.ItemId))
                .Select(item => item.ItemId!),
            StringComparer.OrdinalIgnoreCase);

        return unit.ProductiveTasks
            .Where(task => RequiredPriorTaskId(task) is not string prior || completedRequiredChannelSubmissions.Contains(prior))
            .ToArray();
    }
}
