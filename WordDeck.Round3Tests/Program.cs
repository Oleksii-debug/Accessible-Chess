using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
using Microsoft.Data.Sqlite;
using WordDeck;

internal static class Program
{
    private static int Main()
    {
        try
        {
            TestTempGzipSignatureAndMalformedInput();
            TestExactMultisetAndUnicode();
            TestSafePackIds();
            TestImmutableManifestTransactionAndRecovery();
            TestSqliteStressAndOxfordLinkage();
            TestTatoebaProvenanceFailClosed();
            Console.WriteLine("WordDeck Round-3 Sentence regression harness PASSED.");
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("WordDeck Round-3 Sentence regression harness FAILED: " + ex);
            return 1;
        }
    }

    private static void TestTempGzipSignatureAndMalformedInput()
    {
        string root = TempRoot("gzip");
        try
        {
            string staged = Path.Combine(root, "candidate.json.gz.transaction.tmp");
            SentencePack pack = BuildPack("temp-gzip", "temp", 1);
            SentencePackIo.WriteGZip(staged, pack);
            Require(SentencePackIo.HasGZipSignature(staged), "Staged gzip lost its signature.");
            SentencePack read = SentencePackIo.Read(staged);
            Require(read.PackId == pack.PackId && read.SentenceCount == 1,
                "SentencePackIo relied on a .gz suffix instead of gzip content signature.");

            string malformed = Path.Combine(root, "malformed.json");
            File.WriteAllText(malformed, "{ broken json");
            ExpectFailure(() => SentencePackIo.Read(malformed), "Malformed JSON did not fail closed.");

            string empty = Path.Combine(root, "empty.json");
            File.WriteAllText(empty, "");
            ExpectFailure(() => SentencePackIo.Read(empty), "Empty SentencePack file did not fail closed.");
        }
        finally { DeleteRoot(root); }
    }

    private static void TestExactMultisetAndUnicode()
    {
        SentenceAnswerResult reordered = SentenceAnswerEvaluator.Evaluate(
            "Very very well-known student's skills improve",
            "SKILLS very student’s improve known well very");
        Require(reordered.Accepted && reordered.WordOrderIgnored,
            "Exact normalized token multiset was not accepted across apostrophe/hyphen/case/order normalization.");

        SentenceAnswerResult missingRepeat = SentenceAnswerEvaluator.Evaluate("very very good", "very good");
        Require(!missingRepeat.Accepted && missingRepeat.Missing.SequenceEqual(new[] { "very" }),
            "Repeated required token was collapsed.");

        SentenceAnswerResult extraRepeat = SentenceAnswerEvaluator.Evaluate("very very good", "very very very good");
        Require(!extraRepeat.Accepted && extraRepeat.Extra.SequenceEqual(new[] { "very" }),
            "Repeated extra token was collapsed.");

        SentenceAnswerResult wrongForm = SentenceAnswerEvaluator.Evaluate("She improves skills", "She improve skills");
        Require(!wrongForm.Accepted && wrongForm.Missing.Contains("improves") && wrongForm.Extra.Contains("improve"),
            "Wrong inflected form was accepted semantically.");

        SentenceAnswerResult compatibility = SentenceAnswerEvaluator.Evaluate("Student's skills", "Ｓｔｕｄｅｎｔ’s SKILLS");
        Require(compatibility.Accepted, "Unicode FormKC/apostrophe normalization regressed.");

        string malformed = new(new[] { '\uD800' });
        SentenceAnswerResult malformedResult = SentenceAnswerEvaluator.Evaluate("students improve", malformed);
        Require(!malformedResult.Accepted && malformedResult.Feedback.Contains("Unicode", StringComparison.OrdinalIgnoreCase),
            "Malformed Unicode answer did not fail closed with readable feedback.");
    }

    private static void TestSafePackIds()
    {
        string[] unsafeIds =
        {
            "../escape", "..\\escape", "CON", "NUL.txt", "COM1", "LPT9.log", ".", "..", "trailing.", " leading", "trailing "
        };
        foreach (string id in unsafeIds)
            ExpectFailure(() => SentencePackStore.SafeFileName(id), $"Unsafe PackId '{id}' was accepted.");

        Require(SentencePackStore.SafeFileName("pack Київ 01") == "pack Київ 01",
            "Safe Unicode/spaces PackId was rewritten.");
    }

