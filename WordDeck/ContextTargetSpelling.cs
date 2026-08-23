using System.Text;
using System.Text.RegularExpressions;

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

internal static class ContextPhysicalTargetForm
{
    private const string WordBoundaryClass = "A-Za-z'’‘`\\-‐‑‒–—";

    public static string CanonicalDisplay(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
            throw new InvalidDataException("Context target-spelling physical form is blank.");
        SentenceTokenizer.ValidateUnicode(value, "Context target-spelling physical form");
        return value.Trim();
    }

    public static string NormalizeForComparison(string value, bool trimHarmlessOuterPunctuation)
    {
        SentenceTokenizer.ValidateUnicode(value ?? string.Empty, "Context target-spelling answer");
        string normalized = NormalizeOrthography((value ?? string.Empty).Normalize(NormalizationForm.FormKC));
        normalized = CollapseWhitespace(normalized).Trim();
        if (trimHarmlessOuterPunctuation)
            normalized = TrimOuterPunctuation(normalized);
        return normalized.ToLowerInvariant();
    }

    public static Regex BuildOccurrenceRegex(string physicalForm)
    {
        string canonical = CanonicalDisplay(physicalForm).Normalize(NormalizationForm.FormKC);
        var pattern = new StringBuilder();
        pattern.Append("(?<![").Append(WordBoundaryClass).Append("])");

        bool previousWasWhitespace = false;
        foreach (char raw in canonical)
        {
            char ch = NormalizeOrthographyChar(raw);
            if (char.IsWhiteSpace(ch))
            {
                if (!previousWasWhitespace)
                    pattern.Append(@"\s+");
                previousWasWhitespace = true;
                continue;
            }

            previousWasWhitespace = false;
            if (ch == '\'')
                pattern.Append("['’‘`]");
            else if (ch == '-')
                pattern.Append("[-‐‑‒–—]");
            else
                pattern.Append(Regex.Escape(ch.ToString()));
        }

        pattern.Append("(?![").Append(WordBoundaryClass).Append("])");
        return new Regex(pattern.ToString(), RegexOptions.CultureInvariant | RegexOptions.IgnoreCase);
    }

    private static string NormalizeOrthography(string value)
    {
        var builder = new StringBuilder(value.Length);
        foreach (char ch in value)
            builder.Append(NormalizeOrthographyChar(ch));
        return builder.ToString();
    }

    private static char NormalizeOrthographyChar(char ch) => ch switch
    {
        '’' or '‘' or '`' => '\'',
        '‐' or '‑' or '‒' or '–' or '—' => '-',
        _ => ch
    };

    private static string CollapseWhitespace(string value)
    {
        var builder = new StringBuilder(value.Length);
        bool pendingSpace = false;
        foreach (char ch in value)
        {
            if (char.IsWhiteSpace(ch))
            {
                pendingSpace = builder.Length > 0;
                continue;
            }

            if (pendingSpace)
            {
                builder.Append(' ');
                pendingSpace = false;
            }
            builder.Append(ch);
        }
        return builder.ToString();
    }

    private static string TrimOuterPunctuation(string value)
    {
        int start = 0;
        int end = value.Length;
        while (start < end && !IsTargetCore(value[start]))
            start++;
        while (end > start && !IsTargetCore(value[end - 1]))
            end--;
        return value[start..end].Trim();
    }

    private static bool IsTargetCore(char ch) => char.IsLetterOrDigit(ch) || ch is '\'' or '-';
}

internal sealed class ContextTargetSpellingExercise
{
    private readonly string _expectedPhysicalForm;
    private readonly string _expectedNormalizedForm;
    private readonly string[] _expectedTokens;

    public ContextTargetSpellingPrompt Prompt { get; }

    internal ContextTargetSpellingExercise(
        ContextTargetSpellingPrompt prompt,
        string expectedPhysicalForm)
    {
        Prompt = prompt ?? throw new ArgumentNullException(nameof(prompt));
        _expectedPhysicalForm = ContextPhysicalTargetForm.CanonicalDisplay(expectedPhysicalForm);
        _expectedNormalizedForm = ContextPhysicalTargetForm.NormalizeForComparison(
            _expectedPhysicalForm,
            trimHarmlessOuterPunctuation: false);
        _expectedTokens = SentenceTokenizer.Tokenize(_expectedPhysicalForm).ToArray();
        if (_expectedNormalizedForm.Length == 0 || _expectedTokens.Length == 0)
            throw new InvalidDataException("Context target-spelling exercise has no expected physical target form.");
    }

