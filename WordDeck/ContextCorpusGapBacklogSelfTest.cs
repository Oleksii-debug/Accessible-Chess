using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class ContextCorpusGapBacklogSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            ContextCorpusGapBacklogSelfTest.Run();
    }
}

internal static class ContextCorpusGapBacklogSelfTest
{
    public static void Run()
    {
        DictionaryPackage dictionary = DictionaryLoader.LoadEmbeddedOxford();
        Require(dictionary.Entries.Count == 5446, "expected exact Oxford 5446 dictionary");
        string[] ids = dictionary.Entries.Select(entry => entry.Id).OrderBy(id => id, StringComparer.Ordinal).ToArray();
        string[] oneMissing = ids.Take(2).ToArray();
        string pairOnlyMissing = ids[2];
        string[] tripleOnlyMissing = ids.Skip(3).Take(2).ToArray();

        var oneCovered = ids.Except(oneMissing, StringComparer.OrdinalIgnoreCase).ToArray();
        var twoCovered = oneCovered.Where(id => !id.Equals(pairOnlyMissing, StringComparison.OrdinalIgnoreCase)).ToArray();
        var threeCovered = twoCovered.Where(id => !tripleOnlyMissing.Contains(id, StringComparer.OrdinalIgnoreCase)).ToArray();
        string fingerprint = ContextCorpusCoverageEvidenceBuilder.ComputeDictionaryLexicalFingerprint(dictionary);

        ContextCorpusCoverageEvidenceDocument evidence = MakeEvidence(
            dictionary,
            fingerprint,
            ids,
            oneCovered,
            twoCovered,
            threeCovered);
        ContextCorpusGapBacklog backlog = ContextCorpusGapBacklogBuilder.Build(evidence, dictionary);

        Require(backlog.Summary.OneTargetGapCount == 2, "expected two no-context gaps");
        Require(backlog.Summary.PairOnlyGapCount == 1, "expected one pair-only gap");
        Require(backlog.Summary.TripleOnlyGapCount == 2, "expected two triple-only gaps");
        Require(backlog.Summary.TotalNotTripleReady == 5, "expected five total not-triple-ready entries");
        Require(backlog.Entries.Count == 5, "backlog entry count mismatch");
        Require(backlog.Entries.Count(entry => entry.GapKind == ContextCorpusGapKind.MissingAnyContext) == 2, "no-context classification mismatch");
        Require(backlog.Entries.Count(entry => entry.GapKind == ContextCorpusGapKind.MissingNaturalPair) == 1, "pair-only classification mismatch");
        Require(backlog.Entries.Count(entry => entry.GapKind == ContextCorpusGapKind.MissingNaturalTriple) == 2, "triple-only classification mismatch");
        Require(backlog.Summary.Levels.Sum(level => level.TotalNotTripleReady) == 5, "CEFR summary did not partition backlog");

        string firstTsv = ContextCorpusGapBacklogBuilder.ToDeterministicTsv(backlog);
        string secondTsv = ContextCorpusGapBacklogBuilder.ToDeterministicTsv(ContextCorpusGapBacklogBuilder.Build(evidence, dictionary));
        Require(firstTsv == secondTsv, "identical evidence produced non-deterministic backlog TSV");
        Require(firstTsv.Split('\n', StringSplitOptions.RemoveEmptyEntries).Length == 6, "TSV should contain one header plus five gap rows");

        ContextCorpusCoverageEvidencePayload nonMonotonicPayload = evidence.Payload with
        {
            TwoTarget = MakeDepth(2, ids, ids.Except(new[] { ids[1] }, StringComparer.OrdinalIgnoreCase).ToArray(), Array.Empty<string>())
        };
        ContextCorpusCoverageEvidenceDocument nonMonotonic = new(
            nonMonotonicPayload,
            ContextCorpusCoverageEvidenceBuilder.ComputeEvidenceDigest(nonMonotonicPayload));
        bool nonMonotonicRejected = false;
        try { _ = ContextCorpusGapBacklogBuilder.Build(nonMonotonic, dictionary); }
        catch (InvalidDataException) { nonMonotonicRejected = true; }
        Require(nonMonotonicRejected, "non-monotonic one/two/three coverage was accepted");

        ContextCorpusCoverageEvidencePayload wrongFingerprintPayload = evidence.Payload with
        {
            DictionaryLexicalFingerprintSha256 = new string('0', 64)
        };
        ContextCorpusCoverageEvidenceDocument wrongFingerprint = new(
            wrongFingerprintPayload,
            ContextCorpusCoverageEvidenceBuilder.ComputeEvidenceDigest(wrongFingerprintPayload));
        bool fingerprintRejected = false;
        try { _ = ContextCorpusGapBacklogBuilder.Build(wrongFingerprint, dictionary); }
        catch (InvalidDataException) { fingerprintRejected = true; }
        Require(fingerprintRejected, "dictionary fingerprint mismatch was accepted");

        ContextCorpusCoverageEvidenceDocument badDigest = evidence with { EvidenceDigestSha256 = new string('f', 64) };
        bool digestRejected = false;
        try { _ = ContextCorpusGapBacklogBuilder.Build(badDigest, dictionary); }
        catch (InvalidDataException) { digestRejected = true; }
        Require(digestRejected, "mutated evidence digest was accepted");

        Console.WriteLine("Context R4d gap backlog self-test PASS: monotonic one/two/three gaps, CEFR partition, deterministic TSV, evidence digest and dictionary fingerprint boundaries verified.");
    }

