using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace WordDeck;

internal sealed record ContextCorpusCoverageMeasurementRequest(
    ContextCorpusKind SourceKind,
    string? ExpectedDatabaseSha256 = null,
    string? ExpectedPackId = null,
    bool AllowSyntheticFixtures = false);

internal sealed record ContextCoverageDepthEvidence(
    int RequiredTargetCount,
    int ScopeEntryCount,
    int CoveredEntryCount,
    int UncoveredEntryCount,
    double CoveragePercent,
    IReadOnlyList<string> CoveredEntryIds,
    IReadOnlyList<string> UncoveredEntryIds,
    IReadOnlyList<string> AmbiguousStableEntryIds);

internal sealed record ContextCorpusCoverageEvidencePayload(
    string SchemaId,
    string MeasurementAlgorithm,
    string DatabaseSha256,
    long DatabaseBytes,
    string DictionaryId,
    int DictionaryEntryCount,
    string DictionaryLexicalFingerprintSha256,
    string SourceId,
    ContextCorpusKind SourceKind,
    string Provenance,
    string License,
    bool PrivacyLocalOnly,
    int SentenceCount,
    bool ExactDatabaseIdentityVerified,
    bool ExactOxford5446Verified,
    bool CanSupportRealCorpusCoverageClaim,
    bool RedistributionApproved,
    ContextCoverageDepthEvidence OneTarget,
    ContextCoverageDepthEvidence TwoTarget,
    ContextCoverageDepthEvidence ThreeTarget,
    string EvidenceBoundary,
    string HistoricalComparisonBoundary);

internal sealed record ContextCorpusCoverageEvidenceDocument(
    ContextCorpusCoverageEvidencePayload Payload,
    string EvidenceDigestSha256)
{
    public string ToCanonicalJson() => ContextCorpusCoverageEvidenceBuilder.SerializeDocument(this);
}

internal static class ContextCorpusCoverageEvidenceBuilder
{
    public const string SchemaId = "worddeck-context-coverage-evidence-v1";
    public const string MeasurementAlgorithm = "worddeck-context-natural-lexical-v1";
    public const int ExactOxfordEntryCount = 5446;

    private static readonly JsonSerializerOptions CanonicalJsonOptions = new()
    {
        WriteIndented = false
    };

