namespace WordDeck;

internal enum AdaptiveTargetKind
{
    Lexical,
    GrammarSkill
}

internal enum AdaptiveEvidenceChannel
{
    MeaningRecall,
    Spelling,
    SentenceForm,
    Grammar,
    Listening,
    NarrativeContext,
    ReadingContext
}

internal enum AdaptivePracticeMode
{
    Recall,
    Spelling,
    Sentence,
    Grammar,
    Listening,
    Story,
    Reading
}

internal enum AdaptiveStudyPoolSize
{
    Thirty,
    Hundred,
    TwoHundred,
    Full
}

internal enum AdaptiveEvidenceStatus
{
    Missing,
    ExposureOnly,
    Scored
}

/// <summary>
/// Normalized evidence consumed by the global router. A null FirstTrySuccesses
/// value is deliberately not a score: it can prove exposure, recency and hint
/// dependence, but it cannot prove mastery.
/// </summary>
internal sealed record AdaptiveMasteryObservation(
    string DictionaryId,
    string TargetId,
    AdaptiveTargetKind TargetKind,
    AdaptiveEvidenceChannel Channel,
    int CompletedReviews,
    int? FirstTrySuccesses,
    int WrongAttempts,
    int HintUses,
    int CurrentStreak,
    DateTimeOffset? LastReviewedUtc,
    string SourceId);

internal sealed record AdaptivePracticeCandidate(
    string DictionaryId,
    string TargetId,
    AdaptiveTargetKind TargetKind,
    IReadOnlySet<AdaptivePracticeMode> AvailableModes,
    bool IsHidden = false);

/// <summary>
/// Caller-owned routing constraints. A pedagogical layer such as Fast Track or
/// Deep Practice may later choose a pool and allowed modes without teaching this
/// router any course-completion rule.
/// </summary>
internal sealed record AdaptiveRoutingPlanOptions(
    AdaptiveStudyPoolSize PoolSize,
    IReadOnlySet<AdaptivePracticeMode>? AllowedModes = null,
    string? PolicyId = null);

internal sealed record AdaptiveChannelSnapshot(
    string DictionaryId,
    string TargetId,
    AdaptiveTargetKind TargetKind,
    AdaptiveEvidenceChannel Channel,
    AdaptivePracticeMode Mode,
    int CompletedReviews,
    int ExposureReviews,
    int OutcomeReviews,
    int FirstTrySuccesses,
    int WrongAttempts,
    int HintUses,
    int CurrentStreak,
    DateTimeOffset? LastReviewedUtc,
    double? Mastery,
    double Urgency,
    double DueIntervalHours,
    AdaptiveEvidenceStatus EvidenceStatus,
    bool HasDirectNeed);

internal sealed record AdaptiveRoutingDecision(
    string DictionaryId,
    string TargetId,
    AdaptiveTargetKind TargetKind,
    AdaptiveEvidenceChannel WeakestChannel,
    AdaptivePracticeMode NextMode,
    double? Mastery,
    double Urgency,
    double DueIntervalHours,
    AdaptiveEvidenceStatus EvidenceStatus,
    bool HasDirectNeed,
    string Explanation);

/// <summary>
/// Deterministic/statistical cross-mode router. It never mutates canonical
/// progress, never guesses lexical identity from display text, never treats an
/// exposure/reveal as mastery, and never selects a hidden or unavailable target.
/// </summary>
internal sealed class AdaptiveMasteryRouter
{
    private sealed class Aggregate
    {
        public int Reviews;
        public int OutcomeReviews;
        public int Successes;
        public int Wrong;
        public int Hints;
        public int OutcomeHints;
        public int Streak;
        public DateTimeOffset? LastReviewedUtc;
    }

    private readonly record struct TargetKey(string DictionaryId, string TargetId, AdaptiveTargetKind Kind);
    private readonly record struct ChannelKey(TargetKey Target, AdaptiveEvidenceChannel Channel);

