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
            ContextPhysicalLexicalCoverageEvidenceDocument physicalFormEvidence =
                ContextPhysicalLexicalCoverageEvidenceBuilder.Build(stableTagEvidence, dictionary);
            ContextStableIdentityCoverageEvidenceDocument stableIdentityEvidence =
                ContextStableIdentityCoverageEvidenceBuilder.Build(stableTagEvidence, physicalFormEvidence, dictionary);
            ContextCorpusGapRemediationDocument legacyRemediation =
                ContextCorpusGapRemediationBuilder.Build(stableTagEvidence, dictionary);

            Directory.CreateDirectory(Path.GetDirectoryName(outputPath) ?? ".");
            var utf8NoBom = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);
            File.WriteAllText(outputPath, stableTagEvidence.ToCanonicalJson(), utf8NoBom);
            string outputStem = Path.Combine(
                Path.GetDirectoryName(outputPath) ?? ".",
                Path.GetFileNameWithoutExtension(outputPath));
            string physicalFormsJsonPath = outputStem + ".physical-forms.json";
            string stableJsonPath = outputStem + ".stable-identities.json";
            string gapJsonPath = outputStem + ".gaps.json";
            string gapTsvPath = outputStem + ".gaps.tsv";
            File.WriteAllText(physicalFormsJsonPath, physicalFormEvidence.ToCanonicalJson(), utf8NoBom);
            File.WriteAllText(stableJsonPath, stableIdentityEvidence.ToCanonicalJson(), utf8NoBom);
            File.WriteAllText(gapJsonPath, legacyRemediation.ToCanonicalJson(), utf8NoBom);
            File.WriteAllText(gapTsvPath, ContextCorpusGapRemediationBuilder.ToTsv(legacyRemediation), utf8NoBom);

            ContextCorpusCoverageEvidencePayload raw = stableTagEvidence.Payload;
            ContextPhysicalLexicalCoverageEvidencePayload physical = physicalFormEvidence.Payload;
            ContextStableIdentityCoverageEvidencePayload stable = stableIdentityEvidence.Payload;
            ContextCorpusGapRemediationPayload legacyGaps = legacyRemediation.Payload;

            Console.WriteLine(
                $"Context real-corpus UNIQUE PHYSICAL-FORM coverage PASS: pack={physical.SourceId}; sentences={physical.SentenceCount}; " +
                $"forms={physical.UniqueLexicalFormCount}; ambiguous_forms={physical.AmbiguousLexicalFormCount}; " +
                $"one={physical.OneTarget.CoveredLexicalFormCount}/{physical.OneTarget.LexicalFormCount}; " +
                $"two={physical.TwoTarget.CoveredLexicalFormCount}/{physical.TwoTarget.LexicalFormCount}; " +
                $"three={physical.ThreeTarget.CoveredLexicalFormCount}/{physical.ThreeTarget.LexicalFormCount}; " +
                $"physical_evidence_sha256={physicalFormEvidence.EvidenceDigestSha256}");
            Console.WriteLine(
                $"Context conservative STABLE-ID/POS-SENSE coverage PASS: " +
                $"one={stable.OneTarget.ResolvedStableCoveredEntryCount}/{stable.OneTarget.ScopeEntryCount}; " +
                $"two={stable.TwoTarget.ResolvedStableCoveredEntryCount}/{stable.TwoTarget.ScopeEntryCount}; " +
                $"three={stable.ThreeTarget.ResolvedStableCoveredEntryCount}/{stable.ThreeTarget.ScopeEntryCount}; " +
                $"unresolved_homograph_ids={stable.OneTarget.UnresolvedAmbiguousEntryCount}; " +
                $"stable_evidence_sha256={stableIdentityEvidence.EvidenceDigestSha256}");
            Console.WriteLine(
                $"Context historical STABLE-TAG participation evidence (compatibility only; do not call this sense coverage): " +
                $"one={raw.OneTarget.CoveredEntryCount}/{raw.OneTarget.ScopeEntryCount}; " +
                $"two={raw.TwoTarget.CoveredEntryCount}/{raw.TwoTarget.ScopeEntryCount}; " +
                $"three={raw.ThreeTarget.CoveredEntryCount}/{raw.ThreeTarget.ScopeEntryCount}; " +
                $"database_sha256={raw.DatabaseSha256}; evidence_sha256={stableTagEvidence.EvidenceDigestSha256}");
            Console.WriteLine(
                $"Context evidence chain PASS: stable-tag={stable.StableTagEvidenceSha256}; " +
                $"physical-form={stable.PhysicalFormEvidenceSha256}; stable-identity={stableIdentityEvidence.EvidenceDigestSha256}");
            Console.WriteLine(
                $"Context historical stable-tag gap plan (compatibility only): missing_one={legacyGaps.MissingOneTargetCount}; " +
                $"missing_pair_only={legacyGaps.MissingNaturalPairOnlyCount}; " +
                $"missing_triple_only={legacyGaps.MissingNaturalTripleOnlyCount}; " +
                $"triple_covered={legacyGaps.NaturalTripleCoveredCount}; plan_sha256={legacyRemediation.PlanDigestSha256}. " +
                $"Authoritative physical gaps are the uncovered lexical keys in *.physical-forms.json; stable-ID ambiguity/gaps are in *.stable-identities.json.");
            Environment.Exit(0);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("Context coverage evidence command failed: " + ex.Message);
            Environment.Exit(2);
        }
    }
}
