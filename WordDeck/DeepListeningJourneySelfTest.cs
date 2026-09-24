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
        // legitimate completion for that exercise. History credit is bounded by the
        // durable per-exercise CompletedReviews count.
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
        Require(duplicateHistory.CorrectReviews == 1 && duplicateHistory.NeedsReview == 0 &&
                duplicateHistory.WrongAttempts == 0 && duplicateHistory.Replays == 0,
            "A duplicate same-exercise history row leaked stale outcome evidence into Deep Listening feedback.");

        // A stale row can also precede the real completion after recovery/import.
        // When both rows have the same outcome, aggregate counts alone cannot tell
        // them apart. Prefer the newer corroborated chronology so an older duplicate
        // cannot displace the actual later completion and leak stale attempt evidence.
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
        Require(leadingDuplicate.CompletedReviews == 1 && leadingDuplicate.CorrectReviews == 1 &&
                leadingDuplicate.NeedsReview == 0 && leadingDuplicate.Remaining == 4,
            "An older same-outcome duplicate displaced the newer corroborated completion.");
        Require(leadingDuplicate.WrongAttempts == 0 && leadingDuplicate.Replays == 0,
            "An older same-outcome duplicate leaked stale attempt evidence into Deep Listening feedback.");

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
        Require(partial.CorrectReviews == 2 && partial.NeedsReview == 1,
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
        Require(complete.CorrectReviews == 3 && complete.NeedsReview == 2,
            "Completed journey feedback counted outcomes incorrectly.");
        Require(complete.WrongAttempts == 3 && complete.Replays == 3,
            "Completed journey feedback counted attempt/replay evidence incorrectly.");

        string summary = DeepListeningJourney.DescribeAfterCompletion(state, dictionaryId, available);
        Require(summary == "Deep Listening journey complete: 3 of 5 correct; 2 need more practice; 3 wrong attempts; 3 replays. Next begins another 5-review journey.",
            "Completed journey summary is not deterministic.");

        DeepListeningJourney.Progress next = DeepListeningJourney.ActiveProgress(state, dictionaryId, available);
        Require(next.CompletedReviews == 0 && next.Remaining == 5 && !next.CycleCompleted,
            "Starting view after a completed five-review boundary did not roll to the next journey.");

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
        Require(resumed.CompletedReviews == 1 && resumed.CorrectReviews == 1 && resumed.Remaining == 4,
            "Journey progress was not reconstructable from durable history after the boundary.");

        ListeningExercise[] hiddenDuringNext = available
            .Where(item => !string.Equals(item.ExerciseId, "word:e1", StringComparison.OrdinalIgnoreCase))
            .ToArray();
        DeepListeningJourney.Progress hiddenResumed = DeepListeningJourney.ActiveProgress(state, dictionaryId, hiddenDuringNext);
        Require(hiddenResumed.CompletedReviews == 1 && hiddenResumed.CorrectReviews == 1 && hiddenResumed.Remaining == 4,
            "Current eligibility rewrote already-counted progress in the next journey.");

        Console.WriteLine("WordDeck Deep Listening journey self-test passed: bounded five-review progress, deterministic feedback, per-exercise durable completion/outcome reconciliation, stale-leading duplicate resistance, hide/unhide-stable history boundaries and resume continuity.");
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
