using System.Security.Cryptography;
using System.Text;

namespace WordDeck;

/// <summary>
/// Offline analyzer for an external morphology candidate. This command never
/// accepts or records production approval; it only validates the candidate
/// against the exact embedded dictionary and emits reproducible evidence files.
/// </summary>
internal static class MorphologyCandidateAnalysisCommand
{
    private const long MaxCandidateBytes = 64L * 1024 * 1024;

    public static int Run(string[] args)
    {
        if (args.Length != 4)
        {
            Console.Error.WriteLine("Usage: WordDeck.exe --analyze-morphology-candidate <relations.tsv> <summary.tsv> <gaps.tsv>");
            return 2;
        }

        try
        {
            string inputPath = Path.GetFullPath(args[1]);
            string summaryPath = Path.GetFullPath(args[2]);
            string gapsPath = Path.GetFullPath(args[3]);
            EnsureDistinctPaths(inputPath, summaryPath, gapsPath);
            if (!File.Exists(inputPath))
                throw new FileNotFoundException("Morphology candidate TSV was not found.", inputPath);

            var fileInfo = new FileInfo(inputPath);
            if (fileInfo.Length > MaxCandidateBytes)
                throw new InvalidDataException($"Morphology candidate exceeds the {MaxCandidateBytes / (1024 * 1024)} MiB offline-analysis limit.");

            byte[] exactBytes = File.ReadAllBytes(inputPath);
            string candidateSha256 = Convert.ToHexString(SHA256.HashData(exactBytes)).ToLowerInvariant();
            string candidateText;
            using (var stream = new MemoryStream(exactBytes, writable: false))
            using (var reader = new StreamReader(stream, new UTF8Encoding(false, true), detectEncodingFromByteOrderMarks: true))
                candidateText = reader.ReadToEnd();

            DictionaryPackage dictionary = DictionaryLoader.LoadEmbeddedOxford();
            MorphologyImportResult imported = MorphologyOverlayTsv.Parse(candidateText);
            EnsureParent(summaryPath);
            EnsureParent(gapsPath);

            if (imported.Package is null)
            {
                File.WriteAllText(summaryPath, WriteImportFailureSummary(dictionary, imported.Issues, candidateSha256, exactBytes.LongLength), new UTF8Encoding(false));
                File.WriteAllText(gapsPath, WriteAllDictionaryGaps(dictionary), new UTF8Encoding(false));
                Console.Error.WriteLine($"Morphology candidate analysis FAILED before package construction; issues={imported.Issues.Count}. Evidence was written to '{summaryPath}' and '{gapsPath}'.");
                return 1;
            }

            MorphologyBuildResult build = MorphologyOverlayBuilder.Build(imported.Package, dictionary);
            MorphologyCandidateDiagnostics diagnostics = MorphologyDiagnostics.Analyze(
                imported.Package,
                build,
                dictionary,
                releaseEvidence: null,
                importIssues: imported.Issues);

            File.WriteAllText(summaryPath, WriteSummary(diagnostics, imported.Package, candidateSha256, exactBytes.LongLength, imported.Issues, build.Issues), new UTF8Encoding(false));
            File.WriteAllText(gapsPath, MorphologyDiagnostics.WriteGapTsv(diagnostics), new UTF8Encoding(false));

            Console.WriteLine($"Morphology candidate analyzed: dictionary={diagnostics.DictionaryEntries}; acceptedRelations={diagnostics.AcceptedRelations}; coveredStableIds={diagnostics.CoveredStableIds}; gaps={diagnostics.GapStableIds}; quarantinedIssues={diagnostics.QuarantinedIssues}; sha256={candidateSha256}.");
            Console.WriteLine("Dataset class is ExternalCandidate. This command does not grant redistribution or production approval.");
            return diagnostics.QuarantinedIssues == 0 ? 0 : 1;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"Morphology candidate analysis FAILED: {ex.Message}");
            return 1;
        }
    }

    internal static string WriteSummary(
        MorphologyCandidateDiagnostics diagnostics,
        MorphologyOverlayPackage package,
        string candidateSha256,
        long candidateBytes,
        IReadOnlyList<MorphologyValidationIssue> importIssues,
        IReadOnlyList<MorphologyValidationIssue> buildIssues)
    {
        var builder = new StringBuilder();
        builder.AppendLine("metric\tvalue");
        Metric("packageId", diagnostics.PackageId);
        Metric("candidateSha256", candidateSha256);
        Metric("candidateBytes", candidateBytes);
        Metric("sourceId", package.Source.SourceId);
        Metric("sourceName", package.Source.SourceName);
        Metric("sourceLicense", package.Source.License);
        Metric("sourceAttribution", package.Source.Attribution);
        Metric("sourceUri", package.Source.SourceUri ?? string.Empty);
        Metric("sourceVersion", package.Source.Version ?? string.Empty);
        Metric("dictionaryId", package.PackageId.Length > 0 ? "embedded-current" : "embedded-current");
        Metric("dictionaryEntries", diagnostics.DictionaryEntries);
        Metric("acceptedRelations", diagnostics.AcceptedRelations);
        Metric("quarantinedIssues", diagnostics.QuarantinedIssues);
        Metric("familyCount", diagnostics.FamilyCount);
        Metric("coveredStableIds", diagnostics.CoveredStableIds);
        Metric("gapStableIds", diagnostics.GapStableIds);
        Metric("ambiguousSurfaceGroupsTouched", diagnostics.AmbiguousSurfaceGroupsTouched);
        Metric("ambiguousSurfaceStableIdsTouched", diagnostics.AmbiguousSurfaceStableIdsTouched);
        Metric("datasetClass", diagnostics.DatasetClass);
        Metric("redistributionApproved", diagnostics.RedistributionApproved);
        Metric("releaseEligible", diagnostics.ReleaseEligible);
        Metric("evidenceBoundary", diagnostics.EvidenceBoundary);
        foreach ((MorphologyRelationKind kind, int count) in diagnostics.RelationsByKind.OrderBy(pair => pair.Key))
            Metric($"relationKind.{kind}", count);
        foreach (MorphologyLevelCoverage level in diagnostics.CoverageByLevel)
        {
            Metric($"level.{level.Level}.total", level.TotalEntries);
            Metric($"level.{level.Level}.covered", level.CoveredEntries);
            Metric($"level.{level.Level}.gaps", level.GapEntries);
            Metric($"level.{level.Level}.coveragePercent", level.CoveragePercent.ToString(System.Globalization.CultureInfo.InvariantCulture));
        }

        builder.AppendLine();
        builder.AppendLine("issueSource\tsourceLine\trelationId\tcode\tmessage");
        foreach (MorphologyValidationIssue issue in importIssues)
            Issue("import", issue);
        foreach (MorphologyValidationIssue issue in buildIssues)
            Issue("build", issue);
        return builder.ToString();

        void Metric(string key, object? value) =>
            builder.Append(Escape(key)).Append('\t').Append(Escape(value?.ToString() ?? string.Empty)).AppendLine();
        void Issue(string source, MorphologyValidationIssue issue) =>
            builder.Append(source).Append('\t')
                .Append(issue.SourceLine).Append('\t')
                .Append(Escape(issue.RelationId)).Append('\t')
                .Append(Escape(issue.Code)).Append('\t')
                .Append(Escape(issue.Message)).AppendLine();
    }

    private static string WriteImportFailureSummary(
        DictionaryPackage dictionary,
        IReadOnlyList<MorphologyValidationIssue> issues,
        string candidateSha256,
        long candidateBytes)
    {
        var builder = new StringBuilder();
        builder.AppendLine("metric\tvalue");
        builder.Append("packageId\t").AppendLine();
        builder.Append("candidateSha256\t").Append(candidateSha256).AppendLine();
        builder.Append("candidateBytes\t").Append(candidateBytes).AppendLine();
        builder.Append("dictionaryEntries\t").Append(dictionary.Entries.Count).AppendLine();
        builder.Append("acceptedRelations\t0").AppendLine();
        builder.Append("quarantinedIssues\t").Append(issues.Count).AppendLine();
        builder.Append("datasetClass\tExternalCandidate").AppendLine();
        builder.Append("redistributionApproved\tFalse").AppendLine();
        builder.Append("releaseEligible\tFalse").AppendLine();
        builder.Append("evidenceBoundary\tExternal morphology candidate only. Import failed before a valid package could be constructed.").AppendLine();
        builder.AppendLine();
        builder.AppendLine("issueSource\tsourceLine\trelationId\tcode\tmessage");
        foreach (MorphologyValidationIssue issue in issues)
        {
            builder.Append("import\t").Append(issue.SourceLine).Append('\t')
                .Append(Escape(issue.RelationId)).Append('\t')
                .Append(Escape(issue.Code)).Append('\t')
                .Append(Escape(issue.Message)).AppendLine();
        }
        return builder.ToString();
    }

    private static string WriteAllDictionaryGaps(DictionaryPackage dictionary)
    {
        var builder = new StringBuilder();
        builder.AppendLine("entryId\tlevel\tsource");
        foreach (DictionaryEntry entry in dictionary.Entries.OrderBy(entry => entry.Id, StringComparer.OrdinalIgnoreCase))
        {
            builder.Append(Escape(entry.Id)).Append('\t')
                .Append(Escape(entry.Level)).Append('\t')
                .Append(Escape(entry.Source)).AppendLine();
        }
        return builder.ToString();
    }

    private static void EnsureDistinctPaths(params string[] paths)
    {
        for (int i = 0; i < paths.Length; i++)
        for (int j = i + 1; j < paths.Length; j++)
            if (string.Equals(paths[i], paths[j], StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Morphology candidate input, summary and gap paths must be distinct.");
    }

    private static void EnsureParent(string path)
    {
        string? directory = Path.GetDirectoryName(path);
        if (!string.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);
    }

    private static string Escape(string value) =>
        value.Replace("\t", " ", StringComparison.Ordinal)
             .Replace("\r", " ", StringComparison.Ordinal)
             .Replace("\n", " ", StringComparison.Ordinal);
}
