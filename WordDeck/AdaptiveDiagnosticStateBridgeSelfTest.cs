namespace WordDeck;

internal static class AdaptiveDiagnosticStateBridgeSelfTest
{
    public static void Run()
    {
        IncorrectFormalOutcomeRoutesDeepPracticeAndPersists();
        CleanFormalOutcomePersistsEvidenceWithoutRoute();
        UnscoredFormalOutcomeCannotCreateWeakness();
        IncompleteOrPracticeSessionCannotRoute();
        ForeignRouteOwnerFailsClosedBeforeMutation();
        ConflictingMirroredAttemptFailsClosed();
    }

    private static void IncorrectFormalOutcomeRoutesDeepPracticeAndPersists()
    {
        WithStore((store, root) =>
        {
            AssessmentRuntimeState assessment = CompleteState(
                AssessmentMode.Assessment,
                AssessmentMark.Incorrect,
                AssessmentMark.Skipped);
            LearnerCourseState learner = LearnerCourseStateStore.NewEmpty();
            AdaptiveDiagnosticBinding binding = Binding();
            DateTimeOffset now = new(2026, 9, 13, 13, 0, 0, TimeSpan.Zero);

            var bridge = new AdaptiveDiagnosticStateBridge();
            AdaptiveDiagnosticStateResult result = bridge.Apply(assessment, learner, store, binding, now);

            Require(result.HasDirectNeed, "one incorrect formal outcome must remain a direct adaptive need.");
            Require(result.EvidenceStatus == AdaptiveEvidenceStatus.Scored,
                "scored formal evidence plus a skip must remain scored, not become exposure-only.");
            Require(result.RecommendedMode == AdaptivePracticeMode.Grammar,
                "the existing adaptive router must map the Grammar channel to Grammar practice.");
            Require(result.DeepPracticePersisted, "direct diagnostic need was not persisted as DeepPractice.");
            Require(learner.EvidenceHistory.Count == 2, "all consumed formal attempts must be mirrored as attributable course evidence.");
            Require(learner.MasteryByObjectiveId.Count == 0 && learner.SkillLevelsBySkillId.Count == 0,
                "diagnostic routing must not create mastery or CEFR/skill-level estimates.");

            AdaptiveRouteDecision route = learner.AdaptiveRouteByPathId[binding.PathId];
            Require(route.Route == AdaptivePracticeRoute.DeepPractice, "formal weakness must not synthesize FastTrack or Standard routing.");
            Require(route.EvidenceEventIds.SequenceEqual(new[] { "formal-assessment:attempt-1" }, StringComparer.OrdinalIgnoreCase),
                "only scored formal outcomes may justify the persisted DeepPractice decision.");

            LearnerCourseState reopened = store.Load();
            Require(reopened.EvidenceHistory.Count == 2 && reopened.AdaptiveRouteByPathId.ContainsKey(binding.PathId),
                "diagnostic evidence/route did not survive close/reopen persistence.");
            DateTimeOffset assigned = reopened.AdaptiveRouteByPathId[binding.PathId].AssignedAtUtc;

            AdaptiveDiagnosticStateResult replay = bridge.Apply(
                assessment,
                reopened,
                store,
                binding,
                now.AddHours(1));
            Require(replay.DeepPracticePersisted && reopened.EvidenceHistory.Count == 2,
                "replaying the same formal session must be idempotent rather than duplicating evidence.");
            Require(reopened.AdaptiveRouteByPathId[binding.PathId].AssignedAtUtc == assigned,
                "an idempotent replay must not rewrite an unchanged route assignment timestamp.");
        });
    }

    private static void CleanFormalOutcomePersistsEvidenceWithoutRoute()
    {
        WithStore((store, root) =>
        {
            AssessmentRuntimeState assessment = CompleteState(
                AssessmentMode.Assessment,
                AssessmentMark.Correct,
                AssessmentMark.Correct);
            LearnerCourseState learner = LearnerCourseStateStore.NewEmpty();
            AdaptiveDiagnosticStateResult result = new AdaptiveDiagnosticStateBridge().Apply(
                assessment,
                learner,
                store,
                Binding(),
                new DateTimeOffset(2026, 9, 13, 13, 10, 0, TimeSpan.Zero));

            Require(!result.HasDirectNeed && !result.DeepPracticePersisted,
                "clean formal outcomes must not invent a remediation route.");
            Require(learner.EvidenceHistory.Count == 2,
                "clean formal outcomes still need durable attributable evidence.");
            Require(learner.AdaptiveRouteByPathId.Count == 0,
                "absence of direct need must not be converted into Standard or FastTrack state.");
            Require(learner.MasteryByObjectiveId.Count == 0 && learner.SkillLevelsBySkillId.Count == 0,
                "clean assessment performance is not an automatic mastery/level promotion.");
        });
    }

