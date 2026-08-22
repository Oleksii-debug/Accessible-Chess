using System.Runtime.CompilerServices;

namespace WordDeck;

/// <summary>
/// Prevents an empty Enter press in the Spelling/Sentence answer boxes from
/// becoming a learning event. The filter runs before WinForms dispatches the
/// key message to the form's existing Submit handler, so a rapid double-Enter
/// after a successful answer cannot turn the freshly-cleared next exercise into
/// a synthetic wrong attempt.
/// </summary>
internal sealed class BlankLearningSubmissionGuard : IMessageFilter, IDisposable
{
    private const int WmKeyDown = 0x0100;
    private readonly Form _form;
    private readonly string _answerAccessibleName;
    private bool _disposed;

    private BlankLearningSubmissionGuard(Form form, string answerAccessibleName)
    {
        _form = form ?? throw new ArgumentNullException(nameof(form));
        _answerAccessibleName = string.IsNullOrWhiteSpace(answerAccessibleName)
            ? throw new ArgumentException("Answer accessible name must not be blank.", nameof(answerAccessibleName))
            : answerAccessibleName;
        Application.AddMessageFilter(this);
    }

    public static BlankLearningSubmissionGuard Attach(Form form, string answerAccessibleName) =>
        new(form, answerAccessibleName);

    public bool PreFilterMessage(ref Message m)
    {
        if (_disposed || m.Msg != WmKeyDown || !_form.ContainsFocus)
            return false;

        Keys key = (Keys)m.WParam.ToInt32();
        if (key != Keys.Enter)
            return false;

        Control? focused = FindFocusedControl(_form);
        if (focused is not TextBoxBase textBox ||
            !string.Equals(textBox.AccessibleName, _answerAccessibleName, StringComparison.Ordinal) ||
            !ShouldSuppressBlankEnter(key, textBox.Text))
            return false;

        textBox.Focus();
        AccessibilityAnnouncer.Announce(
            textBox,
            "Type an answer before pressing Enter. No learning statistics were changed.");
        return true;
    }

    internal static bool ShouldSuppressBlankEnter(Keys key, string? text) =>
        key == Keys.Enter && string.IsNullOrWhiteSpace(text);

    private static Control? FindFocusedControl(Control root)
    {
        if (root.Focused)
            return root;

        foreach (Control child in root.Controls)
        {
            if (!child.ContainsFocus)
                continue;
            return FindFocusedControl(child) ?? child;
        }
        return null;
    }

    public void Dispose()
    {
        if (_disposed)
            return;
        _disposed = true;
        Application.RemoveMessageFilter(this);
    }
}

internal static class BlankLearningSubmissionGuardSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (!Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            return;

        Require(BlankLearningSubmissionGuard.ShouldSuppressBlankEnter(Keys.Enter, string.Empty),
            "Empty Enter was not classified as a non-learning submission.");
        Require(BlankLearningSubmissionGuard.ShouldSuppressBlankEnter(Keys.Enter, "   \t"),
            "Whitespace-only Enter was not classified as a non-learning submission.");
        Require(!BlankLearningSubmissionGuard.ShouldSuppressBlankEnter(Keys.Enter, "answer"),
            "Non-empty answer was incorrectly suppressed.");
        Require(!BlankLearningSubmissionGuard.ShouldSuppressBlankEnter(Keys.Tab, string.Empty),
            "A non-submit navigation key was incorrectly suppressed.");

        Console.WriteLine("WordDeck R4 blank-submit guard passed: empty/whitespace Enter is a non-learning event before Spelling/Sentence statistics mutation.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException("R4 blank-submit guard self-test failed: " + message);
    }
}
