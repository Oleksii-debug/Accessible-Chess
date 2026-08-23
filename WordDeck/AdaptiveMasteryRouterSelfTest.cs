namespace WordDeck;

internal static class AdaptiveMasteryRouterSelfTest
{
    public static void Run()
    {
        WeakSpellingRoutesToSpelling();
        UnavailableWeakModeIsNeverSelected();
        ColdStartUsesDeterministicModePriority();
        RecallExposureCannotPretendToBeScoredMastery();
        StableIdsNeverCollapseBySurfaceForm();
        InputOrderDoesNotChangeDecision();
        StudyPoolSizesAreExactAndBounded();
        SentenceEvidenceFailsClosedOnUnknownStableId();
        LearningEvidenceModeMappingFailsClosed();
        FullOxfordScalePlanIsCompleteAndUnique();
    }

    private static void WeakSpellingRoutesToSpelling()
    {
        DateTimeOffset now = new(2026, 8, 23, 12, 0, 0, TimeSpan.Zero);
        AdaptivePracticeCandidate candidate = Lexical("oxford", "word-1", AdaptivePracticeMode.Recall, AdaptivePracticeMode.Spelling);
        AdaptiveMasteryObservation[] evidence =
        {
            Obs("word-1", AdaptiveEvidenceChannel.MeaningRecall, 6, null, 0, 0, 0, now.AddHours(-2), "recall"),
            Obs("word-1", AdaptiveEvidenceChannel.Spelling, 4, 1, 4, 1, 0, now.AddHours(-20), "spelling")
        };

        AdaptiveRoutingDecision decision = new AdaptiveMasteryRouter().RouteNext(new[] { candidate }, evidence, now)
            ?? throw new InvalidOperationException("Adaptive router returned no decision for an eligible target.");
        Require(decision.NextMode == AdaptivePracticeMode.Spelling, "A weak scored Spelling channel must outrank stronger exposure-only Recall evidence.");
        Require(decision.Explanation.Contains("Spelling", StringComparison.Ordinal), "Adaptive decisions must contain a human-readable mode explanation.");
    }

    private static void UnavailableWeakModeIsNeverSelected()
    {
        DateTimeOffset now = DateTimeOffset.Parse("2026-08-23T12:00:00Z");
        AdaptivePracticeCandidate candidate = Lexical("oxford", "word-2", AdaptivePracticeMode.Recall, AdaptivePracticeMode.Spelling);
        AdaptiveMasteryObservation[] evidence =
        {
            Obs("word-2", AdaptiveEvidenceChannel.Listening, 1, 0, 4, 1, 0, now.AddDays(-4), "listening"),
            Obs("word-2", AdaptiveEvidenceChannel.Spelling, 3, 2, 1, 0, 2, now.AddDays(-2), "spelling")
        };
        AdaptiveRoutingDecision decision = new AdaptiveMasteryRouter().RouteNext(new[] { candidate }, evidence, now)!;
        Require(decision.NextMode != AdaptivePracticeMode.Listening, "Router must never select a mode that is not explicitly available.");
    }

    private static void ColdStartUsesDeterministicModePriority()
    {
        DateTimeOffset now = DateTimeOffset.UtcNow;
        AdaptiveMasteryRouter router = new();
        AdaptivePracticeCandidate lexical = Lexical("oxford", "cold-lexical",
            AdaptivePracticeMode.Reading, AdaptivePracticeMode.Spelling, AdaptivePracticeMode.Recall);
        AdaptiveRoutingDecision lexicalDecision = router.RouteNext(new[] { lexical }, Array.Empty<AdaptiveMasteryObservation>(), now)!;
        Require(lexicalDecision.NextMode == AdaptivePracticeMode.Recall, "Lexical cold start must prefer meaning Recall when it is available.");

        AdaptivePracticeCandidate grammar = new(
            "oxford",
            "grammar:present-perfect",
            AdaptiveTargetKind.GrammarSkill,
            new HashSet<AdaptivePracticeMode> { AdaptivePracticeMode.Sentence, AdaptivePracticeMode.Grammar, AdaptivePracticeMode.Reading });
        AdaptiveRoutingDecision grammarDecision = router.RouteNext(new[] { grammar }, Array.Empty<AdaptiveMasteryObservation>(), now)!;
        Require(grammarDecision.NextMode == AdaptivePracticeMode.Grammar, "Grammar-skill cold start must prefer direct Grammar practice.");
    }

