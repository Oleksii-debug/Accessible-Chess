using System.Diagnostics;
using Microsoft.Data.Sqlite;

namespace WordDeck;

internal static class SentenceRound2SelfTest
{
    public static void Run()
    {
        TestExactMultisetAndUnicodeContract();
        TestStrictPackIdentityRules();
        TestTransactionalReplacementFailureMatrix();
        TestSqliteBoundedStressAndQueryPlan();
        SentencePackSqlitePrototypeSelfTest.Run();
        Console.WriteLine("WordDeck Sentence Round-2 self-test passed: exact multiset/Unicode, safe PackId, transactional rollback matrix, SQLite bounded stress and query-plan checks validated.");
    }

    private static void TestExactMultisetAndUnicodeContract()
    {
        SentenceAnswerResult reordered = SentenceAnswerEvaluator.Evaluate(
            "Very very well-known student's skills improve",
            "SKILLS very student’s improve known well very");
        Require(reordered.Accepted && reordered.WordOrderIgnored,
            "Sentence Spelling did not preserve exact normalized multiset semantics across case/apostrophe/hyphen/order.");

        SentenceAnswerResult missingRepeat = SentenceAnswerEvaluator.Evaluate("very very good", "very good");
        Require(!missingRepeat.Accepted && missingRepeat.Missing.SequenceEqual(new[] { "very" }),
            "Repeated required token was collapsed or diagnosed incorrectly.");

        SentenceAnswerResult extraRepeat = SentenceAnswerEvaluator.Evaluate("very very good", "very very very good");
        Require(!extraRepeat.Accepted && extraRepeat.Extra.SequenceEqual(new[] { "very" }),
            "Repeated extra token was collapsed or diagnosed incorrectly.");

        SentenceAnswerResult wrongForm = SentenceAnswerEvaluator.Evaluate("She improves skills", "She improve skills");
        Require(!wrongForm.Accepted && wrongForm.Missing.Contains("improves") && wrongForm.Extra.Contains("improve"),
            "Wrong inflected form was accepted semantically instead of exact-form checking.");

        SentenceAnswerResult compatibility = SentenceAnswerEvaluator.Evaluate("Student's skills", "Ｓｔｕｄｅｎｔ’s SKILLS");
        Require(compatibility.Accepted, "Technical Unicode compatibility normalization regressed.");

        string malformed = new(new[] { '\uD800' });
        SentenceAnswerResult malformedResult = SentenceAnswerEvaluator.Evaluate("students improve", malformed);
        Require(!malformedResult.Accepted && malformedResult.Feedback.Contains("Unicode", StringComparison.OrdinalIgnoreCase),
            "Malformed Unicode input did not fail closed with a readable diagnostic.");
    }

    private static void TestStrictPackIdentityRules()
    {
        string[] unsafeIds =
        {
            "../escape", "..\\escape", "CON", "NUL.txt", "COM1", "LPT9.log", ".", "..", "trailing.", " leading", "trailing "
        };
        foreach (string id in unsafeIds)
        {
            bool rejected = false;
            try { _ = SentencePackStore.SafeFileName(id); }
            catch (InvalidDataException) { rejected = true; }
            Require(rejected, $"Unsafe/collision-prone SentencePack id '{id}' was accepted.");
        }

        Require(SentencePackStore.SafeFileName("pack Київ 01") == "pack Київ 01",
            "Safe Unicode/spaces SentencePack id was rewritten instead of preserved deterministically.");
    }