    private static void TestImmutableManifestTransactionAndRecovery()
    {
        string root = TempRoot("atomic Київ");
        try
        {
            string oldSource = Path.Combine(root, "old source.json.gz");
            SentencePackIo.WriteGZip(oldSource, BuildPack("CasePack", "old", 4));
            var store = new SentencePackStore(root);
            InstalledSentencePack first = store.Import(oldSource);
            Require(first.Corpus.LookupByEntryId("target-old").Count > 0,
                "Initial immutable generation was not usable.");

            string packDir = store.DirectoryPath;
            string activeManifest = Path.Combine(packDir, "CasePack.installed.json");
            string backupManifest = Path.Combine(packDir, "CasePack.installed.backup.json");
            Require(File.Exists(activeManifest), "Initial import did not create an active manifest commit point.");
            Require(!File.Exists(backupManifest), "First import unexpectedly created a previous-generation backup.");

            string replacementSource = Path.Combine(root, "replacement.json.gz");
            SentencePackIo.WriteGZip(replacementSource, BuildPack("CasePack", "new", 5));

            string[] failurePoints =
            {
                "source-validated",
                "portable-staged",
                "before-sqlite-build",
                "sqlite-built",
                "identity-stamped",
                "candidate-validated",
                "generation-files-installed",
                "manifest-staged",
                "manifest-validated",
                "before-manifest-commit"
            };

            foreach (string failurePoint in failurePoints)
            {
                var failing = new SentencePackStore(root, reached =>
                {
                    if (reached == failurePoint)
                        throw new IOException("Synthetic Round-3 interruption at " + failurePoint);
                });
                ExpectFailure(() => failing.Import(replacementSource), "Failure injection did not stop at " + failurePoint);
                InstalledSentencePack? stillOld = new SentencePackStore(root).Find("CasePack");
                Require(stillOld is not null && stillOld.Corpus.LookupByEntryId("target-old").Count > 0,
                    "Last-known-good generation was lost after interruption at " + failurePoint);
                Require(!Directory.EnumerateFiles(packDir, "*.tmp", SearchOption.TopDirectoryOnly).Any(),
                    "Transaction staging debris remained after interruption at " + failurePoint);
            }

            InstalledSentencePack committed = new SentencePackStore(root).Import(replacementSource);
            Require(committed.Corpus.LookupByEntryId("target-new").Count > 0,
                "Valid replacement did not become active.");
            Require(File.Exists(activeManifest) && File.Exists(backupManifest),
                "Replacement did not preserve active plus previous manifest generations.");

            string activeJson = File.ReadAllText(activeManifest);
            using (JsonDocument activeDoc = JsonDocument.Parse(activeJson))
            {
                string portable = activeDoc.RootElement.GetProperty("PortableFileName").GetString()!;
                string sqlite = activeDoc.RootElement.GetProperty("SqliteFileName").GetString()!;
                Require(File.Exists(Path.Combine(packDir, portable)) && File.Exists(Path.Combine(packDir, sqlite)),
                    "Active manifest points to missing immutable generation assets.");
            }

            File.WriteAllText(activeManifest, "{ corrupt active manifest");
            InstalledSentencePack? recovered = new SentencePackStore(root).Find("CasePack");
            Require(recovered is not null && recovered.Corpus.LookupByEntryId("target-old").Count > 0,
                "Corrupt active manifest did not fall back to previous validated generation.");

            // Restore current and prove a missing current SQLite also falls back to the previous generation.
            File.WriteAllText(activeManifest, activeJson);
            using (JsonDocument activeDoc = JsonDocument.Parse(activeJson))
            {
                string sqlite = activeDoc.RootElement.GetProperty("SqliteFileName").GetString()!;
                File.Delete(Path.Combine(packDir, sqlite));
            }
            recovered = new SentencePackStore(root).Find("CasePack");
            Require(recovered is not null && recovered.Corpus.LookupByEntryId("target-old").Count > 0,
                "Incomplete active generation did not fall back to previous validated generation.");

            string collisionSource = Path.Combine(root, "collision.json.gz");
            SentencePackIo.WriteGZip(collisionSource, BuildPack("casepack", "collision", 1));
            ExpectFailure(() => new SentencePackStore(root).Import(collisionSource),
                "Case-insensitive PackId collision was accepted.");
        }
        finally
        {
            SqliteConnection.ClearAllPools();
            DeleteRoot(root);
        }
    }

