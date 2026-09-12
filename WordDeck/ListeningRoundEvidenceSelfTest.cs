using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class ListeningRoundEvidenceSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg =>
                string.Equals(arg, "--self-test", StringComparison.OrdinalIgnoreCase)))
            ListeningRoundEvidenceSelfTest.Run();
    }
}

internal static class ListeningRoundEvidenceSelfTest
{
    public static void Run()
    {
        TestCloseReopenPreservesUnfinishedRoundEvidence();
        TestLaterPersistenceFailureCannotEraseEarlierRoundEvidence();
        Console.WriteLine("WordDeck Listening unfinished-round evidence self-test passed: wrong attempts/replays survive close/reopen and later persistence rollback, then enter final history exactly once.");
    }

    private static void TestCloseReopenPreservesUnfinishedRoundEvidence()
    {
        string parent = Path.Combine(Path.GetTempPath(), "WordDeck Listening round restart " + Guid.NewGuid().ToString("N"));
        string root = Path.Combine(parent, "profile");
        Directory.CreateDirectory(parent);
        try
        {
            DictionaryPackage package = Package();
            var source = new FakeSource(new[] { Word("a", "alpha", "A1") });
            var store = new ListeningStateStore(root);
            ListeningCoachState state = store.Load();
            state.ActiveScopeId = StudyScopeIds.A1;
            var engine = new ListeningCoachEngine(package, state, source);
            ListeningExercise pending = engine.StartNext(false);

            Require(!engine.Check("wrong").IsCorrect, "Restart fixture did not record the first wrong attempt.");
            Require(engine.TryPlayCurrent(countAsReplay: true, out string? replayError),
                "Restart fixture could not record a counted replay: " + replayError);
            store.Save(state);

            ListeningCoachState reopened = new ListeningStateStore(root).Load();
            Require(reopened.CurrentExerciseId == pending.ExerciseId &&
                    reopened.CurrentRoundWrongAttempts == 1 &&
                    reopened.CurrentRoundReplays == 1,
                "Persisted unfinished-round evidence was not present after close/reopen.");

            var reopenedEngine = new ListeningCoachEngine(package, reopened, source);
            Require(reopenedEngine.TryResumeCurrent(out ListeningExercise? resumed) && resumed?.ExerciseId == pending.ExerciseId,
                "Unfinished Listening item did not resume with its round evidence.");
            ListeningCheckResult correct = reopenedEngine.Check("alpha");
            Require(correct.IsCorrect && correct.Completed, "Resumed Listening round could not complete.");
            Require(reopened.History.Count == 1 && reopened.History[0].WrongAttempts == 1 && reopened.History[0].Replays == 1,
                "Final history lost wrong/replay evidence that survived close/reopen.");
            Require(reopened.CurrentExerciseId is null && reopened.CurrentRoundWrongAttempts == 0 &&
                    reopened.CurrentRoundReplays == 0 && !reopened.CurrentRoundRevealed,
                "Completed Listening round left stale unfinished-round evidence.");
            store.Save(reopened);

            ListeningCoachState finalRestart = new ListeningStateStore(root).Load();
            Require(finalRestart.History.Count == 1 && finalRestart.History[0].WrongAttempts == 1 && finalRestart.History[0].Replays == 1,
                "Completed Listening history did not survive a second restart.");
            Require(finalRestart.CurrentExerciseId is null && finalRestart.CurrentRoundWrongAttempts == 0 && finalRestart.CurrentRoundReplays == 0,
                "Second restart resurrected cleared unfinished-round evidence.");
        }
        finally
        {
            try { Directory.Delete(parent, recursive: true); } catch { }
        }
    }

