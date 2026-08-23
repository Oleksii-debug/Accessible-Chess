using System.Text;

namespace WordDeck;

/// <summary>
/// Offline analyzer for an external morphology candidate. This command never
/// accepts or records production approval; it only validates the candidate
/// against the exact embedded dictionary and emits reproducible evidence files.
/// </summary>
internal static class MorphologyCandidateAnalysisCommand
{
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

            DictionaryPackage dictionary = DictionaryLoader.LoadEmbeddedOxford();
            MorphologyImportResult imported = MorphologyOverlayTsv.Parse(File.ReadAllText(inputPath, Encoding.UTF8));
            EnsureParent(summaryPath);
            EnsureParent(gapsPath);

            if (imported.Package is null)
            {
                File.WriteAllText(summaryPath, WriteImportFailureSummary(dictionary, imported.Issues), new UTF8Encoding(false));
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

            File.WriteAllText(summaryPath, WriteSummary(diagnostics, imported.Issues, build.Issues), new UTF8Encoding(false));
            File.WriteAllText(gapsPath, MorphologyDiagnostics.WriteGapTsv(diagnostics), new UTF8Encoding(false));

            Console.WriteLine($"Morphology candidate analyzed: dictionary={diagnostics.DictionaryEntries}; acceptedRelations={diagnostics.AcceptedRelations}; coveredStableIds={diagnostics.CoveredStableIds}; gaps={diagnostics.GapStableIds}; quarantinedIssues={diagnostics.QuarantinedIssues}.");
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
        IReadOnlyList<MorphologyValidationIssue> importIssues,
        IReadOnlyList<MorphologyValidationIssue> buildIssues)
    {
        var builder = new StringBuilder();
        builder.AppendLine("metric\tvalue");
        Metric("packageId", diagnostics.PackageId);
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

    private static string WriteImportFailureSummary(DictionaryPackage dictionary, IReadOnlyList<MorphologyValidationIssue> issues)
    {
        var builder = new StringBuilder();
        builder.AppendLine("metric\tvalue");
        builder.Append("packageId\t").AppendLine();
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
