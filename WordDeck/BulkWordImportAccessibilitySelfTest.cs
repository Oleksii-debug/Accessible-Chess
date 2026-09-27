using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class BulkWordImportAccessibilitySelfTest
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (!Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            return;
        Run();
    }

    internal static void Run()
    {
        Require(!BulkWordImportKeyboardPolicy.IsLiteralTabChord(Keys.Tab),
            "Plain Tab must remain navigation, not text insertion.");
        Require(!BulkWordImportKeyboardPolicy.IsLiteralTabChord(Keys.Shift | Keys.Tab),
            "Shift+Tab must remain reverse navigation.");
        Require(BulkWordImportKeyboardPolicy.IsLiteralTabChord(Keys.Control | Keys.Tab),
            "Ctrl+Tab must provide the explicit literal TAB insertion path.");
        Require(!BulkWordImportKeyboardPolicy.IsLiteralTabChord(Keys.Control | Keys.Shift | Keys.Tab),
            "Ctrl+Shift+Tab must not be silently repurposed as text insertion.");
        Require(!BulkWordImportKeyboardPolicy.IsLiteralTabChord(Keys.Alt | Keys.Tab),
            "Alt+Tab must never be treated as text insertion.");
        Require(!BulkWordImportKeyboardPolicy.IsLiteralTabChord(Keys.Control | Keys.A),
            "Only Tab with Control may request a literal separator.");

        IReadOnlyList<WordPair> parsed = BulkWordParser.Parse("apple\tяблуко");
        Require(parsed.Count == 1 && parsed[0].Source == "apple" && parsed[0].Target == "яблуко",
            "Keyboard accessibility repair must preserve TAB-separated import parsing.");

        Console.WriteLine("WordDeck bulk-import accessibility self-test passed: Tab/Shift+Tab navigation preserved, Ctrl+Tab literal separator retained.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException("Bulk import accessibility self-test failed: " + message);
    }
}
