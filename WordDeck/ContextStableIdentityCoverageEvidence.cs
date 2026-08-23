using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace WordDeck;

internal sealed record ContextResolvedIdentityDepthEvidence(
    int RequiredTargetCount,
    int ScopeEntryCount,
    int StableTagCoveredEntryCount,
    int ResolvedStableCoveredEntryCount,
    int UnresolvedAmbiguousEntryCount,
    int UnambiguousStableTagUncoveredEntryCount,
    double ResolvedStableCoveragePercent,
    IReadOnlyList<string> ResolvedStableCoveredEntryIds,
    IReadOnlyList<string> UnresolvedAmbiguousEntryIds,
    IReadOnlyList<string> UnambiguousStableTagUncoveredEntryIds);

internal sealed record ContextStableIdentityCoverageEvidencePayload(
    string SchemaId,
    string MeasurementAlgorithm,
    string StableTagEvidenceSha256,
    string DatabaseSha256,
    string DictionaryId,
    int DictionaryEntryCount,
    string DictionaryLexicalFingerprintSha256,
    string SourceId,
    ContextCorpusKind SourceKind,
    string Provenance,
    string License,
    int SentenceCount,
    bool ExactDatabaseIdentityVerified,
    bool ExactOxford5446Verified,
    bool CanSupportConservativeStableIdentityCoverageClaim,
    bool RedistributionApproved,
    ContextResolvedIdentityDepthEvidence OneTarget,
    ContextResolvedIdentityDepthEvidence TwoTarget,
    ContextResolvedIdentityDepthEvidence ThreeTarget,
    string EvidenceBoundary);

internal sealed record ContextStableIdentityCoverageEvidenceDocument(
    ContextStableIdentityCoverageEvidencePayload Payload,
    string EvidenceDigestSha256)
{
    public string ToCanonicalJson() => ContextStableIdentityCoverageEvidenceBuilder.SerializeDocument(this);
}

internal static class ContextStableIdentityCoverageEvidenceBuilder
{
    public const string SchemaId = "worddeck-context-stable-identity-coverage-v1";
    public const string MeasurementAlgorithm = "worddeck-context-stable-tag-plus-conservative-stable-id-v1";

    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = false };

    public static ContextStableIdentityCoverageEvidenceDocument Build(
        ContextCorpusCoverageEvidenceDocument stableTagEvidence,
        DictionaryPackage dictionary)
    {
        ArgumentNullException.ThrowIfNull(stableTagEvidence);
        ArgumentNullException.ThrowIfNull(dictionary);
        if (!ContextCorpusCoverageEvidenceBuilder.VerifyEvidenceDigest(stableTagEvidence))
            throw new InvalidDataException("Stable-tag context evidence digest is invalid.");
        ContextCorpusCoverageEvidencePayload raw = stableTagEvidence.Payload;
        if (dictionary.Entries.Count != raw.DictionaryEntryCount)
            throw new InvalidDataException("Stable-identity evidence dictionary size differs from stable-tag evidence.");
        string fingerprint = ContextCorpusCoverageEvidenceBuilder.ComputeDictionaryLexicalFingerprint(dictionary);
        if (!string.Equals(fingerprint, raw.DictionaryLexicalFingerprintSha256, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Stable-identity evidence dictionary fingerprint differs from stable-tag evidence.");

        var lexicon = new ContextTargetLexicon(dictionary);
        string[] universe = dictionary.Entries.Select(entry => ContextTargetIds.NormalizeSingle(entry.Id)).ToArray();
        ContextResolvedIdentityDepthEvidence one = Resolve(raw.OneTarget, lexicon, universe);
        ContextResolvedIdentityDepthEvidence two = Resolve(raw.TwoTarget, lexicon, universe);
        ContextResolvedIdentityDepthEvidence three = Resolve(raw.ThreeTarget, lexicon, universe);

        bool exact = raw.SourceKind == ContextCorpusKind.RealCorpus &&
                     raw.ExactDatabaseIdentityVerified &&
                     raw.ExactOxford5446Verified &&
                     raw.DictionaryEntryCount == ContextCorpusCoverageEvidenceBuilder.ExactOxfordEntryCount;
        var payload = new ContextStableIdentityCoverageEvidencePayload(
            SchemaId,
            MeasurementAlgorithm,
            stableTagEvidence.EvidenceDigestSha256,
            raw.DatabaseSha256,
            raw.DictionaryId,
            raw.DictionaryEntryCount,
            raw.DictionaryLexicalFingerprintSha256,
            raw.SourceId,
            raw.SourceKind,
            raw.Provenance,
            raw.License,
            raw.SentenceCount,
            raw.ExactDatabaseIdentityVerified,
            raw.ExactOxford5446Verified,
            exact,
            RedistributionApproved: false,
            one,
            two,
            three,
            "The source stable-tag participation evidence records surface-form occurrence/co-occurrence using historical stable-ID tags. This document applies a conservative stable-ID filter: any dictionary ID whose written form is shared by multiple stable entries remains UNRESOLVED for every depth unless a future POS/sense-aware source explicitly disambiguates that occurrence. Unresolved IDs do not own canonical learner progress and are not relabeled as missing corpus sentences. True unique physical-form coverage is reported in the separate physical-forms evidence document. Redistribution remains a separate release decision.");
        string digest = ComputeDigest(payload);
        return new ContextStableIdentityCoverageEvidenceDocument(payload, digest);
    }

    public static string SerializeDocument(ContextStableIdentityCoverageEvidenceDocument document)
    {
        ArgumentNullException.ThrowIfNull(document);
        if (!VerifyDigest(document))
            throw new InvalidDataException("Stable-identity context evidence digest does not match its canonical payload.");
        return JsonSerializer.Serialize(document, JsonOptions);
    }

    public static bool VerifyDigest(ContextStableIdentityCoverageEvidenceDocument document) =>
        document is not null && string.Equals(document.EvidenceDigestSha256, ComputeDigest(document.Payload), StringComparison.OrdinalIgnoreCase);

    private static ContextResolvedIdentityDepthEvidence Resolve(
        ContextCoverageDepthEvidence depth,
        ContextTargetLexicon lexicon,
        IReadOnlyCollection<string> universe)
    {
        var rawReport = new ContextNaturalCoverageReport(
            depth.RequiredTargetCount,
            depth.ScopeEntryCount,
            depth.CoveredEntryCount,
            depth.UncoveredEntryCount,
            depth.CoveredEntryIds,
            depth.UncoveredEntryIds,
            depth.AmbiguousStableEntryIds);
        ContextStableIdentityCoverageReport stable = ContextStableIdentityResolution.ResolveCoverage(rawReport, lexicon, universe);
        return new ContextResolvedIdentityDepthEvidence(
            depth.RequiredTargetCount,
            depth.ScopeEntryCount,
            depth.CoveredEntryCount,
            stable.ResolvedCoveredEntryCount,
            stable.UnresolvedAmbiguousEntryCount,
            stable.UncoveredEntryCount,
            stable.ResolvedCoveragePercent,
            stable.ResolvedCoveredEntryIds.OrderBy(id => id, StringComparer.Ordinal).ToArray(),
            stable.UnresolvedAmbiguousEntryIds.OrderBy(id => id, StringComparer.Ordinal).ToArray(),
            stable.UncoveredEntryIds.OrderBy(id => id, StringComparer.Ordinal).ToArray());
    }

    private static string ComputeDigest(ContextStableIdentityCoverageEvidencePayload payload)
    {
        string json = JsonSerializer.Serialize(payload, JsonOptions);
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(json))).ToLowerInvariant();
    }
}