    private static ContextCorpusCoverageEvidenceDocument MakeEvidence(
        DictionaryPackage dictionary,
        string fingerprint,
        IReadOnlyList<string> universe,
        IReadOnlyList<string> oneCovered,
        IReadOnlyList<string> twoCovered,
        IReadOnlyList<string> threeCovered)
    {
        ContextCoverageDepthEvidence one = MakeDepth(1, universe, oneCovered, Array.Empty<string>());
        ContextCoverageDepthEvidence two = MakeDepth(2, universe, twoCovered, Array.Empty<string>());
        ContextCoverageDepthEvidence three = MakeDepth(3, universe, threeCovered, Array.Empty<string>());
        var payload = new ContextCorpusCoverageEvidencePayload(
            ContextCorpusCoverageEvidenceBuilder.SchemaId,
            ContextCorpusCoverageEvidenceBuilder.MeasurementAlgorithm,
            new string('a', 64),
            1,
            dictionary.Id,
            dictionary.Entries.Count,
            fingerprint,
            "r4d-gap-backlog-contract-fixture",
            ContextCorpusKind.RealCorpus,
            "WordDeck R4d deterministic gap backlog contract fixture; test only",
            "CC0-1.0",
            false,
            1,
            true,
            true,
            true,
            false,
            one,
            two,
            three,
            "Contract-only self-test payload.",
            "Historical stable-ID coverage is not lexical-form-aware natural coverage.");
        return new ContextCorpusCoverageEvidenceDocument(
            payload,
            ContextCorpusCoverageEvidenceBuilder.ComputeEvidenceDigest(payload));
    }

    private static ContextCoverageDepthEvidence MakeDepth(
        int required,
        IReadOnlyList<string> universe,
        IReadOnlyList<string> covered,
        IReadOnlyList<string> ambiguous)
    {
        string[] coveredSorted = covered.OrderBy(id => id, StringComparer.Ordinal).ToArray();
        string[] uncovered = universe.Except(coveredSorted, StringComparer.OrdinalIgnoreCase).OrderBy(id => id, StringComparer.Ordinal).ToArray();
        return new ContextCoverageDepthEvidence(
            required,
            universe.Count,
            coveredSorted.Length,
            uncovered.Length,
            coveredSorted.Length * 100.0 / universe.Count,
            coveredSorted,
            uncovered,
            ambiguous.OrderBy(id => id, StringComparer.Ordinal).ToArray());
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException("Context R4d gap backlog self-test failed: " + message);
    }
}
