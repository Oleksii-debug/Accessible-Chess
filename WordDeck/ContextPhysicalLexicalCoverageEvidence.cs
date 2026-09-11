using System.Runtime.CompilerServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace WordDeck;

internal sealed record ContextPhysicalLexicalDepthEvidence(
    int RequiredTargetCount,
    int StableTagScopeEntryCount,
    int LexicalFormCount,
    int CoveredLexicalFormCount,
    int UncoveredLexicalFormCount,
    double CoveragePercent,
    IReadOnlyList<string> CoveredLexicalKeys,
    IReadOnlyList<string> UncoveredLexicalKeys);

internal sealed record ContextPhysicalLexicalCoverageEvidencePayload(
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
    int UniqueLexicalFormCount,
    int AmbiguousLexicalFormCount,
    int StableIdsInAmbiguousLexicalForms,
    bool ExactDatabaseIdentityVerified,
    bool ExactOxford5446Verified,
    bool CanSupportPhysicalLexicalFormCoverageClaim,
    bool RedistributionApproved,
    ContextPhysicalLexicalDepthEvidence OneTarget,
    ContextPhysicalLexicalDepthEvidence TwoTarget,
    ContextPhysicalLexicalDepthEvidence ThreeTarget,
    string EvidenceBoundary);

internal sealed record ContextPhysicalLexicalCoverageEvidenceDocument(
    ContextPhysicalLexicalCoverageEvidencePayload Payload,
    string EvidenceDigestSha256)
{
    public string ToCanonicalJson() => ContextPhysicalLexicalCoverageEvidenceBuilder.SerializeDocument(this);
}

internal static class ContextPhysicalLexicalCoverageEvidenceBuilder
{
    public const string SchemaId = "worddeck-context-physical-lexical-coverage-v1";
    public const string MeasurementAlgorithm = "worddeck-context-unique-written-form-depth-v1";

    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = false };

    public static ContextPhysicalLexicalCoverageEvidenceDocument Build(
        ContextCorpusCoverageEvidenceDocument stableTagEvidence,
        DictionaryPackage dictionary)
    {
        ArgumentNullException.ThrowIfNull(stableTagEvidence);
        ArgumentNullException.ThrowIfNull(dictionary);
        if (!ContextCorpusCoverageEvidenceBuilder.VerifyEvidenceDigest(stableTagEvidence))
            throw new InvalidDataException("Stable-tag context evidence digest is invalid.");

        ContextCorpusCoverageEvidencePayload raw = stableTagEvidence.Payload;
        if (dictionary.Entries.Count != raw.DictionaryEntryCount)
            throw new InvalidDataException("Physical lexical-form evidence dictionary size differs from stable-tag evidence.");
        string fingerprint = ContextCorpusCoverageEvidenceBuilder.ComputeDictionaryLexicalFingerprint(dictionary);
        if (!string.Equals(fingerprint, raw.DictionaryLexicalFingerprintSha256, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Physical lexical-form evidence dictionary fingerprint differs from stable-tag evidence.");

        var lexicon = new ContextTargetLexicon(dictionary);
        string[] universeIds = dictionary.Entries.Select(entry => ContextTargetIds.NormalizeSingle(entry.Id)).ToArray();
        string[] lexicalUniverse = universeIds
            .Select(lexicon.LexicalKeyFor)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(key => key, StringComparer.Ordinal)
            .ToArray();
        int ambiguousFormCount = lexicalUniverse.Count(key => lexicon.StableIdsForLexicalKey(key).Count > 1);
        int idsInAmbiguousForms = lexicalUniverse
            .Where(key => lexicon.StableIdsForLexicalKey(key).Count > 1)
            .Sum(key => lexicon.StableIdsForLexicalKey(key).Count);

        ContextPhysicalLexicalDepthEvidence one = ResolveDepth(raw.OneTarget, lexicon, lexicalUniverse);
        ContextPhysicalLexicalDepthEvidence two = ResolveDepth(raw.TwoTarget, lexicon, lexicalUniverse);
        ContextPhysicalLexicalDepthEvidence three = ResolveDepth(raw.ThreeTarget, lexicon, lexicalUniverse);

        bool exact = raw.SourceKind == ContextCorpusKind.RealCorpus &&
                     raw.ExactDatabaseIdentityVerified &&
                     raw.ExactOxford5446Verified &&
                     raw.DictionaryEntryCount == ContextCorpusCoverageEvidenceBuilder.ExactOxfordEntryCount;
        var payload = new ContextPhysicalLexicalCoverageEvidencePayload(
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
            lexicalUniverse.Length,
            ambiguousFormCount,
            idsInAmbiguousForms,
            raw.ExactDatabaseIdentityVerified,
            raw.ExactOxford5446Verified,
            exact,
            RedistributionApproved: false,
            one,
            two,
            three,
            "This report measures UNIQUE normalized written lexical forms. Multiple Oxford stable IDs that share one written form contribute one physical form to the denominator. It does not claim POS/sense resolution. Conservative stable-ID coverage is reported separately, and redistribution remains a separate release decision.");
        return new ContextPhysicalLexicalCoverageEvidenceDocument(payload, ComputeDigest(payload));
    }

    internal static ContextPhysicalLexicalDepthEvidence ResolveDepth(
        ContextCoverageDepthEvidence stableTagDepth,
        ContextTargetLexicon lexicon,
        IReadOnlyCollection<string> lexicalUniverse)
    {
        ArgumentNullException.ThrowIfNull(stableTagDepth);
        ArgumentNullException.ThrowIfNull(lexicon);
        ArgumentNullException.ThrowIfNull(lexicalUniverse);

        string[] universe = lexicalUniverse
            .Where(key => !string.IsNullOrWhiteSpace(key))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(key => key, StringComparer.Ordinal)
            .ToArray();
        if (universe.Length == 0)
            throw new InvalidDataException("Physical lexical-form coverage requires a non-empty lexical universe.");
        var universeSet = new HashSet<string>(universe, StringComparer.OrdinalIgnoreCase);
        string[] covered = stableTagDepth.CoveredEntryIds
            .Select(lexicon.LexicalKeyFor)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(key => key, StringComparer.Ordinal)
            .ToArray();
        if (covered.Any(key => !universeSet.Contains(key)))
            throw new InvalidDataException("Stable-tag coverage produced a lexical form outside the dictionary universe.");
        var coveredSet = new HashSet<string>(covered, StringComparer.OrdinalIgnoreCase);
        string[] uncovered = universe.Where(key => !coveredSet.Contains(key)).ToArray();
        if (covered.Length + uncovered.Length != universe.Length)
            throw new InvalidOperationException("Physical lexical-form coverage did not partition the unique written-form universe.");

        return new ContextPhysicalLexicalDepthEvidence(
            stableTagDepth.RequiredTargetCount,
            stableTagDepth.ScopeEntryCount,
            universe.Length,
            covered.Length,
            uncovered.Length,
            covered.Length * 100.0 / universe.Length,
            covered,
            uncovered);
    }

    public static string SerializeDocument(ContextPhysicalLexicalCoverageEvidenceDocument document)
    {
        ArgumentNullException.ThrowIfNull(document);
        if (!VerifyDigest(document))
            throw new InvalidDataException("Physical lexical-form context evidence digest does not match its canonical payload.");
        return JsonSerializer.Serialize(document, JsonOptions);
    }

    public static bool VerifyDigest(ContextPhysicalLexicalCoverageEvidenceDocument document) =>
        document is not null && string.Equals(document.EvidenceDigestSha256, ComputeDigest(document.Payload), StringComparison.OrdinalIgnoreCase);

    private static string ComputeDigest(ContextPhysicalLexicalCoverageEvidencePayload payload)
    {
        string json = JsonSerializer.Serialize(payload, JsonOptions);
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(json))).ToLowerInvariant();
    }
}