    private static readonly AdaptiveEvidenceChannel[] AllChannels =
    {
        AdaptiveEvidenceChannel.MeaningRecall,
        AdaptiveEvidenceChannel.Spelling,
        AdaptiveEvidenceChannel.SentenceForm,
        AdaptiveEvidenceChannel.Grammar,
        AdaptiveEvidenceChannel.Listening,
        AdaptiveEvidenceChannel.NarrativeContext,
        AdaptiveEvidenceChannel.ReadingContext
    };

    public AdaptiveRoutingDecision? RouteNext(
        IEnumerable<AdaptivePracticeCandidate> candidates,
        IEnumerable<AdaptiveMasteryObservation> observations,
        DateTimeOffset nowUtc)
    {
        List<AdaptiveRoutingDecision> decisions = Plan(
            candidates,
            observations,
            nowUtc,
            new AdaptiveRoutingPlanOptions(AdaptiveStudyPoolSize.Full));
        return decisions.Count == 0 ? null : decisions[0];
    }

    public List<AdaptiveRoutingDecision> Plan(
        IEnumerable<AdaptivePracticeCandidate> candidates,
        IEnumerable<AdaptiveMasteryObservation> observations,
        DateTimeOffset nowUtc,
        AdaptiveStudyPoolSize poolSize) =>
        Plan(candidates, observations, nowUtc, new AdaptiveRoutingPlanOptions(poolSize));

    public List<AdaptiveRoutingDecision> Plan(
        IEnumerable<AdaptivePracticeCandidate> candidates,
        IEnumerable<AdaptiveMasteryObservation> observations,
        DateTimeOffset nowUtc,
        AdaptiveRoutingPlanOptions options)
    {
        ArgumentNullException.ThrowIfNull(candidates);
        ArgumentNullException.ThrowIfNull(observations);
        ArgumentNullException.ThrowIfNull(options);
        if (options.PolicyId is not null &&
            (string.IsNullOrWhiteSpace(options.PolicyId) || !string.Equals(options.PolicyId, options.PolicyId.Trim(), StringComparison.Ordinal)))
            throw new InvalidDataException("Adaptive policy identity must be null or non-blank canonical text.");

        Dictionary<ChannelKey, Aggregate> index = BuildIndex(observations);
        var uniqueCandidates = new Dictionary<TargetKey, AdaptivePracticeCandidate>();
        foreach (AdaptivePracticeCandidate candidate in candidates)
        {
            ValidateCandidate(candidate);
            var key = new TargetKey(candidate.DictionaryId, candidate.TargetId, candidate.TargetKind);
            if (uniqueCandidates.TryGetValue(key, out AdaptivePracticeCandidate? existing))
            {
                if (existing.IsHidden != candidate.IsHidden || !existing.AvailableModes.SetEquals(candidate.AvailableModes))
                    throw new InvalidDataException($"Adaptive candidate {candidate.TargetId} has conflicting eligibility contracts.");
                continue;
            }
            uniqueCandidates[key] = candidate;
        }

        var decisions = new List<AdaptiveRoutingDecision>(uniqueCandidates.Count);
        foreach ((TargetKey key, AdaptivePracticeCandidate candidate) in uniqueCandidates)
        {
            if (candidate.IsHidden) continue;

            AdaptiveChannelSnapshot? weakest = null;
            foreach (AdaptiveEvidenceChannel channel in AllChannels)
            {
                AdaptivePracticeMode mode = ModeFor(channel);
                if (!candidate.AvailableModes.Contains(mode)) continue;
                if (options.AllowedModes is not null && !options.AllowedModes.Contains(mode)) continue;

                index.TryGetValue(new ChannelKey(key, channel), out Aggregate? aggregate);
                AdaptiveChannelSnapshot snapshot = BuildSnapshot(key, channel, mode, aggregate, nowUtc);
                if (weakest is null || IsHigherPriority(snapshot, weakest, key.Kind))
                    weakest = snapshot;
            }

            if (weakest is not null)
                decisions.Add(ToDecision(weakest));
        }

        decisions.Sort(CompareDecisions);
        int limit = PoolLimit(options.PoolSize);
        if (decisions.Count > limit)
            decisions.RemoveRange(limit, decisions.Count - limit);
        return decisions;
    }

