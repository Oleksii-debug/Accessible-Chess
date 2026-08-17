using System.Globalization;

namespace WordDeck;

internal sealed record TatoebaSentencePair(
    long EnglishId,
    string English,
    long UkrainianId,
    string Ukrainian,
    string? EnglishAuthor = null,
    string? UkrainianAuthor = null);

internal sealed record SentencePackBuildReport(
    int InputPairs,
    int AcceptedPairs,
    int RejectedPairs,
    int IndexedEntryIds,
    int OffListTokens);

internal static class TatoebaPairTsv
{
    public static IEnumerable<TatoebaSentencePair> ParseLines(IEnumerable<string> lines)
    {
        int lineNumber = 0;
        foreach (string raw in lines)
        {
            lineNumber++;
            if (string.IsNullOrWhiteSpace(raw) || raw.StartsWith('#'))
                continue;

            string[] columns = raw.Split('\t');
            if (LooksLikeHeader(columns))
                continue;

            if (columns.Length == 8)
            {
                string enLang = columns[1].Trim();
                string ukLang = columns[5].Trim();
                if (!IsEnglish(enLang) || !IsUkrainian(ukLang))
                    throw new InvalidDataException($"Tatoeba pair line {lineNumber} is not EN-UA: {enLang}/{ukLang}.");

                yield return ParsePair(
                    columns[0], columns[2], columns[4], columns[6], lineNumber,
                    columns[3], columns[7], requireAuthors: true);
                continue;
            }

            if (columns.Length == 6)
            {
                string enLang = columns[1].Trim();
                string ukLang = columns[4].Trim();
                if (!IsEnglish(enLang) || !IsUkrainian(ukLang))
                    throw new InvalidDataException($"Tatoeba pair line {lineNumber} is not EN-UA: {enLang}/{ukLang}.");

                yield return ParsePair(columns[0], columns[2], columns[3], columns[5], lineNumber);
                continue;
            }

            if (columns.Length == 4)
            {
                yield return ParsePair(columns[0], columns[1], columns[2], columns[3], lineNumber);
                continue;
            }

            throw new InvalidDataException(
                $"Tatoeba pair line {lineNumber} has {columns.Length} columns. Expected 4, 6, or attributed 8-column EN-UA layout.");
        }
    }

    private static TatoebaSentencePair ParsePair(
        string enIdRaw,
        string englishRaw,
        string ukIdRaw,
        string ukrainianRaw,
        int lineNumber,
        string? englishAuthorRaw = null,
        string? ukrainianAuthorRaw = null,
        bool requireAuthors = false)
    {
        if (!long.TryParse(enIdRaw.Trim(), NumberStyles.None, CultureInfo.InvariantCulture, out long enId) || enId <= 0)
            throw new InvalidDataException($"Tatoeba pair line {lineNumber} has an invalid English sentence id.");
        if (!long.TryParse(ukIdRaw.Trim(), NumberStyles.None, CultureInfo.InvariantCulture, out long ukId) || ukId <= 0)
            throw new InvalidDataException($"Tatoeba pair line {lineNumber} has an invalid Ukrainian sentence id.");

        string english = englishRaw.Trim();
        string ukrainian = ukrainianRaw.Trim();
        if (english.Length == 0 || ukrainian.Length == 0)
            throw new InvalidDataException($"Tatoeba pair line {lineNumber} contains blank sentence text.");
        if (english.Contains('\t') || ukrainian.Contains('\t'))
            throw new InvalidDataException($"Tatoeba pair line {lineNumber} contains an unexpected embedded TAB.");

        string? englishAuthor = NormalizeAuthor(englishAuthorRaw);
        string? ukrainianAuthor = NormalizeAuthor(ukrainianAuthorRaw);
        if (requireAuthors && (englishAuthor is null || ukrainianAuthor is null))
            throw new InvalidDataException($"Tatoeba attributed pair line {lineNumber} is missing an author username.");

        return new TatoebaSentencePair(enId, english, ukId, ukrainian, englishAuthor, ukrainianAuthor);
    }

    private static string? NormalizeAuthor(string? raw)
    {
        if (string.IsNullOrWhiteSpace(raw)) return null;
        string value = raw.Trim();
        return value is "\\N" or "-" or "?" ? null : value;
    }

    private static bool LooksLikeHeader(string[] columns)
    {
        if (columns.Length == 0)
            return false;
        string first = columns[0].Trim();
        return first.Equals("english_id", StringComparison.OrdinalIgnoreCase) ||
               first.Equals("sentence_id", StringComparison.OrdinalIgnoreCase) ||
               first.Equals("en_id", StringComparison.OrdinalIgnoreCase);
    }

    private static bool IsEnglish(string value) =>
        value.Equals("en", StringComparison.OrdinalIgnoreCase) || value.Equals("eng", StringComparison.OrdinalIgnoreCase);

    private static bool IsUkrainian(string value) =>
        value.Equals("uk", StringComparison.OrdinalIgnoreCase) || value.Equals("ukr", StringComparison.OrdinalIgnoreCase);
}

internal static class TatoebaSentencePackBuilder
{
    private const int MinTokens = 2;
    private const int MaxTokens = 24;

