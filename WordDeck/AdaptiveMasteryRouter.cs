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

/// <summary>
/// Normalized, platform-neutral evidence consumed by the Stage 19 router.
/// A null FirstTrySuccesses value means that the producer can prove exposure,
/// recency and hint dependence but cannot truthfully claim correctness. Recall
/// currently uses that conservative form because revealing/viewing a card is not
/// itself a scored answer.
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
    IReadOnlySet<AdaptivePracticeMode> AvailableModes);

internal sealed record AdaptiveChannelSnapshot(
    string DictionaryId,
    string TargetId,
    AdaptiveTargetKind TargetKind,
    AdaptiveEvidenceChannel Channel,
    AdaptivePracticeMode Mode,
    int CompletedReviews,
    int OutcomeReviews,
    int FirstTrySuccesses,
    int WrongAttempts,
    int HintUses,
    int CurrentStreak,
    DateTimeOffset? LastReviewedUtc,
    double Mastery,
    double Urgency,
    double DueIntervalHours,
    bool HasOutcomeEvidence);

internal sealed record AdaptiveRoutingDecision(
    string DictionaryId,
    string TargetId,
    AdaptiveTargetKind TargetKind,
    AdaptiveEvidenceChannel WeakestChannel,
    AdaptivePracticeMode NextMode,
    double Mastery,
    double Urgency,
    double DueIntervalHours,
    string Explanation);

