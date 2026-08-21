namespace WordDeck;

internal static class ShortcutFormatter
{
    public static string Format(Keys keys)
    {
        if (keys == Keys.None) return "Unassigned";

        var parts = new List<string>(5);
        Keys modifiers = keys & Keys.Modifiers;
        if (modifiers.HasFlag(Keys.Control)) parts.Add("Ctrl");
        if (modifiers.HasFlag(Keys.Shift)) parts.Add("Shift");
        if (modifiers.HasFlag(Keys.Alt)) parts.Add("Alt");

        Keys code = keys & Keys.KeyCode;
        if (code != Keys.None) parts.Add(FormatKeyCode(code));

        return parts.Count == 0 ? "Unassigned" : string.Join("+", parts);
    }

    private static string FormatKeyCode(Keys code)
    {
        int value = (int)code;
        if (code is >= Keys.D0 and <= Keys.D9)
            return ((char)('0' + value - (int)Keys.D0)).ToString();
        if (code is >= Keys.A and <= Keys.Z)
            return ((char)('A' + value - (int)Keys.A)).ToString();
        if (code is >= Keys.NumPad0 and <= Keys.NumPad9)
            return "Num" + (value - (int)Keys.NumPad0);
        if (code is >= Keys.F1 and <= Keys.F24)
            return "F" + (value - (int)Keys.F1 + 1);

        return code switch
        {
            Keys.Up => "Up",
            Keys.Down => "Down",
            Keys.Left => "Left",
            Keys.Right => "Right",
            Keys.PageUp => "Page Up",
            Keys.PageDown => "Page Down",
            Keys.Home => "Home",
            Keys.End => "End",
            Keys.Insert => "Insert",
            Keys.Delete => "Delete",
            Keys.Back => "Backspace",
            Keys.Space => "Space",
            Keys.Enter => "Enter",
            Keys.Escape => "Escape",
            Keys.Tab => "Tab",
            Keys.Oemcomma => ",",
            Keys.OemPeriod => ".",
            Keys.OemMinus => "-",
            Keys.Oemplus => "+",
            Keys.OemQuestion => "/",
            Keys.OemSemicolon => ";",
            Keys.OemQuotes => "'",
            Keys.OemOpenBrackets => "[",
            Keys.OemCloseBrackets => "]",
            Keys.OemPipe => "\\",
            Keys.Add => "Num+",
            Keys.Subtract => "Num-",
            Keys.Multiply => "Num*",
            Keys.Divide => "Num/",
            Keys.Decimal => "Num.",
            _ => Enum.GetName(typeof(Keys), code) ?? $"Key {value}"
        };
    }
}
