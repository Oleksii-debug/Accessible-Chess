using System.Text;
using System.Text.RegularExpressions;

namespace WordDeck;

internal sealed record BookPhysicalOccurrence(
    string SentenceId,
    int OccurrenceOrdinal,
    long StartOffset,
    long EndOffset,
    string Surface,
    string NormalizedForm,
    IReadOnlyList<string> StableEntryIds,
    BookWordState State)
{
    public bool IsMapped => StableEntryIds.Count > 0;
    public bool IsAmbiguous => StableEntryIds.Count > 1;
}

internal sealed record BookPhysicalSentenceAnalysis(
    BookSentenceRecord Sentence,
    IReadOnlyList<BookPhysicalOccurrence> Occurrences,
    int Known,
    int Learning,
    int New,
    int OffList,
    double FamiliarityPercent,
    double DifficultyScore)
{
    public int PhysicalLexicalCount => Occurrences.Count;
}

internal sealed record BookPhysicalAnalysis(
    string BookId,
    IReadOnlyList<BookPhysicalSentenceAnalysis> Sentences,
    int PhysicalLexicalCount,
    int Known,
    int Learning,
    int New,
    int OffList,
    int AmbiguousOccurrences,
    double FamiliarityPercent,
    double DifficultyScore,
    string MappingMode);

/// <summary>
/// Exact lexical-form mapper for private reading sources. It deliberately does
/// not pretend to lemmatize inflected forms. One physical occurrence is counted
/// once even when the same surface form maps to multiple stable dictionary IDs.
/// An unresolved multi-ID homograph is fail-closed: it can never inherit Known
/// or Learning mastery from only one candidate stable ID.
/// </summary>
internal sealed partial class BookLexicalFormIndex : IBookLexiconMapper
{
    [GeneratedRegex(@"[\p{L}\p{M}\p{Nd}]+(?:['’\-][\p{L}\p{M}\p{Nd}]+)*", RegexOptions.CultureInvariant)]
    private static partial Regex TokenRegex();

    private readonly Dictionary<string, string[]> _entryIdsByForm;
    private readonly int _maximumTokensPerForm;

    public const string MappingMode = "exact-lexical-form";

    public BookLexicalFormIndex(DictionaryPackage dictionary)
    {
        ArgumentNullException.ThrowIfNull(dictionary);
        _entryIdsByForm = dictionary.Entries
            .Where(entry => entry is not null && !string.IsNullOrWhiteSpace(entry.Id) && !string.IsNullOrWhiteSpace(entry.Source))
            .Select(entry => (Form: NormalizeForm(entry.Source), Id: entry.Id.Trim().ToLowerInvariant()))
            .Where(item => item.Form.Length > 0 && item.Id.Length > 0)
            .GroupBy(item => item.Form, StringComparer.OrdinalIgnoreCase)
            .ToDictionary(
                group => group.Key,
                group => group.Select(item => item.Id)
                    .Distinct(StringComparer.OrdinalIgnoreCase)
                    .OrderBy(id => id, StringComparer.Ordinal)
                    .ToArray(),
                StringComparer.OrdinalIgnoreCase);
        _maximumTokensPerForm = Math.Max(1, _entryIdsByForm.Keys.Select(CountTokens).DefaultIfEmpty(1).Max());
    }

    public IReadOnlyList<string> MapStableEntryIds(string normalizedSentenceText) =>
        MatchOccurrences(normalizedSentenceText, sentenceId: string.Empty, globalOffset: 0, known: null, learning: null)
            .SelectMany(item => item.StableEntryIds)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(id => id, StringComparer.Ordinal)
            .ToArray();

    public BookPhysicalAnalysis Analyze(
        BookDocument document,
        IReadOnlySet<string>? knownEntryIds,
        IReadOnlySet<string>? learningEntryIds)
    {
        ArgumentNullException.ThrowIfNull(document);
        document.Validate();
        HashSet<string> known = NormalizeIdSet(knownEntryIds);
        HashSet<string> learning = NormalizeIdSet(learningEntryIds);
        learning.ExceptWith(known);

        var sentences = new List<BookPhysicalSentenceAnalysis>();
        int total = 0;
        int knownCount = 0;
        int learningCount = 0;
        int newCount = 0;
        int offList = 0;
        int ambiguous = 0;

        foreach (BookSentenceRecord sentence in document.Chapters.OrderBy(chapter => chapter.ChapterOrdinal).SelectMany(chapter => chapter.Sentences.OrderBy(item => item.SentenceOrdinal)))
        {
            IReadOnlyList<BookPhysicalOccurrence> occurrences = MatchOccurrences(sentence.Text, sentence.SentenceId, sentence.Span.StartOffset, known, learning);
            int sentenceKnown = occurrences.Count(item => item.State == BookWordState.Known);
            int sentenceLearning = occurrences.Count(item => item.State == BookWordState.Learning);
            int sentenceNew = occurrences.Count(item => item.State == BookWordState.New);
            int sentenceOffList = occurrences.Count(item => !item.IsMapped);
            int sentenceTotal = occurrences.Count;
            double familiarity = sentenceTotal == 0 ? 100.0 : sentenceKnown * 100.0 / sentenceTotal;
            double difficulty = sentenceTotal == 0 ? 0.0 : (sentenceNew + sentenceLearning * 0.35) * 100.0 / sentenceTotal;
            sentences.Add(new BookPhysicalSentenceAnalysis(
                sentence,
                occurrences,
                sentenceKnown,
                sentenceLearning,
                sentenceNew,
                sentenceOffList,
                familiarity,
                difficulty));
            total += sentenceTotal;
            knownCount += sentenceKnown;
            learningCount += sentenceLearning;
            newCount += sentenceNew;
            offList += sentenceOffList;
            ambiguous += occurrences.Count(item => item.IsAmbiguous);
        }

        double bookFamiliarity = total == 0 ? 100.0 : knownCount * 100.0 / total;
        double bookDifficulty = total == 0 ? 0.0 : (newCount + learningCount * 0.35) * 100.0 / total;
        return new BookPhysicalAnalysis(
            document.BookId,
            sentences,
            total,
            knownCount,
            learningCount,
            newCount,
            offList,
            ambiguous,
            bookFamiliarity,
            bookDifficulty,
            MappingMode);
    }

