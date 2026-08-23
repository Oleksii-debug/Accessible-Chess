using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace WordDeck;

internal enum ContextCoverageGapTier
{
    MissingOneTarget = 1,
    MissingNaturalPair = 2,
    MissingNaturalTriple = 3
}

internal sealed record ContextCoverageGapItem(
    string EntryId,
    string Source,
    string Level,
    string LexicalKey,
    ContextCoverageGapTier Tier,
    bool AmbiguousStableIdentity);

internal sealed record ContextCoverageGapLevelSummary(
    string Level,
    int MissingOneTarget,
    int MissingNaturalPair,
    int MissingNaturalTriple,
    int TotalPriorityGaps);

internal sealed record ContextCorpusGapRemediationPayload(
    string SchemaId,
    string EvidenceDigestSha256,
    string DatabaseSha256,
    string DictionaryLexicalFingerprintSha256,
    string SourceId,
    int DictionaryEntryCount,
    int MissingOneTargetCount,
    int MissingNaturalPairOnlyCount,
    int MissingNaturalTripleOnlyCount,
    int NaturalTripleCoveredCount,
    int AmbiguousStableEntryCount,
    IReadOnlyList<ContextCoverageGapLevelSummary> LevelSummaries,
    IReadOnlyList<ContextCoverageGapItem> PriorityItems,
    string PriorityRule,
    string EvidenceBoundary);

internal sealed record ContextCorpusGapRemediationDocument(
    ContextCorpusGapRemediationPayload Payload,
    string PlanDigestSha256)
{
    public string ToCanonicalJson() => ContextCorpusGapRemediationBuilder.SerializeDocument(this);
}

internal static class ContextCorpusGapRemediationBuilder
{
    public const string SchemaId = "worddeck-context-gap-remediation-v1";

    private static readonly JsonSerializerOptions CanonicalJsonOptions = new()
    {
        WriteIndented = false
    };

