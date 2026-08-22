using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class Round3SentenceSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (!Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            return;
        SentenceRound2SelfTest.Run();
    }
}
