using System.Text;

namespace WordDeck;

internal enum MorphologyPracticeKind
{
    RelatedFormProduction = 1,
    MorphemeProduction = 2
}

internal sealed record MorphologyRelationExplanation(
    string RelationId,
    string FamilyId,
    string SourceEntryId,
    string TargetEntryId,
    string SourceForm,
    string TargetForm,
    MorphologyRelationKind Kind,
    string? Morpheme,
    string Explanation,
    string EvidenceRef);

internal sealed record MorphologyPracticeItem(
    string ExerciseId,
    MorphologyPracticeKind PracticeKind,
    string Prompt,
    string ExpectedAnswer,
    string SourceEntryId,
    string TargetEntryId,
    string FamilyId,
    MorphologyRelationKind RelationKind,
    string RelationId,
    string EvidenceRef)
{
    public bool Check(string? answer)
    {
        if (string.IsNullOrWhiteSpace(answer)) return false;
        return Normalize(answer).Equals(Normalize(ExpectedAnswer), StringComparison.OrdinalIgnoreCase);
    }

    private static string Normalize(string value) =>
        string.Join(' ', value.Trim().Normalize(NormalizationForm.FormC)
            .Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));
}

/// <summary>
/// Stateless Stage-18 practice projection. It consumes only validated explicit
/// morphology relations and canonical dictionary IDs. It never writes learner
/// progress; the adaptive/mastery owner can record outcomes through its own
/// profile contract after integration.
/// </summary>
internal sealed class MorphologyPracticeService
{
    private readonly MorphologyOverlay _overlay;
    private readonly IReadOnlyDictionary<string, DictionaryEntry> _entries;

    public MorphologyPracticeService(MorphologyOverlay overlay, DictionaryPackage dictionary)
    {
        ArgumentNullException.ThrowIfNull(overlay);
        ArgumentNullException.ThrowIfNull(dictionary);
        _overlay = overlay;
        _entries = dictionary.Entries.ToDictionary(entry => entry.Id, StringComparer.OrdinalIgnoreCase);
    }

    public IReadOnlyList<MorphologyRelationExplanation> ExplainEntry(string entryId, int maxItems = 24)
    {
        if (maxItems is < 1 or > 256) throw new ArgumentOutOfRangeException(nameof(maxItems));
        if (!_entries.ContainsKey(entryId)) return Array.Empty<MorphologyRelationExplanation>();

        var explanations = new List<MorphologyRelationExplanation>();
        foreach (MorphologyRelation relation in _overlay.GetRelations(entryId))
        {
            if (!TryResolveOrientation(entryId, relation, out DictionaryEntry? source, out DictionaryEntry? target))
                continue;

            explanations.Add(new MorphologyRelationExplanation(
                relation.Id,
                relation.FamilyId,
                source.Id,
                target.Id,
                source.Source,
                target.Source,
                relation.Kind,
                relation.Morpheme,
                BuildExplanation(source.Source, target.Source, relation),
                relation.EvidenceRef));
            if (explanations.Count >= maxItems) break;
        }
        return explanations;
    }

    public MorphologyPracticeItem? Create(
        string entryId,
        MorphologyPracticeKind kind,
        int sequence = 0)
    {
        IReadOnlyList<MorphologyRelation> candidates = _overlay.GetRelations(entryId)
            .Where(relation => kind != MorphologyPracticeKind.MorphemeProduction ||
                (relation.Kind is MorphologyRelationKind.Prefix or MorphologyRelationKind.Suffix or MorphologyRelationKind.Root &&
                 !string.IsNullOrWhiteSpace(relation.Morpheme)))
            .ToArray();
        if (candidates.Count == 0) return null;

        int index = PositiveModulo(sequence, candidates.Count);
        MorphologyRelation relation = candidates[index];
        if (!TryResolveOrientation(entryId, relation, out DictionaryEntry? source, out DictionaryEntry? target)) return null;

        return kind switch
        {
            MorphologyPracticeKind.RelatedFormProduction => new MorphologyPracticeItem(
                $"morph:related:{relation.Id}:{source.Id}",
                kind,
                BuildRelatedFormPrompt(source.Source, relation),
                target.Source,
                source.Id,
                target.Id,
                relation.FamilyId,
                relation.Kind,
                relation.Id,
                relation.EvidenceRef),

            MorphologyPracticeKind.MorphemeProduction => new MorphologyPracticeItem(
                $"morph:morpheme:{relation.Id}:{source.Id}",
                kind,
                BuildMorphemePrompt(source.Source, target.Source, relation.Kind),
                relation.Morpheme!,
                source.Id,
                target.Id,
                relation.FamilyId,
                relation.Kind,
                relation.Id,
                relation.EvidenceRef),

            _ => throw new ArgumentOutOfRangeException(nameof(kind))
        };
    }

