using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;

namespace WordDeck;

internal enum ContextCorpusGapKind
{
    MissingAnyContext = 1,
    MissingNaturalPair = 2,
    MissingNaturalTriple = 3
}

internal sealed record ContextCorpusGapEntry(
    int Priority,
    ContextCorpusGapKind GapKind,
    string EntryId,
    string Level,
    string Source,
    string LexicalKey,
    bool AmbiguousStableIdentity,
    bool OneTargetCovered,
    bool TwoTargetCovered,
    bool ThreeTargetCovered);

internal sealed record ContextCorpusGapLevelSummary(
    string Level,
    int MissingAnyContext,
    int MissingNaturalPair,
    int MissingNaturalTriple,
    int TotalNotTripleReady);

internal sealed record ContextCorpusGapBacklogSummary(
    string SchemaId,
    string SourceEvidenceDigestSha256,
    string DatabaseSha256,
    string PackId,
    int DictionaryEntryCount,
    int OneTargetGapCount,
    int PairOnlyGapCount,
    int TripleOnlyGapCount,
    int TotalNotTripleReady,
    int AmbiguousGapEntryCount,
    IReadOnlyList<ContextCorpusGapLevelSummary> Levels);

internal sealed record ContextCorpusGapBacklog(
    ContextCorpusGapBacklogSummary Summary,
    IReadOnlyList<ContextCorpusGapEntry> Entries);

internal static class ContextCorpusGapBacklogBuilder
{
    public const string SchemaId = "worddeck-context-gap-backlog-v1";