    private static void TestSqliteStressAndOxfordLinkage()
    {
        DictionaryPackage dictionary = DictionaryLoader.LoadEmbeddedOxford();
        Require(dictionary.Entries.Count == 5446, "Embedded Oxford inventory is not the accepted 5,446-entry corpus.");
        Require(dictionary.Entries.All(entry => entry.Level is "A1" or "A2" or "B1" or "B2" or "C1"),
            "Oxford linkage exposed an unsupported C2/custom study level.");
        DictionaryEntry addition = dictionary.Entries.First(entry => entry.Source.Equals("abolish", StringComparison.OrdinalIgnoreCase));
        string additionSentenceText = "They abolish it";
        var additionPack = new SentencePack
        {
            PackId = "oxford-linkage-test",
            Provenance = "Synthetic Round-3 Oxford linkage fixture",
            License = "CC0 1.0",
            Sentences = new List<SentenceRecord>
            {
                MakeSentence("oxford-addition", additionSentenceText, "Вони скасовують це", new[] { addition.Id }, new[] { addition.Level })
            }
        };
        additionPack.Validate();
        Require(additionPack.LookupByEntryId(addition.Id).Single().Id == "oxford-addition",
            "Sentence stable-ID linkage failed for an Oxford 5000 addition.");

        string root = TempRoot("sqlite stress");
        string database = Path.Combine(root, "stress.sqlite");
        try
        {
            const int sentenceCount = 8000;
            var sentences = new List<SentenceRecord>(sentenceCount);
            for (int i = 0; i < sentenceCount; i++)
            {
                string target = $"target-{i % 400:D3}";
                string english = $"common practice item {NumberWord(i % 10)}";
                List<string> tokens = SentenceTokenizer.Tokenize(english).ToList();
                sentences.Add(new SentenceRecord
                {
                    Id = $"stress-{i:D5}",
                    English = english,
                    Ukrainian = $"Тестове речення {i}",
                    Source = "Synthetic Round-3 SQLite stress fixture",
                    License = "CC0 1.0",
                    Tokens = tokens,
                    Lemmas = tokens.ToList(),
                    TargetEntryIds = new List<string> { "target-common", target },
                    EntryLevels = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
                    {
                        ["target-common"] = "A1",
                        [target] = Level(i % 5)
                    },
                    DifficultyLevel = Level(i % 5)
                });
            }

            var pack = new SentencePack
            {
                PackId = "r3-stress-pack",
                Provenance = "Synthetic Round-3 SQLite stress fixture",
                License = "CC0 1.0",
                Sentences = sentences
            };

            Stopwatch build = Stopwatch.StartNew();
            SentencePackSqlitePrototype.Build(database, pack);
            build.Stop();

            var corpus = new SentencePackSqliteCorpus(database);
            Require(corpus.SentenceCount == sentenceCount, "SQLite stress corpus sentence count changed.");
            IReadOnlyList<string> plan = SentencePackSqliteRuntimeQuery.ExplainRepresentativePlan(database, "target-common");
            Require(plan.Any(detail => detail.Contains("SEARCH", StringComparison.OrdinalIgnoreCase)),
                "Representative SQLite query plan did not use indexed SEARCH behavior.");

            Stopwatch queries = Stopwatch.StartNew();
            for (int i = 0; i < 1000; i++)
            {
                string target = $"target-{i % 400:D3}";
                IReadOnlyList<SentenceRecord> rows = SentencePackSqliteRuntimeQuery.LookupAllTargets(
                    database,
                    new[] { "target-common", target },
                    16);
                Require(rows.Count is > 0 and <= 16, "Bounded two-target SQLite query returned an invalid candidate count.");
            }
            queries.Stop();

            string[] scope = Enumerable.Range(0, 400).Select(i => $"target-{i:D3}").ToArray();
            HashSet<string> covered = corpus.GetCoveredScopeEntryIds(scope, requireSameScopePartner: false);
            Require(covered.Count == 400, "SQLite scope coverage lost indexed target entries.");
            Console.WriteLine($"R3 SQLite stress: build={build.ElapsedMilliseconds} ms; 1000 bounded queries={queries.ElapsedMilliseconds} ms; db={new FileInfo(database).Length} bytes.");
        }
        finally
        {
            SqliteConnection.ClearAllPools();
            DeleteRoot(root);
        }
    }

