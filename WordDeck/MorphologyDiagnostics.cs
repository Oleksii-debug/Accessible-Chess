using System.Text;

namespace WordDeck;

internal enum MorphologyDatasetClass
{
    TestFixture = 1,
    ExternalCandidate = 2,
    ApprovedProduction = 3
}

internal sealed record MorphologyReleaseEvidence(
    MorphologyDatasetClass DatasetClass,
    string SourceSha256,
    bool RedistributionApproved,
    string ApprovalReference)
{
    public IReadOnlyList<string> Validate()
    {
        var issues = new List<string>();
        if (!Enum.IsDefined(typeof(MorphologyDatasetClass), DatasetClass))
            issues.Add("Dataset class is invalid.");
        if (SourceSha256.Length != 64 || !SourceSha256.All(Uri.IsHexDigit))
            issues.Add("Source SHA-256 must contain exactly 64 hexadecimal characters.");
        if (RedistributionApproved && string.IsNullOrWhiteSpace(ApprovalReference))
            issues.Add("Redistribution approval requires a non-empty approval reference.");
        if (DatasetClass == MorphologyDatasetClass.ApprovedProduction && !RedistributionApproved)
            issues.Add("ApprovedProduction data must have explicit redistribution approval.");
        return issues;
    }
}

internal sealed record MorphologyGapEntry(string EntryId, string Level, string Source);

internal sealed record MorphologyLevelCoverage(
    string Level,
    int TotalEntries,
    int CoveredEntries,
    int GapEntries,
    double CoveragePercent);

internal sealed record MorphologyCandidateDiagnostics(
    string PackageId,
    int DictionaryEntries,
    int AcceptedRelations,
    int QuarantinedIssues,
    int FamilyCount,
    int CoveredStableIds,
    int GapStableIds,
    int AmbiguousSurfaceGroupsTouched,
    int AmbiguousSurfaceStableIdsTouched,
    IReadOnlyDictionary<MorphologyRelationKind, int> RelationsByKind,
    IReadOnlyList<MorphologyLevelCoverage> CoverageByLevel,
    IReadOnlyList<MorphologyGapEntry> Gaps,
    MorphologyDatasetClass DatasetClass,
    bool RedistributionApproved,
    bool ReleaseEligible,
    IReadOnlyList<string> ReleaseEvidenceIssues,
    string EvidenceBoundary);

