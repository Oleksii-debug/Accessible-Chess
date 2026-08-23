namespace WordDeck;

/// <summary>
/// Builds one finite Spelling review cycle. Persisted learning evidence may move
/// weak words earlier in the cycle, but every active stable entry ID is still
/// emitted at most once before the cycle is refilled.
/// </summary>
internal static class SpellingReviewOrder
{
    public static Queue<string> Create(
        IEnumerable<string> entryIds,
        IReadOnlyDictionary<string, SpellingEntryStats>? statsByEntry,
        Random random,
        string? avoidFirstId = null)
    {
        ArgumentNullException.ThrowIfNull(entryIds);
        ArgumentNullException.ThrowIfNull(random);

        List<string> ids = entryIds
            .Where(id => !string.IsNullOrWhiteSpace(id))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        // Randomize first, then use that randomized position as the tie breaker.
        // Equal-strength words therefore remain varied without weakening the
        // deterministic priority policy derived from persisted learning evidence.
        for (int i = ids.Count - 1; i > 0; i--)
        {
            int j = random.Next(i + 1);
            (ids[i], ids[j]) = (ids[j], ids[i]);
        }

        var randomRank = ids
            .Select((id, index) => (id, index))
            .ToDictionary(item => item.id, item => item.index, StringComparer.OrdinalIgnoreCase);

        ids.Sort((left, right) =>
        {
            int rightPriority = PriorityScore(GetStats(statsByEntry, right));
            int leftPriority = PriorityScore(GetStats(statsByEntry, left));
            int byPriority = rightPriority.CompareTo(leftPriority);
            return byPriority != 0 ? byPriority : randomRank[left].CompareTo(randomRank[right]);
        });

        // Never repeat the card that was just shown at a cycle/refill boundary.
        // Moving it only to the next suitable position preserves its weakness
        // priority while avoiding an immediate duplicate announcement to NVDA.
        if (!string.IsNullOrWhiteSpace(avoidFirstId) && ids.Count > 1 &&
            string.Equals(ids[0], avoidFirstId, StringComparison.OrdinalIgnoreCase))
        {
            int replacement = ids.FindIndex(1, id => !string.Equals(id, avoidFirstId, StringComparison.OrdinalIgnoreCase));
            if (replacement > 0)
                (ids[0], ids[replacement]) = (ids[replacement], ids[0]);
        }

        return new Queue<string>(ids);
    }

    internal static int PriorityScore(SpellingEntryStats? stats)
    {
        // New/unseen words stay ahead of already-stable words, but confirmed
        // recent mistakes receive a much stronger local priority.
        if (stats is null)
            return 100;

        int completed = Math.Max(0, stats.CompletedReviews);
        int wrong = Math.Max(0, stats.WrongAttempts);
        int hints = Math.Max(0, stats.HintUses);
        int shown = Math.Max(0, stats.ShowAnswerUses);
        int streak = Math.Max(0, stats.CurrentStreak);
        IReadOnlyList<bool> recent = stats.RecentOutcomes ?? Array.Empty<bool>();
        int recentErrors = recent.Count(outcome => !outcome);

        if (completed == 0 && wrong == 0 && hints == 0 && shown == 0)
            return 100;

        double lifetimeCleanRate = completed == 0
            ? 0
            : Math.Clamp((double)Math.Max(0, stats.FirstTrySuccesses) / completed, 0, 1);

        int score = recentErrors * 1000
            + Math.Min(wrong, 50) * 20
            + Math.Min(hints, 50) * 10
            + Math.Min(shown, 50) * 10
            + (int)Math.Round((1 - lifetimeCleanRate) * 200, MidpointRounding.AwayFromZero)
            - Math.Min(streak, 10) * 25;

        // A sustained clean recovery must be allowed to de-prioritize old errors;
        // otherwise historical mistakes would permanently dominate every session.
        double recentCleanRate = recent.Count == 0
            ? 1
            : (double)recent.Count(outcome => outcome) / recent.Count;
        if (completed >= 3 && streak >= 3 && recentErrors == 0 &&
            lifetimeCleanRate >= 0.80 && recentCleanRate >= 0.80)
        {
            score = Math.Min(score, 50);
        }

        return Math.Max(0, score);
    }

    private static SpellingEntryStats? GetStats(
        IReadOnlyDictionary<string, SpellingEntryStats>? statsByEntry,
        string entryId)
    {
        if (statsByEntry is null)
            return null;
        return statsByEntry.TryGetValue(entryId, out SpellingEntryStats? stats) ? stats : null;
    }
}
