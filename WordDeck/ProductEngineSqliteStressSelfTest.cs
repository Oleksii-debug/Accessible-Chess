using System.Diagnostics;
using System.Runtime.CompilerServices;
using System.Text.Json;

namespace WordDeck;

internal static class ProductEngineSqliteStressSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            ProductEngineSqliteStressSelfTest.Run();
    }
}

internal static class ProductEngineSqliteStressSelfTest
{
    public static void Run()
    {
        TestBoundedIndexedQueries();
        TestFullCorpusGapAccounting();
    }

    private static void TestBoundedIndexedQueries()
    {
        string root = Path.Combine(Path.GetTempPath(), "WordDeck R4b SQLite тест " + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        string sqlitePath = Path.Combine(root, "Sentence Pack stress.sqlite");
        try
        {
            SentencePack pack = BuildStressPack();
            SentencePackSqlitePrototype.Build(sqlitePath, pack);

            IReadOnlyList<SentenceRecord> baseline = SentencePackSqliteRuntimeQuery.LookupAllTargets(sqlitePath, new[] { "entry-0" }, maxResults: 16);
            Require(baseline.Count is > 0 and <= 16, "R4b SQLite stress baseline query returned an invalid bounded result count.");
            string[] expected = baseline.Select(sentence => sentence.Id).ToArray();

            var stopwatch = Stopwatch.StartNew();
            for (int i = 0; i < 1000; i++)
            {
                IReadOnlyList<SentenceRecord> result = SentencePackSqliteRuntimeQuery.LookupAllTargets(sqlitePath, new[] { "entry-0" }, maxResults: 16);
                Require(result.Count <= 16, "SQLite runtime query exceeded requested candidate bound during 1000-query stress.");
                Require(result.Select(sentence => sentence.Id).SequenceEqual(expected, StringComparer.Ordinal), "SQLite runtime query became nondeterministic during 1000-query stress.");
            }
            stopwatch.Stop();

            IReadOnlyList<string> plan = SentencePackSqliteRuntimeQuery.ExplainRepresentativePlan(sqlitePath, "entry-0");
            Require(plan.Count > 0, "SQLite runtime query plan could not be inspected after stress.");
            Require(plan.Any(line => line.Contains("INDEX", StringComparison.OrdinalIgnoreCase) || line.Contains("SEARCH", StringComparison.OrdinalIgnoreCase)),
                "SQLite representative lookup plan did not expose indexed/search access after stress.");

            bool maxRejected = false;
            try { _ = SentencePackSqliteRuntimeQuery.LookupAllTargets(sqlitePath, new[] { "entry-0" }, SentencePackSqliteRuntimeQuery.DefaultCandidateLimit + 1); }
            catch (ArgumentOutOfRangeException) { maxRejected = true; }
            Require(maxRejected, "SQLite runtime query accepted an unbounded candidate request.");

            Console.WriteLine($"WordDeck R4b SQLite stress passed: 1000 parameterized disk-backed lookups, 16-candidate bound and indexed plan verified in {stopwatch.ElapsedMilliseconds} ms.");
        }
        finally
        {
            Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
            try { Directory.Delete(root, true); } catch { }
        }
    }

    private static void TestFullCorpusGapAccounting()
    {
        string root = Path.Combine(Path.GetTempPath(), "WordDeck R4b coverage Київ " + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        string sqlitePath = Path.Combine(root, "coverage fixture.sqlite");
        string reportPath = Path.Combine(root, "coverage report.json");
        try
        {
            DictionaryPackage dictionary = DictionaryLoader.LoadEmbeddedOxford();
            Require(dictionary.Entries.Count == 5446, "Full-corpus coverage regression did not load all 5,446 Oxford entries.");
            DictionaryEntry first = dictionary.Entries[0];
            DictionaryEntry second = dictionary.Entries[1];
            const string english = "we learn words";
            List<string> tokens = SentenceTokenizer.Tokenize(english).ToList();
            var pack = new SentencePack
            {
                PackId = "r4b-full-gap-accounting",
                Provenance = "Synthetic R4b full-corpus gap accounting fixture; never release data",
                License = "CC0-1.0",
                Sentences = new()
                {
                    new SentenceRecord
                    {
                        Id = "coverage-sentence-1",
                        English = english,
                        Ukrainian = "Ми вивчаємо слова",
                        Source = "R4b synthetic coverage fixture",
                        License = "CC0-1.0",
                        Tokens = tokens,
                        Lemmas = tokens.ToList(),
                        TargetEntryIds = new() { first.Id, second.Id },
                        EntryLevels = new(StringComparer.OrdinalIgnoreCase)
                        {
                            [first.Id] = first.Level,
                            [second.Id] = second.Level
                        },
                        DifficultyLevel = HigherLevel(first.Level, second.Level),
                        OffListTokenCount = 0
                    }
                }
            };
            pack.Validate();
            SentencePackSqlitePrototype.Build(sqlitePath, pack);
            Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();

            int exitCode = SentencePackDiagnostics.Run(new[] { "--measure-sentence-pack", sqlitePath, reportPath, "--runtime" });
            Require(exitCode == 0 && File.Exists(reportPath), "Full-corpus Sentence runtime diagnostics failed on a valid SQLite fixture.");

            using JsonDocument report = JsonDocument.Parse(File.ReadAllText(reportPath));
            JsonElement rootElement = report.RootElement;
            int scope = rootElement.GetProperty("ScopeEntryCount").GetInt32();
            int oneCovered = rootElement.GetProperty("OneTargetCoveredEntries").GetInt32();
            int oneUncovered = rootElement.GetProperty("OneTargetUncoveredEntries").GetInt32();
            int twoCovered = rootElement.GetProperty("TwoTargetCoveredEntries").GetInt32();
            int twoUncovered = rootElement.GetProperty("TwoTargetUncoveredEntries").GetInt32();
            int oneGapIds = rootElement.GetProperty("OneTargetUncoveredEntryIds").GetArrayLength();
            int twoGapIds = rootElement.GetProperty("TwoTargetUncoveredEntryIds").GetArrayLength();

            Require(scope == 5446, $"Coverage diagnostics used stale scope size {scope} instead of 5446.");
            Require(oneCovered == 2 && twoCovered == 2, "Synthetic two-target coverage fixture did not account for both indexed stable IDs.");
            Require(oneCovered + oneUncovered == scope && twoCovered + twoUncovered == scope,
                "Coverage diagnostics do not partition the full Oxford scope into covered and uncovered entries.");
            Require(oneGapIds == oneUncovered && twoGapIds == twoUncovered,
                "Explicit uncovered stable-ID lists do not match reported gap counts.");
            Require(oneUncovered == 5444 && twoUncovered == 5444,
                "Full-corpus gap accounting silently dropped or invented Oxford entries.");

            Console.WriteLine("WordDeck R4b Sentence coverage evidence passed: exact 5,446-entry scope and explicit stable-ID gap lists are internally consistent.");
        }
        finally
        {
            Microsoft.Data.Sqlite.SqliteConnection.ClearAllPools();
            try { Directory.Delete(root, true); } catch { }
        }
    }

    private static string HigherLevel(string left, string right)
    {
        string[] order = { "A1", "A2", "B1", "B2", "C1" };
        int leftIndex = Array.FindIndex(order, level => string.Equals(level, left, StringComparison.OrdinalIgnoreCase));
        int rightIndex = Array.FindIndex(order, level => string.Equals(level, right, StringComparison.OrdinalIgnoreCase));
        if (leftIndex < 0 || rightIndex < 0) throw new InvalidDataException("Synthetic coverage fixture received an unsupported CEFR level.");
        return order[Math.Max(leftIndex, rightIndex)];
    }

    private static SentencePack BuildStressPack()
    {
        const string english = "we practice words";
        List<string> tokens = SentenceTokenizer.Tokenize(english).ToList();
        var sentences = new List<SentenceRecord>();
        for (int i = 0; i < 200; i++)
        {
            string entryId = "entry-" + (i % 20).ToString(System.Globalization.CultureInfo.InvariantCulture);
            sentences.Add(new SentenceRecord
            {
                Id = "r4b-sentence-" + i.ToString("D4", System.Globalization.CultureInfo.InvariantCulture),
                English = english,
                Ukrainian = "Ми тренуємо слова",
                Source = "R4b synthetic SQLite performance fixture",
                License = "CC0-1.0",
                Tokens = tokens.ToList(),
                Lemmas = tokens.ToList(),
                TargetEntryIds = new() { entryId },
                EntryLevels = new(StringComparer.OrdinalIgnoreCase) { [entryId] = "A1" },
                DifficultyLevel = "A1",
                OffListTokenCount = 0
            });
        }

        var pack = new SentencePack
        {
            PackId = "r4b-sqlite-stress",
            Provenance = "Synthetic R4b performance fixture; never production release data",
            License = "CC0-1.0",
            Sentences = sentences
        };
        pack.Validate();
        return pack;
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }
}
