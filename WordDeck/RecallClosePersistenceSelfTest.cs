using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class RecallClosePersistenceSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg =>
                string.Equals(arg, "--self-test", StringComparison.OrdinalIgnoreCase)))
            RecallClosePersistenceSelfTest.Run();
    }
}

internal static class RecallClosePersistenceSelfTest
{
    public static void Run()
    {
        TestSuccessfulSaveAllowsClose();
        TestFailedSaveBlocksCloseAndPreservesReason();
        Console.WriteLine("WordDeck Recall close-persistence self-test passed: successful saves allow close and failed saves remain inside the Recall window boundary.");
    }

    private static void TestSuccessfulSaveAllowsClose()
    {
        int calls = 0;
        bool saved = RecallClosePersistence.TrySave(() => calls++, out string? error);

        Require(saved, "Successful Recall close persistence was rejected.");
        Require(calls == 1, "Recall close persistence did not invoke the save action exactly once.");
        Require(error is null, "Successful Recall close persistence returned an error.");
    }

    private static void TestFailedSaveBlocksCloseAndPreservesReason()
    {
        int calls = 0;
        bool saved = RecallClosePersistence.TrySave(() =>
        {
            calls++;
            throw new IOException("simulated recall close write failure");
        }, out string? error);

        Require(!saved, "Failed Recall close persistence was reported as successful.");
        Require(calls == 1, "Failed Recall close persistence did not invoke the save action exactly once.");
        Require(error is not null && error.Contains("simulated recall close write failure", StringComparison.Ordinal),
            "Failed Recall close persistence did not preserve the storage failure reason.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException("Recall close-persistence self-test failed: " + message);
    }
}