    private static void RecallExposureCannotPretendToBeScoredMastery()
    {
        DateTimeOffset now = DateTimeOffset.UtcNow;
        AdaptivePracticeCandidate candidate = Lexical("oxford", "recall-only", AdaptivePracticeMode.Recall);
        AdaptiveMasteryObservation evidence = Obs(
            "recall-only", AdaptiveEvidenceChannel.MeaningRecall, 20, null, 0, 0, 0, now.AddHours(-1), "recall-history");
        AdaptiveChannelSnapshot snapshot = new AdaptiveMasteryRouter().Snapshot(
            candidate, AdaptiveEvidenceChannel.MeaningRecall, new[] { evidence }, now);
        Require(!snapshot.HasOutcomeEvidence, "Recall view history must stay marked as exposure-only evidence.");
        Require(snapshot.Mastery <= 0.55, "Exposure-only Recall history must be capped below scored mastery.");
    }

    private static void StableIdsNeverCollapseBySurfaceForm()
    {
        DateTimeOffset now = DateTimeOffset.UtcNow;
        AdaptivePracticeCandidate noun = Lexical("oxford", "lead:noun:b2", AdaptivePracticeMode.Spelling);
        AdaptivePracticeCandidate verb = Lexical("oxford", "lead:verb:b2", AdaptivePracticeMode.Spelling);
        AdaptiveMasteryObservation[] evidence =
        {
            Obs("lead:noun:b2", AdaptiveEvidenceChannel.Spelling, 8, 8, 0, 0, 5, now.AddHours(-1), "spelling")
        };
        AdaptiveRoutingDecision decision = new AdaptiveMasteryRouter().RouteNext(new[] { noun, verb }, evidence, now)!;
        Require(decision.TargetId == "lead:verb:b2", "Homographic lexical forms with distinct stable IDs must retain independent mastery.");
    }

    private static void InputOrderDoesNotChangeDecision()
    {
        DateTimeOffset now = DateTimeOffset.UtcNow;
        AdaptivePracticeCandidate[] candidates =
        {
            Lexical("oxford", "a", AdaptivePracticeMode.Recall, AdaptivePracticeMode.Spelling),
            Lexical("oxford", "b", AdaptivePracticeMode.Recall, AdaptivePracticeMode.Spelling)
        };
        AdaptiveMasteryObservation[] evidence =
        {
            Obs("a", AdaptiveEvidenceChannel.Spelling, 2, 1, 1, 0, 1, now.AddDays(-1), "spelling"),
            Obs("b", AdaptiveEvidenceChannel.Spelling, 2, 1, 1, 0, 1, now.AddDays(-1), "spelling")
        };
        AdaptiveMasteryRouter router = new();
        AdaptiveRoutingDecision first = router.RouteNext(candidates, evidence, now)!;
        AdaptiveRoutingDecision second = router.RouteNext(candidates.Reverse(), evidence.Reverse(), now)!;
        Require(first == second, "Adaptive routing must be deterministic regardless of input enumeration order.");
    }

    private static void StudyPoolSizesAreExactAndBounded()
    {
        DateTimeOffset now = DateTimeOffset.UtcNow;
        AdaptivePracticeCandidate[] candidates = Enumerable.Range(0, 250)
            .Select(i => Lexical("oxford", $"pool-{i:D4}", AdaptivePracticeMode.Recall))
            .ToArray();
        AdaptiveMasteryRouter router = new();
        Require(router.Plan(candidates, Array.Empty<AdaptiveMasteryObservation>(), now, AdaptiveStudyPoolSize.Thirty).Count == 30, "30-target adaptive pool is not exact.");
        Require(router.Plan(candidates, Array.Empty<AdaptiveMasteryObservation>(), now, AdaptiveStudyPoolSize.Hundred).Count == 100, "100-target adaptive pool is not exact.");
        Require(router.Plan(candidates, Array.Empty<AdaptiveMasteryObservation>(), now, AdaptiveStudyPoolSize.TwoHundred).Count == 200, "200-target adaptive pool is not exact.");
        Require(router.Plan(candidates, Array.Empty<AdaptiveMasteryObservation>(), now, AdaptiveStudyPoolSize.Full).Count == 250, "Full adaptive pool must preserve the supplied eligible universe.");
    }

