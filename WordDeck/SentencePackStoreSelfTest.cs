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
            Require(installed.Pack.PackId == pack.PackId, "Imported SentencePack id changed.");
            Require(installed.SqlitePath is not null && File.Exists(installed.SqlitePath), "Imported SentencePack did not build its SQLite runtime companion.");
            Require(installed.Corpus is SentencePackSqliteCorpus, "Imported SentencePack did not expose the SQLite runtime corpus.");
            Require(installed.Corpus.SentenceCount == 1, "SQLite runtime corpus sentence count is incorrect.");
            Require(installed.Corpus.LookupAllTargets(new[] { "ox-learn", "ox-words" }).Single().Id == "sentence-1", "SQLite runtime corpus two-target lookup failed after import.");

            SentencePack compressedRoundTrip = SentencePackIo.Read(installed.Path);
            Require(compressedRoundTrip.PackId == pack.PackId, "Compressed SentencePack did not round-trip.");

            IReadOnlyList<InstalledSentencePack> loaded = store.LoadInstalled();
            Require(loaded.Count == 1 && loaded[0].Pack.Sentences.Count == 1, "Installed SentencePack did not reload.");
            Require(loaded[0].Corpus is SentencePackSqliteCorpus, "Reloaded installed SentencePack did not discover its valid SQLite companion.");

            string legacyPath = Path.Combine(store.DirectoryPath, "legacy-pack.json");
            File.WriteAllText(legacyPath, SentencePackJson.Serialize(BuildPack("legacy-pack", "legacy-sentence")));
            Require(store.Find("legacy-pack")?.Pack.Sentences.Single().Id == "legacy-sentence", "Legacy uncompressed SentencePack compatibility was lost.");

            string replacementSource = Path.Combine(root, "replacement.json.gz");
            SentencePack replacement = BuildPack(pack.PackId, "sentence-2");
            SentencePackIo.WriteGZip(replacementSource, replacement);
            InstalledSentencePack replaced = store.Import(replacementSource);
            Require(replaced.Path == installed.Path, "Same pack id did not replace its canonical compressed file.");
            Require(replaced.SqlitePath == installed.SqlitePath, "Same pack id did not replace its stable SQLite companion path.");
            Require(store.Find(pack.PackId)?.Pack.Sentences.Single().Id == "sentence-2", "SentencePack replacement failed.");
            Require(store.Find(pack.PackId)?.Corpus.LookupByEntryId("ox-learn").Single().Id == "sentence-2", "SQLite runtime companion was not replaced with the new pack content.");
        }
        finally
        {
            try
            {
                if (Directory.Exists(root)) Directory.Delete(root, true);
            }
            catch
            {
            }
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