    public AdaptiveChannelSnapshot Snapshot(
        AdaptivePracticeCandidate candidate,
        AdaptiveEvidenceChannel channel,
        IEnumerable<AdaptiveMasteryObservation> observations,
        DateTimeOffset nowUtc)
    {
        ValidateCandidate(candidate);
        if (candidate.IsHidden)
            throw new InvalidOperationException($"Hidden adaptive target {candidate.TargetId} is not eligible for a study snapshot.");
        AdaptivePracticeMode mode = ModeFor(channel);
        if (!candidate.AvailableModes.Contains(mode))
            throw new InvalidOperationException($"Mode {mode} is not available for adaptive target {candidate.TargetId}.");
        Dictionary<ChannelKey, Aggregate> index = BuildIndex(observations);
        var key = new TargetKey(candidate.DictionaryId, candidate.TargetId, candidate.TargetKind);
        index.TryGetValue(new ChannelKey(key, channel), out Aggregate? aggregate);
        return BuildSnapshot(key, channel, mode, aggregate, nowUtc);
    }

    private static Dictionary<ChannelKey, Aggregate> BuildIndex(IEnumerable<AdaptiveMasteryObservation> observations)
    {
        var index = new Dictionary<ChannelKey, Aggregate>();
        foreach (AdaptiveMasteryObservation observation in observations)
        {
            ValidateObservation(observation);
            var target = new TargetKey(observation.DictionaryId, observation.TargetId, observation.TargetKind);
            var key = new ChannelKey(target, observation.Channel);
            if (!index.TryGetValue(key, out Aggregate? aggregate))
            {
                aggregate = new Aggregate();
                index[key] = aggregate;
            }

            aggregate.Reviews = checked(aggregate.Reviews + observation.CompletedReviews);
            if (observation.FirstTrySuccesses.HasValue)
            {
                aggregate.OutcomeReviews = checked(aggregate.OutcomeReviews + observation.CompletedReviews);
                aggregate.Successes = checked(aggregate.Successes + observation.FirstTrySuccesses.Value);
                aggregate.OutcomeHints = checked(aggregate.OutcomeHints + observation.HintUses);
            }
            aggregate.Wrong = checked(aggregate.Wrong + observation.WrongAttempts);
            aggregate.Hints = checked(aggregate.Hints + observation.HintUses);
            aggregate.Streak = Math.Max(aggregate.Streak, observation.CurrentStreak);
            if (observation.LastReviewedUtc.HasValue &&
                (!aggregate.LastReviewedUtc.HasValue || observation.LastReviewedUtc.Value > aggregate.LastReviewedUtc.Value))
                aggregate.LastReviewedUtc = observation.LastReviewedUtc;
        }
        return index;
    }