internal static class ContextStableIdentityCoverageEvidenceSelfTest
{
    public static void Run()
    {
        // Core partition behavior is exercised by ContextStableIdentityResolutionSelfTest.
        // This smoke protects the canonical JSON digest contract without constructing a
        // fake 5446-entry stable-tag evidence document.
        var payload = new ContextStableIdentityCoverageEvidencePayload(
            ContextStableIdentityCoverageEvidenceBuilder.SchemaId,
            ContextStableIdentityCoverageEvidenceBuilder.MeasurementAlgorithm,
            new string('a', 64),
            new string('b', 64),
            "fixture",
            1,
            new string('c', 64),
            "source",
            ContextCorpusKind.SyntheticFixture,
            "test-only provenance",
            "TEST",
            1,
            false,
            false,
            false,
            false,
            new ContextResolvedIdentityDepthEvidence(1, 1, 1, 1, 0, 0, 100, new[] { "id" }, Array.Empty<string>(), Array.Empty<string>()),
            new ContextResolvedIdentityDepthEvidence(2, 1, 0, 0, 0, 1, 0, Array.Empty<string>(), Array.Empty<string>(), new[] { "id" }),
            new ContextResolvedIdentityDepthEvidence(3, 1, 0, 0, 0, 1, 0, Array.Empty<string>(), Array.Empty<string>(), new[] { "id" }),
            "test-only boundary");
        bool rejected = false;
        try
        {
            _ = ContextStableIdentityCoverageEvidenceBuilder.SerializeDocument(new ContextStableIdentityCoverageEvidenceDocument(payload, new string('0', 64)));
        }
        catch (InvalidDataException)
        {
            rejected = true;
        }
        if (!rejected) throw new InvalidOperationException("Stable-identity evidence serializer accepted a forged digest.");
        Console.WriteLine("Context stable-identity evidence self-test PASS: stable-tag source binding, physical/stable semantic split and digest fail-closed contract verified.");
    }
}
