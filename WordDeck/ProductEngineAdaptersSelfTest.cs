using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class ProductEngineAdaptersSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            ProductEngineAdaptersSelfTest.Run();
    }
}

internal static class ProductEngineAdaptersSelfTest
{
    public static void Run()
    {
        TestUnifiedProfilePortRoundTrip();
        TestSentencePackDescriptorProjection();
        Console.WriteLine("WordDeck R4b Product Engine adapters passed: UI-independent unified profile transfer and validated SentencePack release metadata projection verified.");
    }

    private static void TestUnifiedProfilePortRoundTrip()
    {
        string root = Path.Combine(Path.GetTempPath(), "WordDeck-R4b-product-profile-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            DictionaryPackage package = DictionaryLoader.LoadEmbeddedOxford();
            var appStore = new AppStateStore(root);
            AppState state = AppStateStore.Normalize(new AppState
            {
                ActiveDictionaryId = package.Id,
                AutoPlayPronunciationOnCardChange = true
            });
            appStore.Save(state);

            var profiles = new UnifiedProfileService(appStore, root);
            var port = new LocalUnifiedProfileTransferPort(
                profiles,
                state,
                package.Entries.Select(entry => entry.Id),
                new[] { package.Id });

            string exportPath = Path.Combine(root, "Exports", "profile v3 тест.json");
            port.ExportAsync(new ProfileExportCommand(exportPath)).AsTask().GetAwaiter().GetResult();
            Require(File.Exists(exportPath), "Product profile port did not create the requested export.");

            state.AutoPlayPronunciationOnCardChange = false;
            appStore.Save(state);
            ProfileTransferResultDto imported = port.ImportAsync(new ProfileImportCommand(exportPath)).AsTask().GetAwaiter().GetResult();
            Require(imported.SourceSchemaVersion == UnifiedProfileService.CurrentProfileSchemaVersion, "Product profile port did not report unified schema v3.");
            Require(imported.RecallTransferred && imported.SpellingTransferred && imported.SentenceTransferred, "Product profile port did not report all unified learning domains as transferred.");
            Require(state.AutoPlayPronunciationOnCardChange, "Product profile port round-trip did not restore Recall/application preference state.");
            Require(imported.QuarantinedStableIds.Count == 0, "Clean unified product profile unexpectedly produced quarantined stable IDs.");

            using var cancelled = new CancellationTokenSource();
            cancelled.Cancel();
            bool cancellationObserved = false;
            try { port.ExportAsync(new ProfileExportCommand(Path.Combine(root, "cancelled.json")), cancelled.Token).AsTask().GetAwaiter().GetResult(); }
            catch (OperationCanceledException) { cancellationObserved = true; }
            Require(cancellationObserved && !File.Exists(Path.Combine(root, "cancelled.json")), "Cancelled profile export wrote data or ignored cancellation.");
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    private static void TestSentencePackDescriptorProjection()
    {
        var record = new SentenceRecord
        {
            Id = "sentence-r4b-1",
            English = "I learn",
            Ukrainian = "Я вчуся",
            Source = "verified local fixture",
            License = "CC0-1.0",
            Tokens = SentenceTokenizer.Tokenize("I learn").ToList(),
            Lemmas = SentenceTokenizer.Tokenize("I learn").ToList(),
            TargetEntryIds = new() { "entry-r4b" },
            EntryLevels = new(StringComparer.OrdinalIgnoreCase) { ["entry-r4b"] = "A1" },
            DifficultyLevel = "A1",
            OffListTokenCount = 0
        };
        var pack = new SentencePack
        {
            PackId = "fixture-r4b",
            Provenance = "verified local fixture for product descriptor contract",
            License = "CC0-1.0",
            Sentences = new() { record }
        };

        SentencePackProductDescriptor descriptor = SentencePackProductDescriptorFactory.FromValidatedPortablePack(pack);
        Require(descriptor.PackId == pack.PackId && descriptor.SentenceCount == 1, "SentencePack descriptor changed pack identity/count.");
        Require(descriptor.SourceIdentity.StartsWith("sha256:", StringComparison.Ordinal) && descriptor.SourceIdentity.Length == 71, "SentencePack descriptor did not expose a bounded logical source identity.");
        Require(descriptor.DerivativeIdentity == descriptor.SourceIdentity, "Descriptor without a separate derivative did not use its logical identity consistently.");

        bool rejectedSynthetic = false;
        try { _ = SentencePackProductDescriptorFactory.FromValidatedPortablePack(pack, isSynthetic: true); }
        catch (InvalidDataException) { rejectedSynthetic = true; }
        Require(rejectedSynthetic, "Synthetic SentencePack was allowed to masquerade as release-ready product data.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
}
