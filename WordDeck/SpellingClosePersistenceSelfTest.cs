using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class SpellingClosePersistenceSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg =>
                string.Equals(arg, "--self-test", StringComparison.OrdinalIgnoreCase)))
            SpellingClosePersistenceSelfTest.Run();
    }
}

internal static class SpellingClosePersistenceSelfTest
{
    public static void Run()
    {
        TestSuccessfulSaveAllowsClose();
        TestFailedSaveBlocksCloseWithoutEscaping();
        Console.WriteLine("WordDeck Spelling close-persistence self-test passed: successful saves allow close and failed saves are surfaced without escaping the close boundary.");
    }

    private static void TestSuccessfulSaveAllowsClose()
    {
        int calls = 0;
        bool saved = SpellingClosePersistence.TrySave(() => calls++, out string? error);
        Require(saved, "Successful Spelling close persistence was rejected.");
        Require(calls == 1, "Spelling close persistence did not invoke the save action exactly once.");
        Require(error is null, "Successful Spelling close persistence returned an error.");
    }

    private static void TestFailedSaveBlocksCloseWithoutEscaping()
    {
        int calls = 0;
        bool saved = SpellingClosePersistence.TrySave(() =>
        {
            calls++;
            throw new IOException("simulated spelling close write failure");
        }, out string? error);

        Require(!saved, "Failed Spelling close persistence was reported as successful.");
        Require(calls == 1, "Failed Spelling close persistence did not invoke the save action exactly once.");
        Require(error is not null && error.Contains("simulated spelling close write failure", StringComparison.Ordinal),
            "Failed Spelling close persistence did not return the storage failure reason.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException("Spelling close-persistence self-test failed: " + message);
    }
}
