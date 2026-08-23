namespace WordDeck;

internal static class AdaptiveGrammarEvidenceAdapter
{
    public static IReadOnlyList<AdaptiveMasteryObservation> FromGrammarMastery(
        string dictionaryId,
        IReadOnlyDictionary<string, GrammarSkillMastery> mastery)
    {
        if (string.IsNullOrWhiteSpace(dictionaryId) || !string.Equals(dictionaryId, dictionaryId.Trim(), StringComparison.Ordinal))
            throw new InvalidDataException("Adaptive grammar dictionary identity must be non-blank canonical text.");
        ArgumentNullException.ThrowIfNull(mastery);

        var result = new List<AdaptiveMasteryObservation>(mastery.Count);
        foreach ((string key, GrammarSkillMastery row) in mastery.OrderBy(pair => pair.Key, StringComparer.Ordinal))
        {
            if (row is null) throw new InvalidDataException($"Grammar mastery row '{key}' is missing.");
            if (!string.Equals(key, row.SkillId, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException($"Grammar mastery key '{key}' does not match stable skill id '{row.SkillId}'.");
            if (!GrammarSkillCatalog.ById.ContainsKey(row.SkillId))
                throw new InvalidDataException($"Grammar mastery references unknown stable skill id '{row.SkillId}'.");
            if (row.Attempts < 0 || row.Correct < 0 || row.Correct > row.Attempts || row.Mastery is < 0 or > 1)
                throw new InvalidDataException($"Grammar mastery for '{row.SkillId}' contains invalid counters.");

            result.Add(new AdaptiveMasteryObservation(
                dictionaryId,
                row.SkillId,
                AdaptiveTargetKind.GrammarSkill,
                AdaptiveEvidenceChannel.Grammar,
                row.Attempts,
                row.Correct,
                row.Attempts - row.Correct,
                HintUses: 0,
                CurrentStreak: 0,
                row.Attempts == 0 || row.UpdatedUtc == DateTimeOffset.MinValue ? null : row.UpdatedUtc,
                "grammar-mastery"));
        }
        return result;
    }
}

internal static class AdaptiveGrammarEvidenceSelfTest
{
    public static void Run()
    {
        ConvertsCanonicalGrammarMastery();
        RejectsUnknownGrammarSkill();
        WeakGrammarSkillRoutesToGrammar();
    }

    private static void ConvertsCanonicalGrammarMastery()
    {
        DateTimeOffset now = new(2026, 8, 23, 15, 0, 0, TimeSpan.Zero);
        var mastery = new Dictionary<string, GrammarSkillMastery>(StringComparer.OrdinalIgnoreCase)
        {
            ["present.simple.core"] = new("present.simple.core", 5, 3, 0.42, now.AddHours(-8))
        };
        AdaptiveMasteryObservation evidence = AdaptiveGrammarEvidenceAdapter.FromGrammarMastery("oxford", mastery).Single();
        Require(evidence.TargetKind == AdaptiveTargetKind.GrammarSkill, "Grammar evidence must remain a grammar-skill target, not a lexical surface form.");
        Require(evidence.Channel == AdaptiveEvidenceChannel.Grammar, "Grammar mastery was mapped to the wrong global channel.");
        Require(evidence.CompletedReviews == 5 && evidence.FirstTrySuccesses == 3 && evidence.WrongAttempts == 2,
            "Grammar scored attempts were not preserved exactly.");
    }

    private static void RejectsUnknownGrammarSkill()
    {
        var mastery = new Dictionary<string, GrammarSkillMastery>(StringComparer.OrdinalIgnoreCase)
        {
            ["unknown.skill"] = new("unknown.skill", 1, 1, 1.0, DateTimeOffset.UtcNow)
        };
        bool failed = false;
        try { _ = AdaptiveGrammarEvidenceAdapter.FromGrammarMastery("oxford", mastery); }
        catch (InvalidDataException) { failed = true; }
        Require(failed, "Adaptive grammar bridge must fail closed on unknown stable skill IDs.");
    }

    private static void WeakGrammarSkillRoutesToGrammar()
    {
        DateTimeOffset now = new(2026, 8, 23, 15, 0, 0, TimeSpan.Zero);
        var mastery = new Dictionary<string, GrammarSkillMastery>(StringComparer.OrdinalIgnoreCase)
        {
            ["present.simple.core"] = new("present.simple.core", 4, 1, 0.20, now.AddDays(-2))
        };
        IReadOnlyList<AdaptiveMasteryObservation> evidence = AdaptiveGrammarEvidenceAdapter.FromGrammarMastery("oxford", mastery);
        var candidate = new AdaptivePracticeCandidate(
            "oxford",
            "present.simple.core",
            AdaptiveTargetKind.GrammarSkill,
            new HashSet<AdaptivePracticeMode> { AdaptivePracticeMode.Grammar, AdaptivePracticeMode.Sentence, AdaptivePracticeMode.Reading });
        AdaptiveRoutingDecision decision = new AdaptiveMasteryRouter().RouteNext(new[] { candidate }, evidence, now)
            ?? throw new InvalidOperationException("Global router returned no Grammar decision.");
        Require(decision.NextMode == AdaptivePracticeMode.Grammar, "A weak canonical grammar skill must route to direct Grammar practice when available.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException("AdaptiveGrammarEvidenceSelfTest: " + message);
    }
}
