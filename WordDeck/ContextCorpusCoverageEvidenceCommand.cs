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
            ContextCorpusCoverageEvidenceDocument evidence = ContextCorpusCoverageEvidenceBuilder.Build(
                databasePath,
                dictionary,
                new ContextCorpusCoverageMeasurementRequest(
                    ContextCorpusKind.RealCorpus,
                    expectedSha256,
                    expectedPackId));
            ContextStableIdentityCoverageEvidenceDocument stableEvidence =
                ContextStableIdentityCoverageEvidenceBuilder.Build(evidence, dictionary);
            ContextCorpusGapRemediationDocument remediation = ContextCorpusGapRemediationBuilder.Build(evidence, dictionary);

            Directory.CreateDirectory(Path.GetDirectoryName(outputPath) ?? ".");
            var utf8NoBom = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);
            File.WriteAllText(outputPath, evidence.ToCanonicalJson(), utf8NoBom);
            string outputStem = Path.Combine(
                Path.GetDirectoryName(outputPath) ?? ".",
                Path.GetFileNameWithoutExtension(outputPath));
            string stableJsonPath = outputStem + ".stable-identities.json";
            string gapJsonPath = outputStem + ".gaps.json";
            string gapTsvPath = outputStem + ".gaps.tsv";
            File.WriteAllText(stableJsonPath, stableEvidence.ToCanonicalJson(), utf8NoBom);
            File.WriteAllText(gapJsonPath, remediation.ToCanonicalJson(), utf8NoBom);
            File.WriteAllText(gapTsvPath, ContextCorpusGapRemediationBuilder.ToTsv(remediation), utf8NoBom);

            ContextCorpusCoverageEvidencePayload payload = evidence.Payload;
            ContextStableIdentityCoverageEvidencePayload stable = stableEvidence.Payload;
            ContextCorpusGapRemediationPayload gaps = remediation.Payload;
            Console.WriteLine(
                $"Context real-corpus PHYSICAL-FORM coverage evidence PASS: pack={payload.SourceId}; sentences={payload.SentenceCount}; " +
                $"one={payload.OneTarget.CoveredEntryCount}/{payload.OneTarget.ScopeEntryCount}; " +
                $"two={payload.TwoTarget.CoveredEntryCount}/{payload.TwoTarget.ScopeEntryCount}; " +
                $"three={payload.ThreeTarget.CoveredEntryCount}/{payload.ThreeTarget.ScopeEntryCount}; " +
                $"database_sha256={payload.DatabaseSha256}; evidence_sha256={evidence.EvidenceDigestSha256}");
            Console.WriteLine(
                $"Context conservative STABLE-ID coverage evidence PASS: " +
                $"one={stable.OneTarget.ResolvedStableCoveredEntryCount}/{stable.OneTarget.ScopeEntryCount}; " +
                $"two={stable.TwoTarget.ResolvedStableCoveredEntryCount}/{stable.TwoTarget.ScopeEntryCount}; " +
                $"three={stable.ThreeTarget.ResolvedStableCoveredEntryCount}/{stable.ThreeTarget.ScopeEntryCount}; " +
                $"unresolved_homograph_ids={stable.OneTarget.UnresolvedAmbiguousEntryCount}; " +
                $"stable_evidence_sha256={stableEvidence.EvidenceDigestSha256}");
            Console.WriteLine(
                $"Context corpus physical-form remediation plan PASS: missing_one={gaps.MissingOneTargetCount}; " +
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
