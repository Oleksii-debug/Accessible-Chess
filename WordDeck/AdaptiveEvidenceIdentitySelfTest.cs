namespace WordDeck;

internal static class AdaptiveEvidenceIdentitySelfTest
{
    public static void Run()
    {
        RejectsDuplicateSameSourceSnapshot();
        AggregatesDistinctSourcesWithoutConfusingIdentity();
    }

    private static void RejectsDuplicateSameSourceSnapshot()
    {
        DateTimeOffset now = new(2026, 9, 12, 7, 0, 0, TimeSpan.Zero);
        var candidate = Candidate();
        var evidence = new AdaptiveMasteryObservation(
            "oxford",
            "stable:word:1",
            AdaptiveTargetKind.Lexical,
            AdaptiveEvidenceChannel.Spelling,
            CompletedReviews: 1,
            FirstTrySuccesses: 1,
            WrongAttempts: 0,
            HintUses: 0,
            CurrentStreak: 1,
            LastReviewedUtc: now.AddHours(-1),
            SourceId: "spelling");

        bool failedClosed = false;
        try
        {
            _ = new AdaptiveMasteryRouter().Snapshot(
                candidate,
                AdaptiveEvidenceChannel.Spelling,
                new[] { evidence, evidence },
                now);
        }
        catch (InvalidDataException ex) when (ex.Message.Contains("duplicates source", StringComparison.Ordinal))
        {
            failedClosed = true;
        }

        Require(failedClosed,
            "Repeating the same source snapshot must fail closed instead of increasing adaptive outcome count/confidence/mastery.");
    }

    private static void AggregatesDistinctSourcesWithoutConfusingIdentity()
    {
        DateTimeOffset now = new(2026, 9, 12, 7, 0, 0, TimeSpan.Zero);
        var candidate = Candidate();
        var primary = new AdaptiveMasteryObservation(
            "oxford",
            "stable:word:1",
            AdaptiveTargetKind.Lexical,
            AdaptiveEvidenceChannel.Spelling,
            CompletedReviews: 1,
            FirstTrySuccesses: 1,
            WrongAttempts: 0,
            HintUses: 0,
            CurrentStreak: 1,
            LastReviewedUtc: now.AddHours(-2),
            SourceId: "spelling-primary");
        var secondary = primary with
        {
            SourceId = "spelling-secondary",
            LastReviewedUtc = now.AddHours(-1)
        };

        AdaptiveChannelSnapshot snapshot = new AdaptiveMasteryRouter().Snapshot(
            candidate,
            AdaptiveEvidenceChannel.Spelling,
            new[] { primary, secondary },
            now);

        Require(snapshot.OutcomeReviews == 2 && snapshot.FirstTrySuccesses == 2,
            "Distinct source identities in the same evidence channel no longer aggregate deterministically.");
        Require(snapshot.EvidenceStatus == AdaptiveEvidenceStatus.Scored && snapshot.Mastery.HasValue,
            "Distinct scored sources must remain scored adaptive evidence.");
    }

    private static AdaptivePracticeCandidate Candidate() => new(
        "oxford",
        "stable:word:1",
        AdaptiveTargetKind.Lexical,
        new HashSet<AdaptivePracticeMode> { AdaptivePracticeMode.Spelling });

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException("Adaptive evidence identity self-test failed: " + message);
    }
}
