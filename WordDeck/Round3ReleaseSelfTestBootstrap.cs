using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class Round3ReleaseSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (!Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            return;
        ReleaseRegressionSelfTest.Run();
        ReleaseStateFailureSelfTest.Run();
        Console.WriteLine("WordDeck Round-3 release/state regression passed: Recall, Spelling and Sentence recovery/fail-closed contracts validated.");
    }
}
