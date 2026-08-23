namespace WordDeck;

internal sealed record ContextSentenceTargetSpellingPrompt(
    string SentenceId,
    string TargetEntryId,
    string TargetMeaningUkrainian,
    string UkrainianSentence,
    string EnglishCloze,
    bool AmbiguousStableIdentity,
    ContextSourceDescriptor Source,
    LocalTextContextLocation? LocalTextLocation,
    string Instruction);

internal sealed record ContextSentenceTargetSpellingResult(
    bool Accepted,
    bool MalformedInput,
    bool SameWordsWrongOrder,
    string Feedback);

internal sealed class ContextSentenceTargetSpellingExercise
{
    private readonly string[] _expectedTokens;

    public ContextSentenceTargetSpellingPrompt Prompt { get; }

    internal ContextSentenceTargetSpellingExercise(
        ContextSentenceTargetSpellingPrompt prompt,
        IEnumerable<string> expectedTokens)
    {
        Prompt = prompt ?? throw new ArgumentNullException(nameof(prompt));
        _expectedTokens = expectedTokens.Select(SentenceTokenizer.NormalizeToken).Where(token => token.Length > 0).ToArray();
        if (_expectedTokens.Length == 0)
            throw new InvalidDataException("Sentence target spelling exercise has no expected physical target form.");
    }

    public ContextSentenceTargetSpellingResult Check(string typedTargetForm)
    {
        string[] typed;
        try
        {
            typed = SentenceTokenizer.Tokenize(typedTargetForm ?? string.Empty).ToArray();
        }
        catch (InvalidDataException)
        {
            return new ContextSentenceTargetSpellingResult(
                false,
                true,
                false,
                "The typed target form contains malformed Unicode and was not accepted.");
        }

        bool accepted = _expectedTokens.SequenceEqual(typed, StringComparer.Ordinal);
        if (accepted)
            return new ContextSentenceTargetSpellingResult(true, false, false, "Correct target form.");

        bool sameWordsWrongOrder = _expectedTokens.Length == typed.Length &&
            _expectedTokens.OrderBy(token => token, StringComparer.Ordinal)
                .SequenceEqual(typed.OrderBy(token => token, StringComparer.Ordinal), StringComparer.Ordinal);

        return new ContextSentenceTargetSpellingResult(
            false,
            false,
            sameWordsWrongOrder,
            sameWordsWrongOrder
                ? "The target words are present, but the target phrase word order is wrong."
                : "The target form is not correct. Try again or use Show answer.");
    }

    public string RevealExpectedForm() => string.Join(" ", _expectedTokens);
}

internal static class ContextSentenceTargetSpellingFactory
{
    public static ContextSentenceTargetSpellingExercise Create(
        RankedContextSentence ranked,
        string focusTargetEntryId,
        ContextTargetLexicon lexicon,
        DictionaryPackage dictionary)
    {
        ArgumentNullException.ThrowIfNull(ranked);
        ArgumentNullException.ThrowIfNull(lexicon);
        ArgumentNullException.ThrowIfNull(dictionary);

        ranked.Candidate.Validate();
        string focusId = ContextTargetIds.NormalizeSingle(focusTargetEntryId);
        string[] required = ContextTargetIds.NormalizeRequired(ranked.RequiredTargetEntryIds);
        if (!required.Contains(focusId, StringComparer.OrdinalIgnoreCase))
            throw new InvalidDataException("Sentence target spelling focus must be one of the ranked exercise target stable IDs.");

        DictionaryEntry target = dictionary.Entries.FirstOrDefault(entry =>
            string.Equals(ContextTargetIds.NormalizeSingle(entry.Id), focusId, StringComparison.OrdinalIgnoreCase))
            ?? throw new InvalidDataException($"Sentence target spelling stable ID {focusId} is not present in dictionary {dictionary.Id}.");

        string lexicalKey = lexicon.LexicalKeyFor(focusId);
        string[] physicalTokens = SentenceTokenizer.Tokenize(lexicalKey).ToArray();
        if (physicalTokens.Length == 0)
            throw new InvalidDataException($"Sentence target spelling stable ID {focusId} has no physical English form.");

        SentenceRecord sentence = ranked.Candidate.Sentence;
        List<int> starts = FindNonOverlappingOccurrences(sentence.Tokens, physicalTokens);
        if (starts.Count == 0)
        {
            throw new InvalidDataException(
                $"Sentence {sentence.Id} indexes target {focusId}, but its exact physical lexical form '{lexicalKey}' is not present in the canonical token stream. Target-form spelling fails closed rather than guessing morphology.");
        }

        string cloze = BuildCloze(sentence.Tokens, starts, physicalTokens.Length);
        var prompt = new ContextSentenceTargetSpellingPrompt(
            sentence.Id,
            focusId,
            target.Target,
            sentence.Ukrainian,
            cloze,
            lexicon.IsAmbiguousStableIdentity(focusId),
            ranked.Candidate.Source,
            ranked.Candidate.LocalTextLocation,
            "Type only the missing target word or phrase. Do not type the whole English sentence.");

        return new ContextSentenceTargetSpellingExercise(prompt, physicalTokens);
    }

    public static IReadOnlyList<ContextSentenceTargetSpellingExercise> CreateForAllTargets(
        RankedContextSentence ranked,
        ContextTargetLexicon lexicon,
        DictionaryPackage dictionary) =>
        ContextTargetIds.NormalizeRequired(ranked.RequiredTargetEntryIds)
            .Select(id => Create(ranked, id, lexicon, dictionary))
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
