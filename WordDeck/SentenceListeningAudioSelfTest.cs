using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class SentenceListeningAudioSelfTest
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (!Environment.GetCommandLineArgs().Any(arg => string.Equals(arg, "--self-test", StringComparison.OrdinalIgnoreCase))) return;
        Run();
    }

    private static void Run()
    {
        SentencePack pack = BuildPack();
        var catalog = new FakeCatalog(new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["s1"] = Path.Combine(Path.GetTempPath(), "approved-sentence-s1.mp3")
        });
        var player = new FakePlayer();
        using var source = new SentencePackListeningExerciseSource(pack, catalog, player);

        IReadOnlyList<ListeningExercise> a1 = source.GetAvailable(StudyScopeIds.A1);
        Require(a1.Count == 1 && a1[0].ExerciseId == "sentence:test-pack:s1", "Exact local-audio sentence was not exposed in A1.");
        Require(a1[0].TargetText == "We learn." && a1[0].StableEntryIds.SequenceEqual(new[] { "word-a" }),
            "Sentence Listening adapter lost English text or stable Oxford target IDs.");
        Require(source.GetAvailable(StudyScopeIds.A2).Count == 0, "A1 sentence leaked into A2 Listening scope.");
        Require(source.GetAvailable(StudyScopeIds.All).Count == 1, "Sentence without local audio was incorrectly promoted into All Listening.");

        Require(source.TryPlay(a1[0], out string? error) && error is null && player.LastPath == catalog.Paths["s1"],
            "Sentence Listening adapter did not play the exact resolved local asset.");

        var noAudioExercise = new ListeningExercise(
            "sentence:test-pack:s2", ListeningExerciseKind.Sentence, "Context helps.", "B1", new[] { "word-b" }, "sentence:test-pack:s2");
        Require(!source.TryPlay(noAudioExercise, out string? missingError) && !string.IsNullOrWhiteSpace(missingError),
            "Sentence without installed audio did not fail closed at playback.");

        Console.WriteLine("WordDeck Sentence Listening audio self-test passed: valid SentencePack + exact stable sentence ID + local audio required; missing audio remains unavailable.");
    }

    private static SentencePack BuildPack() => new()
    {
        PackId = "test-pack",
        Provenance = "synthetic-test-fixture-only",
        License = "CC0-1.0-test-fixture",
        SourceLanguage = "en",
        TargetLanguage = "uk",
        Sentences = new List<SentenceRecord>
        {
            new()
            {
                Id = "s1",
                English = "We learn.",
                Ukrainian = "Ми вчимося.",
                Source = "synthetic-test-fixture-only",
                License = "CC0-1.0-test-fixture",
                Tokens = new List<string> { "we", "learn" },
                Lemmas = new List<string> { "we", "learn" },
                TargetEntryIds = new List<string> { "word-a" },
                EntryLevels = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase) { ["word-a"] = "A1" },
                DifficultyLevel = "A1",
                OffListTokenCount = 0
            },
            new()
            {
                Id = "s2",
                English = "Context helps.",
                Ukrainian = "Контекст допомагає.",
                Source = "synthetic-test-fixture-only",
                License = "CC0-1.0-test-fixture",
                Tokens = new List<string> { "context", "helps" },
                Lemmas = new List<string> { "context", "help" },
                TargetEntryIds = new List<string> { "word-b" },
                EntryLevels = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase) { ["word-b"] = "B1" },
                DifficultyLevel = "B1",
                OffListTokenCount = 0
            }
        }
    };

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException("Sentence Listening audio self-test failed: " + message);
    }

    private sealed class FakeCatalog : ISentenceAudioCatalog
    {
        public Dictionary<string, string> Paths { get; }
        public FakeCatalog(Dictionary<string, string> paths) => Paths = paths;
        public bool TryResolve(string packId, string sentenceId, out string? audioPath)
        {
            if (packId == "test-pack" && Paths.TryGetValue(sentenceId, out string? path))
            {
                audioPath = path;
                return true;
            }
            audioPath = null;
            return false;
        }
    }

    private sealed class FakePlayer : IListeningAudioFilePlayer
    {
        public string? LastPath { get; private set; }
        public bool TryPlay(string path, out string? error) { LastPath = path; error = null; return true; }
        public void Dispose() { }
    }
}