internal static class MorphologyDiagnostics
{
    public static MorphologyCandidateDiagnostics Analyze(
        MorphologyOverlayPackage package,
        MorphologyBuildResult build,
        DictionaryPackage dictionary,
        MorphologyReleaseEvidence? releaseEvidence = null,
        IReadOnlyList<MorphologyValidationIssue>? importIssues = null)
    {
        ArgumentNullException.ThrowIfNull(package);
        ArgumentNullException.ThrowIfNull(build);
        ArgumentNullException.ThrowIfNull(dictionary);

        var entriesById = new Dictionary<string, DictionaryEntry>(StringComparer.OrdinalIgnoreCase);
        foreach (DictionaryEntry entry in dictionary.Entries)
        {
            if (!entriesById.TryAdd(entry.Id, entry))
                throw new InvalidDataException($"Morphology diagnostics cannot analyze duplicate dictionary stable ID '{entry.Id}'.");
        }

        var covered = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (MorphologyRelation relation in build.Overlay.Relations)
        {
            covered.Add(relation.FromEntryId);
            covered.Add(relation.ToEntryId);
        }

        MorphologyGapEntry[] gaps = dictionary.Entries
            .Where(entry => !covered.Contains(entry.Id))
            .OrderBy(entry => LevelRank(entry.Level))
            .ThenBy(entry => entry.Source, StringComparer.OrdinalIgnoreCase)
            .ThenBy(entry => entry.Id, StringComparer.OrdinalIgnoreCase)
            .Select(entry => new MorphologyGapEntry(entry.Id, entry.Level, entry.Source))
            .ToArray();

        MorphologyLevelCoverage[] levelCoverage = dictionary.Entries
            .GroupBy(entry => string.IsNullOrWhiteSpace(entry.Level) ? "UNKNOWN" : entry.Level.Trim().ToUpperInvariant(), StringComparer.OrdinalIgnoreCase)
            .Select(group =>
            {
                int total = group.Count();
                int coveredCount = group.Count(entry => covered.Contains(entry.Id));
                return new MorphologyLevelCoverage(
                    group.Key,
                    total,
                    coveredCount,
                    total - coveredCount,
                    total == 0 ? 0 : Math.Round(coveredCount * 100.0 / total, 4));
            })
            .OrderBy(item => LevelRank(item.Level))
            .ThenBy(item => item.Level, StringComparer.OrdinalIgnoreCase)
            .ToArray();

        Dictionary<string, string[]> surfaceGroups = dictionary.Entries
            .GroupBy(entry => NormalizeSurface(entry.Source), StringComparer.OrdinalIgnoreCase)
            .ToDictionary(
                group => group.Key,
                group => group.Select(entry => entry.Id).Distinct(StringComparer.OrdinalIgnoreCase).ToArray(),
                StringComparer.OrdinalIgnoreCase);
        var ambiguousTouchedGroups = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        int ambiguousTouchedIds = 0;
        foreach (string entryId in covered)
        {
            if (!entriesById.TryGetValue(entryId, out DictionaryEntry? entry)) continue;
            string key = NormalizeSurface(entry.Source);
            if (surfaceGroups.TryGetValue(key, out string[]? ids) && ids.Length > 1)
            {
                ambiguousTouchedGroups.Add(key);
                ambiguousTouchedIds++;
            }
        }

        var relationCounts = Enum.GetValues<MorphologyRelationKind>()
            .ToDictionary(kind => kind, kind => build.Overlay.Relations.Count(relation => relation.Kind == kind));

        int quarantineCount = build.Issues.Count + (importIssues?.Count ?? 0);
        MorphologyDatasetClass datasetClass = releaseEvidence?.DatasetClass ?? MorphologyDatasetClass.ExternalCandidate;
        bool redistributionApproved = releaseEvidence?.RedistributionApproved ?? false;
        IReadOnlyList<string> evidenceIssues = releaseEvidence?.Validate() ?? new[] { "No explicit release evidence was supplied." };
        bool releaseEligible =
            releaseEvidence is not null &&
            releaseEvidence.DatasetClass == MorphologyDatasetClass.ApprovedProduction &&
            releaseEvidence.RedistributionApproved &&
            evidenceIssues.Count == 0 &&
            quarantineCount == 0 &&
            build.AcceptedRelations > 0;

        string boundary = releaseEligible
            ? "Release evidence is structurally complete for this exact candidate. Independent source/license review is still required before integration or shipment."
            : datasetClass == MorphologyDatasetClass.TestFixture
                ? "Synthetic/test-only morphology evidence. It cannot support production Word Families claims or release packaging."
                : "External morphology candidate only. Coverage and validation do not imply redistribution approval or production acceptance.";

        return new MorphologyCandidateDiagnostics(
            package.PackageId,
            dictionary.Entries.Count,
            build.AcceptedRelations,
            quarantineCount,
            build.Overlay.Relations.Select(relation => relation.FamilyId).Distinct(StringComparer.OrdinalIgnoreCase).Count(),
            covered.Count,
            gaps.Length,
            ambiguousTouchedGroups.Count,
            ambiguousTouchedIds,
            relationCounts,
            levelCoverage,
            gaps,
            datasetClass,
            redistributionApproved,
            releaseEligible,
            evidenceIssues,
            boundary);
    }

    public static string WriteGapTsv(MorphologyCandidateDiagnostics diagnostics)
    {
        ArgumentNullException.ThrowIfNull(diagnostics);
        var builder = new StringBuilder();
        builder.AppendLine("entryId\tlevel\tsource");
        foreach (MorphologyGapEntry gap in diagnostics.Gaps)
        {
            builder.Append(Escape(gap.EntryId)).Append('\t')
                .Append(Escape(gap.Level)).Append('\t')
                .Append(Escape(gap.Source)).AppendLine();
        }
        return builder.ToString();
    }

    private static string NormalizeSurface(string source) =>
        string.Join(' ', (source ?? string.Empty).Trim().Normalize(NormalizationForm.FormC)
            .Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries))
            .ToLowerInvariant();

    private static string Escape(string value) =>
        value.Replace("\t", " ", StringComparison.Ordinal)
             .Replace("\r", " ", StringComparison.Ordinal)
             .Replace("\n", " ", StringComparison.Ordinal);

    private static int LevelRank(string level) => (level ?? string.Empty).Trim().ToUpperInvariant() switch
    {
        "A1" => 1,
        "A2" => 2,
        "B1" => 3,
        "B2" => 4,
        "C1" => 5,
        "CUSTOM" => 6,
        "UNKNOWN" => 98,
        _ => 99
    };
}
