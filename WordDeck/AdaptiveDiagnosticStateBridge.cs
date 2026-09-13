namespace WordDeck;

/// <summary>
/// Explicit identity binding from one formal assessment skill to one existing
/// adaptive target/channel and one persisted course path. The bridge never
/// infers this mapping from display text, scores, CEFR labels, or course order.
/// </summary>
internal sealed record AdaptiveDiagnosticBinding(
    string PathId,
    string CourseId,
    string AssessmentSessionId,
    string AssessmentSkillId,
    string DictionaryId,
    string TargetId,
    AdaptiveTargetKind TargetKind,
    AdaptiveEvidenceChannel Channel,
    string RuleVersion);

internal sealed record AdaptiveDiagnosticStateResult(
    string AssessmentSessionId,
    string AssessmentSkillId,
    string TargetId,
    AdaptiveEvidenceStatus EvidenceStatus,
    AdaptivePracticeMode RecommendedMode,
    bool HasDirectNeed,
    int MirroredEvidenceEvents,
    bool DeepPracticePersisted,
    IReadOnlyList<string> RouteEvidenceEventIds);

/// <summary>
/// Narrow adapter between the versioned formal AssessmentRuntime and the existing
/// global AdaptiveMasteryRouter/LearnerCourseStateStore contracts.
///
/// This type owns no scoring model and no second router. Formal attempts are
/// normalized into AdaptiveMasteryObservation, the canonical router determines
/// direct need and the channel's practice mode, and only an evidence-backed
/// DeepPractice decision may be persisted. Clean or unscored evidence never
/// creates FastTrack, mastery, CEFR/skill-level, or protected assessment claims.
/// </summary>
internal sealed class AdaptiveDiagnosticStateBridge
{
    public const string DirectNeedReasonCode = "formal-diagnostic-direct-need";

    private readonly AdaptiveMasteryRouter _router;

    public AdaptiveDiagnosticStateBridge()
        : this(new AdaptiveMasteryRouter())
    {
    }

    internal AdaptiveDiagnosticStateBridge(AdaptiveMasteryRouter router)
    {
        _router = router ?? throw new ArgumentNullException(nameof(router));
    }