    private static void UnscoredFormalOutcomeCannotCreateWeakness()
    {
        WithStore((store, root) =>
        {
            AssessmentRuntimeState assessment = CompleteState(
                AssessmentMode.Assessment,
                AssessmentMark.Skipped,
                AssessmentMark.Unscored);
            LearnerCourseState learner = LearnerCourseStateStore.NewEmpty();
            AdaptiveDiagnosticStateResult result = new AdaptiveDiagnosticStateBridge().Apply(
                assessment,
                learner,
                store,
                Binding(),
                new DateTimeOffset(2026, 9, 13, 13, 20, 0, TimeSpan.Zero));

            Require(result.EvidenceStatus == AdaptiveEvidenceStatus.ExposureOnly,
                "skipped/unscored formal attempts must remain exposure-only in the adaptive router.");
            Require(!result.HasDirectNeed && learner.AdaptiveRouteByPathId.Count == 0,
                "unscored evidence must not be misread as failure or a direct remediation need.");
            Require(learner.EvidenceHistory.All(item => item.Correct is null),
                "unscored/skipped assessment facts must persist without invented correctness.");
        });
    }

    private static void IncompleteOrPracticeSessionCannotRoute()
    {
        WithStore((store, root) =>
        {
            LearnerCourseState learner = LearnerCourseStateStore.NewEmpty();
            bool practiceRejected = false;
            try
            {
                _ = new AdaptiveDiagnosticStateBridge().Apply(
                    CompleteState(AssessmentMode.Practice, AssessmentMark.Incorrect),
                    learner,
                    store,
                    Binding(),
                    DateTimeOffset.UtcNow);
            }
            catch (InvalidDataException)
            {
                practiceRejected = true;
            }
            Require(practiceRejected && learner.EvidenceHistory.Count == 0,
                "practice-mode attempts must never leak into the formal diagnostic route.");

            bool incompleteRejected = false;
            try
            {
                _ = new AdaptiveDiagnosticStateBridge().Apply(
                    IncompleteFormalState(),
                    learner,
                    store,
                    Binding(),
                    DateTimeOffset.UtcNow);
            }
            catch (InvalidDataException)
            {
                incompleteRejected = true;
            }
            Require(incompleteRejected && learner.EvidenceHistory.Count == 0,
                "partial formal sessions must not create diagnostic routing state.");
        });
    }

    private static void ForeignRouteOwnerFailsClosedBeforeMutation()
    {
        WithStore((store, root) =>
        {
            AdaptiveDiagnosticBinding binding = Binding();
            LearnerCourseState learner = LearnerCourseStateStore.NewEmpty();
            learner.EvidenceHistory.Add(new LearnerEvidenceEvent
            {
                EventId = "existing-evidence",
                ActivityKind = LearnerActivityKind.Practice,
                PathId = binding.PathId,
                CourseId = binding.CourseId,
                Completed = true,
                Correct = false,
                AttemptNumber = 1,
                OccurredAtUtc = new DateTimeOffset(2026, 9, 13, 12, 0, 0, TimeSpan.Zero)
            });
            learner.AdaptiveRouteByPathId[binding.PathId] = new AdaptiveRouteDecision
            {
                PathId = binding.PathId,
                Route = AdaptivePracticeRoute.FastTrack,
                RuleVersion = "other-rule-v1",
                ReasonCode = "other-owner",
                EvidenceEventIds = new List<string> { "existing-evidence" },
                AssignedAtUtc = new DateTimeOffset(2026, 9, 13, 12, 0, 0, TimeSpan.Zero)
            };
            LearnerCourseStateStore.Validate(learner);

            bool rejected = false;
            try
            {
                _ = new AdaptiveDiagnosticStateBridge().Apply(
                    CompleteState(AssessmentMode.Assessment, AssessmentMark.Incorrect),
                    learner,
                    store,
                    binding,
                    new DateTimeOffset(2026, 9, 13, 13, 30, 0, TimeSpan.Zero));
            }
            catch (InvalidDataException)
            {
                rejected = true;
            }

            Require(rejected, "a foreign adaptive rule owner must block route replacement.");
            Require(learner.EvidenceHistory.Count == 1 &&
                    learner.AdaptiveRouteByPathId[binding.PathId].RuleVersion == "other-rule-v1",
                "foreign-route collision must fail before diagnostic state mutation.");
        });
    }

