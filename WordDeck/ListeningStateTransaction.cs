using System.Runtime.CompilerServices;
using System.Text.Json;

namespace WordDeck;

/// <summary>
/// Failure-atomic persistence boundary for Listening UI actions. The engine may
/// mutate its in-memory state before a disk write is attempted, so callers take
/// an exact snapshot first and replace their live state with the restored copy
/// whenever persistence fails.
/// </summary>
internal static class ListeningStateTransaction
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true
    };

    public static ListeningCoachState Snapshot(ListeningCoachState state)
    {
        ArgumentNullException.ThrowIfNull(state);
        ListeningCoachState clone = JsonSerializer.Deserialize<ListeningCoachState>(
                   JsonSerializer.Serialize(state, JsonOptions), JsonOptions)
               ?? throw new InvalidDataException("Could not snapshot Listening state for a safe transaction.");
        // JSON round-tripping does not preserve Dictionary comparers. Reuse the
        // canonical state normalization so a restored snapshot keeps the same
        // case-insensitive dictionary semantics as a normally loaded profile.
        return ListeningStateStore.Normalize(clone);
    }

    public static bool TryCommit(
        ListeningStateStore store,
        ListeningCoachState current,
        ListeningCoachState beforeAction,
        out ListeningCoachState effectiveState,
        out string? error)
    {
        ArgumentNullException.ThrowIfNull(store);
        ArgumentNullException.ThrowIfNull(current);
        ArgumentNullException.ThrowIfNull(beforeAction);
        try
        {
            store.Save(current);
            effectiveState = current;
            error = null;
            return true;
        }
        catch (Exception ex)
        {
            effectiveState = Snapshot(beforeAction);
            error = ex.Message;
            return false;
        }
    }
}

internal static class ListeningStateTransactionSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg =>
                string.Equals(arg, "--self-test", StringComparison.OrdinalIgnoreCase)))
            ListeningStateTransactionSelfTest.Run();
    }
}

internal static class ListeningStateTransactionSelfTest
{
    public static void Run()
    {
        TestSnapshotPreservesCanonicalDictionarySemantics();
        TestSuccessfulCommitPersistsExactMutation();
        TestFailedCommitRestoresExactPreActionState();
        Console.WriteLine("WordDeck Listening state transaction self-test passed: snapshots retain canonical dictionary semantics, successful mutations persist and failed durable writes restore the exact pre-action learner state.");
    }

    private static void TestSnapshotPreservesCanonicalDictionarySemantics()
    {
        ListeningCoachState snapshot = ListeningStateTransaction.Snapshot(BuildBaseline());
        Require(snapshot.StatsByDictionary.ContainsKey("TEST-DICTIONARY"),
            "Listening transaction snapshot lost the canonical case-insensitive dictionary comparer.");
        Require(snapshot.StatsByDictionary["TEST-DICTIONARY"].ContainsKey("WORD:A"),
            "Listening transaction snapshot lost the canonical case-insensitive exercise comparer.");
    }

    private static void TestSuccessfulCommitPersistsExactMutation()
    {
        string parent = Path.Combine(Path.GetTempPath(), "WordDeck Listening transaction success " + Guid.NewGuid().ToString("N"));
        string root = Path.Combine(parent, "profile");
        Directory.CreateDirectory(parent);
        try
        {
            var store = new ListeningStateStore(root);
            ListeningCoachState before = BuildBaseline();
            store.Save(before);
            ListeningCoachState mutated = ListeningStateTransaction.Snapshot(before);
            mutated.ActiveScopeId = StudyScopeIds.A2;
            mutated.CurrentExerciseId = "word:b";
            mutated.SelectionCounter = 8;

            bool committed = ListeningStateTransaction.TryCommit(
                store, mutated, before, out ListeningCoachState effective, out string? error);

            Require(committed && error is null, "Valid Listening mutation did not commit.");
            Require(ReferenceEquals(effective, mutated), "Successful transaction unexpectedly replaced the committed state instance.");
            ListeningCoachState reloaded = new ListeningStateStore(root).Load();
            Require(reloaded.ActiveScopeId == StudyScopeIds.A2 && reloaded.CurrentExerciseId == "word:b" && reloaded.SelectionCounter == 8,
                "Successful Listening transaction did not survive close/reopen.");
        }
        finally
        {
            try { Directory.Delete(parent, recursive: true); } catch { }
        }
    }