    public ContextTargetSpellingResult Check(string typedTargetForm)
    {
        string normalizedTyped;
        string[] typedTokens;
        try
        {
            normalizedTyped = ContextPhysicalTargetForm.NormalizeForComparison(
                typedTargetForm ?? string.Empty,
                trimHarmlessOuterPunctuation: true);
            typedTokens = SentenceTokenizer.Tokenize(typedTargetForm ?? string.Empty).ToArray();
        }
        catch (InvalidDataException)
        {
            return new ContextTargetSpellingResult(
                false,
                true,
                false,
                "The typed target form contains malformed Unicode and was not accepted.");
        }

        if (string.Equals(_expectedNormalizedForm, normalizedTyped, StringComparison.Ordinal))
            return new ContextTargetSpellingResult(true, false, false, "Correct target form.");

        bool sameWordsWrongOrder = _expectedTokens.Length == typedTokens.Length &&
            !_expectedTokens.SequenceEqual(typedTokens, StringComparer.Ordinal) &&
            _expectedTokens.OrderBy(token => token, StringComparer.Ordinal)
                .SequenceEqual(typedTokens.OrderBy(token => token, StringComparer.Ordinal), StringComparer.Ordinal);

        return new ContextTargetSpellingResult(
            false,
            false,
            sameWordsWrongOrder,
            sameWordsWrongOrder
                ? "The target words are present, but the target phrase word order is wrong."
                : "The target form is not exact. Check spelling, spaces, hyphens and apostrophes, or use Show answer.");
    }

    public string RevealExpectedForm() => _expectedPhysicalForm;
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

        if (lexicon.IsAmbiguousStableIdentity(focusId))
        {
            string lexicalKey = lexicon.LexicalKeyFor(focusId);
            string candidates = string.Join("|", lexicon.StableIdsForLexicalKey(lexicalKey));
            throw new InvalidDataException(
                $"Sentence target-spelling stable ID {focusId} is unresolved because physical form '{lexicalKey}' maps to multiple dictionary entries [{candidates}]. Explicit POS/sense evidence is required before this exercise can own canonical progress.");
        }

        string physicalForm = ContextPhysicalTargetForm.CanonicalDisplay(target.Source);
        Regex occurrenceRegex = ContextPhysicalTargetForm.BuildOccurrenceRegex(physicalForm);
        MatchCollection occurrences = occurrenceRegex.Matches(card.EnglishAnswer);
        if (occurrences.Count == 0)
        {
            throw new InvalidDataException(
                $"Sentence {card.SentenceId} indexes target {focusId}, but exact physical dictionary form '{physicalForm}' is not present in the canonical English sentence. Target-form spelling fails closed rather than guessing morphology, spacing or hyphenation.");
        }
        if (occurrences.Count > 1)
        {
            throw new InvalidDataException(
                $"Sentence {card.SentenceId} contains the exact physical dictionary form '{physicalForm}' more than once. Target-form spelling fails closed because one typed answer must correspond to exactly one missing target occurrence.");
        }

        var prompt = new ContextTargetSpellingPrompt(
            card.SentenceId,
            focusId,
            target.Target,
            card.UkrainianPrompt,
            occurrenceRegex.Replace(card.EnglishAnswer, "[blank]", 1),
            card.SourceId,
            card.SourceKind,
            card.Provenance,
            card.License,
            card.LocalTextLocation,
            "Type only the missing target word or phrase. Do not type the whole English sentence.");
        return new ContextTargetSpellingExercise(prompt, physicalForm);
    }

    public static IReadOnlyList<ContextTargetSpellingExercise> BuildAllTargets(
        ContextPracticeCard card,
        ContextTargetLexicon lexicon,
        DictionaryPackage dictionary) =>
        ContextTargetIds.NormalizeRequired(card.TargetEntryIds)
            .Select(id => Build(card, id, lexicon, dictionary))
            .ToArray();
}
