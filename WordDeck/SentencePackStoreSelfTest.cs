using Microsoft.Data.Sqlite;

namespace WordDeck;

internal static class SentencePackStoreSelfTest
{
    public static void Run()
    {
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck sentence store Київ {Guid.NewGuid():N}");
        try
        {
            Directory.CreateDirectory(root);
            string source = Path.Combine(root, "source pack.json");
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
            Require(installed.Corpus is SentencePackSqliteCorpus importedSqlite && importedSqlite.Provenance == pack.Provenance,
                "SQLite runtime corpus did not preserve pack provenance metadata.");

            IReadOnlyList<string> plan = SentencePackSqliteRuntimeQuery.ExplainRepresentativePlan(installed.SqlitePath!, "ox-learn");
            Require(plan.Any(detail => detail.Contains("SEARCH", StringComparison.OrdinalIgnoreCase) && detail.Contains("sentence_targets", StringComparison.OrdinalIgnoreCase)),
                "Representative SQLite target lookup did not expose an indexed SEARCH query plan.");

            SentencePack compressedRoundTrip = SentencePackIo.Read(installed.Path);
            Require(compressedRoundTrip.PackId == pack.PackId, "Compressed SentencePack did not round-trip.");

            IReadOnlyList<InstalledSentencePack> loaded = store.LoadInstalled();
            Require(loaded.Count == 1, "Installed SentencePack did not reload.");
            Require(loaded[0].PackId == pack.PackId && loaded[0].SentenceCount == 1, "Installed SentencePack metadata did not reload from SQLite.");
            Require(loaded[0].PortablePack is null, "Normal installed-pack discovery eagerly materialized the portable SentencePack.");
            Require(loaded[0].Corpus is SentencePackSqliteCorpus, "Reloaded installed SentencePack did not discover its valid SQLite companion.");
            Require(loaded[0].Corpus.LookupByEntryId("ox-learn").Single().Id == "sentence-1", "Reloaded SQLite corpus lookup failed.");

            string corruptSqlite = Path.Combine(root, "corrupt-missing-index.sqlite");
            File.Copy(installed.SqlitePath!, corruptSqlite, true);
            using (var connection = new SqliteConnection(new SqliteConnectionStringBuilder
            {
                DataSource = corruptSqlite,
                Mode = SqliteOpenMode.ReadWrite,
                Pooling = false
            }.ToString()))
            {
                connection.Open();
                using SqliteCommand drop = connection.CreateCommand();
                drop.CommandText = "DROP INDEX ix_sentence_targets_sentence;";
                drop.ExecuteNonQuery();
            }
            bool corruptRejected = false;
            try { _ = new SentencePackSqliteCorpus(corruptSqlite); }
            catch (InvalidDataException) { corruptRejected = true; }
            Require(corruptRejected, "SQLite SentencePack missing its required runtime index was accepted.");

            string legacyPath = Path.Combine(store.DirectoryPath, "legacy-pack.json");
            File.WriteAllText(legacyPath, SentencePackJson.Serialize(BuildPack("legacy-pack", "legacy-sentence")));
            InstalledSentencePack? legacy = store.Find("legacy-pack");
            Require(legacy?.PortablePack?.Sentences.Single().Id == "legacy-sentence", "Legacy uncompressed SentencePack compatibility was lost.");
            Require(legacy?.Corpus.LookupByEntryId("ox-learn").Single().Id == "legacy-sentence", "Legacy in-memory corpus fallback failed.");

            string replacementSource = Path.Combine(root, "replacement.json.gz");
            SentencePack replacement = BuildPack(pack.PackId, "sentence-2");
            SentencePackIo.WriteGZip(replacementSource, replacement);
            InstalledSentencePack replaced = store.Import(replacementSource);
            Require(replaced.Path == installed.Path, "Same pack id did not replace its canonical compressed file.");
            Require(replaced.SqlitePath == installed.SqlitePath, "Same pack id did not replace its stable SQLite companion path.");
            Require(store.Find(pack.PackId)?.Corpus.LookupByEntryId("ox-learn").Single().Id == "sentence-2", "SQLite runtime companion was not replaced with the new pack content.");

            string interruptedSource = Path.Combine(root, "interrupted replacement.json.gz");
            SentencePack interrupted = BuildPack(pack.PackId, "sentence-3");
            SentencePackIo.WriteGZip(interruptedSource, interrupted);
            var interruptedStore = new SentencePackStore(root, checkpoint =>
            {
                if (checkpoint == "portable-installed")
                    throw new IOException("Synthetic interruption after portable replacement.");
            });
            bool interruptedRejected = false;
            try { _ = interruptedStore.Import(interruptedSource); }
            catch (IOException) { interruptedRejected = true; }
            Require(interruptedRejected, "Synthetic interrupted SentencePack replacement did not fail.");

            InstalledSentencePack? afterInterrupted = new SentencePackStore(root).Find(pack.PackId);
            Require(afterInterrupted is not null && afterInterrupted.Corpus.LookupByEntryId("ox-learn").Single().Id == "sentence-2",
                "Interrupted SentencePack replacement did not restore the last usable SQLite corpus.");
            Require(SentencePackIo.Read(afterInterrupted.Path).Sentences.Single().Id == "sentence-2",
                "Interrupted SentencePack replacement did not restore the last usable portable pack.");
            Require(!Directory.EnumerateFiles(store.DirectoryPath, "*.rollback", SearchOption.TopDirectoryOnly).Any(),
                "Successful rollback left stale rollback files behind.");
        }
        finally
        {
            try
            {
                SqliteConnection.ClearAllPools();
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
