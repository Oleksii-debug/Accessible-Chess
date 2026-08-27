using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class SentenceCoachPoolStateSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (!Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            return;

        string[] ids = Enumerable.Range(1, 205).Select(index => $"pool-{index:000}").ToArray();
        Require(ContextStudyPoolBuilder.Build(ids, ContextStudyPoolPreset.Thirty).EntryIds.Count == 30, "30-target Sentence pool was not bounded to 30.");
        Require(ContextStudyPoolBuilder.Build(ids, ContextStudyPoolPreset.Hundred).EntryIds.Count == 100, "100-target Sentence pool was not bounded to 100.");
        Require(ContextStudyPoolBuilder.Build(ids, ContextStudyPoolPreset.TwoHundred).EntryIds.Count == 200, "200-target Sentence pool was not bounded to 200.");
        Require(ContextStudyPoolBuilder.Build(ids, ContextStudyPoolPreset.Full).EntryIds.Count == 205, "Full Sentence pool did not preserve every resolved target.");

        var state = new SentenceCoachState
        {
            PoolPreset = ContextStudyPoolPreset.TwoHundred,
            TargetCount = 3,
            CurrentTargetEntryIds = new List<string> { "a", "b", "c" },
            CurrentTargetIndex = 2
        };
        SentenceCoachStateStore.Normalize(state);
        Require(state.PoolPreset == ContextStudyPoolPreset.TwoHundred && state.TargetCount == 3 && state.CurrentTargetIndex == 2,
            "Sentence restart state did not preserve 200-pool / natural-3 selection and target position.");

        state.PoolPreset = (ContextStudyPoolPreset)999;
        SentenceCoachStateStore.Normalize(state);
        Require(state.PoolPreset == ContextStudyPoolPreset.Full, "Unknown persisted Sentence pool value did not fail safely to Full.");

        Console.WriteLine("Sentence Coach pool-state self-test PASS: 30/100/200/full bounds and persisted pool/target position verified.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException("Sentence Coach pool-state self-test failed: " + message);
    }
}
