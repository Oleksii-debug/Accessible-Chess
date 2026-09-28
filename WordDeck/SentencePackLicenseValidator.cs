using System.Globalization;

namespace WordDeck;

internal static class SentencePackLicenseValidator
{
    private const string TatoebaCcBy = "CC BY 2.0 FR";

    public static void ValidateForInstallation(SentencePack pack)
    {
        if (pack is null) throw new ArgumentNullException(nameof(pack));

        // Installation is a trust boundary. The portable parser already bounds raw
        // bytes, while this second layer bounds the validated object graph before it
        // can drive SQLite generation or become persistent user data.
        SentencePackStructuralLimits.Validate(pack);

        foreach (SentenceRecord sentence in pack.Sentences)
        {
            if (!string.Equals(sentence.License, pack.License, StringComparison.Ordinal))
            {
                throw new InvalidDataException(
                    $"SentencePack {pack.PackId} mixes sentence license '{sentence.License}' with pack license '{pack.License}'. Mixed-license packs are not accepted by this release format.");
            }
        }

        bool tatoeba = pack.Provenance.Contains("Tatoeba", StringComparison.OrdinalIgnoreCase);
        if (!tatoeba) return;

        foreach (SentenceRecord sentence in pack.Sentences)
        {
            if (!IsPositiveTatoebaSentenceId(sentence.SourceSentenceId) ||
                !IsPositiveTatoebaSentenceId(sentence.TranslationSentenceId))
            {
                throw new InvalidDataException(
                    $"Tatoeba SentencePack record {sentence.Id} is missing a valid positive decimal upstream sentence identifier.");
            }
        }

        if (!string.Equals(pack.License, TatoebaCcBy, StringComparison.Ordinal))
            return;

        foreach (SentenceRecord sentence in pack.Sentences)
        {
            if (!HasSideAttribution(sentence.Source, "English sentence", sentence.SourceSentenceId!) ||
                !HasSideAttribution(sentence.Source, "Ukrainian sentence", sentence.TranslationSentenceId!))
            {
                throw new InvalidDataException(
                    $"Attributed Tatoeba record {sentence.Id} is missing exact per-side author attribution bound to its upstream sentence IDs.");
            }
        }
    }

    private static bool IsPositiveTatoebaSentenceId(string? value) =>
        !string.IsNullOrWhiteSpace(value) &&
        long.TryParse(value, NumberStyles.None, CultureInfo.InvariantCulture, out long parsed) &&
        parsed > 0;

    private static bool HasSideAttribution(string source, string sideLabel, string sentenceId)
    {
        string marker = $"{sideLabel} #{sentenceId} by ";
        int markerIndex = source.IndexOf(marker, StringComparison.Ordinal);
        if (markerIndex < 0)
            return false;

        int authorStart = markerIndex + marker.Length;
        int separator = source.IndexOf(';', authorStart);
        int period = source.IndexOf('.', authorStart);
        int authorEnd = separator >= 0 && period >= 0
            ? Math.Min(separator, period)
            : separator >= 0 ? separator : period >= 0 ? period : source.Length;

        return authorEnd > authorStart && !string.IsNullOrWhiteSpace(source[authorStart..authorEnd]);
    }
}
