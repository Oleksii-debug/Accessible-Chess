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
/// evidence, stable-tag-participating homographic IDs stay unresolved and cannot own
/// canonical progress. If a stable ID does not participate in the historical stable-tag
/// index, it remains a corpus gap. Unique physical written-form coverage is measured by
/// a separate evidence axis and must not be inferred from this per-stable-ID partition.
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
        ContextNaturalCoverageReport stableTagParticipation,
        ContextTargetLexicon lexicon,
        IReadOnlyCollection<string> scopeEntryIds)
    {
        ArgumentNullException.ThrowIfNull(stableTagParticipation);
        ArgumentNullException.ThrowIfNull(lexicon);
        ArgumentNullException.ThrowIfNull(scopeEntryIds);

        string[] scope = ContextTargetIds.NormalizeStudyPool(scopeEntryIds);
        if (scope.Length != stableTagParticipation.ScopeEntryCount)
            throw new InvalidDataException("Stable-tag participation scope does not match stable-identity resolution scope.");

        var participating = new HashSet<string>(stableTagParticipation.CoveredEntryIds, StringComparer.OrdinalIgnoreCase);
        var absent = new HashSet<string>(stableTagParticipation.UncoveredEntryIds, StringComparer.OrdinalIgnoreCase);
        if (participating.Overlaps(absent) || participating.Count + absent.Count != scope.Length)
            throw new InvalidDataException("Stable-tag participation does not exactly partition the requested stable-ID universe.");

        var unresolved = new HashSet<string>(
            scope.Where(id => participating.Contains(id) && lexicon.IsAmbiguousStableIdentity(id)),
            StringComparer.OrdinalIgnoreCase);
        string[] resolvedCovered = scope.Where(id => participating.Contains(id) && !unresolved.Contains(id)).ToArray();
        string[] unresolvedOrdered = scope.Where(unresolved.Contains).ToArray();
        string[] uncovered = scope.Where(absent.Contains).ToArray();

        if (resolvedCovered.Length + unresolvedOrdered.Length + uncovered.Length != scope.Length)
            throw new InvalidOperationException("Stable-identity coverage did not partition the complete requested universe.");

        return new ContextStableIdentityCoverageReport(
            stableTagParticipation.RequiredTargetCount,
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

        var stableTags = new ContextNaturalCoverageReport(
            1,
            4,
            3,
            1,
            new[] { "run-n", "run-v", "daily-adv" },
            new[] { "practice-v" },
            new[] { "run-n", "run-v" });
        ContextStableIdentityCoverageReport stable = ContextStableIdentityResolution.ResolveCoverage(
            stableTags,
            lexicon,
            new[] { "run-n", "run-v", "daily-adv", "practice-v" });
        Check(stable.ResolvedCoveredEntryIds.SequenceEqual(new[] { "daily-adv" }, StringComparer.OrdinalIgnoreCase),
            "Only an unambiguous stable-tag-participating entry should count as conservative resolved stable-ID coverage.");
        Check(stable.UnresolvedAmbiguousEntryIds.SequenceEqual(new[] { "run-n", "run-v" }, StringComparer.OrdinalIgnoreCase),
            "Both stable-tag-participating homographic stable IDs must remain unresolved.");
        Check(stable.UncoveredEntryIds.SequenceEqual(new[] { "practice-v" }, StringComparer.OrdinalIgnoreCase),
            "Stable-tag-absent entry must remain a corpus gap rather than being classified as ambiguous.");

        var stableTagGap = new ContextNaturalCoverageReport(
            1,
            4,
            1,
            3,
            new[] { "daily-adv" },
            new[] { "run-n", "run-v", "practice-v" },
            new[] { "run-n", "run-v" });
        ContextStableIdentityCoverageReport stableGap = ContextStableIdentityResolution.ResolveCoverage(
            stableTagGap,
            lexicon,
            new[] { "run-n", "run-v", "daily-adv", "practice-v" });
        Check(stableGap.UnresolvedAmbiguousEntryIds.Count == 0,
            "A homographic stable ID without stable-tag participation must remain a corpus gap, not a false sense-resolution finding.");
        Check(stableGap.UncoveredEntryIds.SequenceEqual(new[] { "run-n", "run-v", "practice-v" }, StringComparer.OrdinalIgnoreCase),
            "Stable-tag-absent homographic IDs must remain in the uncovered stable-ID partition.");

        Console.WriteLine("Context stable-identity self-test PASS: stable-tag-participating homographs remain unresolved, stable-tag-absent IDs remain corpus gaps, and unique physical-form coverage stays a separate evidence axis.");
    }

    private static void Check(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
}
