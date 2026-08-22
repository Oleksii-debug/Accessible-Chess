using System.Diagnostics;
using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class ContextCoverageDepthR4cSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            ContextCoverageDepthR4cSelfTest.Run();
    }
}

internal static class ContextCoverageDepthR4cSelfTest
{
    public static void Run()
    {
        DictionaryPackage dictionary = DictionaryLoader.LoadEmbeddedOxford();
        string[] universe = dictionary.Entries.Select(entry => entry.Id).ToArray();
        Check(universe.Length == 5446, "Depth coverage must use the exact 5446-entry universe.");

        TestAccountingContract(universe);
        TestSqliteFullUniverse(dictionary, universe);
        Console.WriteLine("Context coverage-depth R4c self-test PASS: exact 5446-ID one/two/three-target participation and natural triple semantics verified.");
    }

    private static void TestAccountingContract(string[] universe)
    {
        var fake = new FakeDepthCoverageSource(
            universe.Take(5300),
            universe.Take(4200),
            universe.Take(3000));

        ContextCoverageDepthReport one = ContextCoverageDepthAnalyzer.AnalyzeUniverse(fake, universe, 1);
        ContextCoverageDepthReport two = ContextCoverageDepthAnalyzer.AnalyzeUniverse(fake, universe, 2);
        ContextCoverageDepthReport three = ContextCoverageDepthAnalyzer.AnalyzeUniverse(fake, universe, 3);

        Check(one.RequestedEntryCount == 5446 && one.CoveredEntryCount == 5300 && one.UncoveredEntryCount == 146, "One-target 5446 accounting failed.");
        Check(two.RequestedEntryCount == 5446 && two.CoveredEntryCount == 4200 && two.UncoveredEntryCount == 1246, "Two-target 5446 accounting failed.");
        Check(three.RequestedEntryCount == 5446 && three.CoveredEntryCount == 3000 && three.UncoveredEntryCount == 2446, "Three-target 5446 accounting failed.");
        Check(one.CoveredEntryIds.Count + one.UncoveredEntryIds.Count == 5446, "One-target report does not partition 5446 IDs.");
        Check(two.CoveredEntryIds.Count + two.UncoveredEntryIds.Count == 5446, "Two-target report does not partition 5446 IDs.");
        Check(three.CoveredEntryIds.Count + three.UncoveredEntryIds.Count == 5446, "Three-target report does not partition 5446 IDs.");
        Check(three.UncoveredEntryIds.SequenceEqual(universe.Skip(3000).Select(ContextTargetIds.NormalizeSingle)), "Three-target uncovered IDs are not explicit/deterministic.");
    }

