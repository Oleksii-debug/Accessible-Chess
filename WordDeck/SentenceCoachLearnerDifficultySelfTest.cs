using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class SentenceCoachLearnerDifficultySelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (!Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            return;

        var dictionary = new DictionaryPackage
        {
            Id = "sentence-known-context-self-test",
            Name = "Sentence known-context self-test",
            SourceLanguage = "en",
            TargetLanguage = "uk",
            Entries = new List<DictionaryEntry>
            {
                new("target-learn", "A1", "learn", "вивчати"),
                new("helper-easy", "A1", "easy", "легкий"),
                new("helper-obscure", "B2", "obscure", "маловідомий")
            }
        };
        var lexicon = new ContextTargetLexicon(dictionary);
        SentenceRecord knownSentence = MakeSentence("s-known", "Learn easy", "Вивчай легке", "helper-easy", "A1");
        SentenceRecord unknownSentence = MakeSentence("s-unknown", "Learn obscure", "Вивчай маловідоме", "helper-obscure", "B2");
        var pack = new SentencePack
        {
            PackId = "known-context-fixture",
            Provenance = "Synthetic learner-ranking self-test fixture",
            License = "internal-test-only",
            Sentences = new List<SentenceRecord> { unknownSentence, knownSentence }
        };
        pack.Validate();

        DictionaryEntry anchor = dictionary.Entries.Single(entry => entry.Id == "target-learn");
        IReadOnlyList<SentenceCoachTargetSetCandidate> variants = SentenceCoachTargetOnlyPlanner.FindNaturalTargetSets(
            pack,
            anchor,
            dictionary.Entries,
            lexicon,
            1,
            maxSets: 10);
        Require(variants.Select(item => item.EvidenceSentenceId).ToHashSet(StringComparer.OrdinalIgnoreCase).SetEquals(new[] { "s-known", "s-unknown" }),
            "Planner collapsed distinct real sentence evidence for the same one-target set before learner-aware ranking.");

        var context = new SentenceSelectionContext(
            new HashSet<string>(dictionary.Entries.Select(entry => entry.Id), StringComparer.OrdinalIgnoreCase),
            new HashSet<string>(new[] { "target-learn", "helper-easy" }, StringComparer.OrdinalIgnoreCase),
            new HashSet<string>(StringComparer.OrdinalIgnoreCase),
            dictionary.Entries.ToDictionary(entry => entry.Id, entry => entry.Level, StringComparer.OrdinalIgnoreCase));
        int knownScore = SentenceSelector.Score(knownSentence, new[] { "target-learn" }, context);
        int unknownScore = SentenceSelector.Score(unknownSentence, new[] { "target-learn" }, context);
        Require(knownScore < unknownScore,
            $"Learner-known vocabulary did not outrank an unknown helper context. known={knownScore}; unknown={unknownScore}");

        Console.WriteLine("Sentence Coach learner-difficulty self-test PASS: same-target sentence variants survive planning and learner-known context ranks ahead of unknown context.");
    }

    private static SentenceRecord MakeSentence(string id, string english, string ukrainian, string helperId, string helperLevel)
    {
        IReadOnlyList<string> tokens = SentenceTokenizer.Tokenize(english);
        return new SentenceRecord
        {
            Id = id,
            English = english,
            Ukrainian = ukrainian,
            Source = "Synthetic learner-ranking self-test fixture",
            License = "internal-test-only",
            Tokens = tokens.ToList(),
            Lemmas = tokens.ToList(),
            TargetEntryIds = new List<string> { "target-learn", helperId },
            EntryLevels = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                ["target-learn"] = "A1",
                [helperId] = helperLevel
            },
            DifficultyLevel = helperLevel,
            OffListTokenCount = 0,
            QualityFlags = new List<string>()
        };
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException("Sentence Coach learner-difficulty self-test failed: " + message);
    }
}
