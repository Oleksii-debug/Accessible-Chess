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
        bool CycleCompleted)
    {
        public int Remaining => Math.Max(0, TargetReviews - CompletedReviews);
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
        // single ListeningCoachState: History contains the chronological record and
        // StatsByDictionary records the aggregate CompletedReviews count for the same
        // exercise. Reconcile each chronological history occurrence against that count
        // so duplicate/stale rows cannot gain journey credit merely because their
        // exercise has at least one legitimate completion. This keeps current
        // eligibility out of already-counted chronology without adding another store.
        var remainingCompletedByExercise = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        if (state.StatsByDictionary.TryGetValue(dictionaryId, out Dictionary<string, ListeningItemStats>? perDictionary))
        {
            foreach ((string exerciseId, ListeningItemStats stats) in perDictionary)
                if (stats.CompletedReviews > 0)
                    remainingCompletedByExercise[exerciseId] = stats.CompletedReviews;
        }

        var relevant = new List<ListeningHistoryRecord>();
        foreach (ListeningHistoryRecord record in state.History)
        {
            if (!string.Equals(record.DictionaryId, dictionaryId, StringComparison.OrdinalIgnoreCase) ||
                record.Kind != ListeningExerciseKind.Word ||
                !remainingCompletedByExercise.TryGetValue(record.ExerciseId, out int remaining) ||
                remaining <= 0)
            {
                continue;
            }

            relevant.Add(record);
            remainingCompletedByExercise[record.ExerciseId] = remaining - 1;
        }

        int inCycle = relevant.Count % TargetReviews;
        if (completionView && relevant.Count > 0 && inCycle == 0)
            inCycle = TargetReviews;

        List<ListeningHistoryRecord> cycle = inCycle == 0
            ? new List<ListeningHistoryRecord>()
            : relevant.Skip(relevant.Count - inCycle).ToList();

        return new Progress(
            CompletedReviews: inCycle,
            TargetReviews: TargetReviews,
            CorrectReviews: cycle.Count(record => record.Correct),
            NeedsReview: cycle.Count(record => !record.Correct),
            WrongAttempts: cycle.Sum(record => Math.Max(0, record.WrongAttempts)),
            Replays: cycle.Sum(record => Math.Max(0, record.Replays)),
            CycleCompleted: completionView && inCycle == TargetReviews);
    }
}
