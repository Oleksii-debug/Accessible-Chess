namespace WordDeck;

internal static class AdaptiveMasteryRouterSelfTest
{
    public static void Run()
    {
        EveryWeakChannelRoutesDirectly();
        UnavailableWeakModeIsNeverSelected();
        ColdStartUsesDeterministicModePriority();
        ExposureOnlyRecallHasNoMastery();
        RevealOnlyRecallHasNoMastery();
        MissingEvidenceStaysMissing();
        ExposureDoesNotInflateScoredMastery();
        HiddenWordsAreExcludedFromRoutingAndRecallEvidence();
        StableIdsNeverCollapseBySurfaceForm();
        DictionaryIdentityIsIsolated();
        InputOrderDoesNotChangeDecision();
        StudyPoolSizesAreExactAndBounded();
        PolicySeamConstrainsModesWithoutCompletionRules();
        SentenceEvidenceFailsClosedOnUnknownStableId();
        LearningEvidenceModeMappingFailsClosed();
        LearningEvidenceDictionaryMismatchFailsClosed();
        FullOxfordScalePlanIsCompleteAndUnique();
    }

    private static void EveryWeakChannelRoutesDirectly()
    {
        DateTimeOffset now = new(2026, 8, 27, 7, 0, 0, TimeSpan.Zero);
        (AdaptiveEvidenceChannel Channel, AdaptivePracticeMode Mode)[] cases =
        {
            (AdaptiveEvidenceChannel.MeaningRecall, AdaptivePracticeMode.Recall),
            (AdaptiveEvidenceChannel.Spelling, AdaptivePracticeMode.Spelling),
            (AdaptiveEvidenceChannel.SentenceForm, AdaptivePracticeMode.Sentence),
            (AdaptiveEvidenceChannel.Grammar, AdaptivePracticeMode.Grammar),
            (AdaptiveEvidenceChannel.Listening, AdaptivePracticeMode.Listening),
            (AdaptiveEvidenceChannel.ReadingContext, AdaptivePracticeMode.Reading),
            (AdaptiveEvidenceChannel.NarrativeContext, AdaptivePracticeMode.Story)
        };
        AdaptivePracticeMode[] allModes = Enum.GetValues<AdaptivePracticeMode>();

        foreach ((AdaptiveEvidenceChannel channel, AdaptivePracticeMode expectedMode) in cases)
        {
            string id = "weak-" + expectedMode.ToString().ToLowerInvariant();
            AdaptivePracticeCandidate candidate = Lexical("oxford", id, allModes);
            AdaptiveMasteryObservation weak = Obs(
                "oxford",
                id,
                AdaptiveTargetKind.Lexical,
                channel,
                completed: 4,
                successes: 1,
                wrong: 3,
                hints: 1,
                streak: 0,
                last: now.AddDays(-2),
                source: expectedMode.ToString().ToLowerInvariant());
            AdaptiveRoutingDecision decision = new AdaptiveMasteryRouter().RouteNext(new[] { candidate }, new[] { weak }, now)
                ?? throw new InvalidOperationException("Adaptive router returned no decision for an eligible weak channel.");
            Require(decision.NextMode == expectedMode,
                $"Weak {channel} evidence must route directly to {expectedMode}, not to a merely missing channel.");
            Require(decision.HasDirectNeed, "Weak scored evidence must be marked as a direct practice need.");
        }
    }

    private static void UnavailableWeakModeIsNeverSelected()
    {
        DateTimeOffset now = DateTimeOffset.Parse("2026-08-27T07:00:00Z");
        AdaptivePracticeCandidate candidate = Lexical("oxford", "word-2", AdaptivePracticeMode.Recall, AdaptivePracticeMode.Spelling);
        AdaptiveMasteryObservation[] evidence =
        {
            Obs("oxford", "word-2", AdaptiveTargetKind.Lexical, AdaptiveEvidenceChannel.Listening, 1, 0, 4, 1, 0, now.AddDays(-4), "listening"),
            Obs("oxford", "word-2", AdaptiveTargetKind.Lexical, AdaptiveEvidenceChannel.Spelling, 3, 2, 1, 0, 2, now.AddDays(-2), "spelling")
        };
        AdaptiveRoutingDecision decision = new AdaptiveMasteryRouter().RouteNext(new[] { candidate }, evidence, now)!;
        Require(decision.NextMode != AdaptivePracticeMode.Listening, "Router must never select a mode that is not explicitly available.");
        Require(decision.NextMode == AdaptivePracticeMode.Spelling, "Available weak Spelling must receive the direct route.");
    }

