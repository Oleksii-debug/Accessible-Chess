using Microsoft.Data.Sqlite;
using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class ContextCorpusGapRemediationSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            ContextCorpusGapRemediationSelfTest.Run();
    }
}

internal static class ContextCorpusGapRemediationSelfTest
{
    public static void Run()
    {
        DictionaryPackage dictionary = DictionaryLoader.LoadEmbeddedOxford();
        var lexicon = new ContextTargetLexicon(dictionary);
        (DictionaryEntry homographA, DictionaryEntry homographB) = FindHomographPair(dictionary, lexicon);
        DictionaryEntry[] unique = FindUniqueLexicalEntries(dictionary, lexicon, 6);

        string root = Path.Combine(Path.GetTempPath(), "WordDeck R4d gap remediation Київ " + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        string databasePath = Path.Combine(root, "gap-plan.sqlite");
        try
        {
            SentencePack pack = BuildPack(
                "r4d-gap-remediation-fixture",
                MakeSentence("homograph-pair", new[] { homographA, homographB, unique[0] }, "A2"),
                MakeSentence("natural-triple", new[] { unique[1], unique[2], unique[3] }, "B1"),
                MakeSentence("single-only", new[] { unique[4] }, "A1"));
            SentencePackSqlitePrototype.Build(databasePath, pack);
            SqliteConnection.ClearAllPools();

            ContextCorpusCoverageEvidenceDocument evidence = ContextCorpusCoverageEvidenceBuilder.Build(
                databasePath,
                dictionary,
                new ContextCorpusCoverageMeasurementRequest(
                    ContextCorpusKind.SyntheticFixture,
                    AllowSyntheticFixtures: true));
            ContextCorpusGapRemediationDocument first = ContextCorpusGapRemediationBuilder.Build(evidence, dictionary);
            ContextCorpusGapRemediationDocument second = ContextCorpusGapRemediationBuilder.Build(evidence, dictionary);
            ContextCorpusGapRemediationPayload p = first.Payload;

            Require(ContextCorpusGapRemediationBuilder.VerifyDigest(first), "gap plan digest did not verify");
            Require(first.PlanDigestSha256 == second.PlanDigestSha256, "identical evidence produced a different gap plan digest");
            Require(first.ToCanonicalJson() == second.ToCanonicalJson(), "identical evidence produced nondeterministic gap plan JSON");
            Require(p.DictionaryEntryCount == 5446, "gap plan is not bound to 5,446 Oxford IDs");
            Require(p.MissingOneTargetCount == 5439, $"expected 5,439 absolute fixture gaps, got {p.MissingOneTargetCount}");
            Require(p.MissingNaturalPairOnlyCount == 1, $"expected one pair-only fixture gap, got {p.MissingNaturalPairOnlyCount}");
            Require(p.MissingNaturalTripleOnlyCount == 3, $"expected three triple-only fixture gaps, got {p.MissingNaturalTripleOnlyCount}");
            Require(p.NaturalTripleCoveredCount == 3, $"expected three triple-covered fixture IDs, got {p.NaturalTripleCoveredCount}");
            Require(p.MissingOneTargetCount + p.MissingNaturalPairOnlyCount + p.MissingNaturalTripleOnlyCount + p.NaturalTripleCoveredCount == 5446,
                "exclusive gap tiers do not partition the full Oxford universe");
            Require(p.PriorityItems.Count == 5443, "priority items must contain exactly every three-target gap");
            Require(p.PriorityItems.Count(item => item.Tier == ContextCoverageGapTier.MissingOneTarget) == p.MissingOneTargetCount,
                "priority-1 item count does not match absolute gap count");
            Require(p.PriorityItems.Count(item => item.Tier == ContextCoverageGapTier.MissingNaturalPair) == p.MissingNaturalPairOnlyCount,
                "priority-2 item count does not match pair-only gap count");
            Require(p.PriorityItems.Count(item => item.Tier == ContextCoverageGapTier.MissingNaturalTriple) == p.MissingNaturalTripleOnlyCount,
                "priority-3 item count does not match triple-only gap count");
            Require(p.LevelSummaries.Sum(summary => summary.TotalPriorityGaps) == p.PriorityItems.Count,
                "level summaries do not partition all remediation items");
            Require(p.PriorityItems.SequenceEqual(p.PriorityItems
                    .OrderBy(item => (int)item.Tier)
                    .ThenBy(item => LevelRank(item.Level))
                    .ThenBy(item => item.Source, StringComparer.OrdinalIgnoreCase)
                    .ThenBy(item => item.EntryId, StringComparer.Ordinal)),
                "gap remediation items are not in deterministic priority order");
            Require(p.PriorityItems.Any(item => item.EntryId == homographA.Id && item.AmbiguousStableIdentity) ||
                    p.PriorityItems.Any(item => item.EntryId == homographB.Id && item.AmbiguousStableIdentity) ||
                    (!evidence.Payload.ThreeTarget.UncoveredEntryIds.Contains(homographA.Id, StringComparer.OrdinalIgnoreCase) &&
                     !evidence.Payload.ThreeTarget.UncoveredEntryIds.Contains(homographB.Id, StringComparer.OrdinalIgnoreCase)),
                "gap plan lost same-written-form ambiguity when the ambiguous IDs require remediation");

            string tsv = ContextCorpusGapRemediationBuilder.ToTsv(first);
            string[] lines = tsv.Split('\n', StringSplitOptions.RemoveEmptyEntries);
            Require(lines.Length == p.PriorityItems.Count + 1, "TSV did not export exactly one header plus every remediation row");
            Require(lines[0] == "priority_tier\tentry_id\tlevel\tsource\tlexical_key\tambiguous_stable_identity",
                "TSV header changed unexpectedly");

            ContextCorpusGapRemediationPayload mutated = p with { MissingOneTargetCount = p.MissingOneTargetCount - 1 };
            Require(ContextCorpusGapRemediationBuilder.ComputeDigest(mutated) != first.PlanDigestSha256,
                "gap count mutation did not change the remediation digest");

            var badEvidence = evidence with
            {
                Payload = evidence.Payload with
                {
                    TwoTarget = evidence.Payload.TwoTarget with
                    {
                        UncoveredEntryIds = evidence.Payload.TwoTarget.UncoveredEntryIds
                            .Where(id => !string.Equals(id, evidence.Payload.OneTarget.UncoveredEntryIds[0], StringComparison.OrdinalIgnoreCase))
                            .ToArray(),
                        UncoveredEntryCount = evidence.Payload.TwoTarget.UncoveredEntryCount - 1,
                        CoveredEntryIds = evidence.Payload.TwoTarget.CoveredEntryIds
                            .Append(evidence.Payload.OneTarget.UncoveredEntryIds[0])
                            .OrderBy(id => id, StringComparer.Ordinal)
                            .ToArray(),
                        CoveredEntryCount = evidence.Payload.TwoTarget.CoveredEntryCount + 1
                    }
                }
            };
            badEvidence = badEvidence with
            {
                EvidenceDigestSha256 = ContextCorpusCoverageEvidenceBuilder.ComputeEvidenceDigest(badEvidence.Payload)
            };
            bool nonMonotonicRejected = false;
            try { _ = ContextCorpusGapRemediationBuilder.Build(badEvidence, dictionary); }
            catch (InvalidDataException) { nonMonotonicRejected = true; }
            Require(nonMonotonicRejected, "non-monotonic one/two/three coverage evidence was accepted for remediation planning");

            Console.WriteLine(
                $"Context R4d gap remediation self-test PASS: priority1={p.MissingOneTargetCount}, priority2={p.MissingNaturalPairOnlyCount}, " +
                $"priority3={p.MissingNaturalTripleOnlyCount}, triple-covered={p.NaturalTripleCoveredCount}; deterministic level-aware plan, TSV and monotonicity guards verified.");
        }
        finally
        {
            SqliteConnection.ClearAllPools();
            try { Directory.Delete(root, recursive: true); } catch { }
        }
    }

    private static SentencePack BuildPack(string packId, params SentenceRecord[] sentences)
    {
        var pack = new SentencePack
        {
            PackId = packId,
            Provenance = "WordDeck R4d deterministic gap-remediation fixture; test only",
            License = "CC0-1.0",
            Sentences = sentences.ToList()
        };
        pack.Validate();
        return pack;
    }

    private static SentenceRecord MakeSentence(string id, IReadOnlyList<DictionaryEntry> targets, string difficulty)
    {
        string english = "Context gap remediation test sentence.";
        List<string> tokens = SentenceTokenizer.Tokenize(english).ToList();
        return new SentenceRecord
        {
            Id = id,
            English = english,
            Ukrainian = "Тестове речення для плану прогалин.",
            Source = "WordDeck R4d synthetic gap fixture",
            License = "CC0-1.0",
            Tokens = tokens,
            Lemmas = tokens.ToList(),
            TargetEntryIds = targets.Select(entry => entry.Id).Distinct(StringComparer.OrdinalIgnoreCase).ToList(),
            EntryLevels = targets.GroupBy(entry => entry.Id, StringComparer.OrdinalIgnoreCase)
                .ToDictionary(group => group.Key, group => group.First().Level, StringComparer.OrdinalIgnoreCase),
            DifficultyLevel = difficulty,
            OffListTokenCount = 0
        };
    }

    private static (DictionaryEntry A, DictionaryEntry B) FindHomographPair(DictionaryPackage dictionary, ContextTargetLexicon lexicon)
    {
        IGrouping<string, DictionaryEntry>? group = dictionary.Entries
            .GroupBy(entry => lexicon.LexicalKeyFor(entry.Id), StringComparer.OrdinalIgnoreCase)
            .FirstOrDefault(items => items.Select(entry => entry.Id).Distinct(StringComparer.OrdinalIgnoreCase).Count() >= 2);
        if (group is null)
            throw new InvalidOperationException("R4d gap remediation self-test expected a same-written-form Oxford group.");
        DictionaryEntry[] entries = group.Take(2).ToArray();
        return (entries[0], entries[1]);
    }

    private static DictionaryEntry[] FindUniqueLexicalEntries(DictionaryPackage dictionary, ContextTargetLexicon lexicon, int count)
    {
        var keyCounts = dictionary.Entries.GroupBy(entry => lexicon.LexicalKeyFor(entry.Id), StringComparer.OrdinalIgnoreCase)
            .ToDictionary(group => group.Key, group => group.Count(), StringComparer.OrdinalIgnoreCase);
        DictionaryEntry[] result = dictionary.Entries
            .Where(entry => keyCounts[lexicon.LexicalKeyFor(entry.Id)] == 1)
            .Take(count)
            .ToArray();
        Require(result.Length == count, $"could not find {count} unique lexical entries for gap remediation test");
        return result;
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

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException("Context R4d gap remediation self-test failed: " + message);
    }
}