    private static AdaptiveChannelSnapshot BuildSnapshot(
        TargetKey key,
        AdaptiveEvidenceChannel channel,
        AdaptivePracticeMode mode,
        Aggregate? aggregate,
        DateTimeOffset nowUtc)
    {
        int reviews = aggregate?.Reviews ?? 0;
        int outcomeReviews = aggregate?.OutcomeReviews ?? 0;
        int exposureReviews = Math.Max(0, reviews - outcomeReviews);
        int successes = aggregate?.Successes ?? 0;
        int wrong = aggregate?.Wrong ?? 0;
        int hints = aggregate?.Hints ?? 0;
        int outcomeHints = aggregate?.OutcomeHints ?? 0;
        int streak = aggregate?.Streak ?? 0;
        DateTimeOffset? last = aggregate?.LastReviewedUtc;

        AdaptiveEvidenceStatus status = outcomeReviews > 0
            ? AdaptiveEvidenceStatus.Scored
            : reviews > 0
                ? AdaptiveEvidenceStatus.ExposureOnly
                : AdaptiveEvidenceStatus.Missing;

        double? mastery = status == AdaptiveEvidenceStatus.Scored
            ? CalculateScoredMastery(outcomeReviews, successes, wrong, outcomeHints, streak)
            : null;
        double dueHours = DueIntervalHours(status, outcomeReviews, mastery);
        double duePressure = CalculateDuePressure(last, dueHours, nowUtc);
        double errorRate = outcomeReviews <= 0 ? 0 : Math.Clamp((double)wrong / Math.Max(1, outcomeReviews + wrong), 0, 1);
        double totalHintRate = reviews <= 0 ? 0 : Math.Clamp((double)hints / Math.Max(1, reviews), 0, 1);
        double scoredHintRate = outcomeReviews <= 0 ? 0 : Math.Clamp((double)outcomeHints / Math.Max(1, outcomeReviews), 0, 1);

        bool scoredWeakness = outcomeReviews > 0 &&
            (successes < outcomeReviews || wrong > 0 || outcomeHints > 0);
        bool revealDependence = status == AdaptiveEvidenceStatus.ExposureOnly && hints > 0;
        bool directNeed = scoredWeakness || revealDependence;

        double urgency = status switch
        {
            AdaptiveEvidenceStatus.Missing => 70,
            AdaptiveEvidenceStatus.ExposureOnly => 50 + duePressure * 20 + totalHintRate * 20,
            AdaptiveEvidenceStatus.Scored =>
                (1 - mastery!.Value) * 60 +
                duePressure * 25 +
                errorRate * 20 +
                scoredHintRate * 15,
            _ => throw new ArgumentOutOfRangeException()
        };

        return new AdaptiveChannelSnapshot(
            key.DictionaryId,
            key.TargetId,
            key.Kind,
            channel,
            mode,
            reviews,
            exposureReviews,
            outcomeReviews,
            successes,
            wrong,
            hints,
            streak,
            last,
            mastery.HasValue ? Math.Round(mastery.Value, 6) : null,
            Math.Round(urgency, 6),
            dueHours,
            status,
            directNeed);
    }

    private static double CalculateScoredMastery(
        int outcomeReviews,
        int successes,
        int wrong,
        int outcomeHints,
        int streak)
    {
        if (outcomeReviews <= 0)
            throw new InvalidOperationException("Scored mastery requires scored outcome reviews.");
        double confidence = Math.Min(1, outcomeReviews / 5.0);
        double cleanRate = Math.Clamp((double)successes / outcomeReviews, 0, 1);
        double errorRate = Math.Clamp((double)wrong / Math.Max(1, outcomeReviews + wrong), 0, 1);
        double hintRate = Math.Clamp((double)outcomeHints / outcomeReviews, 0, 1);
        double streakBoost = Math.Min(streak, 5) / 5.0 * 0.10;
        double raw = 0.15 + cleanRate * 0.70 + streakBoost - hintRate * 0.20 - errorRate * 0.15;
        return Math.Clamp(raw * (0.45 + confidence * 0.55), 0, 1);
    }

    private static double DueIntervalHours(AdaptiveEvidenceStatus status, int outcomeReviews, double? mastery)
    {
        if (status == AdaptiveEvidenceStatus.Missing) return 0;
        if (status == AdaptiveEvidenceStatus.ExposureOnly) return 4;
        if (outcomeReviews <= 0 || !mastery.HasValue) return 0;
        if (mastery.Value < 0.30) return 4;
        if (mastery.Value < 0.50) return 12;
        if (mastery.Value < 0.70) return 48;
        if (mastery.Value < 0.85) return 120;
        return 336;
    }

