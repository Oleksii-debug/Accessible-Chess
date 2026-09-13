namespace WordDeck;

/// <summary>
/// Preserves an already-persisted Sentence Spelling exercise across the form's
/// constructor-time pack binding. The initial ComboBox selection raises the same
/// event used for a real pack switch; until that UI lifecycle is split, this
/// snapshot prevents that startup event from replacing a valid resumable exercise.
/// </summary>
internal sealed record SentenceCoachResumeSnapshot(
    string? ActivePackId,
    string? CurrentSentenceId,
    string? CurrentTargetEntryId,
    IReadOnlyList<string> CurrentTargetEntryIds,
    int CurrentTargetIndex,
    bool CurrentTargetHadWrong,
    bool CurrentTargetUsedHint)
{
    public static SentenceCoachResumeSnapshot Capture(SentenceCoachState state) => new(
        state.ActivePackId,
        state.CurrentSentenceId,
        state.CurrentTargetEntryId,
        state.CurrentTargetEntryIds.ToArray(),
        state.CurrentTargetIndex,
        state.CurrentTargetHadWrong,
        state.CurrentTargetUsedHint);

    public bool RestoreIfSamePack(SentenceCoachState state)
    {
        if (string.IsNullOrWhiteSpace(ActivePackId) ||
            string.IsNullOrWhiteSpace(CurrentSentenceId) ||
            !string.Equals(ActivePackId, state.ActivePackId, StringComparison.OrdinalIgnoreCase))
            return false;

        state.CurrentSentenceId = CurrentSentenceId;
        state.CurrentTargetEntryId = CurrentTargetEntryId;
        state.CurrentTargetEntryIds = CurrentTargetEntryIds.ToList();
        state.CurrentTargetIndex = CurrentTargetIndex;
        state.CurrentTargetHadWrong = CurrentTargetHadWrong;
        state.CurrentTargetUsedHint = CurrentTargetUsedHint;
        SentenceCoachStateStore.Normalize(state);
        return true;
    }
}
