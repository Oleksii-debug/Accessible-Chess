namespace WordDeck;

internal static class SentencePackStoreSelfTest
{
    public static void Run()
    {
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck-sentence-store-{Guid.NewGuid():N}");
        try
        {
            Directory.CreateDirectory(root);
            string source = Path.Combine(root, "source.json");
            SentencePack pack = BuildPack("test-pack-one");
            File.WriteAllText(source, SentencePackJson.Serialize(pack));

            var store = new SentencePackStore(root);
            InstalledSentencePack installed = store.Import(source);
            Require(File.Exists(installed.Path), "Imported SentencePack was not persisted.");
            Require(installed.Path.EndsWith(".json.gz", StringComparison.OrdinalIgnoreCase), "Imported SentencePack was not stored in compressed interchange form.");
            Require(installed.PackId == pack.PackId, "Imported SentencePack id changed.");
            Require(installed.SentenceCount == 1, "Imported SentencePack sentence count changed.");
            Require(installed.PortablePack?.Sentences.Count == 1, "Fresh import should retain the already validated portable pack for the current call only.");
            Require(installed.SqlitePath is not null && File.Exists(installed.SqlitePath), "Imported SentencePack did not build its SQLite runtime companion.");
            Require(installed.Corpus is SentencePackSqliteCorpus, "Imported SentencePack did not expose the SQLite runtime corpus.");
            Require(installed.Corpus.LookupAllTargets(new[] { "ox-learn", "ox-words" }).Single().Id == "sentence-1", "SQLite runtime corpus two-target lookup failed after import.");
            string manifestPath = Path.Combine(store.DirectoryPath, pack.PackId + ".installed.json");
            Require(File.Exists(manifestPath), "SentencePack generation commit manifest was not created.");

            SentencePack compressedRoundTrip = SentencePackIo.Read(installed.Path);
            Require(compressedRoundTrip.PackId == pack.PackId, "Compressed SentencePack did not round-trip.");

            IReadOnlyList<InstalledSentencePack> loaded = store.LoadInstalled();
            Require(loaded.Count == 1, "Installed SentencePack did not reload.");
            Require(loaded[0].PackId == pack.PackId && loaded[0].SentenceCount == 1, "Installed SentencePack metadata did not reload from committed SQLite generation.");
            Require(loaded[0].PortablePack is null, "Normal installed-pack discovery eagerly materialized the portable SentencePack.");
            Require(loaded[0].Corpus is SentencePackSqliteCorpus, "Reloaded installed SentencePack did not discover its committed SQLite generation.");
            Require(loaded[0].Corpus.LookupByEntryId("ox-learn").Single().Id == "sentence-1", "Reloaded SQLite corpus lookup failed.");

            string legacyPath = Path.Combine(store.DirectoryPath, "legacy-pack.json");
            File.WriteAllText(legacyPath, SentencePackJson.Serialize(BuildPack("legacy-pack", "legacy-sentence")));
            InstalledSentencePack? legacy = store.Find("legacy-pack");
            Require(legacy?.PortablePack?.Sentences.Single().Id == "legacy-sentence", "Legacy uncompressed SentencePack compatibility was lost.");
            Require(legacy?.Corpus.LookupByEntryId("ox-learn").Single().Id == "legacy-sentence", "Legacy in-memory corpus fallback failed.");

            // An orphan generation without a manifest must never supersede the committed pack.
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
            Require(replaced.Path != installed.Path, "SentencePack replacement did not create a new immutable generation.");
            Require(replaced.SqlitePath != installed.SqlitePath, "SentencePack replacement reused the previous SQLite generation path.");
            Require(store.Find(pack.PackId)?.Corpus.LookupByEntryId("ox-learn").Single().Id == "sentence-2",
                "Committed replacement generation did not become active.");

            string manifestBackup = Path.Combine(store.DirectoryPath, pack.PackId + ".installed.backup.json");
            Require(File.Exists(manifestBackup), "Replacing an installed SentencePack did not preserve the previous committed manifest.");
            File.WriteAllText(manifestPath, "{ broken manifest");
            Require(store.Find(pack.PackId)?.Corpus.LookupByEntryId("ox-learn").Single().Id == "sentence-1",
                "Corrupt current manifest did not recover the previous committed generation.");

            TestSafePackIds();
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

    private static SentencePack BuildPack(string packId, string sentenceId = "sentence-1")
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
                    License = "CC0-1.0",
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
