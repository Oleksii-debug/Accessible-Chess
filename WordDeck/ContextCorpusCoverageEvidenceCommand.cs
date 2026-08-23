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

            Directory.CreateDirectory(Path.GetDirectoryName(outputPath) ?? ".");
            File.WriteAllText(outputPath, evidence.ToCanonicalJson(), new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));

            ContextCorpusCoverageEvidencePayload payload = evidence.Payload;
            Console.WriteLine(
                $"Context real-corpus coverage evidence PASS: pack={payload.SourceId}; sentences={payload.SentenceCount}; " +
                $"one={payload.OneTarget.CoveredEntryCount}/{payload.OneTarget.ScopeEntryCount}; " +
                $"two={payload.TwoTarget.CoveredEntryCount}/{payload.TwoTarget.ScopeEntryCount}; " +
                $"three={payload.ThreeTarget.CoveredEntryCount}/{payload.ThreeTarget.ScopeEntryCount}; " +
                $"database_sha256={payload.DatabaseSha256}; evidence_sha256={evidence.EvidenceDigestSha256}");
            Environment.Exit(0);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("Context coverage evidence command failed: " + ex.Message);
            Environment.Exit(2);
        }
    }
}