    private static void TestFailedCommitRestoresExactPreActionState()
    {
        string parent = Path.Combine(Path.GetTempPath(), "WordDeck Listening transaction failure " + Guid.NewGuid().ToString("N"));
        string root = Path.Combine(parent, "profile");
        Directory.CreateDirectory(parent);
        try
        {
            var store = new ListeningStateStore(root);
            ListeningCoachState before = BuildBaseline();
            store.Save(before);
            string expected = Fingerprint(before);

            ListeningCoachState mutated = ListeningStateTransaction.Snapshot(before);
            mutated.ActiveScopeId = StudyScopeIds.B1;
            mutated.CurrentExerciseId = null;
            mutated.SelectionCounter = 99;
            ListeningItemStats stats = mutated.StatsByDictionary["test-dictionary"]["word:a"];
            stats.CompletedReviews = 7;
            stats.CorrectReviews = 7;
            stats.ShowAnswerUses = 3;
            mutated.History.Add(new ListeningHistoryRecord
            {
                AtUtc = DateTimeOffset.Parse("2026-09-12T07:00:00Z"),
                DictionaryId = "test-dictionary",
                ExerciseId = "word:a",
                Kind = ListeningExerciseKind.Word,
                Correct = true
            });

            // Deterministically make the store root unusable after construction:
            // Save() must call Directory.CreateDirectory(root), which fails when
            // a regular file occupies that exact path.
            Directory.Delete(root, recursive: true);
            File.WriteAllText(root, "block-listening-state-directory");

            bool committed = ListeningStateTransaction.TryCommit(
                store, mutated, before, out ListeningCoachState effective, out string? error);

            Require(!committed && !string.IsNullOrWhiteSpace(error), "Forced Listening persistence failure was not surfaced.");
            Require(Fingerprint(effective) == expected,
                "Failed Listening persistence left mastery/history/current-item mutations in the effective learner state.");
            Require(effective.StatsByDictionary.ContainsKey("TEST-DICTIONARY") &&
                    effective.StatsByDictionary["TEST-DICTIONARY"].ContainsKey("WORD:A"),
                "Failed Listening persistence restored data but lost canonical case-insensitive lookup semantics.");
            Require(Fingerprint(mutated) != expected,
                "Failure fixture did not actually mutate the candidate state before persistence.");
        }
        finally
        {
            try { if (File.Exists(root)) File.Delete(root); } catch { }
            try { Directory.Delete(parent, recursive: true); } catch { }
        }
    }

    private static ListeningCoachState BuildBaseline()
    {
        return new ListeningCoachState
        {
            ActiveScopeId = StudyScopeIds.A1,
            CurrentExerciseId = "word:a",
            SelectionCounter = 4,
            StatsByDictionary = new Dictionary<string, Dictionary<string, ListeningItemStats>>(StringComparer.OrdinalIgnoreCase)
            {
                ["test-dictionary"] = new Dictionary<string, ListeningItemStats>(StringComparer.OrdinalIgnoreCase)
                {
                    ["word:a"] = new ListeningItemStats
                    {
                        CompletedReviews = 2,
                        CorrectReviews = 1,
                        WrongAttempts = 1,
                        ReplayCount = 1,
                        ConsecutiveCorrect = 0
                    }
                }
            },
            History = new List<ListeningHistoryRecord>
            {
                new()
                {
                    AtUtc = DateTimeOffset.Parse("2026-09-12T06:00:00Z"),
                    DictionaryId = "test-dictionary",
                    ExerciseId = "word:a",
                    Kind = ListeningExerciseKind.Word,
                    Correct = false,
                    WrongAttempts = 1,
                    Replays = 1
                }
            }
        };
    }

    private static string Fingerprint(ListeningCoachState state) =>
        JsonSerializer.Serialize(state, new JsonSerializerOptions { PropertyNamingPolicy = null });

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException("Listening state transaction self-test failed: " + message);
    }
}