    private static void TestSqliteFullUniverse(DictionaryPackage dictionary, string[] universe)
    {
        string a = dictionary.Entries[0].Id;
        string b = dictionary.Entries[1].Id;
        string c = dictionary.Entries[2].Id;
        string d = dictionary.Entries[3].Id;
        string e = dictionary.Entries[4].Id;

        SentencePack pack = BuildPack(
            MakeSentence("depth-one", "alpha beta", new[] { a }),
            MakeSentence("depth-two", "alpha beta gamma", new[] { a, b }),
            MakeSentence("depth-three", "alpha beta gamma delta", new[] { a, b, c }),
            MakeSentence("depth-pair", "delta epsilon", new[] { d, e }));

        string root = Path.Combine(Path.GetTempPath(), "WordDeck depth R4c " + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        string path = Path.Combine(root, "контекст coverage.sqlite");
        try
        {
            SentencePackSqlitePrototype.Build(path, pack);
            var source = new ContextSentenceSqliteSource(path, ContextCorpusKind.SyntheticFixture);
            Stopwatch sw = Stopwatch.StartNew();
            ContextCoverageDepthReport one = ContextCoverageDepthAnalyzer.AnalyzeUniverse(source, universe, 1);
            ContextCoverageDepthReport two = ContextCoverageDepthAnalyzer.AnalyzeUniverse(source, universe, 2);
            ContextCoverageDepthReport three = ContextCoverageDepthAnalyzer.AnalyzeUniverse(source, universe, 3);
            sw.Stop();

            var expectedOne = new HashSet<string>(new[] { a, b, c, d, e }.Select(ContextTargetIds.NormalizeSingle), StringComparer.OrdinalIgnoreCase);
            var expectedTwo = new HashSet<string>(new[] { a, b, c, d, e }.Select(ContextTargetIds.NormalizeSingle), StringComparer.OrdinalIgnoreCase);
            var expectedThree = new HashSet<string>(new[] { a, b, c }.Select(ContextTargetIds.NormalizeSingle), StringComparer.OrdinalIgnoreCase);

            Check(one.CoveredEntryCount == 5 && one.CoveredEntryIds.All(expectedOne.Contains), "SQLite one-target full-universe coverage is wrong.");
            Check(two.CoveredEntryCount == 5 && two.CoveredEntryIds.All(expectedTwo.Contains), "SQLite two-target participation must require a natural same-sentence partner.");
            Check(three.CoveredEntryCount == 3 && three.CoveredEntryIds.All(expectedThree.Contains), "SQLite three-target participation must require two distinct natural same-sentence partners.");
            Check(!three.CoveredEntryIds.Contains(ContextTargetIds.NormalizeSingle(d)) && !three.CoveredEntryIds.Contains(ContextTargetIds.NormalizeSingle(e)), "A mere two-word pair was incorrectly promoted to three-target coverage.");
            Check(one.UncoveredEntryCount == 5441 && two.UncoveredEntryCount == 5441 && three.UncoveredEntryCount == 5443, "SQLite full-universe gap counts are wrong.");
            Check(sw.Elapsed < TimeSpan.FromSeconds(10), "Three full-5446 SQLite coverage-depth reports exceeded the generous 10-second regression budget.");
            Console.WriteLine($"Context R4c full-5446 depth coverage: one={one.CoveredEntryCount}, two={two.CoveredEntryCount}, three={three.CoveredEntryCount}; elapsed={sw.ElapsedMilliseconds} ms");
        }
        finally
        {
            try { Directory.Delete(root, recursive: true); } catch { }
        }
    }

    private static SentencePack BuildPack(params SentenceRecord[] sentences)
    {
        var pack = new SentencePack
        {
            PackId = "context-depth-self-test",
            Provenance = "synthetic-self-test-only",
            License = "CC0-1.0",
            Sentences = sentences.ToList()
        };
        pack.Validate();
        return pack;
    }

    private static SentenceRecord MakeSentence(string id, string english, IEnumerable<string> targets)
    {
        List<string> targetIds = targets.Select(ContextTargetIds.NormalizeSingle).Distinct(StringComparer.OrdinalIgnoreCase).ToList();
        List<string> tokens = SentenceTokenizer.Tokenize(english).ToList();
        return new SentenceRecord
        {
            Id = id,
            English = english,
            Ukrainian = "Тестове речення.",
            Source = "WordDeck synthetic depth self-test",
            License = "CC0-1.0",
            Tokens = tokens,
            Lemmas = tokens.ToList(),
            TargetEntryIds = targetIds,
            EntryLevels = targetIds.ToDictionary(target => target, _ => "A1", StringComparer.OrdinalIgnoreCase),
            DifficultyLevel = "A1",
            OffListTokenCount = 0,
            QualityFlags = new List<string>()
        };
    }

    private static void Check(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException("Context coverage-depth R4c self-test failed: " + message);
    }

    private sealed class FakeDepthCoverageSource : IContextTargetCountCoverageSource
    {
        private readonly IReadOnlySet<string> _one;
        private readonly IReadOnlySet<string> _two;
        private readonly IReadOnlySet<string> _three;

        public FakeDepthCoverageSource(IEnumerable<string> one, IEnumerable<string> two, IEnumerable<string> three)
        {
            _one = Set(one);
            _two = Set(two);
            _three = Set(three);
        }

        public IReadOnlySet<string> GetCoveredTargetIds(IReadOnlyCollection<string> candidateEntryIds, int requiredTargetCount)
        {
            IReadOnlySet<string> source = requiredTargetCount switch
            {
                1 => _one,
                2 => _two,
                3 => _three,
                _ => throw new ArgumentOutOfRangeException(nameof(requiredTargetCount))
            };
            return new HashSet<string>(candidateEntryIds.Select(ContextTargetIds.NormalizeSingle).Where(source.Contains), StringComparer.OrdinalIgnoreCase);
        }

        private static IReadOnlySet<string> Set(IEnumerable<string> values) =>
            new HashSet<string>(values.Select(ContextTargetIds.NormalizeSingle), StringComparer.OrdinalIgnoreCase);
    }
}
