using System.Text;

namespace WordDeck;

internal static partial class SentenceTokenizer
{
    internal static void ValidateUnicode(string? value, string description)
    {
        try
        {
            _ = (value ?? string.Empty).Normalize(NormalizationForm.FormKC);
        }
        catch (ArgumentException ex)
        {
            throw new InvalidDataException($"{description} contains malformed Unicode.", ex);
        }
    }

    internal static string NormalizeCompatibilityText(string? value)
    {
        ValidateUnicode(value, "Sentence text");
        return (value ?? string.Empty)
            .Normalize(NormalizationForm.FormKC)
            .Replace('’', '\'')
            .Replace('‘', '\'')
            .Replace('`', '\'');
    }
}
