namespace WordDeck;

/// <summary>
/// Platform-neutral learning evidence exposed by a training mode. The record is
/// intentionally descriptive only: global routing, mastery thresholds and
/// cross-mode recommendations belong to the future adaptive router, not to the
/// individual mode that produced the evidence.
/// </summary>
internal sealed record LearningEvidenceRecord(
    string DictionaryId,
    string EntryId,
    string ModeId,
    int CompletedReviews,
    int FirstTrySuccesses,
    int WrongAttempts,
    int HintUses,
    int CurrentStreak,
    DateTimeOffset? LastReviewedUtc)
{
    public double FirstTryRate => CompletedReviews <= 0
        ? 0
        : Math.Clamp((double)FirstTrySuccesses / CompletedReviews, 0, 1);
}

/// <summary>
/// Read-only boundary that lets future Sentence/Grammar/Listening/global
/// adaptive components consume evidence without depending on WinForms or on a
/// mode's private persistence model.
/// </summary>
internal interface ILearningEvidenceSource
{
    IReadOnlyList<LearningEvidenceRecord> Snapshot(string dictionaryId);
}

internal sealed class SpellingLearningEvidenceSource : ILearningEvidenceSource
{
    public const string ModeId = "spelling";
    private readonly SpellingState _state;

    public SpellingLearningEvidenceSource(SpellingState state) =>
        _state = state ?? throw new ArgumentNullException(nameof(state));

    public IReadOnlyList<LearningEvidenceRecord> Snapshot(string dictionaryId)
    {
        if (string.IsNullOrWhiteSpace(dictionaryId))
            return Array.Empty<LearningEvidenceRecord>();
        if (!_state.StatsByDictionary.TryGetValue(dictionaryId, out Dictionary<string, SpellingEntryStats>? stats))
            return Array.Empty<LearningEvidenceRecord>();

        return stats
            .Where(pair => !string.IsNullOrWhiteSpace(pair.Key) && pair.Value is not null)
            .OrderBy(pair => pair.Key, StringComparer.Ordinal)
            .Select(pair =>
            {
                SpellingEntryStats value = pair.Value;
                int completed = Math.Max(0, value.CompletedReviews);
                int firstTry = Math.Clamp(value.FirstTrySuccesses, 0, completed);
                return new LearningEvidenceRecord(
                    dictionaryId,
                    pair.Key,
                    ModeId,
                    completed,
                    firstTry,
                    Math.Max(0, value.WrongAttempts),
                    Math.Max(0, value.HintUses),
                    Math.Clamp(value.CurrentStreak, 0, completed),
                    value.LastReviewedUtc);
            })
            .ToArray();
    }
}
