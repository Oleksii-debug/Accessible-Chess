using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class DeepListeningJourneySelfTest
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (!Environment.GetCommandLineArgs().Any(arg => string.Equals(arg, "--self-test", StringComparison.OrdinalIgnoreCase))) return;
        Run();
    }

    private static void Run()
    {
        const string dictionaryId = "journey-dict";
        ListeningExercise[] available = Enumerable.Range(1, 5)
            .Select(index => new ListeningExercise(
                $"word:e{index}",
                ListeningExerciseKind.Word,
                $"word{index}",
                "A1",
                new[] { $"e{index}" },
                $"e{index}"))
            .ToArray();

        // Regression WD-G3-R03-F07-DLHIST1: a same-exercise history row does not
        // become a second completed review merely because aggregate stats prove one
        // legitimate completion for that exercise. A contradictory outcome has a
        // zero durable budget, so it is provably stale and does not make feedback
        // ambiguous.
        var duplicateHistoryState = new ListeningCoachState();
        AddCompletedReview(duplicateHistoryState, dictionaryId, "word:e1", correct: true);
        duplicateHistoryState.History.Add(Record(
            dictionaryId,
            "word:e1",
            correct: false,
            wrongAttempts: 9,
            replays: 9));
        DeepListeningJourney.Progress duplicateHistory =
            DeepListeningJourney.ActiveProgress(duplicateHistoryState, dictionaryId, available);
        Require(duplicateHistory.CompletedReviews == 1 && duplicateHistory.Remaining == 4,
            "A duplicate same-exercise history row inflated Deep Listening journey credit beyond durable completion count.");
        Require(!duplicateHistory.FeedbackAmbiguous &&
                duplicateHistory.CorrectReviews == 1 && duplicateHistory.NeedsReview == 0 &&
                duplicateHistory.WrongAttempts == 0 && duplicateHistory.Replays == 0,
            "A provably stale contradictory history row affected Deep Listening feedback.");

        // If a stale row has the same outcome as the genuine completion, aggregate
        // counts can prove cardinality but cannot identify which chronological row is
        // genuine. Fail closed on row-level feedback instead of choosing oldest or
        // newest and potentially leaking stale attempt evidence.
        var leadingDuplicateState = new ListeningCoachState();
        leadingDuplicateState.History.Add(Record(
            dictionaryId,
            "word:e1",
            correct: true,
            wrongAttempts: 9,
            replays: 9));
        AddCompletedReview(leadingDuplicateState, dictionaryId, "word:e1", correct: true);
        DeepListeningJourney.Progress leadingDuplicate =
            DeepListeningJourney.ActiveProgress(leadingDuplicateState, dictionaryId, available);
        Require(leadingDuplicate.CompletedReviews == 1 && leadingDuplicate.Remaining == 4,
            "Same-outcome duplicate ambiguity changed durable journey cardinality.");
        Require(leadingDuplicate.FeedbackAmbiguous &&
                leadingDuplicate.CorrectReviews == 0 && leadingDuplicate.NeedsReview == 0 &&
                leadingDuplicate.WrongAttempts == 0 && leadingDuplicate.Replays == 0,
            "Same-outcome duplicate ambiguity did not fail closed on row-level feedback.");
        Require(
            DeepListeningJourney.DescribeActive(leadingDuplicateState, dictionaryId, available) ==
            "Deep Listening journey: 1 of 5 reviews complete; detailed feedback is unavailable because stored Listening history is ambiguous; 4 remaining.",
            "Ambiguous partial journey feedback was not described deterministically.");

        var state = new ListeningCoachState();
        AddCompletedReview(state, dictionaryId, "word:e1", correct: true);
        AddCompletedReview(state, "other-dict", "word:e1", correct: false, wrongAttempts: 9, replays: 9);
        // A raw history row without matching durable completion stats is not a
        // legitimate completed Listening review and must not create journey credit.
        state.History.Add(Record(dictionaryId, "word:not-available", correct: false, wrongAttempts: 9, replays: 9));
        AddCompletedReview(state, dictionaryId, "word:e2", correct: false, wrongAttempts: 1, replays: 2);
        AddCompletedReview(state, dictionaryId, "word:e3", correct: true);

        DeepListeningJourney.Progress partial = DeepListeningJourney.ActiveProgress(state, dictionaryId, available);
        Require(partial.CompletedReviews == 3, "Durably completed current-dictionary history did not produce 3/5 journey progress.");
        Require(!partial.FeedbackAmbiguous && partial.CorrectReviews == 2 && partial.NeedsReview == 1,
            "Partial journey feedback counted correct/needs-review incorrectly.");
        Require(partial.WrongAttempts == 1 && partial.Replays == 2,
            "Partial journey feedback leaked foreign or unevidenced history.");
        Require(!partial.CycleCompleted && partial.Remaining == 2,
            "Partial journey was incorrectly treated as complete.");

        AddCompletedReview(state, dictionaryId, "word:e4", correct: true);
        AddCompletedReview(state, dictionaryId, "word:e5", correct: false, wrongAttempts: 2, replays: 1);

        DeepListeningJourney.Progress complete = DeepListeningJourney.CompletionProgress(state, dictionaryId, available);
        Require(complete.CompletedReviews == 5 && complete.CycleCompleted,
            "Exact five-review boundary did not produce a completed Deep Listening journey.");
        Require(!complete.FeedbackAmbiguous && complete.CorrectReviews == 3 && complete.NeedsReview == 2,
            "Completed journey feedback counted outcomes incorrectly.");
        Require(complete.WrongAttempts == 3 && complete.Replays == 3,
            "Completed journey feedback counted attempt/replay evidence incorrectly.");

        string summary = DeepListeningJourney.DescribeAfterCompletion(state, dictionaryId, available);
        Require(summary == "Deep Listening journey complete: 3 of 5 correct; 2 need more practice; 3 wrong attempts; 3 replays. Next begins another 5-review journey.",
            "Completed journey summary is not deterministic.");

        DeepListeningJourney.Progress next = DeepListeningJourney.ActiveProgress(state, dictionaryId, available);
        Require(next.CompletedReviews == 0 && next.Remaining == 5 && !next.CycleCompleted,
            "Starting view after a completed five-review boundary did not roll to the next journey.");

        // Regression WD-G3-R03-F07-DLHIST2: a later stale duplicate with the same
        // outcome cannot be selected as the genuine row across an exact five-review
        // boundary. Cardinality remains five, but detailed feedback fails closed.
        var trailingBoundaryDuplicateState = new ListeningCoachState();
        AddCompletedReview(trailingBoundaryDuplicateState, dictionaryId, "word:e1", correct: true);
        AddCompletedReview(trailingBoundaryDuplicateState, dictionaryId, "word:e2", correct: false, wrongAttempts: 1, replays: 1);
        AddCompletedReview(trailingBoundaryDuplicateState, dictionaryId, "word:e3", correct: true);
        AddCompletedReview(trailingBoundaryDuplicateState, dictionaryId, "word:e4", correct: true);
        AddCompletedReview(trailingBoundaryDuplicateState, dictionaryId, "word:e5", correct: false, wrongAttempts: 2, replays: 2);
        trailingBoundaryDuplicateState.History.Add(Record(
            dictionaryId,
            "word:e1",
            correct: true,
            wrongAttempts: 9,
            replays: 9));

        DeepListeningJourney.Progress trailingBoundaryDuplicate =
            DeepListeningJourney.CompletionProgress(trailingBoundaryDuplicateState, dictionaryId, available);
        Require(trailingBoundaryDuplicate.CompletedReviews == 5 && trailingBoundaryDuplicate.CycleCompleted &&
                trailingBoundaryDuplicate.Remaining == 0,
            "A later same-outcome duplicate changed the durable five-review boundary.");
        Require(trailingBoundaryDuplicate.FeedbackAmbiguous &&
                trailingBoundaryDuplicate.CorrectReviews == 0 && trailingBoundaryDuplicate.NeedsReview == 0 &&
                trailingBoundaryDuplicate.WrongAttempts == 0 && trailingBoundaryDuplicate.Replays == 0,
            "A later same-outcome duplicate leaked ambiguous current-cycle feedback.");
        Require(
            DeepListeningJourney.DescribeAfterCompletion(trailingBoundaryDuplicateState, dictionaryId, available) ==
            "Deep Listening journey complete: 5 reviews recorded; detailed feedback is unavailable because stored Listening history is ambiguous. Next begins another 5-review journey.",
            "Ambiguous completed journey feedback was not described deterministically.");

        // Ambiguity in an older cycle must not suppress detailed feedback forever.
        // Five later, independently corroborated reviews place the stale duplicate
        // fully behind the current feedback window.
        for (int index = 1; index <= 5; index++)
        {
            AddCompletedReview(
                trailingBoundaryDuplicateState,
                dictionaryId,
                $"word:e{index}",
                correct: index != 5,
                wrongAttempts: index == 5 ? 1 : 0,
                replays: index == 5 ? 1 : 0);
        }
        DeepListeningJourney.Progress recoveredFeedback =
            DeepListeningJourney.CompletionProgress(trailingBoundaryDuplicateState, dictionaryId, available);
        Require(recoveredFeedback.CompletedReviews == 5 && recoveredFeedback.CycleCompleted &&
                !recoveredFeedback.FeedbackAmbiguous,
            "Old duplicate ambiguity was not bounded to the affected feedback window.");
        Require(recoveredFeedback.CorrectReviews == 4 && recoveredFeedback.NeedsReview == 1 &&
                recoveredFeedback.WrongAttempts == 1 && recoveredFeedback.Replays == 1,
            "Detailed feedback did not recover after five later unambiguous reviews.");

        // Regression WD-G3-R01-F07-QA-001: hiding a word changes current
        // selection/playback eligibility, but it must not rewrite already-counted
        // chronology or move the durable five-review boundary on reopen.
        ListeningExercise[] hiddenAfterFive = available
            .Where(item => !string.Equals(item.ExerciseId, "word:e3", StringComparison.OrdinalIgnoreCase))
            .ToArray();
        DeepListeningJourney.Progress hiddenBoundary = DeepListeningJourney.CompletionProgress(state, dictionaryId, hiddenAfterFive);
        Require(hiddenBoundary.CompletedReviews == 5 && hiddenBoundary.CycleCompleted,
            "Hiding a previously reviewed word rewrote the completed five-review boundary.");
        DeepListeningJourney.Progress reopenedHidden = DeepListeningJourney.ActiveProgress(state, dictionaryId, hiddenAfterFive);
        Require(reopenedHidden.CompletedReviews == 0 && reopenedHidden.Remaining == 5 && !reopenedHidden.CycleCompleted,
            "Reopening after hiding a reviewed word shifted the next-journey boundary.");
        DeepListeningJourney.Progress unhidden = DeepListeningJourney.ActiveProgress(state, dictionaryId, available);
        Require(unhidden.CompletedReviews == 0 && unhidden.Remaining == 5 && !unhidden.CycleCompleted,
            "Unhiding a reviewed word shifted the stable five-review boundary.");

        AddCompletedReview(state, dictionaryId, "word:e1", correct: true);
        DeepListeningJourney.Progress resumed = DeepListeningJourney.ActiveProgress(state, dictionaryId, available);
        Require(resumed.CompletedReviews == 1 && resumed.CorrectReviews == 1 && resumed.Remaining == 4 &&
                !resumed.FeedbackAmbiguous,
            "Journey progress was not reconstructable from durable history after the boundary.");

        ListeningExercise[] hiddenDuringNext = available
            .Where(item => !string.Equals(item.ExerciseId, "word:e1", StringComparison.OrdinalIgnoreCase))
            .ToArray();
        DeepListeningJourney.Progress hiddenResumed = DeepListeningJourney.ActiveProgress(state, dictionaryId, hiddenDuringNext);
        Require(hiddenResumed.CompletedReviews == 1 && hiddenResumed.CorrectReviews == 1 && hiddenResumed.Remaining == 4,
            "Current eligibility rewrote already-counted progress in the next journey.");

        Console.WriteLine("WordDeck Deep Listening journey self-test passed: bounded five-review progress, deterministic feedback, durable completion/outcome reconciliation, fail-closed same-outcome duplicate handling, bounded ambiguity recovery, hide/unhide-stable history boundaries and resume continuity.");
    }

    private static void AddCompletedReview(
        ListeningCoachState state,
        string dictionaryId,
        string exerciseId,
        bool correct,
        int wrongAttempts = 0,
        int replays = 0)
    {
        if (!state.StatsByDictionary.TryGetValue(dictionaryId, out Dictionary<string, ListeningItemStats>? perDictionary))
        {
            perDictionary = new Dictionary<string, ListeningItemStats>(StringComparer.OrdinalIgnoreCase);
            state.StatsByDictionary[dictionaryId] = perDictionary;
        }
        if (!perDictionary.TryGetValue(exerciseId, out ListeningItemStats? stats))
        {
            stats = new ListeningItemStats();
            perDictionary[exerciseId] = stats;
        }

        stats.CompletedReviews++;
        if (correct) stats.CorrectReviews++;
        stats.WrongAttempts += Math.Max(0, wrongAttempts);
        stats.ReplayCount += Math.Max(0, replays);
        stats.LastReviewedUtc = DateTimeOffset.Parse("2026-01-01T00:00:00Z");
        state.History.Add(Record(dictionaryId, exerciseId, correct, wrongAttempts, replays));
    }

    private static ListeningHistoryRecord Record(
        string dictionaryId,
        string exerciseId,
        bool correct,
        int wrongAttempts = 0,
        int replays = 0) => new()
    {
        AtUtc = DateTimeOffset.Parse("2026-01-01T00:00:00Z"),
        DictionaryId = dictionaryId,
        ExerciseId = exerciseId,
        Kind = ListeningExerciseKind.Word,
        Correct = correct,
        ShowedAnswer = !correct,
        Skipped = false,
        WrongAttempts = wrongAttempts,
        Replays = replays
    };

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException("Deep Listening journey self-test failed: " + message);
    }
}
