using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class StoryCourseSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            StoryCourseSelfTest.Run();
    }
}