    public static ContextCorpusGapRemediationDocument Build(
        ContextCorpusCoverageEvidenceDocument evidence,
        DictionaryPackage dictionary)
    {
        ArgumentNullException.ThrowIfNull(evidence);
        ArgumentNullException.ThrowIfNull(dictionary);
        if (!ContextCorpusCoverageEvidenceBuilder.VerifyEvidenceDigest(evidence))
            throw new InvalidDataException("Cannot build a context gap remediation plan from coverage evidence with an invalid digest.");
        ContextCorpusCoverageEvidencePayload coverage = evidence.Payload;
        if (coverage.DictionaryEntryCount != ContextCorpusCoverageEvidenceBuilder.ExactOxfordEntryCount ||
            dictionary.Entries.Count != ContextCorpusCoverageEvidenceBuilder.ExactOxfordEntryCount)
            throw new InvalidDataException("Context gap remediation requires the exact 5,446-entry Oxford universe.");

        string dictionaryFingerprint = ContextCorpusCoverageEvidenceBuilder.ComputeDictionaryLexicalFingerprint(dictionary);
        if (!string.Equals(dictionaryFingerprint, coverage.DictionaryLexicalFingerprintSha256, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Context gap remediation dictionary fingerprint does not match the measured coverage evidence.");

        var entryById = dictionary.Entries.ToDictionary(
            entry => ContextTargetIds.NormalizeSingle(entry.Id),
            StringComparer.OrdinalIgnoreCase);
        var lexicon = new ContextTargetLexicon(dictionary);
        var oneGaps = ToValidatedSet(coverage.OneTarget.UncoveredEntryIds, entryById, "one-target");
        var twoGaps = ToValidatedSet(coverage.TwoTarget.UncoveredEntryIds, entryById, "two-target");
        var threeGaps = ToValidatedSet(coverage.ThreeTarget.UncoveredEntryIds, entryById, "three-target");

        if (!oneGaps.IsSubsetOf(twoGaps))
            throw new InvalidDataException("Natural two-target gaps must include every one-target gap.");
        if (!twoGaps.IsSubsetOf(threeGaps))
            throw new InvalidDataException("Natural three-target gaps must include every two-target gap.");

        int missingOne = oneGaps.Count;
        int missingPairOnly = twoGaps.Except(oneGaps).Count();
        int missingTripleOnly = threeGaps.Except(twoGaps).Count();
        int tripleCovered = coverage.ThreeTarget.CoveredEntryCount;
        if (missingOne + missingPairOnly + missingTripleOnly + tripleCovered != dictionary.Entries.Count)
            throw new InvalidDataException("Context gap tiers do not partition the exact 5,446-entry Oxford universe.");

        var ambiguous = new HashSet<string>(
            coverage.OneTarget.AmbiguousStableEntryIds,
            StringComparer.OrdinalIgnoreCase);
        if (!ambiguous.SetEquals(coverage.TwoTarget.AmbiguousStableEntryIds) ||
            !ambiguous.SetEquals(coverage.ThreeTarget.AmbiguousStableEntryIds))
            throw new InvalidDataException("Ambiguous stable-ID catalog changed between coverage depths.");

        var items = new List<ContextCoverageGapItem>(threeGaps.Count);
        foreach (string id in threeGaps)
        {
            ContextCoverageGapTier tier = oneGaps.Contains(id)
                ? ContextCoverageGapTier.MissingOneTarget
                : twoGaps.Contains(id)
                    ? ContextCoverageGapTier.MissingNaturalPair
                    : ContextCoverageGapTier.MissingNaturalTriple;
            DictionaryEntry entry = entryById[id];
            items.Add(new ContextCoverageGapItem(
                id,
                entry.Source,
                entry.Level,
                lexicon.LexicalKeyFor(id),
                tier,
                ambiguous.Contains(id)));
        }

        ContextCoverageGapItem[] orderedItems = items
            .OrderBy(item => (int)item.Tier)
            .ThenBy(item => LevelRank(item.Level))
            .ThenBy(item => item.Source, StringComparer.OrdinalIgnoreCase)
            .ThenBy(item => item.EntryId, StringComparer.Ordinal)
            .ToArray();

        ContextCoverageGapLevelSummary[] levelSummaries = dictionary.Entries
            .Select(entry => entry.Level)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(LevelRank)
            .ThenBy(level => level, StringComparer.Ordinal)
            .Select(level =>
            {
                ContextCoverageGapItem[] levelItems = orderedItems
                    .Where(item => string.Equals(item.Level, level, StringComparison.OrdinalIgnoreCase))
                    .ToArray();
                return new ContextCoverageGapLevelSummary(
                    level,
                    levelItems.Count(item => item.Tier == ContextCoverageGapTier.MissingOneTarget),
                    levelItems.Count(item => item.Tier == ContextCoverageGapTier.MissingNaturalPair),
                    levelItems.Count(item => item.Tier == ContextCoverageGapTier.MissingNaturalTriple),
                    levelItems.Length);
            })
            .ToArray();

        const string priorityRule =
            "Priority 1: entries missing any usable sentence. Priority 2: entries with one-target context but no natural physically-distinct pair. Priority 3: entries with a natural pair but no natural physically-distinct triple. Within each tier sort by CEFR A1,A2,B1,B2,C1, then source form, then stable ID.";
        const string boundary =
            "This plan prioritizes corpus/search/index remediation only. It does not authorize generated examples, public redistribution, licensing changes or automatic replacement of real-corpus-first policy.";

        var payload = new ContextCorpusGapRemediationPayload(
            SchemaId,
            evidence.EvidenceDigestSha256,
            coverage.DatabaseSha256,
            coverage.DictionaryLexicalFingerprintSha256,
            coverage.SourceId,
            dictionary.Entries.Count,
            missingOne,
            missingPairOnly,
            missingTripleOnly,
            tripleCovered,
            ambiguous.Count,
            levelSummaries,
            orderedItems,
            priorityRule,
            boundary);
        return new ContextCorpusGapRemediationDocument(payload, ComputeDigest(payload));
    }

    public static string SerializeDocument(ContextCorpusGapRemediationDocument document)
    {
        ArgumentNullException.ThrowIfNull(document);
        if (!VerifyDigest(document))
            throw new InvalidDataException("Context gap remediation plan digest does not match its canonical payload.");
        return JsonSerializer.Serialize(document, CanonicalJsonOptions);
    }

    public static string ToTsv(ContextCorpusGapRemediationDocument document)
    {
        ArgumentNullException.ThrowIfNull(document);
        if (!VerifyDigest(document))
            throw new InvalidDataException("Cannot export a context gap remediation plan with an invalid digest.");
        var builder = new StringBuilder();
        builder.Append("priority_tier\tentry_id\tlevel\tsource\tlexical_key\tambiguous_stable_identity\n");
        foreach (ContextCoverageGapItem item in document.Payload.PriorityItems)
        {
            builder.Append((int)item.Tier).Append('\t')
                .Append(EscapeTsv(item.EntryId)).Append('\t')
                .Append(EscapeTsv(item.Level)).Append('\t')
                .Append(EscapeTsv(item.Source)).Append('\t')
                .Append(EscapeTsv(item.LexicalKey)).Append('\t')
                .Append(item.AmbiguousStableIdentity ? "true" : "false")
                .Append('\n');
        }
        return builder.ToString();
    }

    public static bool VerifyDigest(ContextCorpusGapRemediationDocument document) =>
        document is not null && string.Equals(
            document.PlanDigestSha256,
            ComputeDigest(document.Payload),
            StringComparison.OrdinalIgnoreCase);

    internal static string ComputeDigest(ContextCorpusGapRemediationPayload payload)
    {
        ArgumentNullException.ThrowIfNull(payload);
        string canonicalPayload = JsonSerializer.Serialize(payload, CanonicalJsonOptions);
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(canonicalPayload))).ToLowerInvariant();
    }

    private static HashSet<string> ToValidatedSet(
        IReadOnlyList<string> ids,
        IReadOnlyDictionary<string, DictionaryEntry> entryById,
        string description)
    {
        var set = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (string rawId in ids)
        {
            string id = ContextTargetIds.NormalizeSingle(rawId);
            if (!entryById.ContainsKey(id))
                throw new InvalidDataException($"Context {description} gap contains stable ID {id} outside the exact Oxford dictionary.");
            if (!set.Add(id))
                throw new InvalidDataException($"Context {description} gap contains duplicate stable ID {id}.");
        }
        return set;
    }

    private static int LevelRank(string? level) => (level ?? string.Empty).Trim().ToUpperInvariant() switch
    {
        "A1" => 1,
        "A2" => 2,
        "B1" => 3,
        "B2" => 4,
        "C1" => 5,
        _ => 100
    };

    private static string EscapeTsv(string? value) =>
        (value ?? string.Empty).Replace("\t", " ").Replace("\r", " ").Replace("\n", " ");
}
