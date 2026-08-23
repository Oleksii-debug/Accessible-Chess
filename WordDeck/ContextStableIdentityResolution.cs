namespace WordDeck;

internal sealed record ContextStableIdentityCoverageReport(
    int RequiredTargetCount,
    int ScopeEntryCount,
    int ResolvedCoveredEntryCount,
    int UnresolvedAmbiguousEntryCount,
    int UncoveredEntryCount,
    IReadOnlyList<string> ResolvedCoveredEntryIds,
    IReadOnlyList<string> UnresolvedAmbiguousEntryIds,
    IReadOnlyList<string> UncoveredEntryIds)
{
    public double ResolvedCoveragePercent =>
        ScopeEntryCount == 0 ? 100.0 : ResolvedCoveredEntryCount * 100.0 / ScopeEntryCount;
}

/// <summary>
/// Stable-ID/sense safety boundary for surface-form corpora.
/// A corpus occurrence of a written form such as "run" is physical-form evidence,
/// but it is not evidence for one particular Oxford stable ID when the dictionary
/// contains multiple entries with that same written form. Without explicit POS/sense
/// evidence, those IDs stay unresolved and cannot own canonical progress.
/// </summary>
internal static class ContextStableIdentityResolution
{
    public static IReadOnlyList<string> UnresolvedStableIds(
        ContextTargetLexicon lexicon,
        IEnumerable<string> entryIds)
    {
        ArgumentNullException.ThrowIfNull(lexicon);
        ArgumentNullException.ThrowIfNull(entryIds);
        string[] ids = ContextTargetIds.NormalizeStudyPool(entryIds);
        return ids.Where(lexicon.IsAmbiguousStableIdentity).ToArray();
    }

    public static void EnsureResolvedTargets(
        ContextTargetLexicon lexicon,
        IEnumerable<string> targetEntryIds)
    {
        ArgumentNullException.ThrowIfNull(lexicon);
        string[] ids = ContextTargetIds.NormalizeRequired(targetEntryIds);
        string[] unresolved = ids.Where(lexicon.IsAmbiguousStableIdentity).ToArray();
        if (unresolved.Length == 0)
            return;

        string details = string.Join(", ", unresolved.Select(id =>
            $"{id}=[{string.Join("|", lexicon.StableIdsForLexicalKey(lexicon.LexicalKeyFor(id)))}]"));
        throw new InvalidDataException(
            "Context stable-ID target is unresolved because its physical written form maps to multiple dictionary entries. " +
            "Surface-form corpus evidence cannot choose a POS/sense identity. Explicit disambiguating evidence is required before canonical progress can be recorded. " +
            details);
    }

    public static IReadOnlyList<string> ResolvedStudyPool(
        ContextTargetLexicon lexicon,
        IEnumerable<string> studyPoolEntryIds)
    {
        ArgumentNullException.ThrowIfNull(lexicon);
        string[] ids = ContextTargetIds.NormalizeStudyPool(studyPoolEntryIds);
        return ids.Where(id => !lexicon.IsAmbiguousStableIdentity(id)).ToArray();
    }

    public static ContextStableIdentityCoverageReport ResolveCoverage(
        ContextNaturalCoverageReport physicalCoverage,
        ContextTargetLexicon lexicon,
        IReadOnlyCollection<string> scopeEntryIds)
    {
        ArgumentNullException.ThrowIfNull(physicalCoverage);
        ArgumentNullException.ThrowIfNull(lexicon);
        ArgumentNullException.ThrowIfNull(scopeEntryIds);

        string[] scope = ContextTargetIds.NormalizeStudyPool(scopeEntryIds);
        if (scope.Length != physicalCoverage.ScopeEntryCount)
            throw new InvalidDataException("Physical-form coverage scope does not match stable-identity resolution scope.");

        var physicalCovered = new HashSet<string>(physicalCoverage.CoveredEntryIds, StringComparer.OrdinalIgnoreCase);
        var physicalUncovered = new HashSet<string>(physicalCoverage.UncoveredEntryIds, StringComparer.OrdinalIgnoreCase);
        if (physicalCovered.Overlaps(physicalUncovered) || physicalCovered.Count + physicalUncovered.Count != scope.Length)
            throw new InvalidDataException("Physical-form coverage does not exactly partition the requested stable-ID universe.");

        var unresolved = new HashSet<string>(
            scope.Where(lexicon.IsAmbiguousStableIdentity),
            StringComparer.OrdinalIgnoreCase);
        string[] resolvedCovered = scope.Where(id => physicalCovered.Contains(id) && !unresolved.Contains(id)).ToArray();
        string[] unresolvedOrdered = scope.Where(unresolved.Contains).ToArray();
        string[] uncovered = scope.Where(id => physicalUncovered.Contains(id) && !unresolved.Contains(id)).ToArray();

        if (resolvedCovered.Length + unresolvedOrdered.Length + uncovered.Length != scope.Length)
            throw new InvalidOperationException("Stable-identity coverage did not partition the complete requested universe.");

        return new ContextStableIdentityCoverageReport(
            physicalCoverage.RequiredTargetCount,
            scope.Length,
            resolvedCovered.Length,
            unresolvedOrdered.Length,
            uncovered.Length,
            resolvedCovered,
            unresolvedOrdered,
            uncovered);
    }
}

internal static class ContextStableIdentityResolutionSelfTest
{
    public static void Run()
    {
        var lexicon = new ContextTargetLexicon("ambiguity-test", new[]
        {
            ("run-n", "run"),
            ("run-v", "run"),
            ("daily-adv", "daily"),
            ("practice-v", "practice")
        });

        bool blocked = false;
        try
        {
            ContextStableIdentityResolution.EnsureResolvedTargets(lexicon, new[] { "run-v" });
        }
        catch (InvalidDataException ex)
        {
            blocked = ex.Message.Contains("POS/sense", StringComparison.OrdinalIgnoreCase);
        }
        Check(blocked, "Ambiguous stable target must fail closed without explicit sense evidence.");
        ContextStableIdentityResolution.EnsureResolvedTargets(lexicon, new[] { "daily-adv", "practice-v" });

        var physical = new ContextNaturalCoverageReport(
            1,
            4,
            3,
            1,
            new[] { "run-n", "run-v", "daily-adv" },
            new[] { "practice-v" },
            new[] { "run-n", "run-v" });
        ContextStableIdentityCoverageReport stable = ContextStableIdentityResolution.ResolveCoverage(
            physical,
            lexicon,
            new[] { "run-n", "run-v", "daily-adv", "practice-v" });
        Check(stable.ResolvedCoveredEntryIds.SequenceEqual(new[] { "daily-adv" }, StringComparer.OrdinalIgnoreCase),
            "Only unambiguous physically covered entry should count as resolved stable-ID coverage.");
        Check(stable.UnresolvedAmbiguousEntryIds.SequenceEqual(new[] { "run-n", "run-v" }, StringComparer.OrdinalIgnoreCase),
            "Both homographic stable IDs must remain unresolved.");
        Check(stable.UncoveredEntryIds.SequenceEqual(new[] { "practice-v" }, StringComparer.OrdinalIgnoreCase),
            "Unambiguous physical gap must remain uncovered rather than ambiguous.");

        Console.WriteLine("Context stable-identity self-test PASS: homographs remain unresolved and cannot own stable-ID practice or coverage without POS/sense evidence.");
    }

    private static void Check(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
}
