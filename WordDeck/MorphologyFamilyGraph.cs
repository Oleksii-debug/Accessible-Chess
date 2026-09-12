using System.Text;

namespace WordDeck;

internal sealed record MorphologyRelationSemantics(
    string RelationId,
    string FamilyId,
    string FromEntryId,
    string ToEntryId,
    string FromLabel,
    string ToLabel,
    MorphologyRelationKind Kind,
    string? Morpheme,
    string Description);

/// <summary>
/// Family-scoped traversal and explicit relation semantics over the validated morphology overlay.
/// It never derives lexical identity from spelling and never changes canonical DictionaryEntry IDs.
/// For Prefix/Suffix relations, the stored FromEntryId -> ToEntryId edge is the declared source-backed
/// derivational direction. Root relations remain non-directional/shared-root evidence.
/// </summary>
internal sealed class MorphologyFamilyGraph
{
    private readonly MorphologyOverlay _overlay;
    private readonly IReadOnlyDictionary<string, DictionaryEntry> _entries;
    private readonly MorphologyLexicalIdentityFormatter _identity;

    public MorphologyFamilyGraph(MorphologyOverlay overlay, DictionaryPackage dictionary)
    {
        ArgumentNullException.ThrowIfNull(overlay);
        ArgumentNullException.ThrowIfNull(dictionary);
        _overlay = overlay;
        _entries = dictionary.Entries.ToDictionary(entry => entry.Id, StringComparer.OrdinalIgnoreCase);
        _identity = new MorphologyLexicalIdentityFormatter(dictionary);
    }

    public IReadOnlyList<string> GetFamilyIds(string entryId)
    {
        string id = RequireKnownEntry(entryId);
        return _overlay.GetRelations(id)
            .Select(relation => relation.FamilyId)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(family => family, StringComparer.OrdinalIgnoreCase)
            .ToArray();
    }

    public IReadOnlyList<string> GetFamilyMembers(string entryId, string familyId, int maxNodes = 128)
    {
        if (maxNodes is < 1 or > 4096)
            throw new ArgumentOutOfRangeException(nameof(maxNodes), "Family traversal bound must be between 1 and 4096.");
        string anchor = RequireKnownEntry(entryId);
        if (string.IsNullOrWhiteSpace(familyId))
            throw new ArgumentException("Family ID cannot be blank.", nameof(familyId));
        string family = familyId.Trim();
        if (!GetFamilyIds(anchor).Contains(family, StringComparer.OrdinalIgnoreCase))
            return new[] { anchor };

        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { anchor };
        var queue = new Queue<string>();
        queue.Enqueue(anchor);
        while (queue.Count > 0 && seen.Count < maxNodes)
        {
            string current = queue.Dequeue();
            foreach (MorphologyRelation relation in _overlay.GetRelations(current)
                         .Where(item => item.FamilyId.Equals(family, StringComparison.OrdinalIgnoreCase)))
            {
                string neighbor = relation.FromEntryId.Equals(current, StringComparison.OrdinalIgnoreCase)
                    ? relation.ToEntryId
                    : relation.FromEntryId;
                if (seen.Count >= maxNodes) break;
                if (seen.Add(neighbor)) queue.Enqueue(neighbor);
            }
        }

        return seen.OrderBy(id => id, StringComparer.OrdinalIgnoreCase).ToArray();
    }

    /// <summary>
    /// Aggregate view for an anchor that deliberately traverses each family independently.
    /// It prevents an unrelated family attached to a downstream member from becoming a hidden
    /// transitive bridge into the anchor's family result.
    /// </summary>
    public IReadOnlyList<string> GetAnchorFamiliesWithoutCrossFamilyLeakage(string entryId, int maxNodes = 128)
    {
        if (maxNodes is < 1 or > 4096)
            throw new ArgumentOutOfRangeException(nameof(maxNodes), "Family traversal bound must be between 1 and 4096.");
        string anchor = RequireKnownEntry(entryId);
        var result = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { anchor };
        foreach (string family in GetFamilyIds(anchor))
        {
            int remaining = maxNodes - result.Count;
            if (remaining <= 0) break;
            foreach (string member in GetFamilyMembers(anchor, family, Math.Min(maxNodes, remaining + 1)))
            {
                result.Add(member);
                if (result.Count >= maxNodes) break;
            }
        }
        return result.OrderBy(id => id, StringComparer.OrdinalIgnoreCase).ToArray();
    }

    public MorphologyRelationSemantics Describe(string relationId)
    {
        if (string.IsNullOrWhiteSpace(relationId))
            throw new ArgumentException("Relation ID cannot be blank.", nameof(relationId));
        MorphologyRelation relation = _overlay.Relations.FirstOrDefault(item =>
            item.Id.Equals(relationId.Trim(), StringComparison.OrdinalIgnoreCase))
            ?? throw new InvalidDataException($"Morphology relation '{relationId.Trim()}' is not present in the validated overlay.");
        return Describe(relation);
    }