    private static void ColdStartUsesDeterministicModePriority()
    {
        DateTimeOffset now = DateTimeOffset.Parse("2026-08-27T07:00:00Z");
        AdaptiveMasteryRouter router = new();
        AdaptivePracticeCandidate lexical = Lexical("oxford", "cold-lexical",
            AdaptivePracticeMode.Reading, AdaptivePracticeMode.Spelling, AdaptivePracticeMode.Recall);
        AdaptiveRoutingDecision lexicalDecision = router.RouteNext(new[] { lexical }, Array.Empty<AdaptiveMasteryObservation>(), now)!;
        Require(lexicalDecision.NextMode == AdaptivePracticeMode.Recall, "Lexical cold start must use deterministic channel priority when all evidence is missing.");
        Require(lexicalDecision.EvidenceStatus == AdaptiveEvidenceStatus.Missing && lexicalDecision.Mastery is null,
            "Cold-start evidence must remain explicitly missing with unknown mastery.");

        AdaptivePracticeCandidate grammar = new(
            "oxford",
            "grammar:present-perfect",
            AdaptiveTargetKind.GrammarSkill,
            new HashSet<AdaptivePracticeMode> { AdaptivePracticeMode.Sentence, AdaptivePracticeMode.Grammar, AdaptivePracticeMode.Reading });
        AdaptiveRoutingDecision grammarDecision = router.RouteNext(new[] { grammar }, Array.Empty<AdaptiveMasteryObservation>(), now)!;
        Require(grammarDecision.NextMode == AdaptivePracticeMode.Grammar, "Grammar-skill cold start must prefer direct Grammar under deterministic tie-breaking.");
    }

    private static void ExposureOnlyRecallHasNoMastery()
    {
        DateTimeOffset now = DateTimeOffset.Parse("2026-08-27T07:00:00Z");
        AdaptivePracticeCandidate candidate = Lexical("oxford", "recall-only", AdaptivePracticeMode.Recall);
        AdaptiveMasteryObservation evidence = Obs(
            "oxford", "recall-only", AdaptiveTargetKind.Lexical, AdaptiveEvidenceChannel.MeaningRecall,
            20, null, 0, 0, 0, now.AddHours(-1), "recall-history");
        AdaptiveChannelSnapshot snapshot = new AdaptiveMasteryRouter().Snapshot(
            candidate, AdaptiveEvidenceChannel.MeaningRecall, new[] { evidence }, now);
        Require(snapshot.EvidenceStatus == AdaptiveEvidenceStatus.ExposureOnly, "Recall view history must remain exposure-only evidence.");
        Require(snapshot.Mastery is null, "Exposure must never be converted into a mastery percentage.");
        Require(!snapshot.HasDirectNeed, "Unassisted exposure alone does not prove a weak or mastered outcome.");
    }

    private static void RevealOnlyRecallHasNoMastery()
    {
        DateTimeOffset now = DateTimeOffset.Parse("2026-08-27T07:00:00Z");
        AdaptivePracticeCandidate candidate = Lexical("oxford", "revealed", AdaptivePracticeMode.Recall, AdaptivePracticeMode.Spelling);
        AdaptiveMasteryObservation evidence = Obs(
            "oxford", "revealed", AdaptiveTargetKind.Lexical, AdaptiveEvidenceChannel.MeaningRecall,
            6, null, 0, 4, 0, now.AddHours(-2), "recall-history");
        AdaptiveChannelSnapshot snapshot = new AdaptiveMasteryRouter().Snapshot(
            candidate, AdaptiveEvidenceChannel.MeaningRecall, new[] { evidence }, now);
        Require(snapshot.Mastery is null, "Translation reveals must never become mastery evidence.");
        Require(snapshot.HasDirectNeed, "Reveal dependence should remain usable routing evidence without pretending it is mastery.");
        AdaptiveRoutingDecision decision = new AdaptiveMasteryRouter().RouteNext(new[] { candidate }, new[] { evidence }, now)!;
        Require(decision.NextMode == AdaptivePracticeMode.Recall, "Reveal dependence in Recall must route back to Recall instead of a merely missing mode.");
    }