    private static double CalculateDuePressure(DateTimeOffset? lastReviewedUtc, double dueHours, DateTimeOffset nowUtc)
    {
        if (!lastReviewedUtc.HasValue || dueHours <= 0) return 1.5;
        double elapsedHours = Math.Max(0, (nowUtc - lastReviewedUtc.Value).TotalHours);
        return Math.Clamp(elapsedHours / dueHours, 0, 2);
    }

    private static bool IsHigherPriority(AdaptiveChannelSnapshot candidate, AdaptiveChannelSnapshot current, AdaptiveTargetKind kind)
    {
        if (candidate.HasDirectNeed != current.HasDirectNeed)
            return candidate.HasDirectNeed;
        int urgency = candidate.Urgency.CompareTo(current.Urgency);
        if (urgency != 0) return urgency > 0;
        int mastery = CompareMastery(candidate.Mastery, current.Mastery);
        if (mastery != 0) return mastery < 0;
        int evidence = candidate.EvidenceStatus.CompareTo(current.EvidenceStatus);
        if (evidence != 0) return evidence < 0;
        return ChannelPriority(kind, candidate.Channel) < ChannelPriority(kind, current.Channel);
    }

    private static int CompareDecisions(AdaptiveRoutingDecision left, AdaptiveRoutingDecision right)
    {
        if (left.HasDirectNeed != right.HasDirectNeed)
            return left.HasDirectNeed ? -1 : 1;
        int urgency = right.Urgency.CompareTo(left.Urgency);
        if (urgency != 0) return urgency;
        int mastery = CompareMastery(left.Mastery, right.Mastery);
        if (mastery != 0) return mastery;
        int evidence = left.EvidenceStatus.CompareTo(right.EvidenceStatus);
        if (evidence != 0) return evidence;
        int dictionary = string.Compare(left.DictionaryId, right.DictionaryId, StringComparison.Ordinal);
        if (dictionary != 0) return dictionary;
        int target = string.Compare(left.TargetId, right.TargetId, StringComparison.Ordinal);
        if (target != 0) return target;
        return left.NextMode.CompareTo(right.NextMode);
    }

    private static int CompareMastery(double? left, double? right)
    {
        if (left.HasValue && right.HasValue) return left.Value.CompareTo(right.Value);
        if (left.HasValue) return 1;
        if (right.HasValue) return -1;
        return 0;
    }

    private static AdaptiveRoutingDecision ToDecision(AdaptiveChannelSnapshot snapshot)
    {
        string quality = snapshot.EvidenceStatus switch
        {
            AdaptiveEvidenceStatus.Missing => "no evidence exists; mastery remains unknown",
            AdaptiveEvidenceStatus.ExposureOnly =>
                $"exposure-only evidence {snapshot.ExposureReviews} reviews, hints/reveals {snapshot.HintUses}; mastery remains unknown",
            AdaptiveEvidenceStatus.Scored =>
                $"scored first-try {snapshot.FirstTrySuccesses}/{snapshot.OutcomeReviews}, wrong attempts {snapshot.WrongAttempts}, scored mastery {snapshot.Mastery!.Value:P0}",
            _ => throw new ArgumentOutOfRangeException()
        };
        string due = snapshot.LastReviewedUtc.HasValue
            ? $"last evidence {snapshot.LastReviewedUtc.Value:O}, review interval {snapshot.DueIntervalHours:0.#}h"
            : "no prior timestamp";
        string reason = snapshot.HasDirectNeed
            ? "direct evidence of error/hint/reveal dependence takes priority over merely missing channels"
            : "highest-priority eligible channel under deterministic evidence/recency ordering";
        return new AdaptiveRoutingDecision(
            snapshot.DictionaryId,
            snapshot.TargetId,
            snapshot.TargetKind,
            snapshot.Channel,
            snapshot.Mode,
            snapshot.Mastery,
            snapshot.Urgency,
            snapshot.DueIntervalHours,
            snapshot.EvidenceStatus,
            snapshot.HasDirectNeed,
            $"Route to {snapshot.Mode}: {reason}; {quality}; {due}.");
    }