    private static void TestTransactionalReplacementFailureMatrix()
    {
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck R2 atomic Київ {Guid.NewGuid():N}");
        try
        {
            Directory.CreateDirectory(root);
            string source = Path.Combine(root, "old source.json.gz");
            SentencePack oldPack = BuildSmallPack("CasePack", "old-sentence", "old");
            SentencePackIo.WriteGZip(source, oldPack);
            var baselineStore = new SentencePackStore(root);
            InstalledSentencePack baseline = baselineStore.Import(source);
            Require(baseline.Corpus.LookupByEntryId("target-old").Single().Id == "old-sentence",
                "Baseline SentencePack installation failed before failure-injection matrix.");

            string malformed = Path.Combine(root, "malformed.json");
            File.WriteAllText(malformed, "{ broken json");
            ExpectFailure(() => baselineStore.Import(malformed), "Malformed source was accepted before staging.");
            AssertOldStillUsable(root);

            string badLicense = Path.Combine(root, "bad-license.json.gz");
            SentencePack bad = BuildSmallPack("CasePack", "bad-license", "bad");
            bad = new SentencePack
            {
                PackId = bad.PackId,
                Provenance = bad.Provenance,
                License = "CC0-1.0",
                Sentences = bad.Sentences.Select(sentence => new SentenceRecord
                {
                    Id = sentence.Id,
                    English = sentence.English,
                    Ukrainian = sentence.Ukrainian,
                    Source = sentence.Source,
                    License = "CC BY 2.0 FR",
                    Tokens = sentence.Tokens,
                    Lemmas = sentence.Lemmas,
                    TargetEntryIds = sentence.TargetEntryIds,
                    EntryLevels = sentence.EntryLevels,
                    DifficultyLevel = sentence.DifficultyLevel
                }).ToList()
            };
            SentencePackIo.WriteGZip(badLicense, bad);
            ExpectFailure(() => baselineStore.Import(badLicense), "Mixed-license source bypassed installation validation.");
            AssertOldStillUsable(root);

            string replacementPath = Path.Combine(root, "replacement.json.gz");
            SentencePack replacement = BuildSmallPack("CasePack", "new-sentence", "new");
            SentencePackIo.WriteGZip(replacementPath, replacement);

            string[] checkpoints =
            {
                "source-validated",
                "portable-staged",
                "before-sqlite-build",
                "sqlite-built",
                "before-candidate-validation",
                "candidate-validated",
                "old-installation-backed-up",
                "portable-installed",
                "sqlite-installed"
            };

            foreach (string checkpoint in checkpoints)
            {
                var failingStore = new SentencePackStore(root, reached =>
                {
                    if (reached == checkpoint)
                        throw new IOException("Synthetic Round-2 interruption at " + checkpoint);
                });
                ExpectFailure(() => failingStore.Import(replacementPath), "Injected interruption did not fail at " + checkpoint + ".");
                AssertOldStillUsable(root);
                AssertNoTransactionDebris(root);
            }

            if (OperatingSystem.IsWindows())
            {
                using FileStream locked = new(
                    baseline.Path,
                    FileMode.Open,
                    FileAccess.Read,
                    FileShare.None);
                ExpectFailure(() => new SentencePackStore(root).Import(replacementPath),
                    "Windows locked destination did not produce a controlled replacement failure.");
            }
            AssertOldStillUsable(root);

            string collisionPath = Path.Combine(root, "collision.json.gz");
            SentencePackIo.WriteGZip(collisionPath, BuildSmallPack("casepack", "collision", "collision"));
            ExpectFailure(() => new SentencePackStore(root).Import(collisionPath),
                "Case-insensitive Windows SentencePack identity collision was accepted.");
            AssertOldStillUsable(root);

            InstalledSentencePack committed = new SentencePackStore(root).Import(replacementPath);
            Require(committed.Corpus.LookupByEntryId("target-new").Single().Id == "new-sentence",
                "Valid replacement did not commit after failure matrix.");
            AssertNoTransactionDebris(root);
        }
        finally
        {
            SqliteConnection.ClearAllPools();
            try { if (Directory.Exists(root)) Directory.Delete(root, true); } catch { }
        }
    }