    public IReadOnlyList<MorphologyIntegrationTarget> SelectContextTargets(
        string entryId,
        IReadOnlySet<string>? allowedEntryIds = null,
        IReadOnlySet<string>? allowedLevels = null,
        int maxTargets = 16)
    {
        if (maxTargets is < 1 or > 256) throw new ArgumentOutOfRangeException(nameof(maxTargets));

        IEnumerable<MorphologyIntegrationTarget> query = _overlay.GetIntegrationTargets(entryId, 256);
        if (allowedEntryIds is not null)
            query = query.Where(target => allowedEntryIds.Contains(target.EntryId));
        if (allowedLevels is not null)
            query = query.Where(target => allowedLevels.Contains(target.Level));

        return query
            .GroupBy(target => target.EntryId, StringComparer.OrdinalIgnoreCase)
            .Select(group => group.First())
            .OrderBy(target => LevelRank(target.Level))
            .ThenBy(target => target.Source, StringComparer.OrdinalIgnoreCase)
            .ThenBy(target => target.EntryId, StringComparer.OrdinalIgnoreCase)
            .Take(maxTargets)
            .ToArray();
    }

    private bool TryResolveOrientation(
        string entryId,
        MorphologyRelation relation,
        out DictionaryEntry source,
        out DictionaryEntry target)
    {
        string targetId = relation.FromEntryId.Equals(entryId, StringComparison.OrdinalIgnoreCase)
            ? relation.ToEntryId
            : relation.FromEntryId;

        if (_entries.TryGetValue(entryId, out DictionaryEntry? resolvedSource) &&
            _entries.TryGetValue(targetId, out DictionaryEntry? resolvedTarget))
        {
            source = resolvedSource;
            target = resolvedTarget;
            return true;
        }

        source = null!;
        target = null!;
        return false;
    }

    private static string BuildExplanation(string source, string target, MorphologyRelation relation)
    {
        string evidence = $" Джерельне посилання: {relation.EvidenceRef}.";
        return relation.Kind switch
        {
            MorphologyRelationKind.Derivation => $"«{source}» і «{target}» мають підтверджений словотвірний зв’язок.{evidence}",
            MorphologyRelationKind.Prefix => $"«{source}» і «{target}» пов’язані префіксом «{relation.Morpheme}».{evidence}",
            MorphologyRelationKind.Suffix => $"«{source}» і «{target}» пов’язані суфіксом «{relation.Morpheme}».{evidence}",
            MorphologyRelationKind.Root => $"«{source}» і «{target}» мають підтверджений спільний корінь «{relation.Morpheme}».{evidence}",
            MorphologyRelationKind.Compound => $"«{source}» і «{target}» мають підтверджений зв’язок як складені лексичні форми.{evidence}",
            _ => throw new ArgumentOutOfRangeException(nameof(relation.Kind))
        };
    }

    private static string BuildRelatedFormPrompt(string source, MorphologyRelation relation) => relation.Kind switch
    {
        MorphologyRelationKind.Derivation => $"Введіть підтверджену словотвірно пов’язану англійську форму для «{source}».",
        MorphologyRelationKind.Prefix => $"Введіть пов’язану англійську форму для «{source}», що утворена з підтвердженим префіксом «{relation.Morpheme}».",
        MorphologyRelationKind.Suffix => $"Введіть пов’язану англійську форму для «{source}», що утворена з підтвердженим суфіксом «{relation.Morpheme}».",
        MorphologyRelationKind.Root => $"Введіть англійське слово з підтвердженим спільним коренем «{relation.Morpheme}» для «{source}».",
        MorphologyRelationKind.Compound => $"Введіть підтверджену пов’язану складену англійську форму для «{source}».",
        _ => throw new ArgumentOutOfRangeException(nameof(relation.Kind))
    };

    private static string BuildMorphemePrompt(string source, string target, MorphologyRelationKind kind)
    {
        string label = kind switch
        {
            MorphologyRelationKind.Prefix => "префікс",
            MorphologyRelationKind.Suffix => "суфікс",
            MorphologyRelationKind.Root => "корінь",
            _ => "морфему"
        };
        return $"Введіть підтверджений {label}, який позначено у зв’язку між «{source}» та «{target}».";
    }

    private static int PositiveModulo(int value, int divisor)
    {
        int remainder = value % divisor;
        return remainder < 0 ? remainder + divisor : remainder;
    }

    private static int LevelRank(string level) => level.Trim().ToUpperInvariant() switch
    {
        "A1" => 1,
        "A2" => 2,
        "B1" => 3,
        "B2" => 4,
        "C1" => 5,
        "CUSTOM" => 6,
        _ => 99
    };
}
