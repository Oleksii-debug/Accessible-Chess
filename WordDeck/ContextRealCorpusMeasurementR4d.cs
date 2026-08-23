using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Security.Cryptography;
using System.Text.Json;

namespace WordDeck;

internal sealed record ContextRealCorpusAmbiguousGroup(
    string LexicalKey,
    IReadOnlyList<string> StableEntryIds);

internal sealed record ContextRealCorpusCoverageBand(
    int RequiredTargetCount,
    int RequestedEntryCount,
    int CoveredEntryCount,
    int UncoveredEntryCount,
    double CoveragePercent,
    long ElapsedMilliseconds,
    IReadOnlyList<string> CoveredEntryIds,
    IReadOnlyList<string> UncoveredEntryIds);

internal sealed record ContextRealCorpusMeasurementReport(
    int ReportSchemaVersion,
    string EvidenceBoundary,
    string EvidenceSource,
    string DatabaseFileName,
    long DatabaseBytes,
    string DatabaseSha256,
    string PackId,
    string Provenance,
    string License,
    int SentenceCount,
    string DictionaryId,
    int DictionaryEntryCount,
    int AmbiguousStableEntryCount,
    IReadOnlyList<ContextRealCorpusAmbiguousGroup> AmbiguousStableGroups,
    IReadOnlyList<ContextRealCorpusCoverageBand> NaturalLexicalCoverage,
    IReadOnlyList<ContextRealCorpusCoverageBand> StableIdDiagnosticCoverage);

internal static class ContextRealCorpusMeasurement
{
    public const int CurrentReportSchemaVersion = 1;
    public const int ExpectedOxfordEntryCount = 5446;

    public static ContextRealCorpusMeasurementReport Measure(
        string sqlitePath,
        string evidenceSource,
        string? expectedPackId = null,
        int? expectedLegacyOneTargetCount = null,
        int? expectedLegacyTwoTargetCount = null)
    {
        if (string.IsNullOrWhiteSpace(sqlitePath))
            throw new ArgumentException("A real SentencePack SQLite path is required.", nameof(sqlitePath));
        if (string.IsNullOrWhiteSpace(evidenceSource))
            throw new ArgumentException("A factual evidence source description is required.", nameof(evidenceSource));

        string fullPath = Path.GetFullPath(sqlitePath);
        if (!File.Exists(fullPath))
            throw new FileNotFoundException("The real SentencePack SQLite file was not found.", fullPath);

        var fileInfo = new FileInfo(fullPath);
        if (fileInfo.Length <= 0)
            throw new InvalidDataException("The real SentencePack SQLite file is empty.");

        DictionaryPackage dictionary = DictionaryLoader.LoadEmbeddedOxford();
        if (dictionary.Entries.Count != ExpectedOxfordEntryCount)
            throw new InvalidDataException($"Real-corpus measurement requires the exact {ExpectedOxfordEntryCount}-entry Oxford universe; current dictionary has {dictionary.Entries.Count} entries.");

        string[] universe = dictionary.Entries.Select(entry => entry.Id).ToArray();
        var lexicon = new ContextTargetLexicon(dictionary);
        var source = new ContextSentenceSqliteSource(fullPath, ContextCorpusKind.RealCorpus);
        var corpus = new SentencePackSqliteCorpus(fullPath);

        if (!string.IsNullOrWhiteSpace(expectedPackId) &&
            !string.Equals(corpus.PackId, expectedPackId.Trim(), StringComparison.Ordinal))
        {
            throw new InvalidDataException($"Real SentencePack identity mismatch. Expected PackId '{expectedPackId.Trim()}', got '{corpus.PackId}'.");
        }
        if (!string.Equals(source.Descriptor.SourceId, corpus.PackId, StringComparison.Ordinal))
            throw new InvalidDataException("Context source descriptor and SQLite SentencePack PackId disagree.");
        if (source.Descriptor.Kind != ContextCorpusKind.RealCorpus)
            throw new InvalidDataException("Real-corpus measurement cannot run against a synthetic/local-user source classification.");

        IReadOnlyList<ContextRealCorpusCoverageBand> natural = Enumerable.Range(1, 3)
            .Select(required => MeasureNatural(source, lexicon, universe, required))
            .ToArray();

        IReadOnlyList<ContextRealCorpusCoverageBand> stableDiagnostics = Enumerable.Range(1, 3)
            .Select(required => MeasureStableDiagnostic(source, universe, required))
            .ToArray();

        if (expectedLegacyOneTargetCount.HasValue && stableDiagnostics[0].CoveredEntryCount != expectedLegacyOneTargetCount.Value)
            throw new InvalidDataException($"Historical one-target stable-ID checkpoint mismatch: expected {expectedLegacyOneTargetCount.Value}, measured {stableDiagnostics[0].CoveredEntryCount}.");
        if (expectedLegacyTwoTargetCount.HasValue && stableDiagnostics[1].CoveredEntryCount != expectedLegacyTwoTargetCount.Value)
            throw new InvalidDataException($"Historical two-target stable-ID checkpoint mismatch: expected {expectedLegacyTwoTargetCount.Value}, measured {stableDiagnostics[1].CoveredEntryCount}.");

        ContextRealCorpusAmbiguousGroup[] ambiguousGroups = dictionary.Entries
            .Select(entry => new { Entry = entry, Key = lexicon.LexicalKeyFor(entry.Id) })
            .GroupBy(item => item.Key, StringComparer.OrdinalIgnoreCase)
            .Select(group => new ContextRealCorpusAmbiguousGroup(
                group.Key,
                group.Select(item => item.Entry.Id)
                    .Distinct(StringComparer.OrdinalIgnoreCase)
                    .OrderBy(id => id, StringComparer.Ordinal)
                    .ToArray()))
            .Where(group => group.StableEntryIds.Count > 1)
            .OrderBy(group => group.LexicalKey, StringComparer.Ordinal)
            .ToArray();

        int ambiguousStableEntryCount = ambiguousGroups.Sum(group => group.StableEntryIds.Count);
        string databaseSha256;
        using (FileStream stream = File.OpenRead(fullPath))
            databaseSha256 = Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();

        return new ContextRealCorpusMeasurementReport(
            CurrentReportSchemaVersion,
            "Historical real-corpus candidate measurement only. Coverage evidence does not approve redistribution, licensing, provenance, release status, or production bundling.",
            evidenceSource.Trim(),
            fileInfo.Name,
            fileInfo.Length,
            databaseSha256,
            corpus.PackId,
            corpus.Provenance,
            corpus.License,
            corpus.SentenceCount,
            dictionary.Id,
            dictionary.Entries.Count,
            ambiguousStableEntryCount,
            ambiguousGroups,
            natural,
            stableDiagnostics);
    }

