namespace WordDeck;

internal static class DeckDialogs
{
    public static string? PromptForName(IWin32Window owner, string title, string prompt, string initialValue = "")
    {
        using var form = new Form
        {
            Text = title,
            StartPosition = FormStartPosition.CenterParent,
            Width = 520,
            Height = 190,
            MinimizeBox = false,
            MaximizeBox = false,
            AccessibleName = title
        };

        var label = new Label
        {
            Text = prompt,
            Dock = DockStyle.Top,
            AutoSize = true,
            Padding = new Padding(12),
            AccessibleName = prompt
        };
        var text = new TextBox
        {
            Text = initialValue,
            Dock = DockStyle.Top,
            AccessibleName = "Deck name"
        };
        var buttons = new FlowLayoutPanel
        {
            Dock = DockStyle.Bottom,
            AutoSize = true,
            FlowDirection = FlowDirection.RightToLeft,
            Padding = new Padding(8)
        };
        var cancel = new Button { Text = "Cancel", DialogResult = DialogResult.Cancel, AutoSize = true, AccessibleName = "Cancel" };
        var ok = new Button { Text = "OK", DialogResult = DialogResult.OK, AutoSize = true, AccessibleName = "Confirm deck name" };
        buttons.Controls.Add(cancel);
        buttons.Controls.Add(ok);
        form.Controls.Add(text);
        form.Controls.Add(label);
        form.Controls.Add(buttons);
        form.AcceptButton = ok;
        form.CancelButton = cancel;
        form.Shown += (_, _) =>
        {
            text.Focus();
            text.SelectAll();
        };

        return form.ShowDialog(owner) == DialogResult.OK ? text.Text : null;
    }

    public static string? ChooseDeck(
        IWin32Window owner,
        string title,
        string prompt,
        IEnumerable<DeckDefinition> decks,
        string? initialDeckId = null)
    {
        List<DeckDefinition> choices = decks.ToList();
        if (choices.Count == 0)
            return null;

        using var form = new Form
        {
            Text = title,
            StartPosition = FormStartPosition.CenterParent,
            Width = 560,
            Height = 210,
            MinimizeBox = false,
            MaximizeBox = false,
            AccessibleName = title
        };
        var label = new Label
        {
            Text = prompt,
            Dock = DockStyle.Top,
            AutoSize = true,
            Padding = new Padding(12),
            AccessibleName = prompt
        };
        var combo = new ComboBox
        {
            Dock = DockStyle.Top,
            DropDownStyle = ComboBoxStyle.DropDownList,
            DisplayMember = nameof(DeckDefinition.Name),
            AccessibleName = "Destination deck"
        };
        foreach (DeckDefinition deck in choices)
            combo.Items.Add(deck);
        int index = choices.FindIndex(deck => string.Equals(deck.Id, initialDeckId, StringComparison.OrdinalIgnoreCase));
        combo.SelectedIndex = index >= 0 ? index : 0;

        var buttons = new FlowLayoutPanel
        {
            Dock = DockStyle.Bottom,
            AutoSize = true,
            FlowDirection = FlowDirection.RightToLeft,
            Padding = new Padding(8)
        };
        var cancel = new Button { Text = "Cancel", DialogResult = DialogResult.Cancel, AutoSize = true, AccessibleName = "Cancel" };
        var ok = new Button { Text = "OK", DialogResult = DialogResult.OK, AutoSize = true, AccessibleName = "Confirm destination deck" };
        buttons.Controls.Add(cancel);
        buttons.Controls.Add(ok);
        form.Controls.Add(combo);
        form.Controls.Add(label);
        form.Controls.Add(buttons);
        form.AcceptButton = ok;
        form.CancelButton = cancel;
        form.Shown += (_, _) => combo.Focus();

        if (form.ShowDialog(owner) != DialogResult.OK || combo.SelectedItem is not DeckDefinition selected)
            return null;
        return selected.Id;
    }
}
