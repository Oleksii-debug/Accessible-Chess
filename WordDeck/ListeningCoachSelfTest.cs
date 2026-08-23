using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class ListeningCoachSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (!Environment.GetCommandLineArgs().Any(arg => string.Equals(arg, "--self-test", StringComparison.OrdinalIgnoreCase))) return;
        ListeningCoachSelfTest.Run();
    }
}

internal static class ListeningCoachSelfTest
{
    public static void Run()
    {
        string root = Path.Combine(Path.GetTempPath(), "WordDeck-listening-selftest-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            TestStateRestartAndIsolation(root);
            TestLastKnownGoodRecovery(root);
            TestSchedulingAndSeparateMastery();
            TestBlankSubmissionIsNonLearning();
            TestAnswerHiddenPresentation();
            TestSentenceReadyContract();
            TestShortcutRegistry();
            TestProfileRoundTrip(root);
            TestMigrationBackup(root);
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    private static void TestStateRestartAndIsolation(string root)
    {
        string recall = Path.Combine(root, "state.json");
        string spelling = Path.Combine(root, "spelling-state.json");
        File.WriteAllText(recall, "RECALL-SENTINEL");
        File.WriteAllText(spelling, "SPELLING-SENTINEL");
        byte[] recallBefore = File.ReadAllBytes(recall);
        byte[] spellingBefore = File.ReadAllBytes(spelling);

        var store = new ListeningStateStore(root);
        ListeningCoachState state = store.Load();
        state.ActiveScopeId = StudyScopeIds.B2;
        state.StatsByDictionary["test"] = new Dictionary<string, ListeningItemStats>(StringComparer.OrdinalIgnoreCase)
        {
            ["word:a"] = new() { CompletedReviews = 2, CorrectReviews = 1, WrongAttempts = 1 }
        };
        store.Save(state);
        ListeningCoachState restarted = store.Load();
        Require(restarted.ActiveScopeId == StudyScopeIds.B2, "Listening scope did not survive restart.");
        Require(restarted.StatsByDictionary["test"]["word:a"].CompletedReviews == 2, "Listening stats did not survive restart.");
        Require(recallBefore.SequenceEqual(File.ReadAllBytes(recall)), "Listening state changed Recall state.");
        Require(spellingBefore.SequenceEqual(File.ReadAllBytes(spelling)), "Listening state changed Spelling state.");
    }

    private static void TestLastKnownGoodRecovery(string root)
    {
        string recoveryRoot = Path.Combine(root, "recovery-case");
        Directory.CreateDirectory(recoveryRoot);
        var store = new ListeningStateStore(recoveryRoot);

        ListeningCoachState first = store.Load();
        first.ActiveScopeId = StudyScopeIds.A1;
        first.StatsByDictionary["test"] = new Dictionary<string, ListeningItemStats>(StringComparer.OrdinalIgnoreCase)
        {
            ["word:a"] = new() { CompletedReviews = 1, CorrectReviews = 1 }
        };
        store.Save(first);

        ListeningCoachState second = store.Load();
        second.ActiveScopeId = StudyScopeIds.C1;
        second.StatsByDictionary["test"]["word:a"].CompletedReviews = 2;
        second.StatsByDictionary["test"]["word:a"].CorrectReviews = 1;
        store.Save(second);

        string primary = Path.Combine(recoveryRoot, "listening-state.json");
        string recovery = Path.Combine(recoveryRoot, "listening-state.backup.json");
        Require(File.Exists(recovery), "Second Listening save did not preserve a last-known-good recovery copy.");

        File.WriteAllText(primary, "{ broken primary");
        ListeningCoachState recovered = store.Load();
        Require(recovered.ActiveScopeId == StudyScopeIds.A1 && recovered.StatsByDictionary["test"]["word:a"].CompletedReviews == 1,
            "Corrupted Listening primary did not recover the previous verified state.");

        File.WriteAllText(recovery, "{ broken recovery");
        bool rejected = false;
        try { _ = store.Load(); } catch (InvalidDataException) { rejected = true; }
        Require(rejected, "Corrupted Listening primary and recovery did not fail closed.");
        Require(File.ReadAllText(primary) == "{ broken primary" && File.ReadAllText(recovery) == "{ broken recovery",
            "Fail-closed Listening recovery unexpectedly rewrote corrupted evidence files.");
    }

    private static void TestSchedulingAndSeparateMastery()
    {
        DictionaryPackage package = Package();
        var source = new FakeSource(new[]
        {
            Word("a", "alpha", "A1"), Word("b", "bravo", "A1"), Word("c", "charlie", "A1")
        });
        var state = new ListeningCoachState { ActiveScopeId = StudyScopeIds.A1 };
        state.StatsByDictionary[package.Id] = new(StringComparer.OrdinalIgnoreCase)
        {
            ["word:a"] = new() { CompletedReviews = 10, CorrectReviews = 10, ConsecutiveCorrect = 10, LastReviewedUtc = DateTimeOffset.UtcNow },
            ["word:b"] = new() { CompletedReviews = 3, CorrectReviews = 0, WrongAttempts = 4, LastReviewedUtc = DateTimeOffset.UtcNow },
            ["word:c"] = new() { CompletedReviews = 8, CorrectReviews = 8, ConsecutiveCorrect = 8, LastReviewedUtc = DateTimeOffset.UtcNow }
        };
        var engine = new ListeningCoachEngine(package, state, source);
        ListeningExercise next = engine.StartNext(false);
        Require(next.ExerciseId == "word:b", "Weak-item scheduling did not prioritize the listening weakness.");
        ListeningCheckResult wrong = engine.Check("wrong");
        Require(!wrong.IsCorrect && !wrong.Completed, "Wrong listening answer should remain retryable.");
        ListeningCheckResult correct = engine.Check("bravo");
        Require(correct.IsCorrect && correct.Completed, "Correct listening answer did not complete review.");
        Require(state.StatsByDictionary[package.Id]["word:b"].CompletedReviews == 4, "Listening completion was not recorded independently.");
    }

    private static void TestBlankSubmissionIsNonLearning()
    {
        DictionaryPackage package = Package();
        var state = new ListeningCoachState { ActiveScopeId = StudyScopeIds.A1 };
        var engine = new ListeningCoachEngine(package, state, new FakeSource(new[] { Word("a", "alpha", "A1") }));
        _ = engine.StartNext(false);

        ListeningCheckResult blank = engine.Check("   \t\r\n");
        Require(!blank.IsCorrect && !blank.Completed, "Blank Listening submit must remain retryable.");
        Require(!state.StatsByDictionary.TryGetValue(package.Id, out Dictionary<string, ListeningItemStats>? stats) ||
                !stats.TryGetValue("word:a", out ListeningItemStats? item) ||
                (item.WrongAttempts == 0 && item.CompletedReviews == 0),
            "Blank Listening submit mutated learning statistics.");
        Require(state.History.Count == 0, "Blank Listening submit created study history.");
    }

    private static void TestAnswerHiddenPresentation()
    {
        ListeningExercise exercise = Word("secret", "never-display-before-check", "B1");
        string before = ListeningCoachPresentation.BeforeCheck(exercise);
        Require(!before.Contains(exercise.TargetText, StringComparison.OrdinalIgnoreCase), "Listening presentation leaked the answer before checking.");
        Require(ListeningCoachPresentation.AfterShow(exercise).Contains(exercise.TargetText, StringComparison.Ordinal), "Explicit show did not expose the requested answer.");
    }

    private static void TestSentenceReadyContract()
    {
        DictionaryPackage package = Package();
        var sentence = new ListeningExercise(
            "sentence:s1", ListeningExerciseKind.Sentence, "We learn from context.", "B1", new[] { "a", "b" }, "sentence-audio:s1");
        var state = new ListeningCoachState();
        var source = new FakeSource(new[] { sentence });
        var engine = new ListeningCoachEngine(package, state, source);
        ListeningExercise selected = engine.StartNext(false);
        Require(selected.Kind == ListeningExerciseKind.Sentence, "Listening engine rejected sentence-ready source contract.");
        Require(engine.Check("  WE learn from context. ").IsCorrect, "Sentence-ready normalization failed.");
    }

    private static void TestShortcutRegistry()
    {
        AppState app = AppStateStore.Normalize(new AppState());
        var all = new ShortcutManager(app, Array.Empty<DeckDefinition>(), ShortcutDispatchContext.All);
        Require(all.Get(ActionIds.OpenListening) == (Keys.Control | Keys.Alt | Keys.L), "Listening open shortcut default is missing.");
        Require(all.Get(ActionIds.ListeningReplay) != Keys.None && all.Get(ActionIds.ListeningShowAnswer) != Keys.None && all.Get(ActionIds.ListeningNext) != Keys.None,
            "Listening in-mode shortcuts collide with the global shortcut registry.");

        var recallOnly = new ShortcutManager(app);
        Require(!recallOnly.Definitions.Any(def => def.Id.StartsWith("listening_", StringComparison.OrdinalIgnoreCase)),
            "Listening shortcuts leaked into the Recall-only fallback registry.");

        var listening = new ShortcutManager(app, null, ShortcutDispatchContext.Listening);
        Keys replay = listening.Get(ActionIds.ListeningReplay);
        Require(listening.FindAction(replay) == ActionIds.ListeningReplay, "Listening dispatch context did not route replay.");
        Require(listening.FindAction(Keys.Control | Keys.P) is null, "Listening context incorrectly routed a Recall shortcut.");

        Keys remapped = Keys.Control | Keys.Shift | Keys.Alt | Keys.F9;
        Require(listening.TrySet(ActionIds.ListeningReplay, remapped, out string? error), $"Listening replay could not be remapped: {error}");
        Require(listening.Get(ActionIds.ListeningReplay) == remapped && listening.FindAction(remapped) == ActionIds.ListeningReplay,
            "Listening remapped shortcut was not used by dispatch.");
    }

    private static void TestProfileRoundTrip(string root)
    {
        var store = new ListeningStateStore(root);
        ListeningCoachState state = store.Load();
        state.ActiveScopeId = StudyScopeIds.C1;
        store.Save(state);
        string profile = Path.Combine(root, "export", "listening.json");
        var service = new ListeningProfileService(store);
        service.Export(state, profile);
        state.ActiveScopeId = StudyScopeIds.A1;
        store.Save(state);
        string? backup = service.Import(profile);
        Require(backup is not null && File.Exists(backup), "Listening profile import did not create recovery backup.");
        Require(store.Load().ActiveScopeId == StudyScopeIds.C1, "Listening profile round trip failed.");
    }

    private static void TestMigrationBackup(string root)
    {
        string migrationRoot = Path.Combine(root, "migration");
        Directory.CreateDirectory(migrationRoot);
        string statePath = Path.Combine(migrationRoot, "listening-state.json");
        File.WriteAllText(statePath, "{\"SchemaVersion\":0,\"ActiveScopeId\":\"a2\",\"SelectionCounter\":0,\"StatsByDictionary\":{},\"History\":[]}");
        var store = new ListeningStateStore(migrationRoot);
        ListeningCoachState migrated = store.Load();
        Require(migrated.SchemaVersion == ListeningStateStore.CurrentSchemaVersion, "Listening schema migration did not complete.");
        Require(Directory.GetFiles(Path.Combine(migrationRoot, "Backups"), "listening-state-*-pre-migration.json").Length == 1, "Listening migration did not preserve a backup.");
    }

    private static DictionaryPackage Package() => new()
    {
        Id = "test-dictionary",
        Name = "Test",
        SourceLanguage = "en",
        TargetLanguage = "uk",
        Entries = new[]
        {
            new DictionaryEntry("a", "A1", "alpha", "альфа"),
            new DictionaryEntry("b", "A1", "bravo", "браво"),
            new DictionaryEntry("c", "A1", "charlie", "чарлі")
        }
    };

    private static ListeningExercise Word(string id, string target, string level) =>
        new($"word:{id}", ListeningExerciseKind.Word, target, level, new[] { id }, id);

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException("Listening self-test failed: " + message);
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