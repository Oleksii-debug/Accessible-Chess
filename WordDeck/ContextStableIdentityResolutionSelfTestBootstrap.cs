using System.Runtime.CompilerServices;

namespace WordDeck;

// Keep this safety test in the ordinary WordDeck --self-test path so a future
// Context corpus change cannot silently turn a surface-form match into a POS/sense claim.
internal static class ContextStableIdentityResolutionSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            ContextStableIdentityResolutionSelfTest.Run();
    }
}