    private static void SentenceEvidenceFailsClosedOnUnknownStableId()
    {
        var state = new SentenceCoachState
        {
            StatsByDictionary = new Dictionary<string, Dictionary<string, SentenceTargetStats>>(StringComparer.OrdinalIgnoreCase)
            {
                ["oxford"] = new Dictionary<string, SentenceTargetStats>(StringComparer.OrdinalIgnoreCase)
                {
                    ["unknown-id"] = new SentenceTargetStats { CompletedReviews = 1, FirstTrySuccesses = 1 }
                }
            }
        };
        bool failed = false;
        try
        {
            _ = AdaptiveEvidenceAdapters.FromSentence(state, "oxford", new[] { "known-id" });
        }
        catch (InvalidDataException)
        {
            failed = true;
        }
        Require(failed, "Sentence adaptive evidence must fail closed instead of remapping an unknown stable ID by surface form.");
    }

    private static void LearningEvidenceModeMappingFailsClosed()
    {
        var source = new FakeEvidenceSource(new LearningEvidenceRecord(
            "oxford", "word", "future-unknown-mode", 1, 1, 0, 0, 1, DateTimeOffset.UtcNow));
        bool failed = false;
        try
        {
            _ = AdaptiveEvidenceAdapters.FromLearningEvidence(source, "oxford");
        }
        catch (InvalidDataException)
        {
            failed = true;
        }
        Require(failed, "Unknown evidence modes must not be silently assigned to a mastery channel.");
    }

    private static void FullOxfordScalePlanIsCompleteAndUnique()
    {
        const int OxfordUniverse = 5446;
        DateTimeOffset now = DateTimeOffset.UtcNow;
        AdaptivePracticeCandidate[] candidates = Enumerable.Range(1, OxfordUniverse)
            .Select(i => Lexical("oxford-5446", $"ox-{i:D4}", AdaptivePracticeMode.Recall, AdaptivePracticeMode.Spelling, AdaptivePracticeMode.Sentence))
            .ToArray();
        List<AdaptiveRoutingDecision> plan = new AdaptiveMasteryRouter().Plan(
            candidates,
            Array.Empty<AdaptiveMasteryObservation>(),
            now,
            AdaptiveStudyPoolSize.Full);
        Require(plan.Count == OxfordUniverse, "Adaptive full-pool planner did not cover all 5446 supplied lexical targets.");
        Require(plan.Select(item => item.TargetId).Distinct(StringComparer.Ordinal).Count() == OxfordUniverse,
            "Adaptive full-pool planner emitted duplicate stable targets.");
    }

    private static AdaptivePracticeCandidate Lexical(string dictionaryId, string targetId, params AdaptivePracticeMode[] modes) =>
        new(dictionaryId, targetId, AdaptiveTargetKind.Lexical, new HashSet<AdaptivePracticeMode>(modes));

    private static AdaptiveMasteryObservation Obs(
        string targetId,
        AdaptiveEvidenceChannel channel,
        int completed,
        int? successes,
        int wrong,
        int hints,
        int streak,
        DateTimeOffset? last,
        string source) =>
        new("oxford", targetId, AdaptiveTargetKind.Lexical, channel, completed, successes, wrong, hints, streak, last, source);

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException("AdaptiveMasteryRouterSelfTest: " + message);
    }

    private sealed class FakeEvidenceSource : ILearningEvidenceSource
    {
        private readonly LearningEvidenceRecord[] _records;
        public FakeEvidenceSource(params LearningEvidenceRecord[] records) => _records = records;
        public IReadOnlyList<LearningEvidenceRecord> Snapshot(string dictionaryId) => _records;
    }
}
