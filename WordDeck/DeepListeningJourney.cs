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

        var availableIds = new HashSet<string>(
            available.Select(item => item.ExerciseId),
            StringComparer.OrdinalIgnoreCase);

        List<ListeningHistoryRecord> relevant = state.History
            .Where(record =>
                string.Equals(record.DictionaryId, dictionaryId, StringComparison.OrdinalIgnoreCase) &&
                availableIds.Contains(record.ExerciseId))
            .ToList();

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