    public static (SentencePack Pack, SentencePackBuildReport Report) Build(
        IEnumerable<TatoebaSentencePair> pairs,
        DictionaryPackage dictionary,
        string packId,
        string provenance,
        string license)
    {
        if (string.IsNullOrWhiteSpace(packId))
            throw new ArgumentException("SentencePack id is required.", nameof(packId));
        if (string.IsNullOrWhiteSpace(provenance))
            throw new ArgumentException("SentencePack provenance is required.", nameof(provenance));
        if (string.IsNullOrWhiteSpace(license))
            throw new ArgumentException("SentencePack license is required.", nameof(license));

        Dictionary<string, List<DictionaryEntry>> bySurface = BuildSurfaceIndex(dictionary.Entries);
        var sentences = new List<SentenceRecord>();
        var stableIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        int input = 0;
        int rejected = 0;
        int indexedIds = 0;
        int offListTotal = 0;

        foreach (TatoebaSentencePair pair in pairs)
        {
            input++;
            IReadOnlyList<string> tokens = SentenceTokenizer.Tokenize(pair.English);
            if (tokens.Count < MinTokens || tokens.Count > MaxTokens)
            {
                rejected++;
                continue;
            }

            string stableId = $"tatoeba-en-{pair.EnglishId}-uk-{pair.UkrainianId}";
            if (!stableIds.Add(stableId))
            {
                rejected++;
                continue;
            }

            var targetIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var entryLevels = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            int offList = 0;
            foreach (string token in tokens)
            {
                if (!bySurface.TryGetValue(token, out List<DictionaryEntry>? entries))
                {
                    offList++;
                    continue;
                }

                foreach (DictionaryEntry entry in entries)
                {
                    targetIds.Add(entry.Id);
                    entryLevels[entry.Id] = entry.Level;
                }
            }

            if (targetIds.Count == 0)
            {
                rejected++;
                continue;
            }

            string difficulty = EstimateDifficulty(tokens, bySurface);
            var flags = new List<string>();
            if (offList > Math.Max(2, tokens.Count / 3))
                flags.Add("high-off-list-context");
            if (tokens.Count > 16)
                flags.Add("long-sentence");

            sentences.Add(new SentenceRecord
            {
                Id = stableId,
                English = pair.English,
                Ukrainian = pair.Ukrainian,
                Source = BuildRecordSource(pair),
                License = license,
                SourceSentenceId = pair.EnglishId.ToString(CultureInfo.InvariantCulture),
                TranslationSentenceId = pair.UkrainianId.ToString(CultureInfo.InvariantCulture),
                Tokens = tokens.ToList(),
                Lemmas = tokens.ToList(),
                TargetEntryIds = targetIds.OrderBy(id => id, StringComparer.Ordinal).ToList(),
                EntryLevels = entryLevels,
                DifficultyLevel = difficulty,
                OffListTokenCount = offList,
                QualityFlags = flags
            });
            indexedIds += targetIds.Count;
            offListTotal += offList;
        }

        var pack = new SentencePack
        {
            PackId = packId,
            Provenance = provenance,
            License = license,
            Sentences = sentences
        };
        pack.Validate();
        return (pack, new SentencePackBuildReport(input, sentences.Count, rejected, indexedIds, offListTotal));
    }

    private static string BuildRecordSource(TatoebaSentencePair pair)
    {
        if (!string.IsNullOrWhiteSpace(pair.EnglishAuthor) && !string.IsNullOrWhiteSpace(pair.UkrainianAuthor))
            return $"Tatoeba; English sentence #{pair.EnglishId} by {pair.EnglishAuthor}; Ukrainian sentence #{pair.UkrainianId} by {pair.UkrainianAuthor}.";
        return "Tatoeba EN-UA sentence-pair export";
    }

    private static Dictionary<string, List<DictionaryEntry>> BuildSurfaceIndex(IEnumerable<DictionaryEntry> entries)
    {
        var result = new Dictionary<string, List<DictionaryEntry>>(StringComparer.OrdinalIgnoreCase);
        foreach (DictionaryEntry entry in entries)
        {
            IReadOnlyList<string> tokens = SentenceTokenizer.Tokenize(entry.Source);
            if (tokens.Count != 1)
                continue;
            string normalizedSource = SentenceTokenizer.NormalizeToken(entry.Source);
            if (!string.Equals(tokens[0], normalizedSource, StringComparison.Ordinal))
                continue;
            if (!result.TryGetValue(normalizedSource, out List<DictionaryEntry>? list))
            {
                list = new List<DictionaryEntry>();
                result[normalizedSource] = list;
            }
            list.Add(entry);
        }
        return result;
    }

    private static string EstimateDifficulty(IReadOnlyList<string> tokens, IReadOnlyDictionary<string, List<DictionaryEntry>> bySurface)
    {
        int max = 1;
        foreach (string token in tokens)
        {
            if (!bySurface.TryGetValue(token, out List<DictionaryEntry>? entries))
                continue;
            int tokenLevel = entries.Select(entry => LevelValue(entry.Level)).DefaultIfEmpty(1).Min();
            max = Math.Max(max, tokenLevel);
        }
        return max switch { <= 1 => "A1", 2 => "A2", 3 => "B1", 4 => "B2", 5 => "C1", _ => "C2" };
    }

    private static int LevelValue(string level) => level.ToUpperInvariant() switch
    {
        "A1" => 1,
        "A2" => 2,
        "B1" => 3,
        "B2" => 4,
        "C1" => 5,
        "C2" => 6,
        _ => 7
    };
}