    public static ContextCorpusCoverageEvidenceDocument Build(
        string databasePath,
        DictionaryPackage dictionary,
        ContextCorpusCoverageMeasurementRequest request)
    {
        if (string.IsNullOrWhiteSpace(databasePath))
            throw new ArgumentException("Context corpus SQLite path is required.", nameof(databasePath));
        ArgumentNullException.ThrowIfNull(dictionary);
        ArgumentNullException.ThrowIfNull(request);

        string fullPath = Path.GetFullPath(databasePath);
        if (!File.Exists(fullPath))
            throw new FileNotFoundException("Context corpus SQLite file was not found.", fullPath);

        ValidateExactOxfordDictionary(dictionary);
        string databaseSha256 = ComputeDatabaseSha256(fullPath);
        long databaseBytes = new FileInfo(fullPath).Length;
        if (databaseBytes <= 0)
            throw new InvalidDataException("Context corpus SQLite file is empty.");

        string? expectedSha = NormalizeOptionalSha256(request.ExpectedDatabaseSha256);
        string? expectedPackId = NormalizeOptionalCanonicalText(request.ExpectedPackId, "Expected SentencePack id");
        if (request.SourceKind == ContextCorpusKind.RealCorpus)
        {
            if (expectedSha is null || expectedPackId is null)
                throw new InvalidDataException(
                    "Real-corpus context coverage requires both the expected SQLite SHA-256 and exact expected PackId. Coverage must be bound to one explicitly identified corpus artifact.");
        }

        if (expectedSha is not null && !string.Equals(expectedSha, databaseSha256, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Context corpus SQLite SHA-256 does not match the expected exact artifact identity.");

        var source = new ContextSentenceSqliteSource(fullPath, request.SourceKind);
        if (expectedPackId is not null && !string.Equals(source.Descriptor.SourceId, expectedPackId, StringComparison.Ordinal))
            throw new InvalidDataException("Context corpus PackId does not match the expected exact artifact identity.");

        var useOptions = new ContextProductUseOptions(request.AllowSyntheticFixtures);
        ContextPracticeProductFacade.ValidateSourceForProductUse(source, useOptions);

        var lexicon = new ContextTargetLexicon(dictionary);
        string[] universe = dictionary.Entries
            .Select(entry => ContextTargetIds.NormalizeSingle(entry.Id))
            .ToArray();

        ContextCoverageEvidence one = ContextPracticeProductFacade.AnalyzeNaturalCoverage(
            source, lexicon, universe, 1, useOptions);
        ContextCoverageEvidence two = ContextPracticeProductFacade.AnalyzeNaturalCoverage(
            source, lexicon, universe, 2, useOptions);
        ContextCoverageEvidence three = ContextPracticeProductFacade.AnalyzeNaturalCoverage(
            source, lexicon, universe, 3, useOptions);

        var corpus = new SentencePackSqliteCorpus(fullPath);
        bool identityVerified = expectedSha is not null && expectedPackId is not null;
        bool exactOxford = universe.Length == ExactOxfordEntryCount &&
                           universe.Distinct(StringComparer.OrdinalIgnoreCase).Count() == ExactOxfordEntryCount;
        bool realCoverageEvidence = request.SourceKind == ContextCorpusKind.RealCorpus && identityVerified && exactOxford;

        string evidenceBoundary = request.SourceKind switch
        {
            ContextCorpusKind.SyntheticFixture =>
                "Synthetic fixture measurement is test-only. It cannot support a real-corpus coverage, production SentencePack or redistribution claim.",
            ContextCorpusKind.LocalUserText =>
                "Local user-text measurement is privacy-local only. It cannot be used as public corpus or redistribution evidence.",
            _ =>
                "Exact real-corpus coverage measurement is bound to this SQLite SHA-256 and PackId. Coverage measurement does not approve source licensing, attribution, redistribution or release packaging."
        };

        const string historicalBoundary =
            "Historical stable-ID two-target coverage is not equivalent to lexical-form-aware two-physical-word coverage. Do not reuse an older two-target percentage as exact natural two-word evidence; remeasure the exact corpus with this algorithm.";

        var payload = new ContextCorpusCoverageEvidencePayload(
            SchemaId,
            MeasurementAlgorithm,
            databaseSha256,
            databaseBytes,
            dictionary.Id,
            universe.Length,
            ComputeDictionaryLexicalFingerprint(dictionary),
            source.Descriptor.SourceId,
            source.Descriptor.Kind,
            source.Descriptor.Provenance,
            source.Descriptor.License,
            source.Descriptor.PrivacyLocalOnly,
            corpus.SentenceCount,
            identityVerified,
            exactOxford,
            realCoverageEvidence,
            RedistributionApproved: false,
            ToDepthEvidence(one.Coverage),
            ToDepthEvidence(two.Coverage),
            ToDepthEvidence(three.Coverage),
            evidenceBoundary,
            historicalBoundary);

        string digest = ComputeEvidenceDigest(payload);
        return new ContextCorpusCoverageEvidenceDocument(payload, digest);
    }

    internal static string ComputeDatabaseSha256(string databasePath)
    {
        using FileStream stream = File.OpenRead(databasePath);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }

    internal static string ComputeDictionaryLexicalFingerprint(DictionaryPackage dictionary)
    {
        ArgumentNullException.ThrowIfNull(dictionary);
        var builder = new StringBuilder(dictionary.Entries.Count * 48);
        foreach (DictionaryEntry entry in dictionary.Entries.OrderBy(entry => entry.Id, StringComparer.Ordinal))
        {
            AppendLengthPrefixed(builder, ContextTargetIds.NormalizeSingle(entry.Id));
            AppendLengthPrefixed(builder, entry.Level ?? string.Empty);
            AppendLengthPrefixed(builder, entry.Source ?? string.Empty);
            AppendLengthPrefixed(builder, entry.Target ?? string.Empty);
            builder.Append('\n');
        }
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(builder.ToString()))).ToLowerInvariant();
    }

