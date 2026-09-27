namespace WordDeck;

internal static class RecallPersistenceSafetySelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg =>
                string.Equals(arg, "--self-test", StringComparison.OrdinalIgnoreCase)))
            RecallPersistenceSafetySelfTest.Run();
    }
}

internal static class RecallPersistenceSafetySelfTest
{
    public static void Run()
    {
        TestSuccessfulSaveAllowsClose();
        TestFailedSaveBlocksCloseAndPreservesReason();
        TestDeckAssignmentsMustBeReacquiredAfterNormalization();
        Console.WriteLine("WordDeck Recall close-persistence self-test passed: successful saves allow close and failed saves remain inside the Recall window boundary.");
    }

    private static void TestSuccessfulSaveAllowsClose()
    {
        int calls = 0;
        bool saved = RecallPersistenceSafety.TrySave(() => calls++, out string? error);

        Require(saved, "Successful Recall close persistence was rejected.");
        Require(calls == 1, "Recall close persistence did not invoke the save action exactly once.");
        Require(error is null, "Successful Recall close persistence returned an error.");
    }

    private static void TestFailedSaveBlocksCloseAndPreservesReason()
    {
        int calls = 0;
        bool saved = RecallPersistenceSafety.TrySave(() =>
        {
            calls++;
            throw new IOException("simulated recall close write failure");
        }, out string? error);

        Require(!saved, "Failed Recall close persistence was reported as successful.");
        Require(calls == 1, "Failed Recall close persistence did not invoke the save action exactly once.");
        Require(error is not null && error.Contains("simulated recall close write failure", StringComparison.Ordinal),
            "Failed Recall close persistence did not preserve the storage failure reason.");
    }

    private static void TestDeckAssignmentsMustBeReacquiredAfterNormalization()
    {
        const string dictionaryId = "recall-persistence-map-test";
        var entries = new List<DictionaryEntry>
        {
            new("entry-one", "A1", "one", "один")
        };

        AppState state = AppStateStore.Normalize(new AppState());
        var scopes = new RecallStudyScopeService(state, dictionaryId, entries);
        Dictionary<string, string> cachedBeforeNormalize = scopes.Assignments(StudyScopeIds.All);
        scopes.Move(StudyScopeIds.All, "entry-one", DeckIds.Core(2));
        Require(cachedBeforeNormalize["entry-one"] == DeckIds.Core(2),
            "Recall persistence fixture did not establish the pre-normalization assignment.");

        AppStateStore.Normalize(state);
        Dictionary<string, string> authoritativeAfterNormalize = scopes.Assignments(StudyScopeIds.All);
        Require(!ReferenceEquals(cachedBeforeNormalize, authoritativeAfterNormalize),
            "Recall persistence regression fixture no longer replaces the scope assignment dictionary during normalization.");

        scopes.Move(StudyScopeIds.All, "entry-one", DeckIds.Core(3));
        Require(authoritativeAfterNormalize["entry-one"] == DeckIds.Core(3),
            "Reacquired Recall assignment map did not track authoritative scope changes.");
        Require(cachedBeforeNormalize["entry-one"] == DeckIds.Core(2),
            "Detached pre-normalization Recall assignment map unexpectedly remained authoritative.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException("Recall close-persistence self-test failed: " + message);
    }
}
