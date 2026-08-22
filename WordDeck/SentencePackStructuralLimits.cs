namespace WordDeck;

internal static class SentencePackStructuralLimits
{
    public const int MaxSentences = 500_000;
    public const int MaxTokensPerSentence = 128;
    public const int MaxTargetEntriesPerSentence = 512;
    public const int MaxQualityFlagsPerSentence = 64;
    public const int MaxSentenceTextChars = 8_192;
    public const int MaxProvenanceChars = 4_096;
    public const int MaxIdentifierChars = 256;
    public const int MaxTokenOrFlagChars = 256;

    public static void Validate(SentencePack pack)
    {
        ArgumentNullException.ThrowIfNull(pack);
        pack.Validate();

        if (pack.SentenceCount > MaxSentences)
            throw new InvalidDataException($"SentencePack contains {pack.SentenceCount:N0} sentences; this build supports at most {MaxSentences:N0} per imported pack.");
        RequireLength(pack.PackId, MaxIdentifierChars, "SentencePack id");
        RequireLength(pack.Provenance, MaxProvenanceChars, "SentencePack provenance");
        RequireLength(pack.License, MaxIdentifierChars, "SentencePack license");

        foreach (SentenceRecord sentence in pack.Sentences)
        {
            RequireLength(sentence.Id, MaxIdentifierChars, $"Sentence {sentence.Id} id");
            RequireLength(sentence.English, MaxSentenceTextChars, $"Sentence {sentence.Id} English text");
            RequireLength(sentence.Ukrainian, MaxSentenceTextChars, $"Sentence {sentence.Id} Ukrainian text");
            RequireLength(sentence.Source, MaxProvenanceChars, $"Sentence {sentence.Id} provenance source");
            RequireLength(sentence.License, MaxIdentifierChars, $"Sentence {sentence.Id} license");
            if (sentence.Tokens.Count > MaxTokensPerSentence || sentence.Lemmas.Count > MaxTokensPerSentence)
                throw new InvalidDataException($"Sentence {sentence.Id} exceeds the {MaxTokensPerSentence}-token import limit.");
            if (sentence.TargetEntryIds.Count > MaxTargetEntriesPerSentence || sentence.EntryLevels.Count > MaxTargetEntriesPerSentence)
                throw new InvalidDataException($"Sentence {sentence.Id} indexes too many dictionary targets.");
            if (sentence.QualityFlags.Count > MaxQualityFlagsPerSentence)
                throw new InvalidDataException($"Sentence {sentence.Id} contains too many quality flags.");
            foreach (string token in sentence.Tokens) RequireLength(token, MaxTokenOrFlagChars, $"Sentence {sentence.Id} token");
            foreach (string lemma in sentence.Lemmas) RequireLength(lemma, MaxTokenOrFlagChars, $"Sentence {sentence.Id} lemma");
            foreach (string target in sentence.TargetEntryIds) RequireLength(target, MaxIdentifierChars, $"Sentence {sentence.Id} target stable id");
            foreach (string flag in sentence.QualityFlags) RequireLength(flag, MaxTokenOrFlagChars, $"Sentence {sentence.Id} quality flag");
        }
    }

    private static void RequireLength(string? value, int maximum, string description)
    {
        if ((value ?? string.Empty).Length > maximum)
            throw new InvalidDataException($"{description} exceeds the supported {maximum:N0}-character limit.");
    }
}
