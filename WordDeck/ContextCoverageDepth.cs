namespace WordDeck;

internal interface IContextTargetCountCoverageSource
{
    IReadOnlySet<string> GetCoveredTargetIds(IReadOnlyCollection<string> candidateEntryIds, int requiredTargetCount);
}

internal sealed record ContextCoverageDepthReport(
    int RequiredTargetCount,
    int RequestedEntryCount,
    int CoveredEntryCount,
    int UncoveredEntryCount,
    IReadOnlyList<string> CoveredEntryIds,
    IReadOnlyList<string> UncoveredEntryIds)
{
    public double CoveragePercent => RequestedEntryCount == 0 ? 100.0 : CoveredEntryCount * 100.0 / RequestedEntryCount;
}

internal static class ContextCoverageDepthAnalyzer
{
    public static ContextCoverageDepthReport AnalyzeUniverse(
        IContextTargetCountCoverageSource source,
        IReadOnlyCollection<string> entryIds,
        int requiredTargetCount)
    {
        ArgumentNullException.ThrowIfNull(source);
        if (requiredTargetCount is < 1 or > 3)
            throw new ArgumentOutOfRangeException(nameof(requiredTargetCount), "Context coverage depth supports one, two, or three naturally co-occurring targets.");

        string[] requested = ContextTargetIds.NormalizeStudyPool(entryIds);
        IReadOnlySet<string> coveredSet = source.GetCoveredTargetIds(requested, requiredTargetCount);
        string[] covered = requested.Where(coveredSet.Contains).ToArray();
        string[] uncovered = requested.Where(id => !coveredSet.Contains(id)).ToArray();
        if (covered.Length + uncovered.Length != requested.Length)
            throw new InvalidOperationException("Context depth coverage did not exactly partition the stable-ID universe.");

        return new ContextCoverageDepthReport(
            requiredTargetCount,
            requested.Length,
            covered.Length,
            uncovered.Length,
            covered,
            uncovered);
    }
}
