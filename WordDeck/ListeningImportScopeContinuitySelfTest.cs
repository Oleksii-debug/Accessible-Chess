using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class ListeningImportScopeContinuitySelfTest
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (!Environment.GetCommandLineArgs().Any(arg => string.Equals(arg, "--self-test", StringComparison.OrdinalIgnoreCase))) return;
        Run();
    }

    private static void Run()
    {
        Require(!ListeningCoachForm.ShouldApplyScopeChange(StudyScopeIds.B1, "b1"),
            "Programmatic scope synchronization would be treated as a real scope change and could discard an imported unfinished Listening item.");
        Require(ListeningCoachForm.ShouldApplyScopeChange(StudyScopeIds.A2, StudyScopeIds.B1),
            "A real learner-initiated Listening scope change was incorrectly suppressed.");
        Console.WriteLine("WordDeck Listening import-scope continuity self-test passed.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
}