    private static ContextRealCorpusCoverageBand MeasureNatural(
        ContextSentenceSqliteSource source,
        ContextTargetLexicon lexicon,
        IReadOnlyCollection<string> universe,
        int requiredTargetCount)
    {
        var stopwatch = Stopwatch.StartNew();
        ContextNaturalCoverageReport report = ContextNaturalCoverageAnalyzer.Analyze(source, lexicon, universe, requiredTargetCount);
        stopwatch.Stop();
        return new ContextRealCorpusCoverageBand(
            requiredTargetCount,
            report.ScopeEntryCount,
            report.CoveredEntryCount,
            report.UncoveredEntryCount,
            report.CoveragePercent,
            stopwatch.ElapsedMilliseconds,
            report.CoveredEntryIds,
            report.UncoveredEntryIds);
    }

    private static ContextRealCorpusCoverageBand MeasureStableDiagnostic(
        ContextSentenceSqliteSource source,
        IReadOnlyCollection<string> universe,
        int requiredTargetCount)
    {
        var stopwatch = Stopwatch.StartNew();
        ContextCoverageDepthReport report = ContextCoverageDepthAnalyzer.AnalyzeUniverse(source, universe, requiredTargetCount);
        stopwatch.Stop();
        return new ContextRealCorpusCoverageBand(
            requiredTargetCount,
            report.RequestedEntryCount,
            report.CoveredEntryCount,
            report.UncoveredEntryCount,
            report.CoveragePercent,
            stopwatch.ElapsedMilliseconds,
            report.CoveredEntryIds,
            report.UncoveredEntryIds);
    }
}

internal static class ContextRealCorpusMeasurementR4dBootstrap
{
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };

    [ModuleInitializer]
    internal static void Initialize()
    {
        if (!Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            return;

        string? sqlitePath = Environment.GetEnvironmentVariable("WORDDECK_CONTEXT_REAL_SQLITE");
        if (string.IsNullOrWhiteSpace(sqlitePath))
            return;

        string outputPath = Environment.GetEnvironmentVariable("WORDDECK_CONTEXT_MEASUREMENT_OUTPUT")
            ?? throw new InvalidDataException("WORDDECK_CONTEXT_MEASUREMENT_OUTPUT is required when real-corpus measurement is enabled.");
        string evidenceSource = Environment.GetEnvironmentVariable("WORDDECK_CONTEXT_EVIDENCE_SOURCE")
            ?? throw new InvalidDataException("WORDDECK_CONTEXT_EVIDENCE_SOURCE is required when real-corpus measurement is enabled.");
        string? expectedPackId = Environment.GetEnvironmentVariable("WORDDECK_CONTEXT_EXPECT_PACK_ID");
        int? expectedLegacyOne = ParseOptionalInt("WORDDECK_CONTEXT_EXPECT_LEGACY_ONE");
        int? expectedLegacyTwo = ParseOptionalInt("WORDDECK_CONTEXT_EXPECT_LEGACY_TWO");

        ContextRealCorpusMeasurementReport report = ContextRealCorpusMeasurement.Measure(
            sqlitePath,
            evidenceSource,
            expectedPackId,
            expectedLegacyOne,
            expectedLegacyTwo);

        string fullOutputPath = Path.GetFullPath(outputPath);
        string? parent = Path.GetDirectoryName(fullOutputPath);
        if (!string.IsNullOrWhiteSpace(parent)) Directory.CreateDirectory(parent);
        File.WriteAllText(fullOutputPath, JsonSerializer.Serialize(report, JsonOptions));

        string naturalSummary = string.Join(", ", report.NaturalLexicalCoverage.Select(band =>
            $"{band.RequiredTargetCount}-target={band.CoveredEntryCount}/{band.RequestedEntryCount} ({band.CoveragePercent:F2}%)"));
        string stableSummary = string.Join(", ", report.StableIdDiagnosticCoverage.Select(band =>
            $"{band.RequiredTargetCount}-target={band.CoveredEntryCount}/{band.RequestedEntryCount}"));
        Console.WriteLine($"Context R4d REAL attributed corpus measurement PASS: {naturalSummary}; stable-ID diagnostics: {stableSummary}; ambiguous stable IDs={report.AmbiguousStableEntryCount}; sentences={report.SentenceCount}; sqlite_sha256={report.DatabaseSha256}.");
    }

    private static int? ParseOptionalInt(string name)
    {
        string? raw = Environment.GetEnvironmentVariable(name);
        if (string.IsNullOrWhiteSpace(raw)) return null;
        if (!int.TryParse(raw, out int value) || value < 0)
            throw new InvalidDataException($"{name} must be a non-negative integer when supplied.");
        return value;
    }
}
