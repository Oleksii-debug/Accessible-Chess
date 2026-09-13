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

        var state = new ListeningCoachState();
        state.History.Add(Record(dictionaryId, "word:e1", correct: true));
        state.History.Add(Record("other-dict", "word:e1", correct: false, wrongAttempts: 9, replays: 9));
        state.History.Add(Record(dictionaryId, "word:not-available", correct: false, wrongAttempts: 9, replays: 9));
        state.History.Add(Record(dictionaryId, "word:e2", correct: false, wrongAttempts: 1, replays: 2));
        state.History.Add(Record(dictionaryId, "word:e3", correct: true));

        DeepListeningJourney.Progress partial = DeepListeningJourney.ActiveProgress(state, dictionaryId, available);
        Require(partial.CompletedReviews == 3, "Current eligible history did not produce 3/5 journey progress.");
        Require(partial.CorrectReviews == 2 && partial.NeedsReview == 1,
            "Partial journey feedback counted correct/needs-review incorrectly.");
        Require(partial.WrongAttempts == 1 && partial.Replays == 2,
            "Partial journey feedback leaked foreign or unavailable history.");
        Require(!partial.CycleCompleted && partial.Remaining == 2,
            "Partial journey was incorrectly treated as complete.");

        state.History.Add(Record(dictionaryId, "word:e4", correct: true));
        state.History.Add(Record(dictionaryId, "word:e5", correct: false, wrongAttempts: 2, replays: 1));

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

        state.History.Add(Record(dictionaryId, "word:e1", correct: true));
        DeepListeningJourney.Progress resumed = DeepListeningJourney.ActiveProgress(state, dictionaryId, available);
        Require(resumed.CompletedReviews == 1 && resumed.CorrectReviews == 1 && resumed.Remaining == 4,
            "Journey progress was not reconstructable from durable history after the boundary.");

        Console.WriteLine("WordDeck Deep Listening journey self-test passed: bounded five-review progress, deterministic feedback, scope filtering and history-derived resume continuity.");
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
