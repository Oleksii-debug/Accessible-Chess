using System.Runtime.CompilerServices;
using System.Text;

namespace WordDeck;

internal static class ContextCorpusCoverageEvidenceCommandBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        string[] args = Environment.GetCommandLineArgs();
        int commandIndex = Array.FindIndex(args, arg => arg.Equals("--measure-context-coverage", StringComparison.OrdinalIgnoreCase));
        if (commandIndex < 0)
            return;

        try
        {
            if (args.Length <= commandIndex + 4)
                throw new ArgumentException(
                    "Usage: --measure-context-coverage <sentencepack.sqlite> <evidence.json> <expected-sha256> <expected-pack-id>");

            string databasePath = args[commandIndex + 1];
            string outputPath = Path.GetFullPath(args[commandIndex + 2]);
            string expectedSha256 = args[commandIndex + 3];
            string expectedPackId = args[commandIndex + 4];
            if (args.Length != commandIndex + 5)
                throw new ArgumentException("Unexpected extra arguments after the exact expected PackId.");

            DictionaryPackage dictionary = DictionaryLoader.LoadEmbeddedOxford();
            ContextCorpusCoverageEvidenceDocument stableTagEvidence = ContextCorpusCoverageEvidenceBuilder.Build(
                databasePath,
                dictionary,
                new ContextCorpusCoverageMeasurementRequest(
                    ContextCorpusKind.RealCorpus,
                    expectedSha256,
                    expectedPackId));
            ContextPhysicalLexicalCoverageEvidenceDocument physicalEvidence =
                ContextPhysicalLexicalCoverageEvidenceBuilder.Build(stableTagEvidence, dictionary);
            ContextStableIdentityCoverageEvidenceDocument stableIdentityEvidence =
                ContextStableIdentityCoverageEvidenceBuilder.Build(stableTagEvidence, dictionary);
            ContextCorpusGapRemediationDocument remediation = ContextCorpusGapRemediationBuilder.Build(stableTagEvidence, dictionary);

            Directory.CreateDirectory(Path.GetDirectoryName(outputPath) ?? ".");
            var utf8NoBom = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);
            File.WriteAllText(outputPath, stableTagEvidence.ToCanonicalJson(), utf8NoBom);
            string outputStem = Path.Combine(
                Path.GetDirectoryName(outputPath) ?? ".",
                Path.GetFileNameWithoutExtension(outputPath));
            string physicalJsonPath = outputStem + ".physical.json";
            string stableIdentityJsonPath = outputStem + ".stable-identity.json";
            string gapJsonPath = outputStem + ".gaps.json";
            string gapTsvPath = outputStem + ".gaps.tsv";
            File.WriteAllText(physicalJsonPath, physicalEvidence.ToCanonicalJson(), utf8NoBom);
            File.WriteAllText(stableIdentityJsonPath, stableIdentityEvidence.ToCanonicalJson(), utf8NoBom);
            File.WriteAllText(gapJsonPath, remediation.ToCanonicalJson(), utf8NoBom);
            File.WriteAllText(gapTsvPath, ContextCorpusGapRemediationBuilder.ToTsv(remediation), utf8NoBom);

            ContextCorpusCoverageEvidencePayload raw = stableTagEvidence.Payload;
            ContextPhysicalLexicalCoverageEvidencePayload physical = physicalEvidence.Payload;
            ContextStableIdentityCoverageEvidencePayload stable = stableIdentityEvidence.Payload;
            ContextCorpusGapRemediationPayload gaps = remediation.Payload;
            Console.WriteLine(
                $"Context stable-tag participation evidence PASS: pack={raw.SourceId}; sentences={raw.SentenceCount}; " +
                $"one={raw.OneTarget.CoveredEntryCount}/{raw.OneTarget.ScopeEntryCount}; " +
                $"two={raw.TwoTarget.CoveredEntryCount}/{raw.TwoTarget.ScopeEntryCount}; " +
                $"three={raw.ThreeTarget.CoveredEntryCount}/{raw.ThreeTarget.ScopeEntryCount}; " +
                $"database_sha256={raw.DatabaseSha256}; evidence_sha256={stableTagEvidence.EvidenceDigestSha256}");
            Console.WriteLine(
                $"Context physical lexical-form coverage PASS: forms={physical.UniqueLexicalFormCount}; " +
                $"one={physical.OneTarget.CoveredLexicalFormCount}/{physical.OneTarget.LexicalFormCount}; " +
                $"two={physical.TwoTarget.CoveredLexicalFormCount}/{physical.TwoTarget.LexicalFormCount}; " +
                $"three={physical.ThreeTarget.CoveredLexicalFormCount}/{physical.ThreeTarget.LexicalFormCount}; " +
                $"ambiguous_forms={physical.AmbiguousLexicalFormCount}");
            Console.WriteLine(
                $"Context conservative stable-ID coverage PASS: " +
                $"one_resolved={stable.OneTarget.ResolvedStableCoveredEntryCount}/{stable.OneTarget.ScopeEntryCount}; " +
                $"one_unresolved_ambiguous={stable.OneTarget.UnresolvedAmbiguousEntryCount}; " +
                $"two_resolved={stable.TwoTarget.ResolvedStableCoveredEntryCount}/{stable.TwoTarget.ScopeEntryCount}; " +
                $"three_resolved={stable.ThreeTarget.ResolvedStableCoveredEntryCount}/{stable.ThreeTarget.ScopeEntryCount}; " +
                $"evidence_sha256={stableIdentityEvidence.EvidenceDigestSha256}");
            Console.WriteLine(
                $"Context corpus remediation plan PASS: missing_one={gaps.MissingOneTargetCount}; " +
                $"missing_pair_only={gaps.MissingNaturalPairOnlyCount}; " +
                $"missing_triple_only={gaps.MissingNaturalTripleOnlyCount}; " +
                $"triple_covered={gaps.NaturalTripleCoveredCount}; plan_sha256={remediation.PlanDigestSha256}");
            Environment.Exit(0);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("Context coverage evidence command failed: " + ex.Message);
            Environment.Exit(2);
        }
    }
}