    internal static string ComputeEvidenceDigest(ContextCorpusCoverageEvidencePayload payload)
    {
        ArgumentNullException.ThrowIfNull(payload);
        string canonicalPayload = JsonSerializer.Serialize(payload, CanonicalJsonOptions);
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(canonicalPayload))).ToLowerInvariant();
    }

    internal static bool VerifyEvidenceDigest(ContextCorpusCoverageEvidenceDocument document) =>
        document is not null && string.Equals(
            document.EvidenceDigestSha256,
            ComputeEvidenceDigest(document.Payload),
            StringComparison.OrdinalIgnoreCase);

    internal static string SerializeDocument(ContextCorpusCoverageEvidenceDocument document)
    {
        ArgumentNullException.ThrowIfNull(document);
        if (!VerifyEvidenceDigest(document))
            throw new InvalidDataException("Context corpus coverage evidence digest does not match its canonical payload.");
        return JsonSerializer.Serialize(document, CanonicalJsonOptions);
    }

    private static ContextCoverageDepthEvidence ToDepthEvidence(ContextNaturalCoverageReport report)
    {
        string[] covered = report.CoveredEntryIds.OrderBy(id => id, StringComparer.Ordinal).ToArray();
        string[] uncovered = report.UncoveredEntryIds.OrderBy(id => id, StringComparer.Ordinal).ToArray();
        string[] ambiguous = report.AmbiguousStableEntryIds.OrderBy(id => id, StringComparer.Ordinal).ToArray();
        if (covered.Length != report.CoveredEntryCount || uncovered.Length != report.UncoveredEntryCount ||
            covered.Length + uncovered.Length != report.ScopeEntryCount)
            throw new InvalidDataException("Context coverage evidence does not exactly partition the requested stable-ID universe.");
        if (covered.Intersect(uncovered, StringComparer.OrdinalIgnoreCase).Any())
            throw new InvalidDataException("Context coverage evidence contains a stable ID in both covered and uncovered lists.");

        return new ContextCoverageDepthEvidence(
            report.RequiredTargetCount,
            report.ScopeEntryCount,
            covered.Length,
            uncovered.Length,
            report.CoveragePercent,
            covered,
            uncovered,
            ambiguous);
    }

    private static void ValidateExactOxfordDictionary(DictionaryPackage dictionary)
    {
        if (string.IsNullOrWhiteSpace(dictionary.Id))
            throw new InvalidDataException("Context coverage dictionary id is required.");
        if (dictionary.Entries.Count != ExactOxfordEntryCount)
            throw new InvalidDataException($"Context corpus coverage evidence requires the exact {ExactOxfordEntryCount}-entry Oxford universe; received {dictionary.Entries.Count} entries.");
        if (dictionary.Entries.Select(entry => entry.Id).Distinct(StringComparer.OrdinalIgnoreCase).Count() != ExactOxfordEntryCount)
            throw new InvalidDataException("Context corpus coverage dictionary contains duplicate stable IDs.");
        _ = new ContextTargetLexicon(dictionary);
    }

    private static string? NormalizeOptionalSha256(string? value)
    {
        if (string.IsNullOrWhiteSpace(value)) return null;
        string normalized = value.Trim().ToLowerInvariant();
        if (normalized.Length != 64 || normalized.Any(ch => !Uri.IsHexDigit(ch)))
            throw new InvalidDataException("Expected context corpus SHA-256 must contain exactly 64 hexadecimal characters.");
        return normalized;
    }

    private static string? NormalizeOptionalCanonicalText(string? value, string description)
    {
        if (string.IsNullOrWhiteSpace(value)) return null;
        if (!string.Equals(value, value.Trim(), StringComparison.Ordinal))
            throw new InvalidDataException($"{description} must not contain leading or trailing whitespace.");
        return value;
    }

    private static void AppendLengthPrefixed(StringBuilder builder, string value) =>
        builder.Append(value.Length).Append(':').Append(value).Append('|');
}