    private static void ConflictingMirroredAttemptFailsClosed()
    {
        WithStore((store, root) =>
        {
            AdaptiveDiagnosticBinding binding = Binding();
            AssessmentRuntimeState assessment = CompleteState(AssessmentMode.Assessment, AssessmentMark.Incorrect);
            AssessmentAttempt attempt = assessment.Attempts[0];
            LearnerCourseState learner = LearnerCourseStateStore.NewEmpty();
            learner.EvidenceHistory.Add(new LearnerEvidenceEvent
            {
                EventId = "formal-assessment:attempt-1",
                ActivityKind = LearnerActivityKind.Assessment,
                PathId = binding.PathId,
                CourseId = binding.CourseId,
                SkillId = "different-skill",
                ItemId = $"{attempt.ItemKey.PoolId}/v{attempt.ItemKey.PoolVersion}/{attempt.ItemKey.ItemId}/v{attempt.ItemKey.ItemVersion}",
                AssessmentId = attempt.SessionId,
                Completed = true,
                Correct = false,
                AttemptNumber = 1,
                OccurredAtUtc = attempt.RecordedAtUtc
            });
            LearnerCourseStateStore.Validate(learner);

            bool rejected = false;
            try
            {
                _ = new AdaptiveDiagnosticStateBridge().Apply(
                    assessment,
                    learner,
                    store,
                    binding,
                    new DateTimeOffset(2026, 9, 13, 13, 40, 0, TimeSpan.Zero));
            }
            catch (InvalidDataException)
            {
                rejected = true;
            }

            Require(rejected && learner.EvidenceHistory.Count == 1 && learner.AdaptiveRouteByPathId.Count == 0,
                "conflicting mirrored attempt identity must fail closed without route/state mutation.");
        });
    }

    private static AssessmentRuntimeState CompleteState(AssessmentMode mode, params AssessmentMark[] marks)
    {
        DateTimeOffset start = new(2026, 9, 13, 12, 0, 0, TimeSpan.Zero);
        var keys = marks.Select((_, index) =>
            new AssessmentItemKey("formal-diagnostic-pool", 1, $"item-{index + 1}", 1)).ToList();
        var state = new AssessmentRuntimeState();
        state.Sessions.Add(new AssessmentSessionState
        {
            SessionId = "diag-session-1",
            PoolId = "formal-diagnostic-pool",
            PoolVersion = 1,
            Mode = mode,
            AdaptiveDifficulty = false,
            RetakeRecentWindow = 0,
            PlannedItemCount = keys.Count,
            ItemOrder = keys,
            Cursor = keys.Count,
            StartedAtUtc = start,
            CompletedAtUtc = start.AddMinutes(keys.Count)
        });
        for (int i = 0; i < marks.Length; i++)
        {
            state.Attempts.Add(new AssessmentAttempt
            {
                AttemptId = $"attempt-{i + 1}",
                SessionId = "diag-session-1",
                Mode = mode,
                ItemKey = keys[i],
                SkillId = "grammar.tense.control",
                DifficultyTier = 2,
                Mark = marks[i],
                UsedHint = false,
                RevealedAnswer = false,
                RecordedAtUtc = start.AddMinutes(i + 1)
            });
        }
        state.Validate();
        return state;
    }

    private static AssessmentRuntimeState IncompleteFormalState()
    {
        DateTimeOffset start = new(2026, 9, 13, 12, 0, 0, TimeSpan.Zero);
        var key1 = new AssessmentItemKey("formal-diagnostic-pool", 1, "item-1", 1);
        var key2 = new AssessmentItemKey("formal-diagnostic-pool", 1, "item-2", 1);
        var state = new AssessmentRuntimeState();
        state.Sessions.Add(new AssessmentSessionState
        {
            SessionId = "diag-session-1",
            PoolId = "formal-diagnostic-pool",
            PoolVersion = 1,
            Mode = AssessmentMode.Assessment,
            AdaptiveDifficulty = false,
            RetakeRecentWindow = 0,
            PlannedItemCount = 2,
            ItemOrder = new List<AssessmentItemKey> { key1, key2 },
            Cursor = 1,
            StartedAtUtc = start,
            CompletedAtUtc = null
        });
        state.Attempts.Add(new AssessmentAttempt
        {
            AttemptId = "attempt-1",
            SessionId = "diag-session-1",
            Mode = AssessmentMode.Assessment,
            ItemKey = key1,
            SkillId = "grammar.tense.control",
            DifficultyTier = 2,
            Mark = AssessmentMark.Incorrect,
            UsedHint = false,
            RevealedAnswer = false,
            RecordedAtUtc = start.AddMinutes(1)
        });
        state.Validate();
        return state;
    }

    private static AdaptiveDiagnosticBinding Binding() => new(
        "complete-english:a1:adaptive",
        "complete-english:a1",
        "diag-session-1",
        "grammar.tense.control",
        "formal-diagnostic",
        "grammar.tense.control",
        AdaptiveTargetKind.GrammarSkill,
        AdaptiveEvidenceChannel.Grammar,
        "diagnostic-adaptive-v1");

    private static void WithStore(Action<LearnerCourseStateStore, string> action)
    {
        string root = Path.Combine(Path.GetTempPath(), "WordDeck-AdaptiveDiagnostic-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            action(new LearnerCourseStateStore(root), root);
        }
        finally
        {
            if (Directory.Exists(root)) Directory.Delete(root, true);
        }
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException("Adaptive diagnostic state bridge self-test failed: " + message);
    }
}