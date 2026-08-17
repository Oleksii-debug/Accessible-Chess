namespace WordDeck;

internal sealed record WordPair(string Source, string Target);

internal static class BulkWordParser
{
    public static IReadOnlyList<WordPair> Parse(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
            throw new InvalidDataException("Paste at least one English/Ukrainian pair.");

        var result = new List<WordPair>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        string[] lines = text.Replace("\r\n", "\n").Replace('\r', '\n').Split('\n');

        for (int i = 0; i < lines.Length; i++)
        {
            string line = lines[i].Trim();
            if (line.Length == 0)
                continue;

            (string source, string target) = SplitPair(line, i + 1);
            string duplicateKey = source + "\u001f" + target;
            if (!seen.Add(duplicateKey))
                continue;
            result.Add(new WordPair(source, target));
        }

        if (result.Count == 0)
            throw new InvalidDataException("No usable word pairs were found.");
        return result;
    }

    private static (string Source, string Target) SplitPair(string line, int lineNumber)
    {
        // One line is always one card. TAB is the preferred unambiguous separator;
        // the other separators are conveniences for text copied from Word or chat.
        string[] separators = { "\t", " | ", " = ", " — ", " – ", ", " };
        foreach (string separator in separators)
        {
            int index = line.IndexOf(separator, StringComparison.Ordinal);
            if (index <= 0)
                continue;

            string source = line[..index].Trim();
            string target = line[(index + separator.Length)..].Trim();
            if (source.Length == 0 || target.Length == 0)
                break;
            return (source, target);
        }

        throw new InvalidDataException(
            $"Line {lineNumber} is not understood. Use one card per line, preferably English<TAB>Ukrainian. " +
            "Also accepted: English | Ukrainian, English = Ukrainian, English — Ukrainian, or English, Ukrainian.");
    }
}

internal sealed class BulkWordImportForm : Form
{
    private readonly TextBox _editor;
    public string PastedText => _editor.Text;

    public BulkWordImportForm(string deckName)
    {
        Text = "Add words to active deck";
        Width = 780;
        Height = 600;
        MinimumSize = new Size(600, 420);
        StartPosition = FormStartPosition.CenterParent;
        AccessibleName = "Bulk add words";

        var instructions = new TextBox
        {
            Dock = DockStyle.Top,
            Height = 125,
            Multiline = true,
            ReadOnly = true,
            TabStop = true,
            AccessibleName = "Word import format instructions",
            Text =
                $"Words will be added to: {deckName}.\r\n" +
                "Use ONE CARD PER LINE. Recommended format: English, then TAB, then Ukrainian.\r\n" +
                "Example: apple<TAB>яблуко\r\n" +
                "Phrases are safe: take care of<TAB>піклуватися про.\r\n" +
                "Also accepted between English and Ukrainian: |, =, an em dash, or comma+space."
        };

        _editor = new TextBox
        {
            Dock = DockStyle.Fill,
            Multiline = true,
            AcceptsTab = true,
            ScrollBars = ScrollBars.Both,
            WordWrap = false,
            AccessibleName = "Paste English and Ukrainian word pairs here",
            AccessibleDescription = "One card per line. English first, Ukrainian second. Tab is the recommended separator."
        };

        var buttons = new FlowLayoutPanel
        {
            Dock = DockStyle.Bottom,
            Height = 54,
            Padding = new Padding(8),
            FlowDirection = FlowDirection.LeftToRight
        };
        var add = new Button
        {
            Text = "Add words",
            AutoSize = true,
            DialogResult = DialogResult.OK,
            AccessibleName = "Add pasted words to active deck"
        };
        var cancel = new Button
        {
            Text = "Cancel",
            AutoSize = true,
            DialogResult = DialogResult.Cancel,
            AccessibleName = "Cancel adding words"
        };
        buttons.Controls.Add(add);
        buttons.Controls.Add(cancel);

        Controls.Add(_editor);
        Controls.Add(instructions);
        Controls.Add(buttons);
        AcceptButton = add;
        CancelButton = cancel;
        Shown += (_, _) => _editor.Focus();
    }
}