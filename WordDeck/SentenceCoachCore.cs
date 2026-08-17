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
    public int SentenceCount => Sentences.Count;

    private Dictionary<string, List<SentenceRecord>>? _byEntryId;
    private Dictionary<string, List<SentenceRecord>>? _byLemma;

    public void Validate()
    {
        if (Version != CurrentVersion) throw new InvalidDataException($"Unsupported SentencePack version {Version}.");
        if (string.IsNullOrWhiteSpace(PackId)) throw new InvalidDataException("SentencePack id is required.");
        if (string.IsNullOrWhiteSpace(Provenance) || string.IsNullOrWhiteSpace(License)) throw new InvalidDataException("SentencePack provenance and license are required.");
        if (!SourceLanguage.Equals("en", StringComparison.OrdinalIgnoreCase) || !TargetLanguage.Equals("uk", StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("This Sentence Coach build currently requires an EN-UA pack.");
        if (Sentences.Select(s => s.Id).Distinct(StringComparer.OrdinalIgnoreCase).Count() != Sentences.Count)
            throw new InvalidDataException("SentencePack contains duplicate stable sentence IDs.");
        foreach (SentenceRecord sentence in Sentences) sentence.Validate();
        BuildIndexes();
    }

    public IReadOnlyList<SentenceRecord> LookupByEntryId(string entryId)
    {
        EnsureIndexes();
        return _byEntryId!.TryGetValue(entryId, out List<SentenceRecord>? values) ? values : Array.Empty<SentenceRecord>();
    }

    public IReadOnlyList<SentenceRecord> LookupByLemma(string lemma)
    {
        EnsureIndexes();
        string normalized = SentenceTokenizer.NormalizeToken(lemma);
        return _byLemma!.TryGetValue(normalized, out List<SentenceRecord>? values) ? values : Array.Empty<SentenceRecord>();
    }

    public IReadOnlyList<SentenceRecord> LookupAllTargets(IReadOnlyCollection<string> targetEntryIds)
    {
        if (targetEntryIds.Count == 0) return Array.Empty<SentenceRecord>();
        EnsureIndexes();
        List<SentenceRecord>? intersection = null;
        foreach (string target in targetEntryIds.Distinct(StringComparer.OrdinalIgnoreCase))
        {
            if (!_byEntryId!.TryGetValue(target, out List<SentenceRecord>? candidates)) return Array.Empty<SentenceRecord>();
            intersection = intersection is null
                ? candidates.ToList()
                : intersection.Where(existing => candidates.Any(c => string.Equals(c.Id, existing.Id, StringComparison.OrdinalIgnoreCase))).ToList();
            if (intersection.Count == 0) return intersection;
        }
        return intersection is null ? Array.Empty<SentenceRecord>() : intersection;
    }

    private void EnsureIndexes() { if (_byEntryId is null || _byLemma is null) BuildIndexes(); }
    private void BuildIndexes()
    {
        _byEntryId = new(StringComparer.OrdinalIgnoreCase);
        _byLemma = new(StringComparer.OrdinalIgnoreCase);
        foreach (SentenceRecord sentence in Sentences)
        {
            foreach (string entryId in sentence.TargetEntryIds.Distinct(StringComparer.OrdinalIgnoreCase)) Add(_byEntryId, entryId, sentence);
            foreach (string lemma in sentence.Lemmas.Select(SentenceTokenizer.NormalizeToken).Where(x => x.Length > 0).Distinct(StringComparer.OrdinalIgnoreCase)) Add(_byLemma, lemma, sentence);
        }
    }
    private static void Add(Dictionary<string, List<SentenceRecord>> index, string key, SentenceRecord sentence)
    {
        if (!index.TryGetValue(key, out List<SentenceRecord>? list)) { list = new(); index[key] = list; }
        list.Add(sentence);
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

    public int Length => Tokens.Count;

    public void Validate()
    {
        if (string.IsNullOrWhiteSpace(Id) || string.IsNullOrWhiteSpace(English) || string.IsNullOrWhiteSpace(Ukrainian))
            throw new InvalidDataException("Sentence record requires id plus EN and UA text.");
        if (string.IsNullOrWhiteSpace(Source) || string.IsNullOrWhiteSpace(License))
            throw new InvalidDataException($"Sentence {Id} is missing provenance/license.");
        IReadOnlyList<string> canonical = SentenceTokenizer.Tokenize(English);
        if (Tokens.Count == 0 || !Tokens.SequenceEqual(canonical, StringComparer.Ordinal))
            throw new InvalidDataException($"Sentence {Id} token index does not match its English text.");
        if (Lemmas.Count != Tokens.Count) throw new InvalidDataException($"Sentence {Id} must have one lemma per normalized token.");
        if (TargetEntryIds.Count == 0) throw new InvalidDataException($"Sentence {Id} does not index any target dictionary entries.");
    }
}

internal static partial class SentenceTokenizer
{
    [GeneratedRegex("[A-Za-z]+(?:['’][A-Za-z]+)?", RegexOptions.CultureInvariant)]
    private static partial Regex EnglishTokenRegex();

    public static IReadOnlyList<string> Tokenize(string text) =>
        EnglishTokenRegex().Matches(NormalizeApostrophes(text ?? string.Empty)).Select(match => NormalizeToken(match.Value)).Where(token => token.Length > 0).ToList();

    public static string NormalizeToken(string token) => NormalizeApostrophes(token ?? string.Empty).Trim().ToLowerInvariant();
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
        List<string> typed = SentenceTokenizer.Tokenize(typedEnglish).ToList();
        Dictionary<string, int> requiredCounts = Counts(required);
        Dictionary<string, int> typedCounts = Counts(typed);
        var missing = ExpandDifference(requiredCounts, typedCounts);
        var extra = ExpandDifference(typedCounts, requiredCounts);
        bool accepted = missing.Count == 0 && extra.Count == 0;
        bool sameOrder = accepted && required.SequenceEqual(typed, StringComparer.Ordinal);
        if (accepted)
            return new(true, !sameOrder, Array.Empty<string>(), Array.Empty<string>(), Array.Empty<string>(),
                sameOrder ? "Correct spelling and required forms." : "Correct spelling and required forms. Word order is not checked in Sentence Spelling mode.");

        List<string> misspellings = DiagnoseMisspellings(missing, extra);
        string feedback = BuildFeedback(missing, extra, misspellings);
        return new(false, false, missing, extra, misspellings, feedback);
    }

    private static Dictionary<string, int> Counts(IEnumerable<string> tokens) => tokens.GroupBy(x => x, StringComparer.Ordinal).ToDictionary(g => g.Key, g => g.Count(), StringComparer.Ordinal);
    private static List<string> ExpandDifference(Dictionary<string, int> left, Dictionary<string, int> right)
    {
        var result = new List<string>();
        foreach ((string token, int count) in left)
            for (int i = 0; i < Math.Max(0, count - right.GetValueOrDefault(token)); i++) result.Add(token);
        return result;
    }

    private static List<string> DiagnoseMisspellings(IReadOnlyList<string> missing, IReadOnlyList<string> extra)
    {
        var result = new List<string>();
        var usedExtra = new HashSet<int>();
        foreach (string required in missing)
        {
            int bestIndex = -1; int bestDistance = int.MaxValue;
            for (int i = 0; i < extra.Count; i++)
            {
                if (usedExtra.Contains(i)) continue;
                int distance = EditDistance(required, extra[i]);
                int threshold = required.Length <= 4 ? 1 : 2;
                if (distance <= threshold && distance < bestDistance) { bestDistance = distance; bestIndex = i; }
            }
            if (bestIndex >= 0) { usedExtra.Add(bestIndex); result.Add($"{extra[bestIndex]} -> {required}"); }
        }
        return result;
    }

    private static int EditDistance(string a, string b)
    {
        int[,] d = new int[a.Length + 1, b.Length + 1];
        for (int i = 0; i <= a.Length; i++) d[i, 0] = i;
        for (int j = 0; j <= b.Length; j++) d[0, j] = j;
        for (int i = 1; i <= a.Length; i++)
            for (int j = 1; j <= b.Length; j++)
                d[i, j] = Math.Min(Math.Min(d[i - 1, j] + 1, d[i, j - 1] + 1), d[i - 1, j - 1] + (a[i - 1] == b[j - 1] ? 0 : 1));
        return d[a.Length, b.Length];
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
    public SentenceSelector(ISentenceCorpus corpus, IControlledSentenceGenerator? fallback = null) { _corpus = corpus; _fallback = fallback; }

    public SentenceSelectionResult? Select(IReadOnlyList<string> targetEntryIds, SentenceSelectionContext context)
    {
        if (targetEntryIds.Count is < 1 or > 3) throw new ArgumentOutOfRangeException(nameof(targetEntryIds), "Sentence Coach supports one to three requested targets.");
        foreach (string target in targetEntryIds)
            if (!context.AllowedTargetEntryIds.Contains(target)) throw new InvalidOperationException($"Target {target} is outside the selected training scope.");

        IReadOnlyList<SentenceRecord> candidates = _corpus.LookupAllTargets(targetEntryIds);
        if (candidates.Count > 0)
        {
            SentenceRecord best = candidates.OrderBy(sentence => Score(sentence, targetEntryIds, context)).ThenBy(sentence => sentence.Id, StringComparer.Ordinal).First();
            return new(best, false, "Selected an indexed corpus sentence containing every requested target and ranked it by personal/CEFR context difficulty.");
        }

        SentenceRecord? generated = _fallback?.TryGenerate(targetEntryIds, context);
        if (generated is null) return null;
        if (!targetEntryIds.All(target => generated.TargetEntryIds.Contains(target, StringComparer.OrdinalIgnoreCase)))
            throw new InvalidDataException("Controlled generator fallback returned a sentence that does not contain every requested target.");
        return new(generated, true, "No suitable corpus intersection existed; used the controlled offline generator fallback.");
    }

    internal static int Score(SentenceRecord sentence, IReadOnlyList<string> targets, SentenceSelectionContext context)
    {
        var targetSet = new HashSet<string>(targets, StringComparer.OrdinalIgnoreCase);
        int targetLevel = targets.Select(id => LevelValue(context.EntryLevels.GetValueOrDefault(id, "C1"))).DefaultIfEmpty(5).Max();
        int unknownContext = sentence.EntryLevels.Keys.Count(id => !targetSet.Contains(id) && !context.KnownEntryIds.Contains(id));
        int aboveLevelUnknown = sentence.EntryLevels.Count(pair => !targetSet.Contains(pair.Key) && !context.KnownEntryIds.Contains(pair.Key) && LevelValue(pair.Value) > targetLevel);
        int lengthPenalty = Math.Abs(sentence.Length - 8) * 2;
        int recentPenalty = context.RecentSentenceIds.Contains(sentence.Id) ? 250 : 0;
        int qualityPenalty = sentence.QualityFlags.Count * 20;
        return unknownContext * 100 + sentence.OffListTokenCount * 80 + aboveLevelUnknown * 30 + lengthPenalty + recentPenalty + qualityPenalty;
    }

    private static int LevelValue(string level) => level.ToUpperInvariant() switch { "A1" => 1, "A2" => 2, "B1" => 3, "B2" => 4, "C1" => 5, "C2" => 6, _ => 7 };
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
