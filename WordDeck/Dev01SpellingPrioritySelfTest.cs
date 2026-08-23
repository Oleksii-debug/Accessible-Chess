using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class Dev01SpellingPrioritySelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (!Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            return;
        Dev01SpellingPrioritySelfTest.Run();
    }
}

internal static class Dev01SpellingPrioritySelfTest
{
    public static void Run()
    {
        TestWeakBeforeNewBeforeMastered();
        TestCycleCoverageAndBoundaryRepeatProtection();
        TestCanonicalScopeCoverageWithWeakWordPriority();
        TestPlanningIsReadOnly();
        Console.WriteLine("WordDeck DEV01 Spelling priority passed: repeated-error words are prioritized without starving the finite full-coverage cycle, refill repeats are prevented, all canonical scopes remain complete, and persisted statistics stay read-only.");
    }

    private static void TestWeakBeforeNewBeforeMastered()
    {
        var stats = new Dictionary<string, SpellingEntryStats>(StringComparer.OrdinalIgnoreCase)
        {
            ["weak"] = new SpellingEntryStats
            {
                CompletedReviews = 6,
                FirstTrySuccesses = 2,
                WrongAttempts = 5,
                HintUses = 2,
                CurrentStreak = 0,
                RecentOutcomes = new List<bool> { false, true, false, false }
            },
            ["mastered"] = new SpellingEntryStats
            {
                CompletedReviews = 10,
                FirstTrySuccesses = 10,
                WrongAttempts = 2,
                HintUses = 1,
                CurrentStreak = 8,
                RecentOutcomes = Enumerable.Repeat(true, 10).ToList()
            }
        };

        string[] order = SpellingReviewOrder.Create(
            new[] { "mastered", "new", "weak" }, stats, new Random(20260823)).ToArray();

        Require(Array.IndexOf(order, "weak") < Array.IndexOf(order, "new"),
            "Repeated-error Spelling word was not prioritized ahead of an unseen word.");
        Require(Array.IndexOf(order, "new") < Array.IndexOf(order, "mastered"),
            "Unseen Spelling word was incorrectly placed behind a strongly mastered word.");
        Require(SpellingReviewOrder.PriorityScore(stats["mastered"]) < SpellingReviewOrder.PriorityScore(stats["weak"]),
            "Recovered mastery did not reduce historical-error priority.");
    }

    private static void TestCycleCoverageAndBoundaryRepeatProtection()
    {
        string[] ids = Enumerable.Range(1, 250).Select(number => $"word-{number:D3}").ToArray();
        var stats = new Dictionary<string, SpellingEntryStats>(StringComparer.OrdinalIgnoreCase);
        foreach (string id in ids.Where((_, index) => index % 17 == 0))
        {
            stats[id] = new SpellingEntryStats
            {
                CompletedReviews = 4,
                FirstTrySuccesses = 1,
                WrongAttempts = 4,
                CurrentStreak = 0,
                RecentOutcomes = new List<bool> { false, false, true, false }
            };
        }

        string avoid = ids[0];
        string[] order = SpellingReviewOrder.Create(ids, stats, new Random(41), avoid).ToArray();
        Require(order.Length == ids.Length, "Priority planner changed the active Spelling cycle size.");
        Require(order.Distinct(StringComparer.OrdinalIgnoreCase).Count() == ids.Length,
            "Priority planner repeated a stable word before cycle completion.");
        Require(new HashSet<string>(order, StringComparer.OrdinalIgnoreCase).SetEquals(ids),
            "Priority planner omitted or invented a stable Spelling entry ID.");
        Require(!string.Equals(order[0], avoid, StringComparison.OrdinalIgnoreCase),
            "Priority planner immediately repeated the just-shown word at a refill boundary.");
    }

    private static void TestCanonicalScopeCoverageWithWeakWordPriority()
    {
        DictionaryPackage package = DictionaryLoader.LoadEmbeddedOxford();
        Require(package.Entries.Count == 5446, $"Expected 5446 canonical entries, got {package.Entries.Count}.");

        int seed = 701;
        foreach (string scopeId in StudyScopeIds.Ordered)
        {
            string[] ids = package.Entries
                .Where(entry => StudyScopeIds.Includes(scopeId, entry))
                .Select(entry => entry.Id)
                .ToArray();
            var stats = new Dictionary<string, SpellingEntryStats>(StringComparer.OrdinalIgnoreCase);
            foreach (string id in ids.Where((_, index) => index % 101 == 0))
            {
                stats[id] = new SpellingEntryStats
                {
                    CompletedReviews = 5,
                    FirstTrySuccesses = 1,
                    WrongAttempts = 6,
                    CurrentStreak = 0,
                    RecentOutcomes = new List<bool> { false, false, false, true }
                };
            }

            string[] order = SpellingReviewOrder.Create(ids, stats, new Random(seed++)).ToArray();
            Require(order.Length == ids.Length,
                $"Priority planner changed canonical {scopeId} Spelling count.");
            Require(new HashSet<string>(order, StringComparer.OrdinalIgnoreCase).SetEquals(ids),
                $"Priority planner broke canonical {scopeId} stable-ID coverage.");

            if (stats.Count > 0 && stats.Count < order.Length)
            {
                int lastWeak = order.Select((id, index) => (id, index))
                    .Where(item => stats.ContainsKey(item.id))
                    .Max(item => item.index);
                int firstNonWeak = order.Select((id, index) => (id, index))
                    .Where(item => !stats.ContainsKey(item.id))
                    .Min(item => item.index);
                Require(lastWeak < firstNonWeak,
                    $"Repeated-error words were not actually prioritized in canonical {scopeId} ordering.");
            }
        }
    }

    private static void TestPlanningIsReadOnly()
    {
        var stats = new SpellingEntryStats
        {
            CompletedReviews = 7,
            FirstTrySuccesses = 3,
            WrongAttempts = 5,
            HintUses = 2,
            ShowAnswerUses = 1,
            CurrentStreak = 1,
            RecentOutcomes = new List<bool> { false, true, false },
            LastReviewedUtc = DateTimeOffset.Parse("2026-08-23T12:00:00Z")
        };
        var map = new Dictionary<string, SpellingEntryStats>(StringComparer.OrdinalIgnoreCase) { ["word"] = stats };
        _ = SpellingReviewOrder.Create(new[] { "word", "other" }, map, new Random(9));

        Require(stats.CompletedReviews == 7 && stats.FirstTrySuccesses == 3 && stats.WrongAttempts == 5 &&
                stats.HintUses == 2 && stats.ShowAnswerUses == 1 && stats.CurrentStreak == 1,
            "Priority planning mutated persisted numeric Spelling evidence.");
        Require(stats.RecentOutcomes.SequenceEqual(new[] { false, true, false }),
            "Priority planning mutated persisted recent Spelling outcomes.");
        Require(stats.LastReviewedUtc == DateTimeOffset.Parse("2026-08-23T12:00:00Z"),
            "Priority planning mutated persisted Spelling review time.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }
}
