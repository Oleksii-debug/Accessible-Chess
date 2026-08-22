using System.Diagnostics;
using System.Runtime.CompilerServices;

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
            try { Directory.Delete(root, true); } catch { }
        }
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
