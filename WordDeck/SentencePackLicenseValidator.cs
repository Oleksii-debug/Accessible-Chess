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
            if (string.IsNullOrWhiteSpace(sentence.SourceSentenceId) || string.IsNullOrWhiteSpace(sentence.TranslationSentenceId))
                throw new InvalidDataException($"Tatoeba SentencePack record {sentence.Id} is missing upstream sentence identifiers.");
        }

        if (!string.Equals(pack.License, TatoebaCcBy, StringComparison.Ordinal))
            return;

        foreach (SentenceRecord sentence in pack.Sentences)
        {
            // The attributed builder writes both owner names into Source. Requiring the two
            // sentence markers prevents a generic CC-BY label from silently replacing record-level attribution.
            if (!sentence.Source.Contains("English sentence #", StringComparison.Ordinal) ||
                !sentence.Source.Contains("Ukrainian sentence #", StringComparison.Ordinal) ||
                !sentence.Source.Contains(" by ", StringComparison.Ordinal))
            {
                throw new InvalidDataException($"Attributed Tatoeba record {sentence.Id} is missing required per-side author attribution.");
            }
        }
    }
}