    public MorphologyRelationSemantics Describe(MorphologyRelation relation)
    {
        ArgumentNullException.ThrowIfNull(relation);
        if (!_entries.TryGetValue(relation.FromEntryId, out DictionaryEntry? from) ||
            !_entries.TryGetValue(relation.ToEntryId, out DictionaryEntry? to))
            throw new InvalidDataException("Morphology relation semantics require both exact canonical stable IDs to resolve.");

        string fromLabel = _identity.Format(from.Id);
        string toLabel = _identity.Format(to.Id);
        string evidence = $" Джерельне посилання: {relation.EvidenceRef}.";
        string description = relation.Kind switch
        {
            MorphologyRelationKind.Derivation =>
                $"Підтверджений словотвірний напрям: «{fromLabel}» → «{toLabel}».{evidence}",
            MorphologyRelationKind.Prefix =>
                $"Підтверджений префіксальний напрям: «{fromLabel}» → «{toLabel}»; префікс «{relation.Morpheme}».{evidence}",
            MorphologyRelationKind.Suffix =>
                $"Підтверджений суфіксальний напрям: «{fromLabel}» → «{toLabel}»; суфікс «{relation.Morpheme}».{evidence}",
            MorphologyRelationKind.Root =>
                $"«{fromLabel}» ↔ «{toLabel}» мають підтверджений спільний корінь «{relation.Morpheme}».{evidence}",
            MorphologyRelationKind.Compound =>
                $"Підтверджений зв’язок складеної лексичної форми: «{fromLabel}» ↔ «{toLabel}».{evidence}",
            _ => throw new ArgumentOutOfRangeException(nameof(relation.Kind))
        };
        return new MorphologyRelationSemantics(
            relation.Id,
            relation.FamilyId,
            from.Id,
            to.Id,
            fromLabel,
            toLabel,
            relation.Kind,
            relation.Morpheme,
            description);
    }

    private string RequireKnownEntry(string entryId)
    {
        if (string.IsNullOrWhiteSpace(entryId))
            throw new InvalidDataException("Morphology family stable ID cannot be blank.");
        string id = entryId.Trim();
        if (!_entries.ContainsKey(id))
            throw new InvalidDataException($"Morphology family stable ID '{id}' is not present in the active dictionary.");
        return id;
    }
}

/// <summary>
/// Human-facing lexical identity labels. A plain surface form is used only when that form maps
/// to one canonical stable ID in the active dictionary. Homographs are disambiguated with the
/// canonical translation already attached to that exact ID; no POS/sense is inferred.
/// </summary>
internal sealed class MorphologyLexicalIdentityFormatter
{
    private readonly IReadOnlyDictionary<string, DictionaryEntry> _entries;
    private readonly IReadOnlyDictionary<string, string[]> _idsBySurface;

    public MorphologyLexicalIdentityFormatter(DictionaryPackage dictionary)
    {
        ArgumentNullException.ThrowIfNull(dictionary);
        _entries = dictionary.Entries.ToDictionary(entry => entry.Id, StringComparer.OrdinalIgnoreCase);
        _idsBySurface = dictionary.Entries
            .GroupBy(entry => NormalizeSurface(entry.Source), StringComparer.OrdinalIgnoreCase)
            .ToDictionary(
                group => group.Key,
                group => group.Select(entry => entry.Id)
                    .Distinct(StringComparer.OrdinalIgnoreCase)
                    .OrderBy(id => id, StringComparer.Ordinal)
                    .ToArray(),
                StringComparer.OrdinalIgnoreCase);
    }

    public string Format(string entryId)
    {
        if (string.IsNullOrWhiteSpace(entryId) || !_entries.TryGetValue(entryId.Trim(), out DictionaryEntry? entry))
            throw new InvalidDataException($"Morphology lexical stable ID '{entryId?.Trim()}' is not present in the active dictionary.");
        string surface = NormalizeSurface(entry.Source);
        bool ambiguous = _idsBySurface.TryGetValue(surface, out string[]? ids) && ids.Length > 1;
        return ambiguous ? $"{entry.Source} — {entry.Target}" : entry.Source;
    }

    public bool IsAmbiguous(string entryId)
    {
        if (string.IsNullOrWhiteSpace(entryId) || !_entries.TryGetValue(entryId.Trim(), out DictionaryEntry? entry))
            throw new InvalidDataException($"Morphology lexical stable ID '{entryId?.Trim()}' is not present in the active dictionary.");
        return _idsBySurface.TryGetValue(NormalizeSurface(entry.Source), out string[]? ids) && ids.Length > 1;
    }

    private static string NormalizeSurface(string source) =>
        string.Join(' ', (source ?? string.Empty).Trim().Normalize(NormalizationForm.FormC)
            .Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries))
            .ToLowerInvariant();
}
