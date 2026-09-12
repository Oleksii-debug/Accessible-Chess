using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class ListeningStatisticsSelfTest
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (!Environment.GetCommandLineArgs().Any(arg => string.Equals(arg, "--self-test", StringComparison.OrdinalIgnoreCase))) return;
        Run();
    }

    private static void Run()
    {
        var package = new DictionaryPackage
        {
            Id = "listening-statistics-test",
            Name = "Listening statistics test",
            SourceLanguage = "en",
            TargetLanguage = "uk",
            Entries = new[]
            {
                new DictionaryEntry("a", "A1", "alpha", "альфа"),
                new DictionaryEntry("b", "A1", "bravo", "браво"),
                new DictionaryEntry("c", "B1", "charlie", "чарлі")
            }
        };
        var items = new[]
        {
            new ListeningExercise("word:a", ListeningExerciseKind.Word, "alpha", "A1", new[] { "a" }, "a"),
            new ListeningExercise("word:b", ListeningExerciseKind.Word, "bravo", "A1", new[] { "b" }, "b")
        };
        var state = new ListeningCoachState { ActiveScopeId = StudyScopeIds.A1 };
        state.StatsByDictionary[package.Id] = new Dictionary<string, ListeningItemStats>(StringComparer.OrdinalIgnoreCase)
        {
            ["word:a"] = new() { CompletedReviews = 2, CorrectReviews = 1, WrongAttempts = 2, ReplayCount = 3, ShowAnswerUses = 1, SkipCount = 0 },
            ["word:b"] = new() { CompletedReviews = 1, CorrectReviews = 1, WrongAttempts = 0, ReplayCount = 1, ShowAnswerUses = 0, SkipCount = 1 },
            // Out-of-scope historical item must not leak into current-scope statistics.
            ["word:c"] = new() { CompletedReviews = 99, CorrectReviews = 0, WrongAttempts = 99, ReplayCount = 99 }
        };
        state.History.Add(new ListeningHistoryRecord { DictionaryId = package.Id, ExerciseId = "word:a", AtUtc = DateTimeOffset.UtcNow, Kind = ListeningExerciseKind.Word });
        state.History.Add(new ListeningHistoryRecord { DictionaryId = package.Id, ExerciseId = "word:b", AtUtc = DateTimeOffset.UtcNow, Kind = ListeningExerciseKind.Word });
        state.History.Add(new ListeningHistoryRecord { DictionaryId = package.Id, ExerciseId = "word:c", AtUtc = DateTimeOffset.UtcNow, Kind = ListeningExerciseKind.Word });

        using var source = new FixedSource(items);
        var engine = new ListeningCoachEngine(package, state, source);
        ListeningStatistics stats = engine.Statistics();

        Require(stats.AvailableItems == 2 && stats.ReviewedItems == 2, "Current-scope item counts are wrong.");
        Require(stats.CompletedReviews == 3 && stats.CorrectReviews == 2, "Current-scope completed/correct totals are wrong.");
        Require(Math.Abs(stats.Accuracy - (2d / 3d)) < 0.000001d, "Listening accuracy is wrong.");
        Require(stats.WrongAttempts == 2 && stats.ReplayCount == 4 && stats.ShowAnswerUses == 1 && stats.SkipCount == 1,
            "Listening event totals are wrong.");
        Require(stats.HistoryEntries == 2, "Out-of-scope Listening history leaked into statistics.");
        Require(stats.AverageMastery >= 0d && stats.AverageMastery <= 1d, "Average Listening mastery is outside 0..1.");

        Console.WriteLine("WordDeck Listening statistics self-test passed: current-scope totals, accuracy, mastery and history isolation verified.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException("Listening statistics self-test failed: " + message);
    }

    private sealed class FixedSource : IListeningExerciseSource
    {
        private readonly IReadOnlyList<ListeningExercise> _items;
        public FixedSource(IReadOnlyList<ListeningExercise> items) => _items = items;
        public IReadOnlyList<ListeningExercise> GetAvailable(string scopeId) => _items;
        public bool TryPlay(ListeningExercise exercise, out string? error) { error = null; return true; }
        public void Dispose() { }
    }
}