    private static void MissingEvidenceStaysMissing()
    {
        DateTimeOffset now = DateTimeOffset.Parse("2026-08-27T07:00:00Z");
        AdaptivePracticeCandidate candidate = Lexical("oxford", "missing", AdaptivePracticeMode.Listening);
        AdaptiveChannelSnapshot snapshot = new AdaptiveMasteryRouter().Snapshot(
            candidate, AdaptiveEvidenceChannel.Listening, Array.Empty<AdaptiveMasteryObservation>(), now);
        Require(snapshot.EvidenceStatus == AdaptiveEvidenceStatus.Missing, "No evidence must remain Missing, not become a zero mastery score.");
        Require(snapshot.Mastery is null, "Missing evidence must not be represented as zero mastery.");
        AdaptiveRoutingDecision decision = new AdaptiveMasteryRouter().RouteNext(new[] { candidate }, Array.Empty<AdaptiveMasteryObservation>(), now)!;
        Require(decision.Explanation.Contains("mastery remains unknown", StringComparison.Ordinal), "Explainability must say missing mastery is unknown.");
    }

    private static void ExposureDoesNotInflateScoredMastery()
    {
        DateTimeOffset now = DateTimeOffset.Parse("2026-08-27T07:00:00Z");
        AdaptivePracticeCandidate candidate = Lexical("oxford", "mixed", AdaptivePracticeMode.Recall);
        AdaptiveMasteryObservation scored = Obs(
            "oxford", "mixed", AdaptiveTargetKind.Lexical, AdaptiveEvidenceChannel.MeaningRecall,
            2, 2, 0, 0, 2, now.AddHours(-1), "future-scored-recall");
        AdaptiveMasteryObservation exposure = Obs(
            "oxford", "mixed", AdaptiveTargetKind.Lexical, AdaptiveEvidenceChannel.MeaningRecall,
            50, null, 0, 0, 0, now.AddMinutes(-5), "recall-history");
        AdaptiveMasteryRouter router = new();
        double scoredOnly = router.Snapshot(candidate, AdaptiveEvidenceChannel.MeaningRecall, new[] { scored }, now).Mastery
            ?? throw new InvalidOperationException("Scored evidence produced no mastery.");
        AdaptiveChannelSnapshot mixed = router.Snapshot(candidate, AdaptiveEvidenceChannel.MeaningRecall, new[] { scored, exposure }, now);
        Require(mixed.Mastery == scoredOnly, "Extra exposure must not increase confidence or mastery from scored outcomes.");
        Require(mixed.ExposureReviews == 50 && mixed.OutcomeReviews == 2, "Exposure and scored review counts must remain separate.");
    }

