using System.Runtime.CompilerServices;

namespace WordDeck;

// Keep these safety tests in the ordinary WordDeck --self-test path so a future
// Context corpus change cannot silently turn a surface-form match into a POS/sense claim
// or weaken the evidence digest boundary.
internal static class ContextStableIdentityResolutionSelfTestBootstrap
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
