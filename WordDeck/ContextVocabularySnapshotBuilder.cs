namespace WordDeck;

internal sealed record ContextVocabularySnapshot(
    ContextLearnerVocabulary Vocabulary,
    int KnownCount,
    int LearningCount,
    int IgnoredUnknownEntryIds);

internal static class ContextVocabularySnapshotBuilder
{
    public static ContextVocabularySnapshot Build(
        DictionaryPackage dictionary,
        AppState recallState,
        SpellingState spellingState)
    {
        ArgumentNullException.ThrowIfNull(dictionary);
        ArgumentNullException.ThrowIfNull(recallState);
        ArgumentNullException.ThrowIfNull(spellingState);

        var validIds = new HashSet<string>(
            dictionary.Entries.Select(entry => ContextTargetIds.NormalizeSingle(entry.Id)),
            StringComparer.OrdinalIgnoreCase);
        var known = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var learning = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        Dictionary<string, SpellingEntryStats>? spellingStats = null;
        if (spellingState.StatsByDictionary is not null)
            spellingState.StatsByDictionary.TryGetValue(dictionary.Id, out spellingStats);

        foreach (string id in validIds)
        {
            SpellingEntryStats? stats = null;
            spellingStats?.TryGetValue(id, out stats);
            if (stats is not null && IsStrongSpellingEvidence(stats))
            {
                known.Add(id);
                continue;
            }

            bool hasSpellingEvidence = stats is not null && HasAnySpellingEvidence(stats);
            bool hasRecallEvidence = recallState.StudyHistoryByEntryId is not null &&
                recallState.StudyHistoryByEntryId.TryGetValue(id, out WordStudyHistory? history) &&
                history is not null &&
                (history.SeenCount > 0 || history.TranslationRevealCount > 0);

            if (hasSpellingEvidence || hasRecallEvidence)
                learning.Add(id);
        }

        // HiddenEntryIds is intentionally not used as a mastery signal. Hiding is a
        // reversible study preference, not evidence that the learner knows the word.
        int ignoredUnknown = CountUnknownEvidenceIds(validIds, recallState, spellingStats);
        var vocabulary = new ContextLearnerVocabulary(known, learning);
        return new ContextVocabularySnapshot(vocabulary, known.Count, learning.Count, ignoredUnknown);
    }

    internal static bool IsStrongSpellingEvidence(SpellingEntryStats stats)
    {
        ArgumentNullException.ThrowIfNull(stats);
        int completed = Math.Max(0, stats.CompletedReviews);
        int firstTry = Math.Clamp(stats.FirstTrySuccesses, 0, completed);
        IReadOnlyList<bool> recent = stats.RecentOutcomes ?? new List<bool>();
        int recentClean = recent.Count(value => value);

        // Keep the contextual "known" threshold exactly aligned with the current
        // deterministic Spelling Coach promotion gate: 3+ completed reviews,
        // streak 3+, lifetime first-try rate 75%+, recent clean rate 80%+.
        return completed >= 3 &&
               stats.CurrentStreak >= 3 &&
               (long)firstTry * 4L >= (long)completed * 3L &&
               recent.Count > 0 &&
               (long)recentClean * 5L >= (long)recent.Count * 4L;
    }

    private static bool HasAnySpellingEvidence(SpellingEntryStats stats) =>
        stats.CompletedReviews > 0 ||
        stats.FirstTrySuccesses > 0 ||
        stats.WrongAttempts > 0 ||
        stats.HintUses > 0 ||
        stats.ShowAnswerUses > 0 ||
        stats.CurrentStreak > 0 ||
        (stats.RecentOutcomes?.Count ?? 0) > 0 ||
        stats.LastReviewedUtc is not null;

    private static int CountUnknownEvidenceIds(
        IReadOnlySet<string> validIds,
        AppState recallState,
        IReadOnlyDictionary<string, SpellingEntryStats>? spellingStats)
    {
        var unknown = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if (recallState.StudyHistoryByEntryId is not null)
        {
            foreach (string raw in recallState.StudyHistoryByEntryId.Keys)
            {
                string id = NormalizeEvidenceId(raw);
                if (id.Length > 0 && !validIds.Contains(id)) unknown.Add(id);
            }
        }

        if (spellingStats is not null)
        {
            foreach (string raw in spellingStats.Keys)
            {
                string id = NormalizeEvidenceId(raw);
                if (id.Length > 0 && !validIds.Contains(id)) unknown.Add(id);
            }
        }
        return unknown.Count;
    }

    private static string NormalizeEvidenceId(string? raw) =>
        string.IsNullOrWhiteSpace(raw) ? string.Empty : raw.Trim().ToLowerInvariant();
}