    private static void HiddenWordsAreExcludedFromRoutingAndRecallEvidence()
    {
        DateTimeOffset now = DateTimeOffset.Parse("2026-08-27T07:00:00Z");
        var state = new AppState();
        state.HiddenEntryIds.Add("hidden-id");
        state.StudyHistoryByEntryId["hidden-id"] = new WordStudyHistory { SeenCount = 5, TranslationRevealCount = 3, LastSeenUtc = now.AddHours(-1) };
        state.StudyHistoryByEntryId["visible-id"] = new WordStudyHistory { SeenCount = 2, LastSeenUtc = now.AddHours(-2) };

        IReadOnlyList<AdaptivePracticeCandidate> candidates = AdaptiveCandidateFactory.FromLexicalTargets(
            state,
            "oxford",
            new[] { "hidden-id", "visible-id" },
            new HashSet<AdaptivePracticeMode> { AdaptivePracticeMode.Recall, AdaptivePracticeMode.Spelling });
        List<AdaptiveRoutingDecision> plan = new AdaptiveMasteryRouter().Plan(
            candidates,
            Array.Empty<AdaptiveMasteryObservation>(),
            now,
            AdaptiveStudyPoolSize.Full);
        Require(plan.Count == 1 && plan[0].TargetId == "visible-id", "Hidden lexical targets must never enter an adaptive plan.");

        IReadOnlyList<AdaptiveMasteryObservation> recall = AdaptiveEvidenceAdapters.FromRecall(
            state, "oxford", new[] { "hidden-id", "visible-id" });
        Require(recall.Count == 1 && recall[0].TargetId == "visible-id", "Hidden Recall history must not feed adaptive routing.");
    }

    private static void StableIdsNeverCollapseBySurfaceForm()
    {
        DateTimeOffset now = DateTimeOffset.Parse("2026-08-27T07:00:00Z");
        AdaptivePracticeCandidate noun = Lexical("oxford", "lead:noun:b2", AdaptivePracticeMode.Spelling);
        AdaptivePracticeCandidate verb = Lexical("oxford", "lead:verb:b2", AdaptivePracticeMode.Spelling);
        AdaptiveMasteryObservation[] evidence =
        {
            Obs("oxford", "lead:noun:b2", AdaptiveTargetKind.Lexical, AdaptiveEvidenceChannel.Spelling, 8, 8, 0, 0, 5, now.AddHours(-1), "spelling")
        };
        AdaptiveRoutingDecision decision = new AdaptiveMasteryRouter().RouteNext(new[] { noun, verb }, evidence, now)!;
        Require(decision.TargetId == "lead:verb:b2", "Homographic forms with distinct stable IDs must retain independent evidence.");
    }

    private static void DictionaryIdentityIsIsolated()
    {
        DateTimeOffset now = DateTimeOffset.Parse("2026-08-27T07:00:00Z");
        AdaptivePracticeCandidate first = Lexical("dictionary-a", "shared-id", AdaptivePracticeMode.Spelling);
        AdaptivePracticeCandidate second = Lexical("dictionary-b", "shared-id", AdaptivePracticeMode.Spelling);
        AdaptiveMasteryObservation strong = Obs(
            "dictionary-a", "shared-id", AdaptiveTargetKind.Lexical, AdaptiveEvidenceChannel.Spelling,
            8, 8, 0, 0, 5, now.AddMinutes(-10), "spelling");
        AdaptiveRoutingDecision decision = new AdaptiveMasteryRouter().RouteNext(new[] { first, second }, new[] { strong }, now)!;
        Require(decision.DictionaryId == "dictionary-b", "Identical stable IDs in different dictionaries must not share mastery evidence.");
    }

    private static void InputOrderDoesNotChangeDecision()
    {
        DateTimeOffset now = DateTimeOffset.Parse("2026-08-27T07:00:00Z");
        AdaptivePracticeCandidate[] candidates =
        {
            Lexical("oxford", "a", AdaptivePracticeMode.Recall, AdaptivePracticeMode.Spelling),
            Lexical("oxford", "b", AdaptivePracticeMode.Recall, AdaptivePracticeMode.Spelling)
        };
        AdaptiveMasteryObservation[] evidence =
        {
            Obs("oxford", "a", AdaptiveTargetKind.Lexical, AdaptiveEvidenceChannel.Spelling, 2, 1, 1, 0, 1, now.AddDays(-1), "spelling"),
            Obs("oxford", "b", AdaptiveTargetKind.Lexical, AdaptiveEvidenceChannel.Spelling, 2, 1, 1, 0, 1, now.AddDays(-1), "spelling")
        };
        AdaptiveMasteryRouter router = new();
        AdaptiveRoutingDecision first = router.RouteNext(candidates, evidence, now)!;
        AdaptiveRoutingDecision second = router.RouteNext(candidates.Reverse(), evidence.Reverse(), now)!;
        Require(first == second, "Adaptive routing must be deterministic regardless of input enumeration order.");
    }

