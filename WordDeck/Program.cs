namespace WordDeck;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();
        AccessibilityAnnouncer.Install();
        Application.Run(new MainForm());
    }
}
