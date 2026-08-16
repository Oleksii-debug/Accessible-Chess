using System.Windows.Forms.Automation;

namespace WordDeck;

internal static class AccessibilityAnnouncer
{
    public static void Install()
    {
        // Intentionally event-driven. MainForm raises announcements exactly when the
        // card, translation, or requested repeat changes. Avoid polling the UI tree.
    }

    public static void Announce(Control control, string text)
    {
        if (string.IsNullOrWhiteSpace(text))
            return;

        try
        {
            control.AccessibilityObject.RaiseAutomationNotification(
                AutomationNotificationKind.Other,
                AutomationNotificationProcessing.ImportantMostRecent,
                text);
        }
        catch
        {
            // UI Automation notifications depend on the Windows accessibility stack.
            // Native WinForms controls and focus remain the fallback for screen readers.
        }
    }
}
