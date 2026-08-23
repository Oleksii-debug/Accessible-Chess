namespace WordDeck;

internal enum ContextStudyPoolPreset
{
    Thirty,
    Hundred,
    TwoHundred,
    Full
}

internal sealed record ContextStudyPool(
    ContextStudyPoolPreset Preset,
    int SourceEntryCount,
    int ActualEntryCount,
    int? RequestedLimit,
    bool Truncated,
    IReadOnlyList<string> EntryIds)
{
    public bool Contains(string entryId) =>
        EntryIds.Contains(ContextTargetIds.NormalizeSingle(entryId), StringComparer.OrdinalIgnoreCase);
}

internal static class ContextStudyPoolResolver
{
    public static ContextStudyPool Create(
        ContextStudyPoolPreset preset,
        IEnumerable<string> orderedEntryIds)
    {
        string[] normalized = ContextTargetIds.NormalizeStudyPool(orderedEntryIds);
        if (normalized.Length == 0)
            throw new InvalidDataException("Context study pool cannot be empty.");

        int? limit = preset switch
        {
            ContextStudyPoolPreset.Thirty => 30,
            ContextStudyPoolPreset.Hundred => 100,
            ContextStudyPoolPreset.TwoHundred => 200,
            ContextStudyPoolPreset.Full => null,
            _ => throw new ArgumentOutOfRangeException(nameof(preset))
        };

        string[] selected = limit is int max
            ? normalized.Take(max).ToArray()
            : normalized;

        return new ContextStudyPool(
            preset,
            normalized.Length,
            selected.Length,
            limit,
            limit is int bounded && normalized.Length > bounded,
            selected);
    }

    public static ContextStudyPoolPreset ParsePersisted(string? value)
    {
        if (Enum.TryParse(value, ignoreCase: true, out ContextStudyPoolPreset parsed))
            return parsed;
        return ContextStudyPoolPreset.Full;
    }

    public static string PersistedValue(ContextStudyPoolPreset preset) => preset.ToString();
}
