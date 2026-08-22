namespace WordDeck;

internal static class SentencePackLicenseValidator
{
    private const string TatoebaCcBy = "CC BY 2.0 FR";

    public static void ValidateForInstallation(SentencePack pack)
    {
        if (pack is null) throw new ArgumentNullException(nameof(pack));
        pack.Validate();

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
            if (!sentence.Source.Contains("English sentence #", StringComparison.Ordinal) ||
                !sentence.Source.Contains("Ukrainian sentence #", StringComparison.Ordinal) ||
                !sentence.Source.Contains(" by ", StringComparison.Ordinal))
            {
                throw new InvalidDataException($"Attributed Tatoeba record {sentence.Id} is missing required per-side author attribution.");
            }
        }
    }
}
