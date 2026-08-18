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
            string key = code switch
            {
                >= Keys.D0 and <= Keys.D9 => ((char)('0' + (code - Keys.D0))).ToString(),
                >= Keys.NumPad0 and <= Keys.NumPad9 => "Num" + (code - Keys.NumPad0),
                Keys.Oemcomma => ",",
                Keys.OemPeriod => ".",
                Keys.OemMinus => "-",
                Keys.Oemplus => "+",
                _ => code.ToString()
            };
            parts.Add(key);
        }

        return parts.Count == 0 ? keys.ToString() : string.Join("+", parts);
    }
}
