namespace WordDeck;

/// <summary>
/// A bounded Deep Listening journey projected from the existing durable Listening
/// history. It deliberately owns no second scheduler or persistence store: the
/// ListeningCoach engine remains the authority for item selection, playback,
/// completion and interruption/resume.
/// </summary>
internal static class DeepListeningJourney
{
    internal const int TargetReviews = 5;

    internal sealed record Progress(
        int CompletedReviews,
        int TargetReviews,
        int CorrectReviews,
        int NeedsReview,
        int WrongAttempts,
        int Replays,
        bool CycleCompleted,
        bool FeedbackAmbiguous)
    {
        public int Remaining => Math.Max(0, TargetReviews - CompletedReviews);
    }

    private sealed class CompletionEvidence
    {
        public int CorrectBudget { get; init; }
        public int IncorrectBudget { get; init; }
        public int CorrectHistory { get; set; }
        public int IncorrectHistory { get; set; }

        public int CreditedReviews =>
            Math.Min(CorrectHistory, CorrectBudget) +
            Math.Min(IncorrectHistory, IncorrectBudget);

        public bool CorrectFeedbackAmbiguous =>
            CorrectBudget > 0 && CorrectHistory > CorrectBudget;

        public bool IncorrectFeedbackAmbiguous =>
            IncorrectBudget > 0 && IncorrectHistory > IncorrectBudget;
    }

    internal static Progress ActiveProgress(
        ListeningCoachState state,
        string dictionaryId,
        IReadOnlyList<ListeningExercise> available) =>
        Build(state, dictionaryId, available, completionView: false);

    internal static Progress CompletionProgress(
        ListeningCoachState state,
        string dictionaryId,
        IReadOnlyList<ListeningExercise> available) =>
        Build(state, dictionaryId, available, completionView: true);

    internal static string DescribeActive(
        ListeningCoachState state,
        string dictionaryId,
        IReadOnlyList<ListeningExercise> available)
    {
        Progress progress = ActiveProgress(state, dictionaryId, available);
        if (progress.CompletedReviews == 0)
            return $"Deep Listening journey: 0 of {TargetReviews} reviews complete. Progress is restored from durable Listening history.";

        if (progress.FeedbackAmbiguous)
            return $"Deep Listening journey: {progress.CompletedReviews} of {TargetReviews} reviews complete; " +
                   $"detailed feedback is unavailable because stored Listening history is ambiguous; {progress.Remaining} remaining.";

        return $"Deep Listening journey: {progress.CompletedReviews} of {TargetReviews} reviews complete; " +
               $"{progress.CorrectReviews} correct, {progress.NeedsReview} need more practice; {progress.Remaining} remaining.";
    }

    internal static string DescribeAfterCompletion(
        ListeningCoachState state,
        string dictionaryId,
        IReadOnlyList<ListeningExercise> available)
    {
        Progress progress = CompletionProgress(state, dictionaryId, available);
        if (progress.CompletedReviews == 0)
            return DescribeActive(state, dictionaryId, available);

        if (progress.FeedbackAmbiguous)
        {
            if (progress.CycleCompleted)
                return $"Deep Listening journey complete: {TargetReviews} reviews recorded; detailed feedback is unavailable because stored Listening history is ambiguous. " +
                       $"Next begins another {TargetReviews}-review journey.";

            return $"Deep Listening journey: {progress.CompletedReviews} of {TargetReviews} complete; " +
                   $"detailed feedback is unavailable because stored Listening history is ambiguous; {progress.Remaining} remaining.";
        }

        if (progress.CycleCompleted)
            return $"Deep Listening journey complete: {progress.CorrectReviews} of {TargetReviews} correct; " +
                   $"{progress.NeedsReview} need more practice; {progress.WrongAttempts} wrong attempts; " +
                   $"{progress.Replays} replays. Next begins another {TargetReviews}-review journey.";

        return $"Deep Listening journey: {progress.CompletedReviews} of {TargetReviews} complete; " +
               $"{progress.CorrectReviews} correct, {progress.NeedsReview} need more practice; " +
               $"{progress.Remaining} remaining.";
    }

    private static Progress Build(
        ListeningCoachState state,
        string dictionaryId,
        IReadOnlyList<ListeningExercise> available,
        bool completionView)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(available);