/// <summary>
/// Deterministic/statistical Stage 19 router. It never mutates canonical
/// progress, never guesses lexical identity from surface text, and never routes
/// into a mode the caller has not explicitly declared available.
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
        List<AdaptiveRoutingDecision> decisions = Plan(candidates, observations, nowUtc, AdaptiveStudyPoolSize.Full);
        return decisions.Count == 0 ? null : decisions[0];
    }

    public List<AdaptiveRoutingDecision> Plan(
        IEnumerable<AdaptivePracticeCandidate> candidates,
        IEnumerable<AdaptiveMasteryObservation> observations,
        DateTimeOffset nowUtc,
        AdaptiveStudyPoolSize poolSize)
    {
        if (candidates is null) throw new ArgumentNullException(nameof(candidates));
        if (observations is null) throw new ArgumentNullException(nameof(observations));

        Dictionary<ChannelKey, Aggregate> index = BuildIndex(observations);
        var uniqueCandidates = new Dictionary<TargetKey, AdaptivePracticeCandidate>();
        foreach (AdaptivePracticeCandidate candidate in candidates)
        {
            ValidateCandidate(candidate);
            var key = new TargetKey(candidate.DictionaryId, candidate.TargetId, candidate.TargetKind);
            if (uniqueCandidates.TryGetValue(key, out AdaptivePracticeCandidate? existing))
            {
                if (!existing.AvailableModes.SetEquals(candidate.AvailableModes))
                    throw new InvalidDataException($"Adaptive candidate {candidate.TargetId} has conflicting available-mode contracts.");
                continue;
            }
            uniqueCandidates[key] = candidate;
        }

        var decisions = new List<AdaptiveRoutingDecision>(uniqueCandidates.Count);
        foreach ((TargetKey key, AdaptivePracticeCandidate candidate) in uniqueCandidates)
        {
            AdaptiveChannelSnapshot? weakest = null;
            foreach (AdaptiveEvidenceChannel channel in AllChannels)
            {
                AdaptivePracticeMode mode = ModeFor(channel);
                if (!candidate.AvailableModes.Contains(mode)) continue;

                index.TryGetValue(new ChannelKey(key, channel), out Aggregate? aggregate);
                AdaptiveChannelSnapshot snapshot = BuildSnapshot(key, channel, mode, aggregate, nowUtc);
                if (weakest is null || IsHigherPriority(snapshot, weakest, key.Kind))
                    weakest = snapshot;
            }

            if (weakest is null) continue;
            decisions.Add(ToDecision(weakest));
        }

        decisions.Sort(CompareDecisions);
        int limit = poolSize switch
        {
            AdaptiveStudyPoolSize.Thirty => 30,
            AdaptiveStudyPoolSize.Hundred => 100,
            AdaptiveStudyPoolSize.TwoHundred => 200,
            AdaptiveStudyPoolSize.Full => int.MaxValue,
            _ => throw new ArgumentOutOfRangeException(nameof(poolSize))
        };
        if (decisions.Count > limit) decisions.RemoveRange(limit, decisions.Count - limit);
        return decisions;
    }

    public AdaptiveChannelSnapshot Snapshot(
        AdaptivePracticeCandidate candidate,
        AdaptiveEvidenceChannel channel,
        IEnumerable<AdaptiveMasteryObservation> observations,
        DateTimeOffset nowUtc)
    {
        ValidateCandidate(candidate);
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
        int successes = aggregate?.Successes ?? 0;
        int wrong = aggregate?.Wrong ?? 0;
        int hints = aggregate?.Hints ?? 0;
        int streak = aggregate?.Streak ?? 0;
        DateTimeOffset? last = aggregate?.LastReviewedUtc;

        double mastery = CalculateMastery(reviews, outcomeReviews, successes, wrong, hints, streak);
        double dueHours = DueIntervalHours(reviews, mastery);
        double duePressure = CalculateDuePressure(last, dueHours, nowUtc);
        double errorRate = outcomeReviews <= 0 ? 0 : Math.Clamp((double)wrong / Math.Max(1, outcomeReviews + wrong), 0, 1);
        double hintRate = reviews <= 0 ? 0 : Math.Clamp((double)hints / Math.Max(1, reviews), 0, 1);
        double urgency =
            (1 - mastery) * 60 +
            duePressure * 25 +
            errorRate * 20 +
            hintRate * 15 +
            (reviews == 0 ? 20 : 0) +
            (reviews > 0 && outcomeReviews == 0 ? 8 : 0);

        return new AdaptiveChannelSnapshot(
            key.DictionaryId,
            key.TargetId,
            key.Kind,
            channel,
            mode,
            reviews,
            outcomeReviews,
            successes,
            wrong,
            hints,
            streak,
            last,
            Math.Round(mastery, 6),
            Math.Round(urgency, 6),
            dueHours,
            outcomeReviews > 0);
    }

    private static double CalculateMastery(int reviews, int outcomeReviews, int successes, int wrong, int hints, int streak)
    {
        if (reviews <= 0) return 0;
        double confidence = Math.Min(1, reviews / 5.0);
        double hintRate = Math.Clamp((double)hints / Math.Max(1, reviews), 0, 1);

        if (outcomeReviews <= 0)
        {
            // Exposure-only evidence is deliberately capped. Viewing/revealing a
            // Recall card cannot by itself prove that the learner can retrieve it.
            double exposure = 0.20 + Math.Min(reviews, 6) * 0.055 - hintRate * 0.25;
            return Math.Clamp(Math.Min(0.55, exposure), 0, 0.55);
        }

        double cleanRate = Math.Clamp((double)successes / outcomeReviews, 0, 1);
        double errorRate = Math.Clamp((double)wrong / Math.Max(1, outcomeReviews + wrong), 0, 1);
        double streakBoost = Math.Min(streak, 5) / 5.0 * 0.10;
        double raw = 0.15 + cleanRate * 0.70 + streakBoost - hintRate * 0.20 - errorRate * 0.15;
        return Math.Clamp(raw * (0.45 + confidence * 0.55), 0, 1);
    }

    private static double DueIntervalHours(int reviews, double mastery)
    {
        if (reviews <= 0) return 0;
        if (mastery < 0.30) return 4;
        if (mastery < 0.50) return 12;
        if (mastery < 0.70) return 48;
        if (mastery < 0.85) return 120;
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
        int urgency = candidate.Urgency.CompareTo(current.Urgency);
        if (urgency != 0) return urgency > 0;
        int mastery = candidate.Mastery.CompareTo(current.Mastery);
        if (mastery != 0) return mastery < 0;
        return ChannelPriority(kind, candidate.Channel) < ChannelPriority(kind, current.Channel);
    }

    private static int CompareDecisions(AdaptiveRoutingDecision left, AdaptiveRoutingDecision right)
    {
        int urgency = right.Urgency.CompareTo(left.Urgency);
        if (urgency != 0) return urgency;
        int mastery = left.Mastery.CompareTo(right.Mastery);
        if (mastery != 0) return mastery;
        int dictionary = string.Compare(left.DictionaryId, right.DictionaryId, StringComparison.Ordinal);
        if (dictionary != 0) return dictionary;
        int target = string.Compare(left.TargetId, right.TargetId, StringComparison.Ordinal);
        if (target != 0) return target;
        return left.NextMode.CompareTo(right.NextMode);
    }

    private static AdaptiveRoutingDecision ToDecision(AdaptiveChannelSnapshot snapshot)
    {
        string quality = snapshot.HasOutcomeEvidence
            ? $"first-try {snapshot.FirstTrySuccesses}/{snapshot.OutcomeReviews}, wrong attempts {snapshot.WrongAttempts}, hints {snapshot.HintUses}"
            : snapshot.CompletedReviews == 0
                ? "no evidence yet"
                : $"exposure-only evidence {snapshot.CompletedReviews} reviews, hints/reveals {snapshot.HintUses}; correctness is not inferred";
        string due = snapshot.LastReviewedUtc.HasValue
            ? $"last evidence {snapshot.LastReviewedUtc.Value:O}, target interval {snapshot.DueIntervalHours:0.#}h"
            : "no prior timestamp";
        return new AdaptiveRoutingDecision(
            snapshot.DictionaryId,
            snapshot.TargetId,
            snapshot.TargetKind,
            snapshot.Channel,
            snapshot.Mode,
            snapshot.Mastery,
            snapshot.Urgency,
            snapshot.DueIntervalHours,
            $"Route to {snapshot.Mode}: {snapshot.Channel} is the highest-priority available weak channel; mastery {snapshot.Mastery:P0}; {quality}; {due}.");
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

    private static void ValidateCandidate(AdaptivePracticeCandidate candidate)
    {
        if (candidate is null) throw new ArgumentNullException(nameof(candidate));
        RequireIdentity(candidate.DictionaryId, "dictionary");
        RequireIdentity(candidate.TargetId, "target");
        if (candidate.AvailableModes is null || candidate.AvailableModes.Count == 0)
            throw new InvalidDataException($"Adaptive target {candidate.TargetId} has no available practice mode.");
    }

    private static void ValidateObservation(AdaptiveMasteryObservation observation)
    {
        if (observation is null) throw new ArgumentNullException(nameof(observation));
        RequireIdentity(observation.DictionaryId, "evidence dictionary");
        RequireIdentity(observation.TargetId, "evidence target");
        RequireIdentity(observation.SourceId, "evidence source");
        if (observation.CompletedReviews < 0 || observation.WrongAttempts < 0 || observation.HintUses < 0 || observation.CurrentStreak < 0)
            throw new InvalidDataException($"Adaptive evidence for {observation.TargetId} contains negative counters.");
        if (observation.FirstTrySuccesses is int successes && (successes < 0 || successes > observation.CompletedReviews))
            throw new InvalidDataException($"Adaptive evidence for {observation.TargetId} has impossible first-try success counts.");
        if (observation.CurrentStreak > observation.CompletedReviews)
            throw new InvalidDataException($"Adaptive evidence for {observation.TargetId} has a streak larger than completed reviews.");
    }

    private static void RequireIdentity(string? value, string label)
    {
        if (string.IsNullOrWhiteSpace(value) || !string.Equals(value, value.Trim(), StringComparison.Ordinal))
            throw new InvalidDataException($"Adaptive {label} identity must be non-blank canonical text.");
    }
}

