namespace WordDeck;

internal sealed record ContextTargetSpellingPrompt(
    string SentenceId,
    string FocusTargetEntryId,
    string TargetMeaningUkrainian,
    string UkrainianSentence,
    string EnglishCloze,
    string SourceId,
    ContextCorpusKind SourceKind,
    string Provenance,
    string License,
    LocalTextContextLocation? LocalTextLocation,
    string Instruction);

internal sealed record ContextTargetSpellingResult(
    bool Accepted,
    bool MalformedInput,
    bool SameWordsWrongOrder,
    string Feedback);

internal sealed class ContextTargetSpellingExercise
{
    private readonly string[] _expectedTokens;

    public ContextTargetSpellingPrompt Prompt { get; }

    internal ContextTargetSpellingExercise(
        ContextTargetSpellingPrompt prompt,
        IEnumerable<string> expectedTokens)
    {
        Prompt = prompt ?? throw new ArgumentNullException(nameof(prompt));
        _expectedTokens = expectedTokens
            .Select(SentenceTokenizer.NormalizeToken)
            .Where(token => token.Length > 0)
            .ToArray();
        if (_expectedTokens.Length == 0)
            throw new InvalidDataException("Context target-spelling exercise has no expected physical target form.");
    }

    public ContextTargetSpellingResult Check(string typedTargetForm)
    {
        string[] typed;
        try
        {
            typed = SentenceTokenizer.Tokenize(typedTargetForm ?? string.Empty).ToArray();
        }
        catch (InvalidDataException)
        {
            return new ContextTargetSpellingResult(
                false,
                true,
                false,
                "The typed target form contains malformed Unicode and was not accepted.");
        }

        if (_expectedTokens.SequenceEqual(typed, StringComparer.Ordinal))
            return new ContextTargetSpellingResult(true, false, false, "Correct target form.");

        bool sameWordsWrongOrder = _expectedTokens.Length == typed.Length &&
            _expectedTokens.OrderBy(token => token, StringComparer.Ordinal)
                .SequenceEqual(typed.OrderBy(token => token, StringComparer.Ordinal), StringComparer.Ordinal);

        return new ContextTargetSpellingResult(
            false,
            false,
            sameWordsWrongOrder,
            sameWordsWrongOrder
                ? "The target words are present, but the target phrase word order is wrong."
                : "The target form is not correct. Try again or use Show answer.");
    }

    public string RevealExpectedForm() => string.Join(" ", _expectedTokens);
}

internal static class ContextTargetSpellingService
{
    public static ContextTargetSpellingExercise Build(
        ContextPracticeCard card,
        string focusTargetEntryId,
        ContextTargetLexicon lexicon,
        DictionaryPackage dictionary)
    {
        ArgumentNullException.ThrowIfNull(card);
        ArgumentNullException.ThrowIfNull(lexicon);
        ArgumentNullException.ThrowIfNull(dictionary);

        string focusId = ContextTargetIds.NormalizeSingle(focusTargetEntryId);
        string[] requiredIds = ContextTargetIds.NormalizeRequired(card.TargetEntryIds);
        if (!requiredIds.Contains(focusId, StringComparer.OrdinalIgnoreCase))
            throw new InvalidDataException("Sentence target-spelling focus must belong to the card's exact stable-ID target set.");

        DictionaryEntry target = dictionary.Entries.FirstOrDefault(entry =>
            string.Equals(ContextTargetIds.NormalizeSingle(entry.Id), focusId, StringComparison.OrdinalIgnoreCase))
            ?? throw new InvalidDataException($"Sentence target-spelling stable ID {focusId} is not present in dictionary {dictionary.Id}.");

        // A surface-form SentencePack occurrence cannot prove which Oxford entry owns a
        // homograph such as noun/verb senses sharing the same written form. Target-only
        // spelling would otherwise award progress to an unproven stable ID, so fail closed.
        if (lexicon.IsAmbiguousStableIdentity(focusId))
        {
            string lexicalKey = lexicon.LexicalKeyFor(focusId);
            string candidates = string.Join("|", lexicon.StableIdsForLexicalKey(lexicalKey));
            throw new InvalidDataException(
                $"Sentence target-spelling stable ID {focusId} is unresolved because physical form '{lexicalKey}' maps to multiple dictionary entries [{candidates}]. Explicit POS/sense evidence is required before this exercise can own canonical progress.");
        }

        string resolvedLexicalKey = lexicon.LexicalKeyFor(focusId);
        string[] physicalTokens = SentenceTokenizer.Tokenize(resolvedLexicalKey).ToArray();
        if (physicalTokens.Length == 0)
            throw new InvalidDataException($"Sentence target-spelling stable ID {focusId} has no usable physical English form.");

        IReadOnlyList<string> sentenceTokens = SentenceTokenizer.Tokenize(card.EnglishAnswer);
        List<int> starts = FindNonOverlappingOccurrences(sentenceTokens, physicalTokens);
        if (starts.Count == 0)
        {
            throw new InvalidDataException(
                $"Sentence {card.SentenceId} indexes target {focusId}, but exact physical lexical form '{resolvedLexicalKey}' is not present in the canonical sentence token stream. Target-form spelling fails closed rather than guessing morphology.");
        }

        var prompt = new ContextTargetSpellingPrompt(
            card.SentenceId,
            focusId,
            target.Target,
            card.UkrainianPrompt,
            BuildCloze(sentenceTokens, starts, physicalTokens.Length),
            card.SourceId,
            card.SourceKind,
            card.Provenance,
            card.License,
            card.LocalTextLocation,
            "Type only the missing target word or phrase. Do not type the whole English sentence.");
        return new ContextTargetSpellingExercise(prompt, physicalTokens);
    }

    public static IReadOnlyList<ContextTargetSpellingExercise> BuildAllTargets(
        ContextPracticeCard card,
        ContextTargetLexicon lexicon,
        DictionaryPackage dictionary) =>
        ContextTargetIds.NormalizeRequired(card.TargetEntryIds)
            .Select(id => Build(card, id, lexicon, dictionary))
            .ToArray();

    private static List<int> FindNonOverlappingOccurrences(
        IReadOnlyList<string> sentenceTokens,
        IReadOnlyList<string> targetTokens)
    {
        var result = new List<int>();
        for (int i = 0; i <= sentenceTokens.Count - targetTokens.Count;)
        {
            bool match = true;
            for (int j = 0; j < targetTokens.Count; j++)
            {
                if (!string.Equals(sentenceTokens[i + j], targetTokens[j], StringComparison.Ordinal))
                {
                    match = false;
                    break;
                }
            }

            if (match)
            {
                result.Add(i);
                i += targetTokens.Count;
            }
            else
            {
                i++;
            }
        }
        return result;
    }

    private static string BuildCloze(
        IReadOnlyList<string> sentenceTokens,
        IReadOnlyCollection<int> occurrenceStarts,
        int targetTokenCount)
    {
        var starts = new HashSet<int>(occurrenceStarts);
        var output = new List<string>();
        for (int i = 0; i < sentenceTokens.Count;)
        {
            if (starts.Contains(i))
            {
                output.Add("[blank]");
                i += targetTokenCount;
            }
            else
            {
                output.Add(sentenceTokens[i]);
                i++;
            }
        }
        return string.Join(" ", output);
    }
}
