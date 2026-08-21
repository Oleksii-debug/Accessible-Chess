namespace WordDeck;

internal sealed class SpellingAccessibilityBehavior : IMessageFilter, IDisposable
{
    private const int WmKeyDown = 0x0100;
    private const int WmSysKeyDown = 0x0104;
    private readonly Form _form;
    private readonly ShortcutManager _shortcuts;
    private bool _installed;

    private SpellingAccessibilityBehavior(Form form, ShortcutManager shortcuts)
    {
        _form = form;
        _shortcuts = shortcuts;
    }

    public static SpellingAccessibilityBehavior Install(Form form, ShortcutManager shortcuts)
    {
        var behavior = new SpellingAccessibilityBehavior(form, shortcuts);
        behavior.AddHelpMenu();
        Application.AddMessageFilter(behavior);
        behavior._installed = true;
        form.FormClosed += (_, _) => behavior.Dispose();
        return behavior;
    }

    public bool PreFilterMessage(ref Message m)
    {
        if (m.Msg != WmKeyDown && m.Msg != WmSysKeyDown) return false;
        if (!_form.ContainsFocus && Form.ActiveForm != _form) return false;
        Keys keyCode = (Keys)(int)m.WParam & Keys.KeyCode;
        if (keyCode != Keys.F1) return false;
        ShowHelp();
        return true;
    }

    private void AddHelpMenu()
    {
        MenuStrip? menu = _form.MainMenuStrip;
        if (menu is null) return;
        if (menu.Items.OfType<ToolStripMenuItem>().Any(item =>
                (item.Text ?? string.Empty).Replace("&", string.Empty).Equals("Help", StringComparison.OrdinalIgnoreCase)))
            return;

        var help = new ToolStripMenuItem("&Help") { AccessibleName = "Spelling help" };
        var helpItem = new ToolStripMenuItem("&Spelling help")
        {
            AccessibleName = "Open Spelling help"
        };
        helpItem.Click += (_, _) => ShowHelp();
        help.DropDownItems.Add(helpItem);
        menu.Items.Add(help);
    }

    private void ShowHelp()
    {
        string shortcutLines = string.Join(
            Environment.NewLine,
            _shortcuts.Definitions
                .Where(definition => definition.Id.StartsWith("spelling.", StringComparison.OrdinalIgnoreCase) ||
                                     definition.Id == ActionIds.OpenSpelling ||
                                     definition.Id == ActionIds.Help)
                .Select(definition => $"{definition.Description}: {ShortcutFormatter.Format(_shortcuts.Get(definition.Id))}"));

        string text =
            "WORDDECK SPELLING HELP\r\n\r\n" +
            "Type the exact English spelling for the Ukrainian prompt and press Enter. " +
            "The five Spelling decks are independent from Recall decks. The adaptive coach uses only your local spelling history.\r\n\r\n" +
            "F1 opens this help. Close the Spelling window with the standard Windows shortcut Alt+F4. " +
            "Alt+F4 returns you to the main WordDeck window and does not delete learning progress.\r\n\r\n" +
            "KEYBOARD SHORTCUTS\r\n" + shortcutLines;

        using var helpForm = new Form
        {
            Text = "WordDeck Spelling help",
            Width = 760,
            Height = 560,
            StartPosition = FormStartPosition.CenterParent,
            AccessibleName = "WordDeck Spelling help"
        };
        var box = new TextBox
        {
            Dock = DockStyle.Fill,
            Multiline = true,
            ReadOnly = true,
            ScrollBars = ScrollBars.Vertical,
            Text = text,
            AccessibleName = "Spelling help text",
            TabStop = true
        };
        helpForm.Controls.Add(box);
        helpForm.Shown += (_, _) =>
        {
            box.Focus();
            box.SelectionStart = 0;
            box.SelectionLength = 0;
        };
        helpForm.ShowDialog(_form);
    }

    public void Dispose()
    {
        if (!_installed) return;
        Application.RemoveMessageFilter(this);
        _installed = false;
    }
}