    private static AdaptivePracticeMode ModeFor(AdaptiveEvidenceChannel channel) => channel switch
    {
        AdaptiveEvidenceChannel.MeaningRecall => AdaptivePracticeMode.Recall,
        AdaptiveEvidenceChannel.Spelling => AdaptivePracticeMode.Spelling,
        AdaptiveEvidenceChannel.SentenceForm => AdaptivePracticeMode.Sentence,
        AdaptiveEvidenceChannel.Grammar => AdaptivePracticeMode.Grammar,
        AdaptiveEvidenceChannel.Listening => AdaptivePracticeMode.Listening,
        AdaptiveEvidenceChannel.NarrativeContext => AdaptivePracticeMode.Story,
        AdaptiveEvidenceChannel.ReadingContext => AdaptivePracticeMode.Reading,
        _ => throw new ArgumentOutOfRangeException(nameof(channel))
    };

    private static int ChannelPriority(AdaptiveTargetKind kind, AdaptiveEvidenceChannel channel)
    {
        if (kind == AdaptiveTargetKind.GrammarSkill && channel == AdaptiveEvidenceChannel.Grammar) return 0;
        return channel switch
        {
            AdaptiveEvidenceChannel.MeaningRecall => 1,
            AdaptiveEvidenceChannel.Spelling => 2,
            AdaptiveEvidenceChannel.SentenceForm => 3,
            AdaptiveEvidenceChannel.Grammar => 4,
            AdaptiveEvidenceChannel.Listening => 5,
            AdaptiveEvidenceChannel.NarrativeContext => 6,
            AdaptiveEvidenceChannel.ReadingContext => 7,
            _ => 99
        };
    }

    private static int PoolLimit(AdaptiveStudyPoolSize poolSize) => poolSize switch
    {
        AdaptiveStudyPoolSize.Thirty => 30,
        AdaptiveStudyPoolSize.Hundred => 100,
        AdaptiveStudyPoolSize.TwoHundred => 200,
        AdaptiveStudyPoolSize.Full => int.MaxValue,
        _ => throw new ArgumentOutOfRangeException(nameof(poolSize))
    };

    private static void ValidateCandidate(AdaptivePracticeCandidate candidate)
    {
        ArgumentNullException.ThrowIfNull(candidate);
        RequireIdentity(candidate.DictionaryId, "dictionary");
        RequireIdentity(candidate.TargetId, "target");
        if (candidate.AvailableModes is null || candidate.AvailableModes.Count == 0)
            throw new InvalidDataException($"Adaptive target {candidate.TargetId} has no available practice mode.");
    }

    private static void ValidateObservation(AdaptiveMasteryObservation observation)
    {
        ArgumentNullException.ThrowIfNull(observation);
        RequireIdentity(observation.DictionaryId, "evidence dictionary");
        RequireIdentity(observation.TargetId, "evidence target");
        RequireIdentity(observation.SourceId, "evidence source");
        if (observation.CompletedReviews < 0 || observation.WrongAttempts < 0 || observation.HintUses < 0 || observation.CurrentStreak < 0)
            throw new InvalidDataException($"Adaptive evidence for {observation.TargetId} contains negative counters.");
        if (observation.FirstTrySuccesses is int successes && (successes < 0 || successes > observation.CompletedReviews))
            throw new InvalidDataException($"Adaptive evidence for {observation.TargetId} has impossible first-try success counts.");
        if (observation.FirstTrySuccesses is null && (observation.WrongAttempts != 0 || observation.CurrentStreak != 0))
            throw new InvalidDataException($"Unscored evidence for {observation.TargetId} cannot carry scored wrong/streak counters.");
        if (observation.CurrentStreak > observation.CompletedReviews)
            throw new InvalidDataException($"Adaptive evidence for {observation.TargetId} has a streak larger than completed reviews.");
    }

