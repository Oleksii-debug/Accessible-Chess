using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class ShortcutCaptureAccessibilitySelfTest
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
        Require(ShortcutCaptureKeyboardPolicy.IsNativeDialogChord(Keys.Alt | Keys.F4),
            "Alt+F4 must remain the standard Windows close command in shortcut capture.");
        Require(ShortcutCaptureKeyboardPolicy.IsNativeDialogChord(Keys.Tab),
            "Plain Tab must remain native forward focus navigation in shortcut capture.");
        Require(ShortcutCaptureKeyboardPolicy.IsNativeDialogChord(Keys.Shift | Keys.Tab),
            "Shift+Tab must remain native reverse focus navigation in shortcut capture.");
        Require(!ShortcutCaptureKeyboardPolicy.IsNativeDialogChord(Keys.Control | Keys.Tab),
            "Ctrl+Tab is a candidate chord and must not be silently treated as plain dialog navigation.");
        Require(!ShortcutCaptureKeyboardPolicy.IsNativeDialogChord(Keys.Control | Keys.S),
            "Ordinary candidate shortcuts must remain capturable.");
        Require(!ShortcutCaptureKeyboardPolicy.IsNativeDialogChord(Keys.F4),
            "Unmodified F4 must remain a candidate shortcut rather than masquerading as Alt+F4.");

        Console.WriteLine("WordDeck shortcut-capture accessibility self-test passed: Alt+F4 and native Tab navigation preserved.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException("Shortcut capture accessibility self-test failed: " + message);
    }
}