internal static class ContextPhysicalLexicalCoverageEvidenceSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            ContextPhysicalLexicalCoverageEvidenceSelfTest.Run();
    }
}

internal static class ContextPhysicalLexicalCoverageEvidenceSelfTest
{
    public static void Run()
    {
        var lexicon = new ContextTargetLexicon("physical-form-test", new[]
        {
            ("run-n", "run"),
            ("run-v", "run"),
            ("daily", "daily"),
            ("practice", "practice")
        });
        var depth = new ContextCoverageDepthEvidence(
            1,
            4,
            3,
            1,
            75.0,
            new[] { "run-n", "run-v", "daily" },
            new[] { "practice" },
            new[] { "run-n", "run-v" });
        ContextPhysicalLexicalDepthEvidence physical = ContextPhysicalLexicalCoverageEvidenceBuilder.ResolveDepth(
            depth,
            lexicon,
            new[] { "run", "daily", "practice" });
        if (physical.LexicalFormCount != 3 || physical.CoveredLexicalFormCount != 2 || physical.UncoveredLexicalFormCount != 1)
            throw new InvalidOperationException("Unique physical-form coverage incorrectly counted homographic stable IDs as multiple written forms.");
        if (!physical.CoveredLexicalKeys.SequenceEqual(new[] { "daily", "run" }, StringComparer.OrdinalIgnoreCase) ||
            !physical.UncoveredLexicalKeys.SequenceEqual(new[] { "practice" }, StringComparer.OrdinalIgnoreCase))
            throw new InvalidOperationException("Unique physical-form coverage partition is wrong.");
        Console.WriteLine("Context physical lexical-form evidence self-test PASS: homographic stable IDs collapse to one written-form denominator and remain separate from stable-ID coverage.");
    }
}
