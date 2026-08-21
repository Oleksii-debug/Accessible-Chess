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
        Width = 760;
        Height = 560;
        MinimizeBox = false;
        MaximizeBox = false;
        KeyPreview = true;
        AccessibleName = "Keyboard shortcut settings";

        var instructions = new Label
        {
            Dock = DockStyle.Top,
            AutoSize = true,
            Padding = new Padding(8),
            Text = "Select a function and press Enter, or choose Change selected. Then press the shortcut you want. Esc cancels shortcut capture. User-created deck and Recall scope shortcuts may start unassigned and can be assigned here.",
            AccessibleName = "Shortcut settings instructions",
            TabStop = false
        };

        _list = new ListView
        {
            Dock = DockStyle.Fill,
            View = View.Details,
            FullRowSelect = true,
            MultiSelect = false,
            HideSelection = false,
            AccessibleName = "Shortcut actions",
            AccessibleDescription = "Each row contains a WordDeck function and its currently assigned shortcut. Select a row and press Enter to change it.",
            TabIndex = 0
        };
        _list.Columns.Add("Function", 480);
        _list.Columns.Add("Current shortcut", 220);
        _list.DoubleClick += (_, _) => ChangeSelected();
        _list.KeyDown += (_, e) =>
        {
            if (e.KeyCode != Keys.Enter) return;
            e.Handled = true;
            e.SuppressKeyPress = true;
            ChangeSelected();
        };

        var buttons = new FlowLayoutPanel
        {
            Dock = DockStyle.Bottom,
            AutoSize = true,
            FlowDirection = FlowDirection.LeftToRight,
            Padding = new Padding(8),
            TabStop = false
        };

        var changeButton = new Button
        {
            Text = "Change selected",
            AutoSize = true,
            AccessibleName = "Change selected shortcut",
            AccessibleDescription = "Open shortcut capture for the selected action.",
            TabIndex = 1
        };
        changeButton.Click += (_, _) => ChangeSelected();
        var clearButton = new Button
        {
            Text = "Clear selected",
            AutoSize = true,
            AccessibleName = "Clear selected shortcut",
            AccessibleDescription = "Remove the key binding from the selected action. F1 will report it as Unassigned.",
            TabIndex = 2
        };
        clearButton.Click += (_, _) => ClearSelected();
        var resetButton = new Button
        {
            Text = "Reset defaults",
            AutoSize = true,
            AccessibleName = "Reset all shortcuts to defaults",
            AccessibleDescription = "Restore the built-in default bindings for every currently available action.",
            TabIndex = 3
        };
        resetButton.Click += (_, _) => { _manager.ResetDefaults(); RefreshList(); };
        var closeButton = new Button
        {
            Text = "Close",
            AutoSize = true,
            DialogResult = DialogResult.OK,
            AccessibleName = "Close shortcut settings",
            TabIndex = 4
        };
        buttons.Controls.Add(changeButton);
        buttons.Controls.Add(clearButton);
        buttons.Controls.Add(resetButton);
        buttons.Controls.Add(closeButton);

        Controls.Add(_list);
        Controls.Add(instructions);
        Controls.Add(buttons);
        CancelButton = closeButton;
        RefreshList();
        Shown += (_, _) =>
        {
            _list.Focus();
            if (_list.SelectedItems.Count > 0) _list.SelectedItems[0].Focused = true;
        };
    }

    private void RefreshList()
    {
        string? selectedId = _list.SelectedItems.Count > 0 ? _list.SelectedItems[0].Tag as string : null;
        _list.BeginUpdate();
        _list.Items.Clear();
        foreach (ShortcutDefinition def in _manager.CurrentDefinitions)
        {
            var item = new ListViewItem(def.Description) { Tag = def.Id };
            item.SubItems.Add(ShortcutFormatter.Format(_manager.Get(def.Id)));
            _list.Items.Add(item);
            if (def.Id == selectedId) item.Selected = true;
        }
        _list.EndUpdate();

        if (_list.Items.Count > 0 && _list.SelectedItems.Count == 0) _list.Items[0].Selected = true;
        if (_list.SelectedItems.Count > 0)
        {
            _list.SelectedItems[0].Focused = true;
            _list.SelectedItems[0].EnsureVisible();
        }
    }

    private void ChangeSelected()
    {
        if (_list.SelectedItems.Count == 0) return;
        string actionId = (string)_list.SelectedItems[0].Tag!;
        ShortcutDefinition? definition = _manager.CurrentDefinitions.FirstOrDefault(x => x.Id == actionId);
        if (definition is null) { RefreshList(); return; }

        using var dialog = new ShortcutCaptureForm(definition.Description, _manager.Get(actionId));
        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        if (!_manager.TrySet(actionId, dialog.CapturedKeys, out string? error))
        {
            MessageBox.Show(this, $"Cannot use that shortcut because {error}.", "Shortcut not available", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return;
        }
        RefreshList();
    }

    private void ClearSelected()
    {
        if (_list.SelectedItems.Count == 0) return;
        string actionId = (string)_list.SelectedItems[0].Tag!;
        _manager.Clear(actionId);
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
        AccessibleName = "Shortcut capture";
        CapturedKeys = current;

        var label = new Label
        {
            Text = $"Press the key combination for: {description}. Press Esc to cancel.",
            Dock = DockStyle.Top,
            AutoSize = true,
            Padding = new Padding(12),
            AccessibleName = "Shortcut capture instructions",
            TabStop = false
        };
        _value = new TextBox
        {
            Text = ShortcutFormatter.Format(current),
            ReadOnly = true,
            Dock = DockStyle.Top,
            AccessibleName = "Captured shortcut",
            AccessibleDescription = "The key combination currently captured for this action.",
            TabIndex = 0
        };
        var cancel = new Button
        {
            Text = "Cancel",
            Dock = DockStyle.Bottom,
            DialogResult = DialogResult.Cancel,
            AccessibleName = "Cancel shortcut change",
            TabIndex = 1
        };

        Controls.Add(cancel);
        Controls.Add(_value);
        Controls.Add(label);
        CancelButton = cancel;
        Shown += (_, _) => { _value.Focus(); _value.SelectAll(); };
    }

    protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
    {
        Keys keyCode = keyData & Keys.KeyCode;
        if (keyCode is Keys.ControlKey or Keys.ShiftKey or Keys.Menu) return true;
        if (keyCode == Keys.Escape)
        {
            DialogResult = DialogResult.Cancel;
            Close();
            return true;
        }

        CapturedKeys = keyData;
        _value.Text = ShortcutFormatter.Format(keyData);
        _value.SelectAll();
        DialogResult = DialogResult.OK;
        Close();
        return true;
    }
}
