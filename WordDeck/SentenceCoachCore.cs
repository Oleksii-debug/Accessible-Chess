using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace WordDeck;

internal interface ISentenceCorpus
{
    string PackId { get; }
    string License { get; }
    int SentenceCount { get; }
    IReadOnlyList<SentenceRecord> LookupByEntryId(string entryId);
    IReadOnlyList<SentenceRecord> LookupAllTargets(IReadOnlyCollection<string> targetEntryIds);
}

internal sealed class SentencePack : ISentenceCorpus
{
    public const int CurrentVersion = 1;
    public int Version { get; init; } = CurrentVersion;
    public string SourceLanguage { get; init; } = "en";
    public string TargetLanguage { get; init; } = "uk";
    public string PackId { get; init; } = string.Empty;
    public string Provenance { get; init; } = string.Empty;
    public string License { get; init; } = string.Empty;
    public List<SentenceRecord> Sentences { get; init; } = new();
    public int SentenceCount => Sentences?.Count ?? 0;

    private Dictionary<string, List<SentenceRecord>>? _byEntryId;
    private Dictionary<string, List<SentenceRecord>>? _byLemma;

    public void Validate()
    {
        if (Version != CurrentVersion)
            throw new InvalidDataException($"Unsupported SentencePack version {Version}.");
        RequireCanonicalValue(PackId, "SentencePack id");
        RequireCanonicalValue(Provenance, "SentencePack provenance");
        RequireCanonicalValue(License, "SentencePack license");
        if (!string.Equals(SourceLanguage, "en", StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(TargetLanguage, "uk", StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("This Sentence Coach build currently requires an EN-UA pack.");
        if (Sentences is null)
            throw new InvalidDataException("SentencePack sentence list is missing.");
        if (Sentences.Count == 0)
            throw new InvalidDataException("SentencePack contains no sentences.");
        if (Sentences.Any(sentence => sentence is null))
            throw new InvalidDataException("SentencePack contains a null sentence record.");
        if (Sentences.Select(sentence => sentence.Id).Distinct(StringComparer.OrdinalIgnoreCase).Count() != Sentences.Count)
            throw new InvalidDataException("SentencePack contains duplicate stable sentence IDs.");
        foreach (SentenceRecord sentence in Sentences)
            sentence.Validate();
        BuildIndexes();
    }

    public IReadOnlyList<SentenceRecord> LookupByEntryId(string entryId)
    {
        EnsureIndexes();
        string key = NormalizeEntryId(entryId);
        return key.Length > 0 && _byEntryId!.TryGetValue(key, out List<SentenceRecord>? values)
            ? values
            : Array.Empty<SentenceRecord>();
    }

    public IReadOnlyList<SentenceRecord> LookupByLemma(string lemma)
    {
        EnsureIndexes();
        string normalized = SentenceTokenizer.NormalizeToken(lemma);
        return _byLemma!.TryGetValue(normalized, out List<SentenceRecord>? values)
            ? values
            : Array.Empty<SentenceRecord>();
    }

    public IReadOnlyList<SentenceRecord> LookupAllTargets(IReadOnlyCollection<string> targetEntryIds)
    {
        if (targetEntryIds.Count == 0)
            return Array.Empty<SentenceRecord>();
        EnsureIndexes();

        string[] targets = targetEntryIds
            .Select(NormalizeEntryId)
            .Where(id => id.Length > 0)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
        if (targets.Length == 0)
            return Array.Empty<SentenceRecord>();

        if (!_byEntryId!.TryGetValue(targets[0], out List<SentenceRecord>? firstCandidates))
            return Array.Empty<SentenceRecord>();
        if (targets.Length == 1)
            return firstCandidates;

        var survivingIds = new HashSet<string>(firstCandidates.Select(sentence => sentence.Id), StringComparer.OrdinalIgnoreCase);
        foreach (string target in targets.Skip(1))
        {
            if (!_byEntryId.TryGetValue(target, out List<SentenceRecord>? candidates))
                return Array.Empty<SentenceRecord>();
            survivingIds.IntersectWith(candidates.Select(sentence => sentence.Id));
            if (survivingIds.Count == 0)
                return Array.Empty<SentenceRecord>();
        }
        return firstCandidates.Where(sentence => survivingIds.Contains(sentence.Id)).ToList();
    }

    private void EnsureIndexes()
    {
        if (_byEntryId is null || _byLemma is null)
            BuildIndexes();
    }

    private void BuildIndexes()
    {
        _byEntryId = new(StringComparer.OrdinalIgnoreCase);
        _byLemma = new(StringComparer.OrdinalIgnoreCase);
        foreach (SentenceRecord sentence in Sentences)
        {
            foreach (string entryId in sentence.TargetEntryIds.Select(NormalizeEntryId).Distinct(StringComparer.OrdinalIgnoreCase))
                Add(_byEntryId, entryId, sentence);
            foreach (string lemma in sentence.Lemmas.Select(SentenceTokenizer.NormalizeToken).Where(value => value.Length > 0).Distinct(StringComparer.OrdinalIgnoreCase))
                Add(_byLemma, lemma, sentence);
        }
    }

    private static void Add(Dictionary<string, List<SentenceRecord>> index, string key, SentenceRecord sentence)
    {
        if (!index.TryGetValue(key, out List<SentenceRecord>? list))
        {
            list = new List<SentenceRecord>();
            index[key] = list;
        }
        list.Add(sentence);
    }

    private static string NormalizeEntryId(string value) => (value ?? string.Empty).Trim().ToLowerInvariant();

    internal static void RequireCanonicalValue(string? value, string description)
    {
        if (string.IsNullOrWhiteSpace(value))
            throw new InvalidDataException($"{description} is required.");
        if (!string.Equals(value, value.Trim(), StringComparison.Ordinal))
            throw new InvalidDataException($"{description} must not have leading or trailing whitespace.");
        SentenceTokenizer.ValidateUnicode(value, description);
    }
}

internal sealed class SentenceRecord
{
    public string Id { get; init; } = string.Empty;
    public string English { get; init; } = string.Empty;
    public string Ukrainian { get; init; } = string.Empty;
    public string Source { get; init; } = string.Empty;
    public string License { get; init; } = string.Empty;
    public string? SourceSentenceId { get; init; }
    public string? TranslationSentenceId { get; init; }
    public List<string> Tokens { get; init; } = new();
    public List<string> Lemmas { get; init; } = new();
    public List<string> TargetEntryIds { get; init; } = new();
    public Dictionary<string, string> EntryLevels { get; init; } = new(StringComparer.OrdinalIgnoreCase);
    public string DifficultyLevel { get; init; } = "A1";
    public int OffListTokenCount { get; init; }
    public List<string> QualityFlags { get; init; } = new();

    public int Length => Tokens?.Count ?? 0;

    public void Validate()
    {
        SentencePack.RequireCanonicalValue(Id, "Sentence id");
        SentencePack.RequireCanonicalValue(English, $"Sentence {Id} English text");
        SentencePack.RequireCanonicalValue(Ukrainian, $"Sentence {Id} Ukrainian text");
        SentencePack.RequireCanonicalValue(Source, $"Sentence {Id} provenance source");
        SentencePack.RequireCanonicalValue(License, $"Sentence {Id} license");

        if (Tokens is null || Lemmas is null || TargetEntryIds is null || EntryLevels is null || QualityFlags is null)
            throw new InvalidDataException($"Sentence {Id} contains a missing collection field.");
        if (ContainsLineBreakOrTab(English) || ContainsLineBreakOrTab(Ukrainian))
            throw new InvalidDataException($"Sentence {Id} text contains an embedded TAB or line break.");

        IReadOnlyList<string> canonical = SentenceTokenizer.Tokenize(English);
        if (Tokens.Count == 0 || !Tokens.SequenceEqual(canonical, StringComparer.Ordinal))
            throw new InvalidDataException($"Sentence {Id} token index does not match its English text.");
        if (Lemmas.Count != Tokens.Count || Lemmas.Any(string.IsNullOrWhiteSpace))
            throw new InvalidDataException($"Sentence {Id} must have one non-blank lemma per normalized token.");
        foreach (string lemma in Lemmas)
            SentenceTokenizer.ValidateUnicode(lemma, $"Sentence {Id} lemma");

        if (TargetEntryIds.Count == 0 || TargetEntryIds.Any(string.IsNullOrWhiteSpace))
            throw new InvalidDataException($"Sentence {Id} does not index any valid target dictionary entries.");
        if (TargetEntryIds.Any(entryId => !string.Equals(entryId, entryId.Trim(), StringComparison.Ordinal)))
            throw new InvalidDataException($"Sentence {Id} contains a non-canonical target entry ID.");
        if (TargetEntryIds.Distinct(StringComparer.OrdinalIgnoreCase).Count() != TargetEntryIds.Count)
            throw new InvalidDataException($"Sentence {Id} contains duplicate target entry IDs.");
        foreach (string entryId in TargetEntryIds)
            SentenceTokenizer.ValidateUnicode(entryId, $"Sentence {Id} target entry ID");

        if (EntryLevels.Any(pair => string.IsNullOrWhiteSpace(pair.Key) || !IsSupportedLevel(pair.Value)))
            throw new InvalidDataException($"Sentence {Id} contains an unsupported or blank CEFR entry level.");
        if (TargetEntryIds.Any(entryId => !EntryLevels.ContainsKey(entryId)))
            throw new InvalidDataException($"Sentence {Id} is missing CEFR metadata for a target entry.");
        if (!IsSupportedLevel(DifficultyLevel))
            throw new InvalidDataException($"Sentence {Id} has unsupported difficulty level {DifficultyLevel}. WordDeck v1 supports A1 through C1 only.");
        if (OffListTokenCount < 0 || OffListTokenCount > Tokens.Count)
            throw new InvalidDataException($"Sentence {Id} has an invalid off-list token count.");
        if (QualityFlags.Any(string.IsNullOrWhiteSpace))
            throw new InvalidDataException($"Sentence {Id} contains a blank quality flag.");
        foreach (string flag in QualityFlags)
            SentenceTokenizer.ValidateUnicode(flag, $"Sentence {Id} quality flag");
    }

    private static bool IsSupportedLevel(string? level) => level?.ToUpperInvariant() is "A1" or "A2" or "B1" or "B2" or "C1";

    private static bool ContainsLineBreakOrTab(string value) => value.IndexOfAny(new[] { '\r', '\n', '\t' }) >= 0;
}

internal static partial class SentenceTokenizer
{
    [GeneratedRegex("[A-Za-z]+(?:['’][A-Za-z]+)?", RegexOptions.CultureInvariant)]
    private static partial Regex EnglishTokenRegex();

    public static IReadOnlyList<string> Tokenize(string text)
    {
        string normalizedText = NormalizeText(text ?? string.Empty);
        return EnglishTokenRegex().Matches(normalizedText)
            .Select(match => NormalizeToken(match.Value))
            .Where(token => token.Length > 0)
            .ToList();
    }

    public static string NormalizeToken(string token) => NormalizeText(token ?? string.Empty).Trim().ToLowerInvariant();

    internal static void ValidateUnicode(string value, string description)
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

    private static string NormalizeText(string value)
    {
        ValidateUnicode(value, "Sentence text");
        return NormalizeApostrophes(value.Normalize(NormalizationForm.FormKC));
    }

    private static string NormalizeApostrophes(string value) => value.Replace('’', '\'').Replace('‘', '\'').Replace('`', '\'');
}

internal sealed record SentenceAnswerResult(
    bool Accepted,
    bool WordOrderIgnored,
    IReadOnlyList<string> Missing,
    IReadOnlyList<string> Extra,
    IReadOnlyList<string> PossibleMisspellings,
    string Feedback);

internal static class SentenceAnswerEvaluator
{
    public static SentenceAnswerResult Evaluate(string requiredEnglish, string typedEnglish)
    {
        List<string> required = SentenceTokenizer.Tokenize(requiredEnglish).ToList();
        List<string> typed;
        try
        {
            typed = SentenceTokenizer.Tokenize(typedEnglish).ToList();
        }
        catch (InvalidDataException)
        {
            return new SentenceAnswerResult(
                false,
                false,
                Array.Empty<string>(),
                Array.Empty<string>(),
                Array.Empty<string>(),
                "The typed answer contains malformed Unicode and was not accepted.");
        }

        Dictionary<string, int> requiredCounts = Counts(required);
        Dictionary<string, int> typedCounts = Counts(typed);
        List<string> missing = ExpandDifference(requiredCounts, typedCounts);
        List<string> extra = ExpandDifference(typedCounts, requiredCounts);
        bool accepted = missing.Count == 0 && extra.Count == 0;
        bool sameOrder = accepted && required.SequenceEqual(typed, StringComparer.Ordinal);
        if (accepted)
        {
            return new SentenceAnswerResult(
                true,
                !sameOrder,
                Array.Empty<string>(),
                Array.Empty<string>(),
                Array.Empty<string>(),
                sameOrder
                    ? "Correct spelling and required forms."
                    : "Correct spelling and required forms. Word order is not checked in Sentence Spelling mode.");
        }

        List<string> misspellings = DiagnoseMisspellings(missing, extra);
        return new SentenceAnswerResult(false, false, missing, extra, misspellings, BuildFeedback(missing, extra, misspellings));
    }

    private static Dictionary<string, int> Counts(IEnumerable<string> tokens) =>
        tokens.GroupBy(token => token, StringComparer.Ordinal)
            .ToDictionary(group => group.Key, group => group.Count(), StringComparer.Ordinal);

    private static List<string> ExpandDifference(Dictionary<string, int> left, Dictionary<string, int> right)
    {
        var result = new List<string>();
        foreach ((string token, int count) in left.OrderBy(pair => pair.Key, StringComparer.Ordinal))
        {
            for (int i = 0; i < Math.Max(0, count - right.GetValueOrDefault(token)); i++)
                result.Add(token);
        }
        return result;
    }

    private static List<string> DiagnoseMisspellings(IReadOnlyList<string> missing, IReadOnlyList<string> extra)
    {
        var result = new List<string>();
        var usedExtra = new HashSet<int>();
        foreach (string required in missing)
        {
            int bestIndex = -1;
            int bestDistance = int.MaxValue;
            for (int i = 0; i < extra.Count; i++)
            {
                if (usedExtra.Contains(i))
                    continue;
                int distance = EditDistance(required, extra[i]);
                int threshold = required.Length <= 4 ? 1 : 2;
                if (distance <= threshold && distance < bestDistance)
                {
                    bestDistance = distance;
                    bestIndex = i;
                }
            }
            if (bestIndex >= 0)
            {
                usedExtra.Add(bestIndex);
                result.Add($"{extra[bestIndex]} -> {required}");
            }
        }
        return result;
    }

    private static int EditDistance(string a, string b)
    {
        int[,] distances = new int[a.Length + 1, b.Length + 1];
        for (int i = 0; i <= a.Length; i++) distances[i, 0] = i;
        for (int j = 0; j <= b.Length; j++) distances[0, j] = j;
        for (int i = 1; i <= a.Length; i++)
        {
            for (int j = 1; j <= b.Length; j++)
            {
                distances[i, j] = Math.Min(
                    Math.Min(distances[i - 1, j] + 1, distances[i, j - 1] + 1),
                    distances[i - 1, j - 1] + (a[i - 1] == b[j - 1] ? 0 : 1));
            }
        }
        return distances[a.Length, b.Length];
    }

    private static string BuildFeedback(IReadOnlyList<string> missing, IReadOnlyList<string> extra, IReadOnlyList<string> misspellings)
    {
        var parts = new List<string>();
        if (missing.Count > 0) parts.Add("Missing required forms: " + string.Join(", ", missing));
        if (extra.Count > 0) parts.Add("Extra or duplicated forms: " + string.Join(", ", extra));
        if (misspellings.Count > 0) parts.Add("Possible misspellings: " + string.Join(", ", misspellings));
        return string.Join(". ", parts) + ".";
    }
}

internal sealed record SentenceSelectionContext(
    IReadOnlySet<string> AllowedTargetEntryIds,
    IReadOnlySet<string> KnownEntryIds,
    IReadOnlySet<string> RecentSentenceIds,
    IReadOnlyDictionary<string, string> EntryLevels);

internal sealed record SentenceSelectionResult(SentenceRecord Sentence, bool Generated, string Explanation);

internal interface IControlledSentenceGenerator
{
    SentenceRecord? TryGenerate(IReadOnlyList<string> targetEntryIds, SentenceSelectionContext context);
}

internal sealed class SentenceSelector
{
    private readonly ISentenceCorpus _corpus;
    private readonly IControlledSentenceGenerator? _fallback;

    public SentenceSelector(ISentenceCorpus corpus, IControlledSentenceGenerator? fallback = null)
    {
        _corpus = corpus;
        _fallback = fallback;
    }

    public SentenceSelectionResult? Select(IReadOnlyList<string> targetEntryIds, SentenceSelectionContext context)
    {
        if (targetEntryIds.Count is < 1 or > 3)
            throw new ArgumentOutOfRangeException(nameof(targetEntryIds), "Sentence Coach supports one to three requested targets.");
        foreach (string target in targetEntryIds)
        {
            if (!context.AllowedTargetEntryIds.Contains(target))
                throw new InvalidOperationException($"Target {target} is outside the selected training scope.");
        }

        IReadOnlyList<SentenceRecord> candidates = _corpus.LookupAllTargets(targetEntryIds);
        if (candidates.Count > 0)
        {
            SentenceRecord best = candidates
                .OrderBy(sentence => Score(sentence, targetEntryIds, context))
                .ThenBy(sentence => sentence.Id, StringComparer.Ordinal)
                .First();
            return new SentenceSelectionResult(best, false,
                "Selected an indexed corpus sentence containing every requested target and ranked it by personal/CEFR context difficulty.");
        }

        SentenceRecord? generated = _fallback?.TryGenerate(targetEntryIds, context);
        if (generated is null)
            return null;
        generated.Validate();
        if (!targetEntryIds.All(target => generated.TargetEntryIds.Contains(target, StringComparer.OrdinalIgnoreCase)))
            throw new InvalidDataException("Controlled generator fallback returned a sentence that does not contain every requested target.");
        return new SentenceSelectionResult(generated, true,
            "No suitable corpus intersection existed; used the controlled offline generator fallback.");
    }

    internal static int Score(SentenceRecord sentence, IReadOnlyList<string> targets, SentenceSelectionContext context)
    {
        var targetSet = new HashSet<string>(targets, StringComparer.OrdinalIgnoreCase);
        int targetLevel = targets.Select(id => LevelValue(context.EntryLevels.GetValueOrDefault(id, "C1"))).DefaultIfEmpty(5).Max();
        int unknownContext = sentence.EntryLevels.Keys.Count(id => !targetSet.Contains(id) && !context.KnownEntryIds.Contains(id));
        int aboveLevelUnknown = sentence.EntryLevels.Count(pair =>
            !targetSet.Contains(pair.Key) && !context.KnownEntryIds.Contains(pair.Key) && LevelValue(pair.Value) > targetLevel);
        int lengthPenalty = Math.Abs(sentence.Length - 8) * 2;
        int recentPenalty = context.RecentSentenceIds.Contains(sentence.Id) ? 250 : 0;
        int qualityPenalty = sentence.QualityFlags.Count * 20;
        return unknownContext * 100 + sentence.OffListTokenCount * 80 + aboveLevelUnknown * 30 + lengthPenalty + recentPenalty + qualityPenalty;
    }

    private static int LevelValue(string level) => level.ToUpperInvariant() switch
    {
        "A1" => 1,
        "A2" => 2,
        "B1" => 3,
        "B2" => 4,
        "C1" => 5,
        _ => 7
    };
}

internal static class SentencePackJson
{
    public static SentencePack Parse(string json)
    {
        SentencePack pack = JsonSerializer.Deserialize<SentencePack>(json, new JsonSerializerOptions { PropertyNameCaseInsensitive = true })
            ?? throw new InvalidDataException("SentencePack JSON is empty.");
        pack.Validate();
        return pack;
    }

    public static string Serialize(SentencePack pack)
    {
        pack.Validate();
        return JsonSerializer.Serialize(pack, new JsonSerializerOptions { WriteIndented = true });
    }
}
