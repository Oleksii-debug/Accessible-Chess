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
        if (code != Keys.None)
        {
            int codeValue = (int)code;
            string key = code switch
            {
                >= Keys.D0 and <= Keys.D9 => ((char)('0' + codeValue - (int)Keys.D0)).ToString(),
                >= Keys.NumPad0 and <= Keys.NumPad9 => "Num" + (codeValue - (int)Keys.NumPad0),
                Keys.Back => "Backspace",
                Keys.Return => "Enter",
                Keys.Escape => "Esc",
                Keys.Space => "Space",
                Keys.Prior => "PageUp",
                Keys.Next => "PageDown",
                Keys.Left => "Left",
                Keys.Up => "Up",
                Keys.Right => "Right",
                Keys.Down => "Down",
                Keys.Insert => "Insert",
                Keys.Delete => "Delete",
                Keys.Home => "Home",
                Keys.End => "End",
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
                Keys.Oemtilde => "`",
                _ => HumanizeFallback(code)
            };
            parts.Add(key);
        }

        return parts.Count == 0 ? "Unassigned" : string.Join("+", parts);
    }

    private static string HumanizeFallback(Keys code)
    {
        string value = code.ToString();
        if (value.StartsWith("Oem", StringComparison.OrdinalIgnoreCase))
            return "Key " + ((int)code).ToString(System.Globalization.CultureInfo.InvariantCulture);
        return value;
    }
}
