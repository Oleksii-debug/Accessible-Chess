namespace WordDeck;

internal sealed class ShortcutSettingsForm : Form
{
    private readonly ShortcutManager _manager;
    private readonly ListView _list;

    public ShortcutSettingsForm(ShortcutManager manager)
    {
        _manager = manager;
        Text = "Keyboard shortcuts";
        StartPosition = FormStartPosition.CenterParent;
        Width = 720;
        Height = 520;
        MinimizeBox = false;
        MaximizeBox = false;
        KeyPreview = true;

        _list = new ListView
        {
            Dock = DockStyle.Fill,
            View = View.Details,
            FullRowSelect = true,
            MultiSelect = false,
            HideSelection = false,
            AccessibleName = "Shortcut actions"
        };
        _list.Columns.Add("Action", 430);
        _list.Columns.Add("Shortcut", 220);
        _list.DoubleClick += (_, _) => ChangeSelected();

        var buttons = new FlowLayoutPanel
        {
            Dock = DockStyle.Bottom,
            AutoSize = true,
            FlowDirection = FlowDirection.LeftToRight,
            Padding = new Padding(8)
        };

        var changeButton = new Button { Text = "Change selected", AutoSize = true, AccessibleName = "Change selected shortcut" };
        changeButton.Click += (_, _) => ChangeSelected();
        var resetButton = new Button { Text = "Reset defaults", AutoSize = true };
        resetButton.Click += (_, _) =>
        {
            _manager.ResetDefaults();
            RefreshList();
        };
        var closeButton = new Button { Text = "Close", AutoSize = true, DialogResult = DialogResult.OK };
        buttons.Controls.Add(changeButton);
        buttons.Controls.Add(resetButton);
        buttons.Controls.Add(closeButton);

        Controls.Add(_list);
        Controls.Add(buttons);
        AcceptButton = closeButton;
        RefreshList();
    }

    private void RefreshList()
    {
        string? selectedId = _list.SelectedItems.Count > 0 ? _list.SelectedItems[0].Tag as string : null;
        _list.BeginUpdate();
        _list.Items.Clear();
        foreach (ShortcutDefinition def in ShortcutManager.Definitions)
        {
            var item = new ListViewItem(def.Description) { Tag = def.Id };
            item.SubItems.Add(_manager.Get(def.Id).ToString());
            _list.Items.Add(item);
            if (def.Id == selectedId)
                item.Selected = true;
        }
        _list.EndUpdate();
        if (_list.Items.Count > 0 && _list.SelectedItems.Count == 0)
            _list.Items[0].Selected = true;
    }

    private void ChangeSelected()
    {
        if (_list.SelectedItems.Count == 0)
            return;

        string actionId = (string)_list.SelectedItems[0].Tag!;
        ShortcutDefinition definition = ShortcutManager.Definitions.First(x => x.Id == actionId);
        using var dialog = new ShortcutCaptureForm(definition.Description, _manager.Get(actionId));
        if (dialog.ShowDialog(this) != DialogResult.OK)
            return;

        if (!_manager.TrySet(actionId, dialog.CapturedKeys, out string? conflict))
        {
            MessageBox.Show(this, $"That shortcut is already assigned to: {conflict}.", "Shortcut conflict", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }
        RefreshList();
    }
}

internal sealed class ShortcutCaptureForm : Form
{
    private readonly TextBox _value;
    public Keys CapturedKeys { get; private set; }

    public ShortcutCaptureForm(string description, Keys current)
    {
        Text = "Press new shortcut";
        StartPosition = FormStartPosition.CenterParent;
        Width = 520;
        Height = 200;
        MinimizeBox = false;
        MaximizeBox = false;
        KeyPreview = true;
        CapturedKeys = current;

        var label = new Label
        {
            Text = $"Press the key combination for: {description}",
            Dock = DockStyle.Top,
            AutoSize = true,
            Padding = new Padding(12)
        };
        _value = new TextBox
        {
            Text = current.ToString(),
            ReadOnly = true,
            Dock = DockStyle.Top,
            AccessibleName = "Captured shortcut"
        };
        var cancel = new Button { Text = "Cancel", Dock = DockStyle.Bottom, DialogResult = DialogResult.Cancel };

        Controls.Add(cancel);
        Controls.Add(_value);
        Controls.Add(label);
        CancelButton = cancel;
        Shown += (_, _) => _value.Focus();
    }

    protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
    {
        Keys keyCode = keyData & Keys.KeyCode;
        if (keyCode is Keys.ControlKey or Keys.ShiftKey or Keys.Menu)
            return true;
        if (keyCode == Keys.Escape)
        {
            DialogResult = DialogResult.Cancel;
            Close();
            return true;
        }

        CapturedKeys = keyData;
        _value.Text = keyData.ToString();
        DialogResult = DialogResult.OK;
        Close();
        return true;
    }
}
