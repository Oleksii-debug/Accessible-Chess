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
            SentencePack pack = BuildPack("test/pack:one");
            File.WriteAllText(source, SentencePackJson.Serialize(pack));

            var store = new SentencePackStore(root);
            InstalledSentencePack installed = store.Import(source);
            Require(File.Exists(installed.Path), "Imported SentencePack was not persisted.");
            Require(installed.Pack.PackId == pack.PackId, "Imported SentencePack id changed.");
            Require(Path.GetFileName(installed.Path).IndexOfAny(Path.GetInvalidFileNameChars()) < 0, "SentencePack filename was not sanitized.");

            IReadOnlyList<InstalledSentencePack> loaded = store.LoadInstalled();
            Require(loaded.Count == 1 && loaded[0].Pack.Sentences.Count == 1, "Installed SentencePack did not reload.");
            Require(store.Find(pack.PackId)?.Pack.Sentences[0].Id == "sentence-1", "SentencePack lookup by stable pack id failed.");

            File.WriteAllText(Path.Combine(store.DirectoryPath, "broken.json"), "{ not valid json");
            IReadOnlyList<InstalledSentencePack> afterBroken = store.LoadInstalled();
            Require(afterBroken.Count == 1 && afterBroken[0].Pack.PackId == pack.PackId, "A malformed optional SentencePack blocked valid installed packs.");

            string replacementSource = Path.Combine(root, "replacement.json");
            SentencePack replacement = BuildPack(pack.PackId, "sentence-2");
            File.WriteAllText(replacementSource, SentencePackJson.Serialize(replacement));
            InstalledSentencePack replaced = store.Import(replacementSource);
            Require(replaced.Path == installed.Path, "Same pack id did not replace its canonical installed file.");
            Require(store.Find(pack.PackId)?.Pack.Sentences.Single().Id == "sentence-2", "SentencePack replacement by stable pack id failed.");
        }
        finally
        {
            try
            {
                if (Directory.Exists(root)) Directory.Delete(root, true);
            }
            catch
            {
                // Cleanup failure must not hide a product regression.
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
