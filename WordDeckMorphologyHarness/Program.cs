namespace WordDeck;

internal static class Program
{
    private static int Main()
    {
        try
        {
            MorphologySelfTest.Run();
            MorphologyPracticeSelfTest.Run();
            MorphologyFamilyGraphSelfTest.Run();
            MorphologyDiagnosticsSelfTest.Run();
            MorphologyContextPolicySelfTest.Run();
            MorphologyReadingBridgeSelfTest.Run();
            Console.WriteLine("WordDeck morphology self-test PASS.");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"WordDeck morphology self-test FAILED: {ex}");
            return 1;
        }
    }
}
