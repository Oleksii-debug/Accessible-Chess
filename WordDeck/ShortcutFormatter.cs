namespace WordDeck;

internal static class ShortcutFormatter
{
    public static string Format(Keys keys)
    {
        if (keys == Keys.None)
            return "Unassigned";

        string? text = new KeysConverter().ConvertToString(keys);
        return string.IsNullOrWhiteSpace(text) ? keys.ToString() : text;
    }
}
