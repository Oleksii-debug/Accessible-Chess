namespace WordDeck;

internal static class KeyboardSelectorFocusGuard
{
    private static readonly HashSet<Keys> NativeSelectionKeys = new()
    {
        Keys.Up,
        Keys.Down,
        Keys.Home,
        Keys.End,
        Keys.PageUp,
        Keys.PageDown
    };

    public static bool IsNativeSelectionNavigation(Keys keyData)
    {
        Keys code = keyData & Keys.KeyCode;
        Keys modifiers = keyData & Keys.Modifiers;
        return modifiers == Keys.None && NativeSelectionKeys.Contains(code);
    }

    public static void Attach(Form form, params string[] accessibleNames)
    {
        var names = new HashSet<string>(accessibleNames, StringComparer.OrdinalIgnoreCase);
        foreach (ComboBox combo in EnumerateControls(form).OfType<ComboBox>().Where(combo => names.Contains(combo.AccessibleName ?? string.Empty)))
            Attach(form, combo);
    }

    private static void Attach(Form form, ComboBox combo)
    {
        bool keyboardSelectionPending = false;

        combo.KeyDown += (_, e) =>
        {
            if (IsNativeSelectionNavigation(e.KeyData))
                keyboardSelectionPending = true;
        };

        combo.SelectedIndexChanged += (_, _) =>
        {
            if (!keyboardSelectionPending) return;
            keyboardSelectionPending = false;
            if (form.IsDisposed || combo.IsDisposed || !form.IsHandleCreated) return;

            form.BeginInvoke(new Action(() =>
            {
                if (!form.IsDisposed && !combo.IsDisposed && combo.CanFocus)
                    combo.Focus();
            }));
        };

        combo.KeyUp += (_, e) =>
        {
            if (IsNativeSelectionNavigation(e.KeyData))
                keyboardSelectionPending = false;
        };
    }

    private static IEnumerable<Control> EnumerateControls(Control root)
    {
        foreach (Control child in root.Controls)
        {
            yield return child;
            foreach (Control descendant in EnumerateControls(child))
                yield return descendant;
        }
    }
}