    private static void StudyPoolSizesAreExactAndBounded()
    {
        DateTimeOffset now = DateTimeOffset.Parse("2026-08-27T07:00:00Z");
        AdaptivePracticeCandidate[] candidates = Enumerable.Range(0, 250)
            .Select(i => Lexical("oxford", $"pool-{i:D4}", AdaptivePracticeMode.Recall))
            .ToArray();
        AdaptiveMasteryRouter router = new();
        Require(router.Plan(candidates, Array.Empty<AdaptiveMasteryObservation>(), now, AdaptiveStudyPoolSize.Thirty).Count == 30, "30-target adaptive pool is not exact.");
        Require(router.Plan(candidates, Array.Empty<AdaptiveMasteryObservation>(), now, AdaptiveStudyPoolSize.Hundred).Count == 100, "100-target adaptive pool is not exact.");
        Require(router.Plan(candidates, Array.Empty<AdaptiveMasteryObservation>(), now, AdaptiveStudyPoolSize.TwoHundred).Count == 200, "200-target adaptive pool is not exact.");
        Require(router.Plan(candidates, Array.Empty<AdaptiveMasteryObservation>(), now, AdaptiveStudyPoolSize.Full).Count == 250, "Full adaptive pool must preserve the supplied eligible universe.");
    }

    private static void PolicySeamConstrainsModesWithoutCompletionRules()
    {
        DateTimeOffset now = DateTimeOffset.Parse("2026-08-27T07:00:00Z");
        AdaptivePracticeCandidate candidate = Lexical("oxford", "policy-word", AdaptivePracticeMode.Recall, AdaptivePracticeMode.Spelling);
        AdaptiveMasteryObservation weakSpelling = Obs(
            "oxford", "policy-word", AdaptiveTargetKind.Lexical, AdaptiveEvidenceChannel.Spelling,
            4, 1, 3, 0, 0, now.AddDays(-2), "spelling");
        var options = new AdaptiveRoutingPlanOptions(
            AdaptiveStudyPoolSize.Full,
            new HashSet<AdaptivePracticeMode> { AdaptivePracticeMode.Recall },
            "external-fast-or-deep-policy");
        AdaptiveRoutingDecision decision = new AdaptiveMasteryRouter().Plan(new[] { candidate }, new[] { weakSpelling }, now, options).Single();
        Require(decision.NextMode == AdaptivePracticeMode.Recall,
            "Caller-owned policy seam must constrain eligible modes without the router inventing a completion threshold.");
        Require(decision.EvidenceStatus == AdaptiveEvidenceStatus.Missing,
            "Policy filtering must not rewrite missing Recall evidence into mastery.");
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

    private static void LearningEvidenceDictionaryMismatchFailsClosed()
    {
        var source = new FakeEvidenceSource(new LearningEvidenceRecord(
            "other-dictionary", "word", "spelling", 1, 1, 0, 0, 1, DateTimeOffset.UtcNow));
        bool failed = false;
        try
        {
            _ = AdaptiveEvidenceAdapters.FromLearningEvidence(source, "oxford");
        }
        catch (InvalidDataException)
        {
            failed = true;
        }
        Require(failed, "Evidence from another dictionary must never leak into the requested stable-ID namespace.");
    }

    private static void FullOxfordScalePlanIsCompleteAndUnique()
    {
        const int OxfordUniverse = 5446;
        DateTimeOffset now = DateTimeOffset.Parse("2026-08-27T07:00:00Z");
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
        string dictionaryId,
        string targetId,
        AdaptiveTargetKind targetKind,
        AdaptiveEvidenceChannel channel,
        int completed,
        int? successes,
        int wrong,
        int hints,
        int streak,
        DateTimeOffset? last,
        string source) =>
        new(dictionaryId, targetId, targetKind, channel, completed, successes, wrong, hints, streak, last, source);

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