    private static void TestTatoebaProvenanceFailClosed()
    {
        string root = TempRoot("tatoeba provenance");
        try
        {
            string pair = Path.Combine(root, "pairs.tsv");
            File.WriteAllText(pair, "english_id\tenglish\tukrainian_id\tukrainian\n1\tHello world\t2\tПривіт світе\n");
            ExpectFailure(() => TatoebaImportProvenance.Resolve(pair),
                "Tatoeba pair TSV without adjacent provenance manifest was accepted.");

            string hash;
            using (FileStream stream = File.OpenRead(pair))
                hash = Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
            File.WriteAllText(pair + ".manifest.json", JsonSerializer.Serialize(new
            {
                schema_version = 1,
                license_filter = "CC0 1.0 on BOTH sentence sides",
                license = "CC0 1.0",
                output_sha256 = hash
            }));
            TatoebaImportMetadata metadata = TatoebaImportProvenance.Resolve(pair);
            Require(metadata.VerifiedCc0Manifest && metadata.License == "CC0 1.0",
                "Valid both-sides-CC0 Tatoeba provenance did not verify.");

            File.AppendAllText(pair, "3\tAnother line\t4\tЩе один рядок\n");
            ExpectFailure(() => TatoebaImportProvenance.Resolve(pair),
                "Tatoeba pair output SHA mismatch was accepted.");
        }
        finally { DeleteRoot(root); }
    }

    private static SentencePack BuildPack(string packId, string suffix, int count)
    {
        var sentences = new List<SentenceRecord>();
        for (int i = 0; i < count; i++)
        {
            string english = $"we practice {suffix} {NumberWord(i % 10)}";
            sentences.Add(MakeSentence(
                $"{suffix}-sentence-{i:D3}",
                english,
                $"Ми тренуємося {i}",
                new[] { "target-" + suffix },
                new[] { "A1" }));
        }
        var pack = new SentencePack
        {
            PackId = packId,
            Provenance = "Synthetic Round-3 transaction fixture",
            License = "CC0 1.0",
            Sentences = sentences
        };
        pack.Validate();
        return pack;
    }

    private static SentenceRecord MakeSentence(
        string id,
        string english,
        string ukrainian,
        IReadOnlyList<string> targets,
        IReadOnlyList<string> levels)
    {
        List<string> tokens = SentenceTokenizer.Tokenize(english).ToList();
        var entryLevels = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        for (int i = 0; i < targets.Count; i++) entryLevels[targets[i]] = levels[i];
        return new SentenceRecord
        {
            Id = id,
            English = english,
            Ukrainian = ukrainian,
            Source = "Synthetic Round-3 regression fixture",
            License = "CC0 1.0",
            Tokens = tokens,
            Lemmas = tokens.ToList(),
            TargetEntryIds = targets.ToList(),
            EntryLevels = entryLevels,
            DifficultyLevel = levels.Count == 0 ? "A1" : levels.Max(StringComparer.Ordinal)
        };
    }

    private static string Level(int value) => value switch
    {
        0 => "A1",
        1 => "A2",
        2 => "B1",
        3 => "B2",
        _ => "C1"
    };

    private static string NumberWord(int value) => value switch
    {
        0 => "zero", 1 => "one", 2 => "two", 3 => "three", 4 => "four",
        5 => "five", 6 => "six", 7 => "seven", 8 => "eight", _ => "nine"
    };

    private static string TempRoot(string label)
    {
        string path = Path.Combine(Path.GetTempPath(), $"WordDeck R3 {label} {Guid.NewGuid():N}");
        Directory.CreateDirectory(path);
        return path;
    }

    private static void DeleteRoot(string root)
    {
        try { if (Directory.Exists(root)) Directory.Delete(root, true); } catch { }
    }

    private static void ExpectFailure(Action action, string message)
    {
        try { action(); }
        catch { return; }
        throw new InvalidDataException(message);
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }
}