    public AdaptiveDiagnosticStateResult Apply(
        AssessmentRuntimeState assessmentState,
        LearnerCourseState learnerState,
        LearnerCourseStateStore store,
        AdaptiveDiagnosticBinding binding,
        DateTimeOffset nowUtc)
    {
        ArgumentNullException.ThrowIfNull(assessmentState);
        ArgumentNullException.ThrowIfNull(learnerState);
        ArgumentNullException.ThrowIfNull(store);
        ArgumentNullException.ThrowIfNull(binding);
        ValidateBinding(binding);

        // Validate the complete runtime graph first so a caller cannot route from
        // orphan attempts, mixed pool versions, duplicate item consumption, or a
        // formal attempt that illegally used a hint/reveal.
        assessmentState.Validate();
        LearnerCourseStateStore.Validate(learnerState);

        AssessmentSessionState session = assessmentState.Sessions.SingleOrDefault(candidate =>
            candidate.SessionId.Equals(binding.AssessmentSessionId, StringComparison.OrdinalIgnoreCase))
            ?? throw new InvalidDataException($"Formal diagnostic session '{binding.AssessmentSessionId}' was not found.");

        if (session.Mode != AssessmentMode.Assessment)
            throw new InvalidDataException($"Diagnostic routing requires AssessmentMode.Assessment; session '{session.SessionId}' is {session.Mode}.");
        if (!session.IsComplete)
            throw new InvalidDataException($"Diagnostic routing requires a completed formal assessment session; '{session.SessionId}' is incomplete.");

        List<AssessmentAttempt> attempts = assessmentState.Attempts
            .Where(attempt =>
                attempt.SessionId.Equals(session.SessionId, StringComparison.OrdinalIgnoreCase) &&
                attempt.SkillId.Equals(binding.AssessmentSkillId, StringComparison.OrdinalIgnoreCase))
            .OrderBy(attempt => attempt.RecordedAtUtc)
            .ThenBy(attempt => attempt.AttemptId, StringComparer.Ordinal)
            .ToList();

        if (attempts.Count == 0)
            throw new InvalidDataException($"Completed formal diagnostic session '{session.SessionId}' contains no attempts for skill '{binding.AssessmentSkillId}'.");

        List<LearnerEvidenceEvent> expectedEvents = attempts
            .Select((attempt, index) => ToLearnerEvidence(binding, attempt, index + 1))
            .ToList();

        // Resolve duplicate/mismatched persisted identities before mutating the
        // caller's state. A repeated bridge call is idempotent only when the
        // already-persisted event is semantically the same assessment fact.
        var existingById = learnerState.EvidenceHistory.ToDictionary(
            evidence => evidence.EventId,
            StringComparer.OrdinalIgnoreCase);
        foreach (LearnerEvidenceEvent expected in expectedEvents)
        {
            if (existingById.TryGetValue(expected.EventId, out LearnerEvidenceEvent? existing) &&
                !EquivalentEvidence(existing, expected))
                throw new InvalidDataException($"Course evidence id '{expected.EventId}' already exists with conflicting diagnostic semantics.");
        }

        IReadOnlyList<AdaptiveMasteryObservation> observations = BuildObservations(binding, session, attempts);
        var candidate = new AdaptivePracticeCandidate(
            binding.DictionaryId,
            binding.TargetId,
            binding.TargetKind,
            new HashSet<AdaptivePracticeMode>(Enum.GetValues<AdaptivePracticeMode>()));
        AdaptiveChannelSnapshot snapshot = _router.Snapshot(candidate, binding.Channel, observations, nowUtc);

        List<string> routeEvidenceIds = attempts
            .Where(attempt => attempt.Mark is AssessmentMark.Correct or AssessmentMark.Incorrect)
            .Select(attempt => EvidenceEventId(attempt.AttemptId))
            .ToList();

        AdaptiveRouteDecision? priorRoute = null;
        bool hadPriorRoute = learnerState.AdaptiveRouteByPathId.TryGetValue(binding.PathId, out priorRoute);
        bool priorRouteOwnedByBridge = hadPriorRoute &&
            priorRoute!.RuleVersion.Equals(binding.RuleVersion, StringComparison.OrdinalIgnoreCase) &&
            priorRoute.Route == AdaptivePracticeRoute.DeepPractice &&
            priorRoute.ReasonCode.Equals(DirectNeedReasonCode, StringComparison.Ordinal);
        if (snapshot.HasDirectNeed && hadPriorRoute)
        {
            if (!priorRoute!.RuleVersion.Equals(binding.RuleVersion, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException($"Adaptive path '{binding.PathId}' is owned by rule '{priorRoute.RuleVersion}', not '{binding.RuleVersion}'.");
            if (!priorRouteOwnedByBridge)
                throw new InvalidDataException($"Adaptive path '{binding.PathId}' contains a conflicting decision under rule '{binding.RuleVersion}'.");
        }

        var addedEvents = new List<LearnerEvidenceEvent>();
        bool routeTouched = false;
        bool changed = false;
        try
        {
            foreach (LearnerEvidenceEvent expected in expectedEvents)
            {
                if (existingById.ContainsKey(expected.EventId))
                    continue;
                learnerState.EvidenceHistory.Add(expected);
                addedEvents.Add(expected);
                existingById.Add(expected.EventId, expected);
                changed = true;
            }

            if (snapshot.HasDirectNeed)
            {
                var replacement = new AdaptiveRouteDecision
                {
                    PathId = binding.PathId,
                    Route = AdaptivePracticeRoute.DeepPractice,
                    RuleVersion = binding.RuleVersion,
                    ReasonCode = DirectNeedReasonCode,
                    EvidenceEventIds = routeEvidenceIds,
                    AssignedAtUtc = nowUtc
                };

                if (!hadPriorRoute || !EquivalentRoute(priorRoute!, replacement))
                {
                    learnerState.AdaptiveRouteByPathId[binding.PathId] = replacement;
                    routeTouched = true;
                    changed = true;
                }
            }
            else if (priorRouteOwnedByBridge)
            {
                // A later clean/unscored formal reassessment supersedes only this
                // bridge's own stale remediation. Foreign routes remain untouched.
                learnerState.AdaptiveRouteByPathId.Remove(binding.PathId);
                routeTouched = true;
                changed = true;
            }

            // This validation proves every route evidence ID resolves to a mirrored
            // assessment event before a disk write is attempted.
            LearnerCourseStateStore.Validate(learnerState);
            if (changed)
                store.Save(learnerState);
        }
        catch
        {
            foreach (LearnerEvidenceEvent added in addedEvents)
                learnerState.EvidenceHistory.Remove(added);
            if (routeTouched)
            {
                if (hadPriorRoute)
                    learnerState.AdaptiveRouteByPathId[binding.PathId] = priorRoute!;
                else
                    learnerState.AdaptiveRouteByPathId.Remove(binding.PathId);
            }
            throw;
        }

        return new AdaptiveDiagnosticStateResult(
            session.SessionId,
            binding.AssessmentSkillId,
            binding.TargetId,
            snapshot.EvidenceStatus,
            snapshot.Mode,
            snapshot.HasDirectNeed,
            expectedEvents.Count,
            snapshot.HasDirectNeed,
            routeEvidenceIds);
    }

    private static IReadOnlyList<AdaptiveMasteryObservation> BuildObservations(
        AdaptiveDiagnosticBinding binding,
        AssessmentSessionState session,
        IReadOnlyList<AssessmentAttempt> attempts)
    {
        var observations = new List<AdaptiveMasteryObservation>(2);
        List<AssessmentAttempt> scored = attempts
            .Where(attempt => attempt.Mark is AssessmentMark.Correct or AssessmentMark.Incorrect)
            .ToList();
        if (scored.Count > 0)
        {
            int successes = scored.Count(attempt => attempt.Mark == AssessmentMark.Correct);
            int wrong = scored.Count(attempt => attempt.Mark == AssessmentMark.Incorrect);
            int trailingCorrect = 0;
            for (int i = scored.Count - 1; i >= 0 && scored[i].Mark == AssessmentMark.Correct; i--)
                trailingCorrect++;

            observations.Add(new AdaptiveMasteryObservation(
                binding.DictionaryId,
                binding.TargetId,
                binding.TargetKind,
                binding.Channel,
                scored.Count,
                successes,
                wrong,
                0,
                trailingCorrect,
                scored[^1].RecordedAtUtc,
                $"assessment:{session.SessionId}:{binding.AssessmentSkillId}:scored"));
        }

        List<AssessmentAttempt> unscored = attempts
            .Where(attempt => attempt.Mark is AssessmentMark.Skipped or AssessmentMark.Unscored)
            .ToList();
        if (unscored.Count > 0)
        {
            observations.Add(new AdaptiveMasteryObservation(
                binding.DictionaryId,
                binding.TargetId,
                binding.TargetKind,
                binding.Channel,
                unscored.Count,
                null,
                0,
                0,
                0,
                unscored[^1].RecordedAtUtc,
                $"assessment:{session.SessionId}:{binding.AssessmentSkillId}:unscored"));
        }

        return observations;
    }

    private static LearnerEvidenceEvent ToLearnerEvidence(
        AdaptiveDiagnosticBinding binding,
        AssessmentAttempt attempt,
        int attemptNumber) =>
        new()
        {
            EventId = EvidenceEventId(attempt.AttemptId),
            ActivityKind = LearnerActivityKind.Assessment,
            PathId = binding.PathId,
            CourseId = binding.CourseId,
            SkillId = binding.AssessmentSkillId,
            ItemId = $"{attempt.ItemKey.PoolId}/v{attempt.ItemKey.PoolVersion}/{attempt.ItemKey.ItemId}/v{attempt.ItemKey.ItemVersion}",
            AssessmentId = attempt.SessionId,
            Completed = true,
            Correct = attempt.Mark switch
            {
                AssessmentMark.Correct => true,
                AssessmentMark.Incorrect => false,
                AssessmentMark.Skipped or AssessmentMark.Unscored => null,
                _ => throw new InvalidDataException($"Unsupported formal assessment mark '{attempt.Mark}'.")
            },
            IsUnseenMaterial = false,
            IsProductivePerformance = false,
            IsTransferPerformance = false,
            HintUses = 0,
            RevealUses = 0,
            AttemptNumber = attemptNumber,
            OccurredAtUtc = attempt.RecordedAtUtc
        };

    private static string EvidenceEventId(string attemptId) => $"formal-assessment:{attemptId}";

    private static bool EquivalentEvidence(LearnerEvidenceEvent left, LearnerEvidenceEvent right) =>
        left.ActivityKind == right.ActivityKind &&
        left.PathId.Equals(right.PathId, StringComparison.OrdinalIgnoreCase) &&
        left.CourseId.Equals(right.CourseId, StringComparison.OrdinalIgnoreCase) &&
        string.Equals(left.ModuleId, right.ModuleId, StringComparison.OrdinalIgnoreCase) &&
        string.Equals(left.UnitId, right.UnitId, StringComparison.OrdinalIgnoreCase) &&
        string.Equals(left.ObjectiveId, right.ObjectiveId, StringComparison.OrdinalIgnoreCase) &&
        string.Equals(left.SkillId, right.SkillId, StringComparison.OrdinalIgnoreCase) &&
        string.Equals(left.ItemId, right.ItemId, StringComparison.OrdinalIgnoreCase) &&
        string.Equals(left.AssessmentId, right.AssessmentId, StringComparison.OrdinalIgnoreCase) &&
        left.LexicalEntryIds.SequenceEqual(right.LexicalEntryIds, StringComparer.OrdinalIgnoreCase) &&
        left.Completed == right.Completed &&
        left.Correct == right.Correct &&
        left.IsUnseenMaterial == right.IsUnseenMaterial &&
        left.IsProductivePerformance == right.IsProductivePerformance &&
        left.IsTransferPerformance == right.IsTransferPerformance &&
        left.HintUses == right.HintUses &&
        left.RevealUses == right.RevealUses &&
        left.AttemptNumber == right.AttemptNumber &&
        left.OccurredAtUtc.Equals(right.OccurredAtUtc);

    private static bool EquivalentRoute(AdaptiveRouteDecision left, AdaptiveRouteDecision right) =>
        left.PathId.Equals(right.PathId, StringComparison.OrdinalIgnoreCase) &&
        left.Route == right.Route &&
        left.RuleVersion.Equals(right.RuleVersion, StringComparison.OrdinalIgnoreCase) &&
        left.ReasonCode.Equals(right.ReasonCode, StringComparison.Ordinal) &&
        left.EvidenceEventIds.SequenceEqual(right.EvidenceEventIds, StringComparer.OrdinalIgnoreCase);

    private static void ValidateBinding(AdaptiveDiagnosticBinding binding)
    {
        RequireStable(binding.PathId, "path id");
        RequireStable(binding.CourseId, "course id");
        RequireStable(binding.AssessmentSessionId, "assessment session id");
        RequireStable(binding.AssessmentSkillId, "assessment skill id");
        RequireStable(binding.DictionaryId, "adaptive dictionary id");
        RequireStable(binding.TargetId, "adaptive target id");
        RequireStable(binding.RuleVersion, "adaptive rule version");
        if (!Enum.IsDefined(typeof(AdaptiveTargetKind), binding.TargetKind))
            throw new InvalidDataException("Diagnostic binding has an undefined adaptive target kind.");
        if (!Enum.IsDefined(typeof(AdaptiveEvidenceChannel), binding.Channel))
            throw new InvalidDataException("Diagnostic binding has an undefined adaptive evidence channel.");
    }

    private static void RequireStable(string? value, string label)
    {
        if (string.IsNullOrWhiteSpace(value) || !string.Equals(value, value.Trim(), StringComparison.Ordinal))
            throw new InvalidDataException($"Diagnostic {label} must be non-blank canonical text.");
    }
}
