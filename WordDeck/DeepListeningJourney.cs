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

        public bool FeedbackAmbiguous =>
            (CorrectBudget > 0 && CorrectHistory > CorrectBudget) ||
            (IncorrectBudget > 0 && IncorrectHistory > IncorrectBudget);
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
        // preserve the durable journey count/boundary while failing closed on row-level
        // current-cycle feedback instead of guessing oldest-versus-newest chronology.
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
        bool feedbackAmbiguous = evidenceByExercise.Values.Any(evidence => evidence.FeedbackAmbiguous);

        int inCycle = creditedReviews % TargetReviews;
        if (completionView && creditedReviews > 0 && inCycle == 0)
            inCycle = TargetReviews;

        List<ListeningHistoryRecord> cycle = new();
        if (!feedbackAmbiguous && inCycle > 0)
        {
            var relevant = new List<ListeningHistoryRecord>();
            foreach (ListeningHistoryRecord record in state.History)
            {
                if (!string.Equals(record.DictionaryId, dictionaryId, StringComparison.OrdinalIgnoreCase) ||
                    record.Kind != ListeningExerciseKind.Word ||
                    !evidenceByExercise.TryGetValue(record.ExerciseId, out CompletionEvidence? evidence))
                {
                    continue;
                }

                // With no positive-budget over-representation, every observed row in
                // a positive outcome bucket is corroborated. Rows in zero-budget
                // buckets are provably stale/unevidenced and are excluded.
                if ((record.Correct && evidence.CorrectBudget > 0) ||
                    (!record.Correct && evidence.IncorrectBudget > 0))
                {
                    relevant.Add(record);
                }
            }

            cycle = relevant.Skip(Math.Max(0, relevant.Count - inCycle)).ToList();
        }

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