        // `available` is the current selection/playback truth. It may change when a
        // learner hides a word, changes scope, or when an audio asset is temporarily
        // unavailable. Projecting durable journey chronology through that reversible
        // view would make prior credit disappear and can move a five-review boundary.
        //
        // A completed Listening review is durably evidenced twice in the existing
        // single ListeningCoachState: History contains chronological row evidence and
        // StatsByDictionary contains the aggregate completion/outcome budget for the
        // same exercise. Aggregate outcome counts can prove how many rows may receive
        // journey credit, but they cannot identify which one is genuine if history is
        // over-represented by a stale duplicate with the same outcome. In that case we
        // preserve the durable journey count/boundary while failing closed only while
        // that ambiguity can still reach the current five-review feedback window.
        var evidenceByExercise = new Dictionary<string, CompletionEvidence>(StringComparer.OrdinalIgnoreCase);
        if (state.StatsByDictionary.TryGetValue(dictionaryId, out Dictionary<string, ListeningItemStats>? perDictionary))
        {
            foreach ((string exerciseId, ListeningItemStats stats) in perDictionary)
            {
                int completed = Math.Max(0, stats.CompletedReviews);
                if (completed == 0) continue;

                int correct = Math.Clamp(stats.CorrectReviews, 0, completed);
                evidenceByExercise[exerciseId] = new CompletionEvidence
                {
                    CorrectBudget = correct,
                    IncorrectBudget = completed - correct
                };
            }
        }

        foreach (ListeningHistoryRecord record in state.History)
        {
            if (!string.Equals(record.DictionaryId, dictionaryId, StringComparison.OrdinalIgnoreCase) ||
                record.Kind != ListeningExerciseKind.Word ||
                !evidenceByExercise.TryGetValue(record.ExerciseId, out CompletionEvidence? evidence))
            {
                continue;
            }

            if (record.Correct)
                evidence.CorrectHistory++;
            else
                evidence.IncorrectHistory++;
        }

        int creditedReviews = evidenceByExercise.Values.Sum(evidence => evidence.CreditedReviews);
        int inCycle = creditedReviews % TargetReviews;
        if (completionView && creditedReviews > 0 && inCycle == 0)
            inCycle = TargetReviews;

        // Keep only unambiguously corroborated rows after the last ambiguous candidate.
        // If that suffix is large enough to cover the current feedback window, older
        // ambiguity is safely behind the active cycle and normal detailed feedback can
        // resume. Zero-budget rows are provably stale and never create ambiguity.
        var safeSuffix = new List<ListeningHistoryRecord>();
        bool sawAmbiguousCandidate = false;
        foreach (ListeningHistoryRecord record in state.History)
        {
            if (!string.Equals(record.DictionaryId, dictionaryId, StringComparison.OrdinalIgnoreCase) ||
                record.Kind != ListeningExerciseKind.Word ||
                !evidenceByExercise.TryGetValue(record.ExerciseId, out CompletionEvidence? evidence))
            {
                continue;
            }

            int budget = record.Correct ? evidence.CorrectBudget : evidence.IncorrectBudget;
            if (budget <= 0)
                continue;

            bool ambiguousCandidate = record.Correct
                ? evidence.CorrectFeedbackAmbiguous
                : evidence.IncorrectFeedbackAmbiguous;

            if (ambiguousCandidate)
            {
                sawAmbiguousCandidate = true;
                safeSuffix.Clear();
                continue;
            }

            safeSuffix.Add(record);
        }

        bool feedbackAmbiguous = inCycle > 0 && sawAmbiguousCandidate && safeSuffix.Count < inCycle;
        List<ListeningHistoryRecord> cycle = feedbackAmbiguous || inCycle == 0
            ? new List<ListeningHistoryRecord>()
            : safeSuffix.Skip(Math.Max(0, safeSuffix.Count - inCycle)).ToList();

        return new Progress(
            CompletedReviews: inCycle,
            TargetReviews: TargetReviews,
            CorrectReviews: cycle.Count(record => record.Correct),
            NeedsReview: cycle.Count(record => !record.Correct),
            WrongAttempts: cycle.Sum(record => Math.Max(0, record.WrongAttempts)),
            Replays: cycle.Sum(record => Math.Max(0, record.Replays)),
            CycleCompleted: completionView && inCycle == TargetReviews,
            FeedbackAmbiguous: feedbackAmbiguous);
    }
}