    private static void RequireIdentity(string? value, string label)
    {
        if (string.IsNullOrWhiteSpace(value) || !string.Equals(value, value.Trim(), StringComparison.Ordinal))
            throw new InvalidDataException($"Adaptive {label} identity must be non-blank canonical text.");
    }
}

internal static class AdaptiveCandidateFactory
{
    public static IReadOnlyList<AdaptivePracticeCandidate> FromLexicalTargets(
        AppState state,
        string dictionaryId,
        IEnumerable<string> targetIds,
        IReadOnlySet<AdaptivePracticeMode> availableModes)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(targetIds);
        ArgumentNullException.ThrowIfNull(availableModes);
        if (string.IsNullOrWhiteSpace(dictionaryId) || !string.Equals(dictionaryId, dictionaryId.Trim(), StringComparison.Ordinal))
            throw new InvalidDataException("Adaptive candidate dictionary identity must be non-blank canonical text.");
        if (availableModes.Count == 0)
            throw new InvalidDataException("Adaptive lexical candidates require at least one available mode.");

        var seen = new HashSet<string>(StringComparer.Ordinal);
        var hidden = new HashSet<string>(state.HiddenEntryIds ?? new HashSet<string>(), StringComparer.OrdinalIgnoreCase);
        var result = new List<AdaptivePracticeCandidate>();
        foreach (string targetId in targetIds)
        {
            if (string.IsNullOrWhiteSpace(targetId) || !string.Equals(targetId, targetId.Trim(), StringComparison.Ordinal))
                throw new InvalidDataException("Adaptive target identity must be non-blank canonical text.");
            if (!seen.Add(targetId)) continue;
            result.Add(new AdaptivePracticeCandidate(
                dictionaryId,
                targetId,
                AdaptiveTargetKind.Lexical,
                new HashSet<AdaptivePracticeMode>(availableModes),
                hidden.Contains(targetId)));
        }
        return result;
    }
}

internal static class AdaptiveEvidenceAdapters
{
    public static IReadOnlyList<AdaptiveMasteryObservation> FromLearningEvidence(
        ILearningEvidenceSource source,
        string dictionaryId,
        IEnumerable<string>? hiddenEntryIds = null)
    {
        ArgumentNullException.ThrowIfNull(source);
        var hidden = new HashSet<string>(hiddenEntryIds ?? Array.Empty<string>(), StringComparer.OrdinalIgnoreCase);
        var result = new List<AdaptiveMasteryObservation>();
        foreach (LearningEvidenceRecord record in source.Snapshot(dictionaryId))
        {
            if (!string.Equals(record.DictionaryId, dictionaryId, StringComparison.Ordinal))
                throw new InvalidDataException($"Learning evidence returned dictionary '{record.DictionaryId}' while '{dictionaryId}' was requested.");
            if (hidden.Contains(record.EntryId)) continue;
            result.Add(Convert(record));
        }
        return result;
    }

    public static IReadOnlyList<AdaptiveMasteryObservation> FromRecall(
        AppState state,
        string dictionaryId,
        IEnumerable<string> knownEntryIds)
    {
        ArgumentNullException.ThrowIfNull(state);
        var known = new HashSet<string>(knownEntryIds ?? Array.Empty<string>(), StringComparer.OrdinalIgnoreCase);
        var hidden = new HashSet<string>(state.HiddenEntryIds ?? new HashSet<string>(), StringComparer.OrdinalIgnoreCase);
        var result = new List<AdaptiveMasteryObservation>();
        foreach ((string entryId, WordStudyHistory history) in state.StudyHistoryByEntryId.OrderBy(pair => pair.Key, StringComparer.Ordinal))
        {
            if (!known.Contains(entryId) || hidden.Contains(entryId) || history is null) continue;
            int seen = Math.Max(0, history.SeenCount);
            int reveals = Math.Clamp(history.TranslationRevealCount, 0, seen);
            result.Add(new AdaptiveMasteryObservation(
                dictionaryId,
                entryId,
                AdaptiveTargetKind.Lexical,
                AdaptiveEvidenceChannel.MeaningRecall,
                seen,
                FirstTrySuccesses: null,
                WrongAttempts: 0,
                HintUses: reveals,
                CurrentStreak: 0,
                history.LastSeenUtc,
                "recall-history"));
        }
        return result;
    }

