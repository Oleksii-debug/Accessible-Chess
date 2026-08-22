namespace WordDeck;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Length > 0 && args[0].Equals("--build-tatoeba-sentence-pack", StringComparison.OrdinalIgnoreCase))
            return BuildTatoebaSentencePack(args);

        if (args.Length > 0 && args[0].Equals("--measure-sentence-pack", StringComparison.OrdinalIgnoreCase))
            return SentencePackDiagnostics.Run(args);

        if (args.Length > 0 && args[0].Equals("--export-oxford5000-audio-source", StringComparison.OrdinalIgnoreCase))
            return ExportOxford5000AudioSource(args);

        if (args.Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
        {
            try
            {
                StudyScopeSelfTest.Run();
                UserDataSelfTest.Run();
                ReleaseRegressionSelfTest.Run();
                ReleaseStateFailureSelfTest.Run();
                FullV1ProfileSelfTest.Run();
                SpellingSelfTest.Run();
                SentenceCoachSelfTest.Run();
                SentencePackStoreSelfTest.Run();
                TatoebaSentencePackSelfTest.Run();
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"WordDeck extended self-test FAILED: {ex}");
                return 1;
            }
            return SelfTest.Run();
        }

        ApplicationConfiguration.Initialize();
        AccessibilityAnnouncer.Install();

        var main = new MainForm();
        TrainingEntryPoints.Install(main);
        Application.Run(main);
        return 0;
    }

    private static int ExportOxford5000AudioSource(string[] args)
    {
        if (args.Length != 2)
        {
            Console.Error.WriteLine("Usage: WordDeck.exe --export-oxford5000-audio-source <output.tsv>");
            return 2;
        }

        try
        {
            string outputPath = Path.GetFullPath(args[1]);
            IReadOnlyList<DictionaryEntry> additions = ReviewedOxford5000Bootstrap.BuildEntriesForTest();
            if (additions.Count != ReviewedOxford5000Bootstrap.ExpectedCanonicalRows)
                throw new InvalidDataException($"Expected {ReviewedOxford5000Bootstrap.ExpectedCanonicalRows} verified Oxford 5000 additions, got {additions.Count}.");

            string? directory = Path.GetDirectoryName(outputPath);
            if (!string.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);

            using var writer = new StreamWriter(outputPath, false, new System.Text.UTF8Encoding(false));
            writer.WriteLine("entry_id\tlevel\tsource");
            var ids = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (DictionaryEntry entry in additions)
            {
                if (!ids.Add(entry.Id))
                    throw new InvalidDataException($"Duplicate Oxford 5000 audio stable ID: {entry.Id}.");
                if (string.IsNullOrWhiteSpace(entry.Source) || string.IsNullOrWhiteSpace(entry.Level))
                    throw new InvalidDataException($"Oxford 5000 audio source contains incomplete entry {entry.Id}.");
                if (entry.Source.Contains('\t') || entry.Source.Contains('\r') || entry.Source.Contains('\n'))
                    throw new InvalidDataException($"Oxford 5000 audio source is not TSV-safe: {entry.Id}.");
                writer.Write(entry.Id);
                writer.Write('\t');
                writer.Write(entry.Level);
                writer.Write('\t');
                writer.WriteLine(entry.Source);
            }

            Console.WriteLine($"Oxford 5000 verified audio source written: {outputPath}; rows={additions.Count}.");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"Oxford 5000 audio-source export FAILED: {ex.Message}");
            return 1;
        }
    }

    private static int BuildTatoebaSentencePack(string[] args)
    {
        if (args.Length is < 3 or > 4)
        {
            Console.Error.WriteLine("Usage: WordDeck.exe --build-tatoeba-sentence-pack <en-uk-pairs.tsv> <output.json> [pack-id]");
            return 2;
        }

        try
        {
            string inputPath = Path.GetFullPath(args[1]);
            string outputPath = Path.GetFullPath(args[2]);
            string packId = args.Length == 4 ? args[3].Trim() : $"tatoeba-en-uk-{DateTime.UtcNow:yyyyMMdd}";
            if (!File.Exists(inputPath))
                throw new FileNotFoundException("Tatoeba EN-UA pair export was not found.", inputPath);

            TatoebaImportMetadata metadata = TatoebaImportProvenance.Resolve(inputPath);
            DictionaryPackage dictionary = DictionaryLoader.LoadEmbeddedOxford();
            IEnumerable<TatoebaSentencePair> pairs = TatoebaPairTsv.ParseLines(File.ReadLines(inputPath));
            (SentencePack pack, SentencePackBuildReport report) = TatoebaSentencePackBuilder.Build(
                pairs, dictionary, packId, metadata.Provenance, metadata.License);

            string? directory = Path.GetDirectoryName(outputPath);
            if (!string.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);
            File.WriteAllText(outputPath, SentencePackJson.Serialize(pack));

            Console.WriteLine($"SentencePack written: {outputPath}");
            Console.WriteLine($"License metadata: {metadata.License}; verified CC0 manifest: {metadata.VerifiedCc0Manifest}; verified attributed CC-BY manifest: {metadata.VerifiedAttributedCcByManifest}.");
            Console.WriteLine($"Input pairs: {report.InputPairs}; accepted: {report.AcceptedPairs}; rejected: {report.RejectedPairs}; indexed entry references: {report.IndexedEntryIds}; off-list tokens: {report.OffListTokens}.");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"SentencePack build FAILED: {ex.Message}");
            return 1;
        }
    }
}
