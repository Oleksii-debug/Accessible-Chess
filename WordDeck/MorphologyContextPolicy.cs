using System.Text;

namespace WordDeck;

internal sealed record MorphologyContextTargetPlan(
    string AnchorEntryId,
    IReadOnlyList<MorphologyIntegrationTarget> SafeRelatedTargets,
    IReadOnlyList<string> ExcludedAmbiguousStableIds)
{
    public IReadOnlyList<string> PhysicalTargetPoolEntryIds =>
        new[] { AnchorEntryId }
            .Concat(SafeRelatedTargets.Select(target => target.EntryId))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
}

/// <summary>
/// Stable-ID and physical-form guard used before morphology relations are offered
/// to Sentence/Context, Grammar or Reading. Exact source-backed morphology edges do
/// not authorize a downstream corpus to guess POS/sense identity from equal spelling.
/// </summary>
internal sealed class MorphologyContextTargetPlanner
{
    private readonly MorphologyPracticeService _practice;
    private readonly IReadOnlyDictionary<string, DictionaryEntry> _entries;
    private readonly IReadOnlyDictionary<string, string[]> _idsBySurface;

    public MorphologyContextTargetPlanner(MorphologyOverlay overlay, DictionaryPackage dictionary)
    {
        ArgumentNullException.ThrowIfNull(overlay);
        ArgumentNullException.ThrowIfNull(dictionary);
        _practice = new MorphologyPracticeService(overlay, dictionary);
        _entries = dictionary.Entries.ToDictionary(entry => entry.Id, StringComparer.OrdinalIgnoreCase);
        _idsBySurface = dictionary.Entries
            .GroupBy(entry => NormalizeSurface(entry.Source), StringComparer.OrdinalIgnoreCase)
            .ToDictionary(
                group => group.Key,
                group => group.Select(entry => entry.Id).Distinct(StringComparer.OrdinalIgnoreCase).OrderBy(id => id, StringComparer.Ordinal).ToArray(),
                StringComparer.OrdinalIgnoreCase);
    }

    public MorphologyContextTargetPlan Plan(
        string anchorEntryId,
        IReadOnlySet<string>? allowedEntryIds = null,
        IReadOnlySet<string>? allowedLevels = null,
        int maxRelatedTargets = 32)
    {
        if (maxRelatedTargets is < 1 or > 256) throw new ArgumentOutOfRangeException(nameof(maxRelatedTargets));
        string anchor = RequireKnownEntry(anchorEntryId);
        if (allowedEntryIds is not null && !allowedEntryIds.Contains(anchor))
            throw new InvalidDataException("Morphology context anchor must belong to the supplied study pool.");
        if (IsAmbiguous(anchor))
            throw new InvalidDataException($"Morphology context anchor '{anchor}' has an unresolved equal-written-form stable-ID ambiguity. Context practice must fail closed until POS/sense identity is proven.");

        IReadOnlyList<MorphologyIntegrationTarget> candidates = _practice.SelectContextTargets(
            anchor,
            allowedEntryIds,
            allowedLevels,
            Math.Min(256, maxRelatedTargets * 4));

        var excluded = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var selectedBySurface = new Dictionary<string, MorphologyIntegrationTarget>(StringComparer.OrdinalIgnoreCase);
        string anchorSurface = NormalizeSurface(_entries[anchor].Source);
        foreach (MorphologyIntegrationTarget candidate in candidates)
        {
            if (!_entries.TryGetValue(candidate.EntryId, out DictionaryEntry? entry)) continue;
            string surface = NormalizeSurface(entry.Source);
            if (IsAmbiguous(candidate.EntryId) || surface.Equals(anchorSurface, StringComparison.OrdinalIgnoreCase))
            {
                excluded.Add(candidate.EntryId);
                continue;
            }

            if (!selectedBySurface.ContainsKey(surface))
                selectedBySurface[surface] = candidate;
        }

        MorphologyIntegrationTarget[] safe = selectedBySurface.Values
            .OrderBy(target => LevelRank(target.Level))
            .ThenBy(target => target.Source, StringComparer.OrdinalIgnoreCase)
            .ThenBy(target => target.EntryId, StringComparer.OrdinalIgnoreCase)
            .Take(maxRelatedTargets)
            .ToArray();

        return new MorphologyContextTargetPlan(
            anchor,
            safe,
            excluded.OrderBy(id => id, StringComparer.OrdinalIgnoreCase).ToArray());
    }

    public bool IsAmbiguous(string entryId)
    {
        string id = RequireKnownEntry(entryId);
        string key = NormalizeSurface(_entries[id].Source);
        return _idsBySurface.TryGetValue(key, out string[]? ids) && ids.Length > 1;
    }

    private string RequireKnownEntry(string entryId)
    {
        if (string.IsNullOrWhiteSpace(entryId))
            throw new InvalidDataException("Morphology context stable ID cannot be blank.");
        string id = entryId.Trim();
        if (!_entries.ContainsKey(id))
            throw new InvalidDataException($"Morphology context stable ID '{id}' is not present in the active dictionary.");
        return id;
    }

    private static string NormalizeSurface(string source) =>
        string.Join(' ', (source ?? string.Empty).Trim().Normalize(NormalizationForm.FormC)
            .Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries))
            .ToLowerInvariant();

    private static int LevelRank(string level) => (level ?? string.Empty).Trim().ToUpperInvariant() switch
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
