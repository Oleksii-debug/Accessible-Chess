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

        TestLocalFileAloneDoesNotActivate(pack, catalog);
        TestExplicitApprovalAndMissingAudio(pack, catalog);
        TestHiddenTargetFailsClosed(pack, catalog);

        Console.WriteLine("WordDeck Sentence Listening audio self-test passed: explicit pack approval + exact stable sentence ID + local audio required; hidden targets and missing audio remain unavailable.");
    }

    private static void TestLocalFileAloneDoesNotActivate(SentencePack pack, FakeCatalog catalog)
    {
        var player = new FakePlayer();
        using var source = new SentencePackListeningExerciseSource(
            pack,
            catalog,
            player,
            approval: null,
            hiddenEntryIds: new HashSet<string>(StringComparer.OrdinalIgnoreCase));

        Require(source.GetAvailable(StudyScopeIds.All).Count == 0,
            "Local sentence audio activated without explicit approved-pack evidence.");
        var candidate = new ListeningExercise(
            "sentence:test-pack:s1", ListeningExerciseKind.Sentence, "We learn.", "A1", new[] { "word-a" }, "sentence:test-pack:s1");
        Require(!source.TryPlay(candidate, out string? error) && !string.IsNullOrWhiteSpace(error),
            "Unapproved sentence pack was playable merely because a local file resolved.");
        Require(player.LastPath is null, "Unapproved sentence audio reached the file player.");
    }

    private static void TestExplicitApprovalAndMissingAudio(SentencePack pack, FakeCatalog catalog)
    {
        var player = new FakePlayer();
        var approval = new ListeningAudioPackApproval("test-pack", "TEST-ONLY-APPROVAL", true);
        using var source = new SentencePackListeningExerciseSource(
            pack,
            catalog,
            player,
            approval,
            new HashSet<string>(StringComparer.OrdinalIgnoreCase));

        IReadOnlyList<ListeningExercise> a1 = source.GetAvailable(StudyScopeIds.A1);
        Require(a1.Count == 1 && a1[0].ExerciseId == "sentence:test-pack:s1", "Approved exact local-audio sentence was not exposed in A1.");
        Require(a1[0].TargetText == "We learn." && a1[0].StableEntryIds.SequenceEqual(new[] { "word-a" }),
            "Sentence Listening adapter lost English text or stable Oxford target IDs.");
        Require(a1[0].AudioContract is { ApprovedForProduction: true, UnitKind: ListeningAudioUnitKind.Sentence },
            "Approved sentence did not carry its presentation-neutral audio contract.");
        Require(source.GetAvailable(StudyScopeIds.A2).Count == 0, "A1 sentence leaked into A2 Listening scope.");
        Require(source.GetAvailable(StudyScopeIds.All).Count == 1, "Sentence without local audio was incorrectly promoted into All Listening.");

        Require(source.TryPlay(a1[0], out string? error) && error is null && player.LastPath == catalog.Paths["s1"],
            "Sentence Listening adapter did not play the exact resolved local asset after explicit approval.");

        var noAudioExercise = new ListeningExercise(
            "sentence:test-pack:s2", ListeningExerciseKind.Sentence, "Context helps.", "B1", new[] { "word-b" }, "sentence:test-pack:s2");
        Require(!source.TryPlay(noAudioExercise, out string? missingError) && !string.IsNullOrWhiteSpace(missingError),
            "Sentence without installed audio did not fail closed at playback.");
    }

    private static void TestHiddenTargetFailsClosed(SentencePack pack, FakeCatalog catalog)
    {
        var player = new FakePlayer();
        var approval = new ListeningAudioPackApproval("test-pack", "TEST-ONLY-APPROVAL", true);
        var hidden = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "word-a" };
        using var source = new SentencePackListeningExerciseSource(pack, catalog, player, approval, hidden);

        Require(source.GetAvailable(StudyScopeIds.A1).Count == 0,
            "Sentence containing a hidden target remained available.");
        var hiddenExercise = new ListeningExercise(
            "sentence:test-pack:s1", ListeningExerciseKind.Sentence, "We learn.", "A1", new[] { "word-a" }, "sentence:test-pack:s1");
        Require(!source.TryPlay(hiddenExercise, out string? error) && !string.IsNullOrWhiteSpace(error),
            "Sentence containing a hidden target remained directly playable.");
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
