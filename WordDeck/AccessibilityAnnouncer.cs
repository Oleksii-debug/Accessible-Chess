using System.Windows.Forms.Automation;

namespace WordDeck;

internal static class AccessibilityAnnouncer
{
    private static readonly System.Windows.Forms.Timer Timer = new() { Interval = 80 };
    private static string? _lastWord;
    private static string? _lastTranslation;

    public static void Install()
    {
        Timer.Tick += (_, _) => Poll();
        Timer.Start();
    }

    private static void Poll()
    {
        Form? form = Application.OpenForms.Cast<Form>().FirstOrDefault(f => f is MainForm && f.Visible);
        if (form is null)
            return;

        TextBox? wordBox = FindByAccessibleName<TextBox>(form, "Current English word");
        TextBox? translationBox = FindByAccessibleName<TextBox>(form, "Ukrainian translation");

        if (wordBox is not null)
        {
            string word = wordBox.Text.Trim();
            if (word.Length > 0 && word != "No words in this deck" && !string.Equals(word, _lastWord, StringComparison.Ordinal))
            {
                _lastWord = word;
                _lastTranslation = null;
                Announce(wordBox, word);
            }
        }

        if (translationBox is not null)
        {
            string translation = translationBox.Text.Trim();
            if (translation.Length == 0)
            {
                _lastTranslation = null;
            }
            else if (!string.Equals(translation, _lastTranslation, StringComparison.Ordinal))
            {
                _lastTranslation = translation;
                Announce(translationBox, translation);
            }
        }
    }

    private static void Announce(Control control, string text)
    {
        try
        {
            control.AccessibilityObject.RaiseAutomationNotification(
                AutomationNotificationKind.Other,
                AutomationNotificationProcessing.ImportantMostRecent,
                text);
        }
        catch
        {
            // Accessibility notification support depends on the Windows UI Automation stack.
            // The native WinForms controls remain usable even if notification delivery is unavailable.
        }
    }

    private static T? FindByAccessibleName<T>(Control root, string accessibleName) where T : Control
    {
        foreach (Control child in root.Controls)
        {
            if (child is T typed && string.Equals(child.AccessibleName, accessibleName, StringComparison.Ordinal))
                return typed;

            T? nested = FindByAccessibleName<T>(child, accessibleName);
            if (nested is not null)
                return nested;
        }
        return null;
    }
}