    private static void TestLaterPersistenceFailureCannotEraseEarlierRoundEvidence()
    {
        string parent = Path.Combine(Path.GetTempPath(), "WordDeck Listening round rollback " + Guid.NewGuid().ToString("N"));
        string root = Path.Combine(parent, "profile");
        Directory.CreateDirectory(parent);
        try
        {
            DictionaryPackage package = Package();
            var source = new FakeSource(new[] { Word("a", "alpha", "A1") });
            var store = new ListeningStateStore(root);
            ListeningCoachState state = store.Load();
            state.ActiveScopeId = StudyScopeIds.A1;
            var engine = new ListeningCoachEngine(package, state, source);
            _ = engine.StartNext(false);
            store.Save(state);

            Require(!engine.Check("first-wrong").IsCorrect, "Rollback fixture did not record the first wrong attempt.");
            Require(engine.TryPlayCurrent(countAsReplay: true, out string? replayError),
                "Rollback fixture could not record the first replay: " + replayError);
            store.Save(state);
            Require(state.CurrentRoundWrongAttempts == 1 && state.CurrentRoundReplays == 1,
                "First successful persistence did not own the unfinished-round counters.");

            ListeningCoachState beforeFailedAction = ListeningStateTransaction.Snapshot(state);
            Require(!engine.Check("second-wrong").IsCorrect, "Rollback fixture did not mutate the later failing action.");
            Require(state.CurrentRoundWrongAttempts == 2,
                "Later failing action did not mutate unfinished-round evidence before persistence.");

            // Deterministic write failure used by the transaction contract: the
            // store root becomes a regular file, so Directory.CreateDirectory
            // inside Save() must fail after the in-memory action already ran.
            Directory.Delete(root, recursive: true);
            File.WriteAllText(root, "block-listening-round-state-directory");

            bool committed = ListeningStateTransaction.TryCommit(
                store,
                state,
                beforeFailedAction,
                out ListeningCoachState effective,
                out string? error);
            Require(!committed && !string.IsNullOrWhiteSpace(error),
                "Forced later Listening persistence failure was not surfaced.");
            Require(effective.CurrentRoundWrongAttempts == 1 && effective.CurrentRoundReplays == 1,
                "Rollback erased or duplicated unfinished-round evidence from the earlier successful save.");
            ListeningItemStats effectiveStats = effective.StatsByDictionary[package.Id]["word:a"];
            Require(effectiveStats.WrongAttempts == 1 && effectiveStats.ReplayCount == 1,
                "Rollback did not restore item statistics to the earlier durable action boundary.");

            File.Delete(root);
            Directory.CreateDirectory(root);
            var recoveredEngine = new ListeningCoachEngine(package, effective, source);
            Require(recoveredEngine.TryResumeCurrent(out ListeningExercise? resumed) && resumed?.ExerciseId == "word:a",
                "Engine rebuild after failed save did not resume the unfinished Listening round.");
            ListeningCheckResult correct = recoveredEngine.Check("alpha");
            Require(correct.IsCorrect && correct.Completed, "Recovered Listening round could not complete after rollback.");
            Require(effective.History.Count == 1 && effective.History[0].WrongAttempts == 1 && effective.History[0].Replays == 1,
                "Final history forgot earlier durable wrong/replay evidence after the later save failure.");
            store.Save(effective);

            ListeningCoachState reopened = new ListeningStateStore(root).Load();
            Require(reopened.History.Count == 1 && reopened.History[0].WrongAttempts == 1 && reopened.History[0].Replays == 1,
                "Recovered final history did not survive close/reopen after rollback.");
            Require(reopened.CurrentExerciseId is null && reopened.CurrentRoundWrongAttempts == 0 &&
                    reopened.CurrentRoundReplays == 0 && !reopened.CurrentRoundRevealed,
                "Recovered completed round retained stale unfinished evidence after restart.");
        }
        finally
        {
            try { if (File.Exists(root)) File.Delete(root); } catch { }
            try { Directory.Delete(parent, recursive: true); } catch { }
        }
    }

    private static DictionaryPackage Package() => new()
    {
        Id = "test-dictionary",
        Name = "Listening round evidence",
        SourceLanguage = "en",
        TargetLanguage = "uk",
        Entries = new[]
        {
            new DictionaryEntry("a", "A1", "alpha", "альфа")
        }
    };

    private static ListeningExercise Word(string id, string target, string level) =>
        new($"word:{id}", ListeningExerciseKind.Word, target, level, new[] { id }, id);

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException("Listening unfinished-round evidence self-test failed: " + message);
    }

    private sealed class FakeSource : IListeningExerciseSource
    {
        private readonly IReadOnlyList<ListeningExercise> _items;
        public FakeSource(IReadOnlyList<ListeningExercise> items) => _items = items;
        public IReadOnlyList<ListeningExercise> GetAvailable(string scopeId) => _items;
        public bool TryPlay(ListeningExercise exercise, out string? error) { error = null; return true; }
        public void Dispose() { }
    }
}