    public IReadOnlyList<BookPhysicalOccurrence> AnalyzeSentence(
        BookSentenceRecord sentence,
        IReadOnlySet<string>? knownEntryIds = null,
        IReadOnlySet<string>? learningEntryIds = null)
    {
        ArgumentNullException.ThrowIfNull(sentence);
        HashSet<string> known = NormalizeIdSet(knownEntryIds);
        HashSet<string> learning = NormalizeIdSet(learningEntryIds);
        learning.ExceptWith(known);
        return MatchOccurrences(sentence.Text, sentence.SentenceId, sentence.Span.StartOffset, known, learning);
    }

    private IReadOnlyList<BookPhysicalOccurrence> MatchOccurrences(
        string text,
        string sentenceId,
        long globalOffset,
        IReadOnlySet<string>? known,
        IReadOnlySet<string>? learning)
    {
        text ??= string.Empty;
        Match[] tokens = TokenRegex().Matches(text).Cast<Match>().ToArray();
        var result = new List<BookPhysicalOccurrence>();
        int tokenIndex = 0;
        while (tokenIndex < tokens.Length)
        {
            int selectedTokenCount = 1;
            string selectedForm = NormalizeForm(tokens[tokenIndex].Value);
            string[] selectedIds = Array.Empty<string>();
            int maximum = Math.Min(_maximumTokensPerForm, tokens.Length - tokenIndex);
            for (int count = maximum; count >= 1; count--)
            {
                Match first = tokens[tokenIndex];
                Match last = tokens[tokenIndex + count - 1];
                int end = checked(last.Index + last.Length);
                string form = NormalizeForm(text[first.Index..end]);
                if (!_entryIdsByForm.TryGetValue(form, out string[]? ids) || ids is null || ids.Length == 0)
                    continue;
                selectedTokenCount = count;
                selectedForm = form;
                selectedIds = ids;
                break;
            }

            Match startToken = tokens[tokenIndex];
            Match endToken = tokens[tokenIndex + selectedTokenCount - 1];
            int localEnd = checked(endToken.Index + endToken.Length);
            string surface = text[startToken.Index..localEnd];
            BookWordState state = Classify(selectedIds, known, learning);
            result.Add(new BookPhysicalOccurrence(
                sentenceId,
                result.Count,
                checked(globalOffset + startToken.Index),
                checked(globalOffset + localEnd),
                surface,
                selectedForm,
                selectedIds,
                state));
            tokenIndex += selectedTokenCount;
        }
        return result;
    }

    private static BookWordState Classify(IReadOnlyList<string> ids, IReadOnlySet<string>? known, IReadOnlySet<string>? learning)
    {
        // A physical form matching more than one stable lexical identity is
        // unresolved. Preserve every candidate ID via StableEntryIds/IsAmbiguous,
        // but never guess that mastery of one sense/POS proves this occurrence.
        if (ids.Count > 1) return BookWordState.New;
        if (ids.Count == 1 && known is not null && known.Contains(ids[0])) return BookWordState.Known;
        if (ids.Count == 1 && learning is not null && learning.Contains(ids[0])) return BookWordState.Learning;
        return BookWordState.New;
    }

    internal static string NormalizeForm(string value)
    {
        if (string.IsNullOrWhiteSpace(value)) return string.Empty;
        string canonical = value.Normalize(NormalizationForm.FormKC).ToLowerInvariant().Replace('’', '\'');
        return string.Join(' ', TokenRegex().Matches(canonical).Cast<Match>().Select(match => match.Value));
    }

    private static int CountTokens(string value) => TokenRegex().Matches(value).Count;

    private static HashSet<string> NormalizeIdSet(IEnumerable<string>? values) =>
        new((values ?? Array.Empty<string>())
            .Where(value => !string.IsNullOrWhiteSpace(value))
            .Select(value => value.Trim().ToLowerInvariant()), StringComparer.OrdinalIgnoreCase);
}