internal static class AdaptiveEvidenceAdapters
{
    public static IReadOnlyList<AdaptiveMasteryObservation> FromLearningEvidence(
        ILearningEvidenceSource source,
        string dictionaryId)
    {
        if (source is null) throw new ArgumentNullException(nameof(source));
        return source.Snapshot(dictionaryId).Select(Convert).ToArray();
    }

    public static IReadOnlyList<AdaptiveMasteryObservation> FromRecall(
        AppState state,
        string dictionaryId,
        IEnumerable<string> knownEntryIds)
    {
        if (state is null) throw new ArgumentNullException(nameof(state));
        var known = new HashSet<string>(knownEntryIds ?? Array.Empty<string>(), StringComparer.OrdinalIgnoreCase);
        var result = new List<AdaptiveMasteryObservation>();
        foreach ((string entryId, WordStudyHistory history) in state.StudyHistoryByEntryId.OrderBy(pair => pair.Key, StringComparer.Ordinal))
        {
            if (!known.Contains(entryId) || history is null) continue;
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
        IEnumerable<string> knownEntryIds)
    {
        if (state is null) throw new ArgumentNullException(nameof(state));
        var known = new HashSet<string>(knownEntryIds ?? Array.Empty<string>(), StringComparer.OrdinalIgnoreCase);
        if (!state.StatsByDictionary.TryGetValue(dictionaryId, out Dictionary<string, SentenceTargetStats>? stats))
            return Array.Empty<AdaptiveMasteryObservation>();

        var result = new List<AdaptiveMasteryObservation>();
        foreach ((string entryId, SentenceTargetStats value) in stats.OrderBy(pair => pair.Key, StringComparer.Ordinal))
        {
            if (!known.Contains(entryId))
                throw new InvalidDataException($"Sentence adaptive evidence references unknown stable target {entryId}.");
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

        return new AdaptiveMasteryObservation(
            record.DictionaryId,
            record.EntryId,
            AdaptiveTargetKind.Lexical,
            channel,
            Math.Max(0, record.CompletedReviews),
            Math.Clamp(record.FirstTrySuccesses, 0, Math.Max(0, record.CompletedReviews)),
            Math.Max(0, record.WrongAttempts),
            Math.Max(0, record.HintUses),
            Math.Clamp(record.CurrentStreak, 0, Math.Max(0, record.CompletedReviews)),
            record.LastReviewedUtc,
            sourceId);
    }
}
