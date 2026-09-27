using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class DeckNameDialogSelfTest
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
        Require(!DeckNameDialogValidation.TryValidate("", out string? blankError) &&
                blankError?.Contains("blank", StringComparison.OrdinalIgnoreCase) == true,
            "Blank deck name was accepted.");
        Require(!DeckNameDialogValidation.TryValidate("   ", out _),
            "Whitespace-only deck name was accepted.");
        Require(DeckNameDialogValidation.TryValidate("  Review later  ", out string? validError) && validError is null,
            "A valid deck name with trim-compatible outer whitespace was rejected.");
        Require(DeckNameDialogValidation.TryValidate(new string('a', 80), out _),
            "Maximum-length deck name was rejected.");
        Require(!DeckNameDialogValidation.TryValidate(new string('a', 81), out string? longError) &&
                longError?.Contains("80", StringComparison.Ordinal) == true,
            "Overlong deck name was accepted.");

        Console.WriteLine("WordDeck deck-name dialog self-test passed: invalid input is rejected before modal commit.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException("Deck-name dialog self-test failed: " + message);
    }
}
