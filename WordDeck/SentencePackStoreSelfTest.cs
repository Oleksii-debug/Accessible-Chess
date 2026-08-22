namespace WordDeck;

internal static class SentencePackStoreSelfTest
{
    public static void Run()
    {
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck-sentence-store-r3-{Guid.NewGuid():N}");
        try
        {
            Directory.CreateDirectory(root);
            string source = Path.Combine(root, "source.json");
            SentencePack pack = BuildPack("test-pack-one");
            File.WriteAllText(source, SentencePackJson.Serialize(pack));

            var store = new SentencePackStore(root);
            InstalledSentencePack installed = store.Import(source);
            Require(File.Exists(installed.Path), "Imported SentencePack was not persisted.");
            Require(installed.Path.EndsWith(".json.gz", StringComparison.OrdinalIgnoreCase), "Imported SentencePack was not compressed.");
            Require(installed.PackId == pack.PackId && installed.SentenceCount == 1, "Imported SentencePack metadata changed.");
            Require(installed.PortablePack?.Sentences.Count == 1, "Fresh import did not retain validated portable pack for current call.");
            Require(installed.SqlitePath is not null && File.Exists(installed.SqlitePath), "Imported SentencePack did not build SQLite companion.");
            Require(installed.Corpus is SentencePackSqliteCorpus, "Imported SentencePack did not expose SQLite runtime corpus.");
            Require(installed.Corpus.LookupAllTargets(new[] { "ox-learn", "ox-words" }).Single().Id == "sentence-1", "SQLite two-target lookup failed after import.");

            string manifestPath = Path.Combine(store.DirectoryPath, pack.PackId + ".installed.json");
            Require(File.Exists(manifestPath), "SentencePack activation manifest was not created.");
            SentencePack compressedRoundTrip = SentencePackIo.Read(installed.Path);
            Require(compressedRoundTrip.PackId == pack.PackId, "Compressed SentencePack did not round-trip.");

            IReadOnlyList<InstalledSentencePack> loaded = store.LoadInstalled();
            Require(loaded.Count == 1, "Installed SentencePack did not reload.");
            Require(loaded[0].PortablePack is null, "Normal installed discovery eagerly loaded the portable SentencePack.");
            Require(loaded[0].Corpus.LookupByEntryId("ox-learn").Single().Id == "sentence-1", "Reloaded SQLite lookup failed.");

            string legacyPath = Path.Combine(store.DirectoryPath, "legacy-pack.json");
            File.WriteAllText(legacyPath, SentencePackJson.Serialize(BuildPack("legacy-pack", "legacy-sentence")));
            InstalledSentencePack? legacy = store.Find("legacy-pack");
            Require(legacy?.PortablePack?.Sentences.Single().Id == "legacy-sentence", "Legacy uncompressed SentencePack compatibility was lost.");

            SentencePack orphan = BuildPack(pack.PackId, "orphan-sentence");
            string orphanPortable = Path.Combine(store.DirectoryPath, pack.PackId + ".orphan.json.gz");
            SentencePackIo.WriteGZip(orphanPortable, orphan);
            string orphanSqlite = Path.Combine(store.DirectoryPath, pack.PackId + ".orphan.sqlite");
            SentencePackSqlitePrototype.Build(orphanSqlite, orphan);
            Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
            Require(store.Find(pack.PackId)?.Corpus.LookupByEntryId("ox-learn").Single().Id == "sentence-1",
                "Uncommitted orphan SentencePack generation became active.");

            string replacementSource = Path.Combine(root, "replacement.json.gz");
            SentencePack replacement = BuildPack(pack.PackId, "sentence-2");
            SentencePackIo.WriteGZip(replacementSource, replacement);
            InstalledSentencePack replaced = store.Import(replacementSource);
            Require(replaced.Path != installed.Path, "Replacement reused previous portable generation path.");
            Require(replaced.SqlitePath != installed.SqlitePath, "Replacement reused previous SQLite generation path.");
            Require(store.Find(pack.PackId)?.Corpus.LookupByEntryId("ox-learn").Single().Id == "sentence-2",
                "Committed replacement generation did not become active.");

            string manifestBackup = Path.Combine(store.DirectoryPath, pack.PackId + ".installed.backup.json");
            Require(File.Exists(manifestBackup), "Replacement did not preserve previous committed manifest.");

            string failedSource = Path.Combine(root, "failed-replacement.json.gz");
            SentencePackIo.WriteGZip(failedSource, BuildPack(pack.PackId, "sentence-3"));
            bool injected = false;
            var failingStore = new SentencePackStore(root, checkpoint =>
            {
                if (checkpoint == "before-manifest-commit")
                {
                    injected = true;
                    throw new IOException("Injected failure before SentencePack manifest activation.");
                }
            });
            bool failed = false;
            try { _ = failingStore.Import(failedSource); }
            catch (IOException) { failed = true; }
            Require(injected && failed, "SentencePack pre-commit failure injection did not execute.");
            Require(store.Find(pack.PackId)?.Corpus.LookupByEntryId("ox-learn").Single().Id == "sentence-2",
                "Failed replacement changed active SentencePack before manifest commit.");

            File.WriteAllText(manifestPath, "{ broken manifest");
            Require(store.Find(pack.PackId)?.Corpus.LookupByEntryId("ox-learn").Single().Id == "sentence-1",
                "Corrupt current manifest did not recover previous committed generation.");

            TestSafePackIds();
            TestCaseInsensitiveCollision(root, pack.PackId);
            TestMixedLicenseRejected(root);
        }
        finally
        {
            try
            {
                Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
                if (Directory.Exists(root)) Directory.Delete(root, true);
            }
            catch { }
        }
    }

