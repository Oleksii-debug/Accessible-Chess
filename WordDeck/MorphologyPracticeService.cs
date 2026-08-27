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
///
/// Homograph prompts use a canonical translation label so equal written forms do not
/// become an implicit stable-ID merge. Prefix/Suffix wording preserves the declared
/// FromEntryId -> ToEntryId source direction instead of silently reversing the affix claim.
/// </summary>
internal sealed class MorphologyPracticeService
{
    private readonly MorphologyOverlay _overlay;
    private readonly IReadOnlyDictionary<string, DictionaryEntry> _entries;
    private readonly MorphologyLexicalIdentityFormatter _identity;

    public MorphologyPracticeService(MorphologyOverlay overlay, DictionaryPackage dictionary)
    {
        ArgumentNullException.ThrowIfNull(overlay);
        ArgumentNullException.ThrowIfNull(dictionary);
        _overlay = overlay;
        _entries = dictionary.Entries.ToDictionary(entry => entry.Id, StringComparer.OrdinalIgnoreCase);
        _identity = new MorphologyLexicalIdentityFormatter(dictionary);
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
                BuildExplanation(relation),
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
                BuildRelatedFormPrompt(source, target, relation),
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
                BuildMorphemePrompt(relation),
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

    private string BuildExplanation(MorphologyRelation relation)
    {
        if (!_entries.TryGetValue(relation.FromEntryId, out DictionaryEntry? from) ||
            !_entries.TryGetValue(relation.ToEntryId, out DictionaryEntry? to))
            throw new InvalidDataException("Morphology explanation requires both exact canonical stable IDs.");
        string fromLabel = _identity.Format(from.Id);
        string toLabel = _identity.Format(to.Id);
        string evidence = $" Джерельне посилання: {relation.EvidenceRef}.";
        return relation.Kind switch
        {
            MorphologyRelationKind.Derivation => $"Підтверджений словотвірний напрям: «{fromLabel}» → «{toLabel}».{evidence}",
            MorphologyRelationKind.Prefix => $"Підтверджений префіксальний напрям: «{fromLabel}» → «{toLabel}»; префікс «{relation.Morpheme}».{evidence}",
            MorphologyRelationKind.Suffix => $"Підтверджений суфіксальний напрям: «{fromLabel}» → «{toLabel}»; суфікс «{relation.Morpheme}».{evidence}",
            MorphologyRelationKind.Root => $"«{fromLabel}» ↔ «{toLabel}» мають підтверджений спільний корінь «{relation.Morpheme}».{evidence}",
            MorphologyRelationKind.Compound => $"«{fromLabel}» ↔ «{toLabel}» мають підтверджений зв’язок як складені лексичні форми.{evidence}",
            _ => throw new ArgumentOutOfRangeException(nameof(relation.Kind))
        };
    }

    private string BuildRelatedFormPrompt(DictionaryEntry source, DictionaryEntry target, MorphologyRelation relation)
    {
        string sourceLabel = _identity.Format(source.Id);
        bool forward = source.Id.Equals(relation.FromEntryId, StringComparison.OrdinalIgnoreCase);
        return relation.Kind switch
        {
            MorphologyRelationKind.Derivation =>
                $"Введіть підтверджену словотвірно пов’язану англійську форму для «{sourceLabel}».",
            MorphologyRelationKind.Prefix when forward =>
                $"Введіть форму, до якої джерело веде від «{sourceLabel}» через підтверджений префіксальний зв’язок «{relation.Morpheme}».",
            MorphologyRelationKind.Prefix =>
                $"Введіть вихідну пов’язану форму, від якої джерело веде до «{sourceLabel}» через підтверджений префіксальний зв’язок «{relation.Morpheme}».",
            MorphologyRelationKind.Suffix when forward =>
                $"Введіть форму, до якої джерело веде від «{sourceLabel}» через підтверджений суфіксальний зв’язок «{relation.Morpheme}».",
            MorphologyRelationKind.Suffix =>
                $"Введіть вихідну пов’язану форму, від якої джерело веде до «{sourceLabel}» через підтверджений суфіксальний зв’язок «{relation.Morpheme}».",
            MorphologyRelationKind.Root =>
                $"Введіть англійське слово з підтвердженим спільним коренем «{relation.Morpheme}» для «{sourceLabel}».",
            MorphologyRelationKind.Compound =>
                $"Введіть підтверджену пов’язану складену англійську форму для «{sourceLabel}».",
            _ => throw new ArgumentOutOfRangeException(nameof(relation.Kind))
        };
    }

    private string BuildMorphemePrompt(MorphologyRelation relation)
    {
        if (!_entries.TryGetValue(relation.FromEntryId, out DictionaryEntry? from) ||
            !_entries.TryGetValue(relation.ToEntryId, out DictionaryEntry? to))
            throw new InvalidDataException("Morpheme prompt requires both exact canonical stable IDs.");
        string label = relation.Kind switch
        {
            MorphologyRelationKind.Prefix => "префікс",
            MorphologyRelationKind.Suffix => "суфікс",
            MorphologyRelationKind.Root => "корінь",
            _ => "морфему"
        };
        string connector = relation.Kind == MorphologyRelationKind.Root ? "↔" : "→";
        return $"Введіть підтверджений {label}, позначений у зв’язку «{_identity.Format(from.Id)}» {connector} «{_identity.Format(to.Id)}».";
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