    private static void TestSqliteBoundedStressAndQueryPlan()
    {
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck R2 sqlite stress {Guid.NewGuid():N}");
        string database = Path.Combine(root, "stress.sqlite");
        try
        {
            Directory.CreateDirectory(root);
            const int sentenceCount = 8000;
            var sentences = new List<SentenceRecord>(sentenceCount);
            for (int i = 0; i < sentenceCount; i++)
            {
                string english = $"common practice word item";
                string target = $"target-{i % 400:D3}";
                List<string> tokens = SentenceTokenizer.Tokenize(english).ToList();
                sentences.Add(new SentenceRecord
                {
                    Id = $"stress-{i:D5}",
                    English = english,
                    Ukrainian = $"Тестове речення {i}",
                    Source = "Synthetic Round-2 SQLite performance fixture",
                    License = "CC0-1.0",
                    Tokens = tokens,
                    Lemmas = tokens.ToList(),
                    TargetEntryIds = new List<string> { "target-common", target },
                    EntryLevels = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
                    {
                        ["target-common"] = "A1",
                        [target] = i % 5 switch { 0 => "A1", 1 => "A2", 2 => "B1", 3 => "B2", _ => "C1" }
                    },
                    DifficultyLevel = i % 5 switch { 0 => "A1", 1 => "A2", 2 => "B1", 3 => "B2", _ => "C1" }
                });
            }

            var pack = new SentencePack
            {
                PackId = "r2-stress-pack",
                Provenance = "Synthetic Round-2 SQLite performance fixture",
                License = "CC0-1.0",
                Sentences = sentences
            };

            var buildWatch = Stopwatch.StartNew();
            SentencePackSqlitePrototype.Build(database, pack);
            buildWatch.Stop();
            Require(buildWatch.Elapsed < TimeSpan.FromMinutes(2),
                $"Synthetic 8k SentencePack SQLite build exceeded two-minute regression ceiling: {buildWatch.Elapsed}.");

            pack = null!;
            sentences = null!;
            GC.Collect();
            GC.WaitForPendingFinalizers();
            GC.Collect();

            var firstWatch = Stopwatch.StartNew();
            IReadOnlyList<SentenceRecord> first = SentencePackSqliteRuntimeQuery.LookupAllTargets(database, new[] { "target-common" }, 32);
            firstWatch.Stop();
            Require(first.Count == 32, "Bounded SQLite lookup did not respect explicit 32-result ceiling.");
            Require(firstWatch.Elapsed < TimeSpan.FromSeconds(10),
                $"First indexed SQLite lookup exceeded ten-second regression ceiling: {firstWatch.Elapsed}.");

            IReadOnlyList<string> plan = SentencePackSqliteRuntimeQuery.ExplainRepresentativePlan(database, "target-common");
            Require(plan.Any(detail => detail.Contains("SEARCH", StringComparison.OrdinalIgnoreCase) && detail.Contains("sentence_targets", StringComparison.OrdinalIgnoreCase)),
                "Representative SQLite query plan did not use indexed SEARCH behavior.");

            var queryWatch = Stopwatch.StartNew();
            for (int i = 0; i < 1000; i++)
            {
                string target = $"target-{i % 400:D3}";
                IReadOnlyList<SentenceRecord> rows = SentencePackSqliteRuntimeQuery.LookupAllTargets(database, new[] { "target-common", target }, 16);
                Require(rows.Count is > 0 and <= 16, "Bounded two-target SQLite stress lookup returned invalid candidate count.");
            }
            queryWatch.Stop();
            Require(queryWatch.Elapsed < TimeSpan.FromMinutes(2),
                $"1000 bounded SQLite queries exceeded two-minute regression ceiling: {queryWatch.Elapsed}.");

            var corpus = new SentencePackSqliteCorpus(database);
            string[] scope = Enumerable.Range(0, 400).Select(i => $"target-{i:D3}").ToArray();
            HashSet<string> covered = corpus.GetCoveredScopeEntryIds(scope, requireSameScopePartner: false);
            Require(covered.Count == 400, "SQLite full-scope coverage lookup lost indexed target entries.");
        }
        finally
        {
            SqliteConnection.ClearAllPools();
            try { if (Directory.Exists(root)) Directory.Delete(root, true); } catch { }
        }
    }

    private static SentencePack BuildSmallPack(string packId, string sentenceId, string suffix)
    {
        string english = $"we practice {suffix}";
        List<string> tokens = SentenceTokenizer.Tokenize(english).ToList();
        string target = "target-" + suffix;
        var pack = new SentencePack
        {
            PackId = packId,
            Provenance = "Synthetic Round-2 transaction fixture",
            License = "CC0-1.0",
            Sentences = new List<SentenceRecord>
            {
                new()
                {
                    Id = sentenceId,
                    English = english,
                    Ukrainian = "Ми тренуємося",
                    Source = "Synthetic Round-2 transaction fixture",
                    License = "CC0-1.0",
                    Tokens = tokens,
                    Lemmas = tokens.ToList(),
                    TargetEntryIds = new List<string> { target },
                    EntryLevels = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase) { [target] = "A1" },
                    DifficultyLevel = "A1"
                }
            }
        };
        pack.Validate();
        return pack;
    }

    private static void AssertOldStillUsable(string root)
    {
        InstalledSentencePack? current = new SentencePackStore(root).Find("CasePack");
        Require(current is not null, "Last-known-good SentencePack disappeared after failed replacement.");
        Require(current.Corpus.LookupByEntryId("target-old").Single().Id == "old-sentence",
            "Failed replacement changed the last-known-good SentencePack content.");
    }

    private static void AssertNoTransactionDebris(string root)
    {
        string directory = Path.Combine(root, "SentencePacks");
        Require(!Directory.EnumerateFiles(directory, "*", SearchOption.TopDirectoryOnly)
                .Any(path => path.EndsWith(".tmp", StringComparison.OrdinalIgnoreCase) ||
                             path.EndsWith(".rollback", StringComparison.OrdinalIgnoreCase)),
            "SentencePack transaction left temporary/rollback debris after a recoverable failure.");
    }

    private static void ExpectFailure(Action action, string message)
    {
        try
        {
            action();
        }
        catch
        {
            return;
        }
        throw new InvalidDataException(message);
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidDataException(message);
    }
}