    private static void TestSafePackIds()
    {
        Require(SentencePackStore.SafeFileName("tatoeba-en-uk-20260821") == "tatoeba-en-uk-20260821", "Normal SentencePack id changed during safe-name validation.");
        Require(SentencePackStore.SafeFileName("український-пакет") == "український-пакет", "Unicode SentencePack id was not preserved.");
        foreach (string unsafeId in new[] { "../escape", "..\\escape", "CON", "NUL.json", "COM1", "LPT9.txt", "pack.", " pack", "pack " })
        {
            bool rejected = false;
            try { SentencePackStore.SafeFileName(unsafeId); } catch (InvalidDataException) { rejected = true; }
            Require(rejected, $"Unsafe Windows/path SentencePack id was accepted: {unsafeId}");
        }
    }

    private static void TestCaseInsensitiveCollision(string root, string existingId)
    {
        string source = Path.Combine(root, "case-collision.json");
        SentencePack collision = BuildPack(existingId.ToUpperInvariant(), "case-sentence");
        File.WriteAllText(source, SentencePackJson.Serialize(collision));
        bool rejected = false;
        try { _ = new SentencePackStore(root).Import(source); }
        catch (InvalidDataException ex) { rejected = ex.Message.Contains("collid", StringComparison.OrdinalIgnoreCase); }
        Require(rejected, "Case-insensitive Windows SentencePack identity collision was accepted.");
    }

    private static void TestMixedLicenseRejected(string root)
    {
        SentencePack mixed = BuildPack("mixed-license-pack", "mixed-sentence", sentenceLicense: "CC-BY-4.0");
        string source = Path.Combine(root, "mixed-license.json");
        File.WriteAllText(source, SentencePackJson.Serialize(mixed));
        bool rejected = false;
        try { _ = new SentencePackStore(root).Import(source); }
        catch (InvalidDataException ex) { rejected = ex.Message.Contains("license", StringComparison.OrdinalIgnoreCase); }
        Require(rejected, "Mixed-license SentencePack was accepted without an explicit release format for mixed attribution.");
    }

    private static SentencePack BuildPack(string packId, string sentenceId = "sentence-1", string sentenceLicense = "CC0-1.0")
    {
        const string english = "We learn words";
        var pack = new SentencePack
        {
            PackId = packId,
            Provenance = "Synthetic SentencePack store regression data",
            License = "CC0-1.0",
            Sentences = new List<SentenceRecord>
            {
                new()
                {
                    Id = sentenceId,
                    English = english,
                    Ukrainian = "Ми вивчаємо слова",
                    Source = "self-test",
                    License = sentenceLicense,
                    Tokens = SentenceTokenizer.Tokenize(english).ToList(),
                    Lemmas = new List<string> { "we", "learn", "words" },
                    TargetEntryIds = new List<string> { "ox-learn", "ox-words" },
                    EntryLevels = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
                    {
                        ["ox-learn"] = "A1",
                        ["ox-words"] = "A1"
                    },
                    DifficultyLevel = "A1"
                }
            }
        };
        pack.Validate();
        return pack;
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }
}
