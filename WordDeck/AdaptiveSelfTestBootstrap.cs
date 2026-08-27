using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class AdaptiveSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (!Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            return;

        AdaptiveMasteryRouterSelfTest.Run();
        AdaptiveGrammarEvidenceSelfTest.Run();
        Console.WriteLine("WordDeck global adaptive mastery self-test PASS.");
    }
}
