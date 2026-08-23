using System.Runtime.CompilerServices;

namespace WordDeck;

/// <summary>
/// Ensures the stable-ID/POS-sense ambiguity boundary participates in every normal
/// WordDeck --self-test run. These tests are intentionally separate from synthetic
/// SentencePack fixtures and protect the evidence semantics required by Stage 11.
/// </summary>
internal static class ContextStableIdentitySelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (!Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            return;

        ContextStableIdentityResolutionSelfTest.Run();
        ContextStableIdentityCoverageEvidenceSelfTest.Run();
    }
}
