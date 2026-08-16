namespace WordDeck;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            return SelfTest.Run();

        ApplicationConfiguration.Initialize();
        AccessibilityAnnouncer.Install();
        Application.Run(new MainForm());
        return 0;
    }
}
