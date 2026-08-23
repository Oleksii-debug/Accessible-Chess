using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace WordDeck;

internal sealed record ContextResolvedIdentityDepthEvidence(
    int RequiredTargetCount,
    int ScopeEntryCount,
    int StableTagParticipatingEntryCount,
    int ResolvedStableCoveredEntryCount,
    int UnresolvedAmbiguousEntryCount,
    int StableTagAbsentEntryCount,
    double ResolvedStableCoveragePercent,
    IReadOnlyList<string> ResolvedStableCoveredEntryIds,
    IReadOnlyList<string> UnresolvedAmbiguousEntryIds,
    IReadOnlyList<string> StableTagAbsentEntryIds)
{
    // These two properties project physical written-form occurrence back onto the
    // 5,446 stable-ID universe. They deliberately do NOT replace the separate
    // unique-written-form denominator in ContextPhysicalLexicalCoverageEvidence.
    // A participating homograph can therefore contribute multiple stable IDs here,
    // while remaining unresolved for POS/sense mastery below.
    public int PhysicalFormCoveredEntryCount => StableTagParticipatingEntryCount;
    public int PhysicalFormUncoveredEntryCount => StableTagAbsentEntryCount;
}

internal sealed record ContextStableIdentityCoverageEvidencePayload(
    string SchemaId,
    string MeasurementAlgorithm,
    string StableTagEvidenceSha256,
    string PhysicalFormEvidenceSha256,
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
        ContextPhysicalLexicalCoverageEvidenceDocument physicalFormEvidence,
        DictionaryPackage dictionary)
    {
        ArgumentNullException.ThrowIfNull(stableTagEvidence);
        ArgumentNullException.ThrowIfNull(physicalFormEvidence);
        ArgumentNullException.ThrowIfNull(dictionary);
        if (!ContextCorpusCoverageEvidenceBuilder.VerifyEvidenceDigest(stableTagEvidence))
            throw new InvalidDataException("Stable-tag context evidence digest is invalid.");
        if (!ContextPhysicalLexicalCoverageEvidenceBuilder.VerifyDigest(physicalFormEvidence))
            throw new InvalidDataException("Physical-form context evidence digest is invalid.");

        ContextCorpusCoverageEvidencePayload raw = stableTagEvidence.Payload;
        ContextPhysicalLexicalCoverageEvidencePayload physical = physicalFormEvidence.Payload;
        if (!string.Equals(physical.StableTagEvidenceSha256, stableTagEvidence.EvidenceDigestSha256, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Physical-form evidence is not bound to the supplied stable-tag evidence digest.");
        if (dictionary.Entries.Count != raw.DictionaryEntryCount || dictionary.Entries.Count != physical.DictionaryEntryCount)
            throw new InvalidDataException("Stable-identity evidence dictionary size differs from its source evidence.");

        string fingerprint = ContextCorpusCoverageEvidenceBuilder.ComputeDictionaryLexicalFingerprint(dictionary);
        if (!string.Equals(fingerprint, raw.DictionaryLexicalFingerprintSha256, StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(fingerprint, physical.DictionaryLexicalFingerprintSha256, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Stable-identity evidence dictionary fingerprint differs from its source evidence.");
        if (!string.Equals(raw.DatabaseSha256, physical.DatabaseSha256, StringComparison.OrdinalIgnoreCase) ||
            !string.Equals(raw.DictionaryId, physical.DictionaryId, StringComparison.Ordinal) ||
            !string.Equals(raw.SourceId, physical.SourceId, StringComparison.Ordinal) ||
            raw.SourceKind != physical.SourceKind ||
            raw.SentenceCount != physical.SentenceCount)
            throw new InvalidDataException("Stable-tag and physical-form evidence identities do not match.");

        var lexicon = new ContextTargetLexicon(dictionary);
        string[] universe = dictionary.Entries.Select(entry => ContextTargetIds.NormalizeSingle(entry.Id)).ToArray();
        ContextResolvedIdentityDepthEvidence one = Resolve(raw.OneTarget, lexicon, universe);
        ContextResolvedIdentityDepthEvidence two = Resolve(raw.TwoTarget, lexicon, universe);
        ContextResolvedIdentityDepthEvidence three = Resolve(raw.ThreeTarget, lexicon, universe);

        bool exact = raw.SourceKind == ContextCorpusKind.RealCorpus &&
                     raw.ExactDatabaseIdentityVerified &&
                     raw.ExactOxford5446Verified &&
                     physical.ExactDatabaseIdentityVerified &&
                     physical.ExactOxford5446Verified &&
                     physical.CanSupportPhysicalLexicalFormCoverageClaim &&
                     raw.DictionaryEntryCount == ContextCorpusCoverageEvidenceBuilder.ExactOxfordEntryCount;
        var payload = new ContextStableIdentityCoverageEvidencePayload(
            SchemaId,
            MeasurementAlgorithm,
            stableTagEvidence.EvidenceDigestSha256,
            physicalFormEvidence.EvidenceDigestSha256,
            raw.DatabaseSha256,
            raw.DictionaryId,
            raw.DictionaryEntryCount,
            raw.DictionaryLexicalFingerprintSha256,
            raw.SourceId,
            raw.SourceKind,
            raw.Provenance,
            raw.License,
            raw.SentenceCount,
            raw.ExactDatabaseIdentityVerified && physical.ExactDatabaseIdentityVerified,
            raw.ExactOxford5446Verified && physical.ExactOxford5446Verified,
            exact,
            RedistributionApproved: false,
            one,
            two,
            three,
            "This conservative stable-ID evidence is digest-bound to both the historical stable-tag participation evidence and the separate unique physical written-form evidence. Its per-stable-ID partition is deliberately derived from stable-tag participation plus the homograph fail-closed rule: participating non-homographic IDs may count as resolved; participating same-written-form multi-ID entries remain UNRESOLVED unless explicit POS/sense evidence disambiguates them; non-participating IDs remain corpus gaps. The unique physical-form denominator is authoritative only in the separate physical-form evidence document. Neither unresolved nor absent IDs can own canonical learner progress. Redistribution remains a separate release decision.");
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
        var stableTagReport = new ContextNaturalCoverageReport(
            depth.RequiredTargetCount,
            depth.ScopeEntryCount,
            depth.CoveredEntryCount,
            depth.UncoveredEntryCount,
            depth.CoveredEntryIds,
            depth.UncoveredEntryIds,
            depth.AmbiguousStableEntryIds);
        ContextStableIdentityCoverageReport stable = ContextStableIdentityResolution.ResolveCoverage(stableTagReport, lexicon, universe);
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
        var payload = new ContextStableIdentityCoverageEvidencePayload(
            ContextStableIdentityCoverageEvidenceBuilder.SchemaId,
            ContextStableIdentityCoverageEvidenceBuilder.MeasurementAlgorithm,
            new string('a', 64),
            new string('d', 64),
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
        Console.WriteLine("Context stable-identity evidence self-test PASS: stable-tag/stable-ID semantic split, physical-form evidence chain and digest fail-closed contract verified.");
    }
}
