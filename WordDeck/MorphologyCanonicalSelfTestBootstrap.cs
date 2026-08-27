using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class MorphologyCanonicalSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (!Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            return;

        MorphologySelfTest.Run();
        MorphologyPracticeSelfTest.Run();
        MorphologyFamilyGraphSelfTest.Run();
        MorphologyDiagnosticsSelfTest.Run();
        MorphologyContextPolicySelfTest.Run();
        MorphologyGrammarBridgeSelfTest.Run();
        MorphologyReadingBridgeSelfTest.Run();
        MorphologyCandidateAnalysisCommandSelfTest.Run();
        Console.WriteLine("WordDeck morphology canonical self-test PASS.");
    }
}