    public static ContextCorpusGapBacklog Build(
        ContextCorpusCoverageEvidenceDocument evidence,
        DictionaryPackage dictionary)
    {
        ArgumentNullException.ThrowIfNull(evidence);
        ArgumentNullException.ThrowIfNull(dictionary);
        if (!ContextCorpusCoverageEvidenceBuilder.VerifyEvidenceDigest(evidence))
            throw new InvalidDataException("Context corpus coverage evidence digest is invalid.");

        ContextCorpusCoverageEvidencePayload payload = evidence.Payload;
        if (!string.Equals(payload.SchemaId, ContextCorpusCoverageEvidenceBuilder.SchemaId, StringComparison.Ordinal) ||
            !string.Equals(payload.MeasurementAlgorithm, ContextCorpusCoverageEvidenceBuilder.MeasurementAlgorithm, StringComparison.Ordinal))
            throw new InvalidDataException("Context gap backlog requires the current lexical-form-aware coverage evidence schema and algorithm.");
        if (!payload.ExactDatabaseIdentityVerified || !payload.ExactOxford5446Verified || !payload.CanSupportRealCorpusCoverageClaim)
            throw new InvalidDataException("Context gap backlog requires exact real-corpus identity and Oxford-5446 coverage evidence.");
        if (payload.RedistributionApproved)
            throw new InvalidDataException("Coverage evidence must not self-approve redistribution.");
        if (payload.SourceKind != ContextCorpusKind.RealCorpus)
            throw new InvalidDataException("Context gap backlog for corpus completion requires real-corpus evidence.");
        if (dictionary.Entries.Count != ContextCorpusCoverageEvidenceBuilder.ExactOxfordEntryCount)
            throw new InvalidDataException("Context gap backlog requires the exact 5446-entry Oxford dictionary.");
        string fingerprint = ContextCorpusCoverageEvidenceBuilder.ComputeDictionaryLexicalFingerprint(dictionary);
        if (!string.Equals(fingerprint, payload.DictionaryLexicalFingerprintSha256, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Current Oxford dictionary lexical fingerprint does not match the measured coverage evidence.");

        ValidateCoverageBand(payload.OneTarget, 1);
        ValidateCoverageBand(payload.TwoTarget, 2);
        ValidateCoverageBand(payload.ThreeTarget, 3);

        var oneCovered = payload.OneTarget.CoveredEntryIds.ToHashSet(StringComparer.OrdinalIgnoreCase);
        var twoCovered = payload.TwoTarget.CoveredEntryIds.ToHashSet(StringComparer.OrdinalIgnoreCase);
        var threeCovered = payload.ThreeTarget.CoveredEntryIds.ToHashSet(StringComparer.OrdinalIgnoreCase);
        if (!twoCovered.IsSubsetOf(oneCovered))
            throw new InvalidDataException("Two-target coverage must be a subset of one-target coverage.");
        if (!threeCovered.IsSubsetOf(twoCovered))
            throw new InvalidDataException("Three-target coverage must be a subset of two-target coverage.");

        var ambiguousIds = payload.OneTarget.AmbiguousStableEntryIds
            .Concat(payload.TwoTarget.AmbiguousStableEntryIds)
            .Concat(payload.ThreeTarget.AmbiguousStableEntryIds)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        var lexicon = new ContextTargetLexicon(dictionary);
        var byId = dictionary.Entries.ToDictionary(entry => entry.Id, StringComparer.OrdinalIgnoreCase);
        var entries = new List<ContextCorpusGapEntry>();

        foreach (DictionaryEntry entry in dictionary.Entries.OrderBy(item => item.Id, StringComparer.Ordinal))
        {
            bool one = oneCovered.Contains(entry.Id);
            bool two = twoCovered.Contains(entry.Id);
            bool three = threeCovered.Contains(entry.Id);
            if (three)
                continue;

            ContextCorpusGapKind kind = !one
                ? ContextCorpusGapKind.MissingAnyContext
                : !two
                    ? ContextCorpusGapKind.MissingNaturalPair
                    : ContextCorpusGapKind.MissingNaturalTriple;
            entries.Add(new ContextCorpusGapEntry(
                (int)kind,
                kind,
                entry.Id,
                entry.Level,
                entry.Source,
                lexicon.LexicalKeyFor(entry.Id),
                ambiguousIds.Contains(entry.Id),
                one,
                two,
                three));
        }

        int oneGap = entries.Count(entry => entry.GapKind == ContextCorpusGapKind.MissingAnyContext);
        int pairOnly = entries.Count(entry => entry.GapKind == ContextCorpusGapKind.MissingNaturalPair);
        int tripleOnly = entries.Count(entry => entry.GapKind == ContextCorpusGapKind.MissingNaturalTriple);
        if (oneGap != payload.OneTarget.UncoveredEntryCount)
            throw new InvalidDataException("One-target gap backlog count does not match coverage evidence.");
        if (oneGap + pairOnly != payload.TwoTarget.UncoveredEntryCount)
            throw new InvalidDataException("Two-target gap backlog count does not match coverage evidence.");
        if (oneGap + pairOnly + tripleOnly != payload.ThreeTarget.UncoveredEntryCount)
            throw new InvalidDataException("Three-target gap backlog count does not match coverage evidence.");

        string[] levelOrder = { "A1", "A2", "B1", "B2", "C1" };
        ContextCorpusGapLevelSummary[] levels = levelOrder.Select(level =>
        {
            ContextCorpusGapEntry[] levelEntries = entries
                .Where(entry => string.Equals(entry.Level, level, StringComparison.OrdinalIgnoreCase))
                .ToArray();
            return new ContextCorpusGapLevelSummary(
                level,
                levelEntries.Count(entry => entry.GapKind == ContextCorpusGapKind.MissingAnyContext),
                levelEntries.Count(entry => entry.GapKind == ContextCorpusGapKind.MissingNaturalPair),
                levelEntries.Count(entry => entry.GapKind == ContextCorpusGapKind.MissingNaturalTriple),
                levelEntries.Length);
        }).ToArray();

        if (levels.Sum(level => level.TotalNotTripleReady) != entries.Count)
            throw new InvalidDataException("Context gap backlog contains an unsupported or missing CEFR level.");

        return new ContextCorpusGapBacklog(
            new ContextCorpusGapBacklogSummary(
                SchemaId,
                evidence.EvidenceDigestSha256,
                payload.DatabaseSha256,
                payload.SourceId,
                payload.DictionaryEntryCount,
                oneGap,
                pairOnly,
                tripleOnly,
                entries.Count,
                entries.Count(entry => entry.AmbiguousStableIdentity),
                levels),
            entries
                .OrderBy(entry => entry.Priority)
                .ThenBy(entry => LevelOrdinal(entry.Level))
                .ThenBy(entry => entry.Source, StringComparer.OrdinalIgnoreCase)
                .ThenBy(entry => entry.EntryId, StringComparer.Ordinal)
                .ToArray());
    }

    public static string ToDeterministicTsv(ContextCorpusGapBacklog backlog)
    {
        ArgumentNullException.ThrowIfNull(backlog);
        var builder = new StringBuilder();
        builder.AppendLine("priority\tgap_kind\tentry_id\tlevel\tsource\tlexical_key\tambiguous_stable_identity\tone_target_covered\ttwo_target_covered\tthree_target_covered");
        foreach (ContextCorpusGapEntry entry in backlog.Entries)
        {
            builder.Append(entry.Priority).Append('\t')
                .Append(entry.GapKind).Append('\t')
                .Append(EscapeTsv(entry.EntryId)).Append('\t')
                .Append(EscapeTsv(entry.Level)).Append('\t')
                .Append(EscapeTsv(entry.Source)).Append('\t')
                .Append(EscapeTsv(entry.LexicalKey)).Append('\t')
                .Append(entry.AmbiguousStableIdentity ? "true" : "false").Append('\t')
                .Append(entry.OneTargetCovered ? "true" : "false").Append('\t')
                .Append(entry.TwoTargetCovered ? "true" : "false").Append('\t')
                .Append(entry.ThreeTargetCovered ? "true" : "false").AppendLine();
        }
        return builder.ToString();
    }

    private static void ValidateCoverageBand(ContextCoverageDepthEvidence band, int expectedTargetCount)
    {
        if (band.RequiredTargetCount != expectedTargetCount || band.ScopeEntryCount != ContextCorpusCoverageEvidenceBuilder.ExactOxfordEntryCount)
            throw new InvalidDataException($"Coverage band {expectedTargetCount} is not the exact Oxford-5446 universe.");
        if (band.CoveredEntryCount + band.UncoveredEntryCount != band.ScopeEntryCount)
            throw new InvalidDataException($"Coverage band {expectedTargetCount} does not partition its universe.");
        if (band.CoveredEntryIds.Count != band.CoveredEntryCount || band.UncoveredEntryIds.Count != band.UncoveredEntryCount)
            throw new InvalidDataException($"Coverage band {expectedTargetCount} list counts do not match summary counts.");
    }

    private static int LevelOrdinal(string level) => level?.ToUpperInvariant() switch
    {
        "A1" => 1,
        "A2" => 2,
        "B1" => 3,
        "B2" => 4,
        "C1" => 5,
        _ => 99
    };

    private static string EscapeTsv(string value) =>
        (value ?? string.Empty).Replace('\t', ' ').Replace('\r', ' ').Replace('\n', ' ');
}

internal static class ContextCorpusGapBacklogCommandBootstrap
{
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true };

    [ModuleInitializer]
    internal static void Initialize()
    {
        string[] args = Environment.GetCommandLineArgs();
        int commandIndex = Array.FindIndex(args, arg => arg.Equals("--build-context-gap-backlog", StringComparison.OrdinalIgnoreCase));
        if (commandIndex < 0)
            return;

        try
        {
            if (args.Length != commandIndex + 4)
                throw new ArgumentException("Usage: --build-context-gap-backlog <coverage-evidence.json> <gap-backlog.tsv> <gap-summary.json>");
            string evidencePath = Path.GetFullPath(args[commandIndex + 1]);
            string tsvPath = Path.GetFullPath(args[commandIndex + 2]);
            string summaryPath = Path.GetFullPath(args[commandIndex + 3]);
            ContextCorpusCoverageEvidenceDocument evidence = JsonSerializer.Deserialize<ContextCorpusCoverageEvidenceDocument>(File.ReadAllText(evidencePath))
                ?? throw new InvalidDataException("Coverage evidence JSON could not be parsed.");
            DictionaryPackage dictionary = DictionaryLoader.LoadEmbeddedOxford();
            ContextCorpusGapBacklog backlog = ContextCorpusGapBacklogBuilder.Build(evidence, dictionary);

            Directory.CreateDirectory(Path.GetDirectoryName(tsvPath) ?? ".");
            Directory.CreateDirectory(Path.GetDirectoryName(summaryPath) ?? ".");
            File.WriteAllText(tsvPath, ContextCorpusGapBacklogBuilder.ToDeterministicTsv(backlog), new UTF8Encoding(false));
            File.WriteAllText(summaryPath, JsonSerializer.Serialize(backlog.Summary, JsonOptions), new UTF8Encoding(false));
            Console.WriteLine($"Context gap backlog PASS: no-context={backlog.Summary.OneTargetGapCount}; pair-only={backlog.Summary.PairOnlyGapCount}; triple-only={backlog.Summary.TripleOnlyGapCount}; total-not-triple-ready={backlog.Summary.TotalNotTripleReady}; ambiguous-gap-ids={backlog.Summary.AmbiguousGapEntryCount}.");
            Environment.Exit(0);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("Context gap backlog command failed: " + ex.Message);
            Environment.Exit(2);
        }
    }
}