    public static IReadOnlyList<AdaptiveMasteryObservation> FromSentence(
        SentenceCoachState state,
        string dictionaryId,
        IEnumerable<string> knownEntryIds,
        IEnumerable<string>? hiddenEntryIds = null)
    {
        ArgumentNullException.ThrowIfNull(state);
        var known = new HashSet<string>(knownEntryIds ?? Array.Empty<string>(), StringComparer.OrdinalIgnoreCase);
        var hidden = new HashSet<string>(hiddenEntryIds ?? Array.Empty<string>(), StringComparer.OrdinalIgnoreCase);
        if (!state.StatsByDictionary.TryGetValue(dictionaryId, out Dictionary<string, SentenceTargetStats>? stats))
            return Array.Empty<AdaptiveMasteryObservation>();

        var result = new List<AdaptiveMasteryObservation>();
        foreach ((string entryId, SentenceTargetStats value) in stats.OrderBy(pair => pair.Key, StringComparer.Ordinal))
        {
            if (!known.Contains(entryId))
                throw new InvalidDataException($"Sentence adaptive evidence references unknown stable target {entryId}.");
            if (hidden.Contains(entryId)) continue;
            if (value is null) throw new InvalidDataException($"Sentence adaptive evidence for {entryId} is missing.");
            int reviews = Math.Max(0, value.CompletedReviews);
            int successes = Math.Clamp(value.FirstTrySuccesses, 0, reviews);
            result.Add(new AdaptiveMasteryObservation(
                dictionaryId,
                entryId,
                AdaptiveTargetKind.Lexical,
                AdaptiveEvidenceChannel.SentenceForm,
                reviews,
                successes,
                Math.Max(0, value.WrongAttempts),
                Math.Max(0, value.ShowAnswerUses),
                CurrentStreak: 0,
                value.LastReviewedUtc,
                "sentence-spelling"));
        }
        return result;
    }

    private static AdaptiveMasteryObservation Convert(LearningEvidenceRecord record)
    {
        (AdaptiveEvidenceChannel channel, string sourceId) = record.ModeId.ToLowerInvariant() switch
        {
            "recall" => (AdaptiveEvidenceChannel.MeaningRecall, "recall"),
            "spelling" => (AdaptiveEvidenceChannel.Spelling, "spelling"),
            "sentence" or "sentence-spelling" => (AdaptiveEvidenceChannel.SentenceForm, record.ModeId),
            "grammar" => (AdaptiveEvidenceChannel.Grammar, "grammar"),
            "listening" or "dictation" => (AdaptiveEvidenceChannel.Listening, record.ModeId),
            "story" => (AdaptiveEvidenceChannel.NarrativeContext, "story"),
            "reading" => (AdaptiveEvidenceChannel.ReadingContext, "reading"),
            _ => throw new InvalidDataException($"Unknown learning-evidence mode '{record.ModeId}'. Adaptive routing fails closed instead of guessing a channel.")
        };

        int completed = Math.Max(0, record.CompletedReviews);
        return new AdaptiveMasteryObservation(
            record.DictionaryId,
            record.EntryId,
            AdaptiveTargetKind.Lexical,
            channel,
            completed,
            Math.Clamp(record.FirstTrySuccesses, 0, completed),
            Math.Max(0, record.WrongAttempts),
            Math.Max(0, record.HintUses),
            Math.Clamp(record.CurrentStreak, 0, completed),
            record.LastReviewedUtc,
            sourceId);
    }
}
