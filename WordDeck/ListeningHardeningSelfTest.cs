using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class ListeningHardeningSelfTest
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (!Environment.GetCommandLineArgs().Any(arg => string.Equals(arg, "--self-test", StringComparison.OrdinalIgnoreCase))) return;
        Run();
    }

    private static void Run()
    {
        TestHiddenWordAndScopeFiltering();
        TestReplayPolicyIsEnforcedByEngine();
        TestRevealDoesNotCreateCorrectMastery();
        Console.WriteLine("WordDeck Listening hardening self-test passed: hidden words/scopes, replay policy and reveal/mastery separation validated.");
    }

    private static void TestHiddenWordAndScopeFiltering()
    {
        var entries = new[]
        {
            new DictionaryEntry("a", "A1", "alpha", "альфа"),
            new DictionaryEntry("b", "A2", "bravo", "браво"),
            new DictionaryEntry("c", "A1", "charlie", "чарлі")
        };
        var hidden = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "c" };
        var withAudio = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "a", "b", "c" };

        IReadOnlyList<DictionaryEntry> a1 = WordAudioListeningExerciseSource.EligibleEntries(
            entries,
            StudyScopeIds.A1,
            hidden,
            entry => withAudio.Contains(entry.Id));

        Require(a1.Select(entry => entry.Id).SequenceEqual(new[] { "a" }),
            "Hidden word or CEFR scope leaked into Listening eligibility.");

        withAudio.Remove("a");
        a1 = WordAudioListeningExerciseSource.EligibleEntries(entries, StudyScopeIds.A1, hidden, entry => withAudio.Contains(entry.Id));
        Require(a1.Count == 0, "Word without installed audio remained Listening-eligible.");
    }

    private static void TestReplayPolicyIsEnforcedByEngine()
    {
        DictionaryPackage package = Package();
        var contract = new ListeningAudioContract(
            "asset:a",
            ListeningAudioUnitKind.Word,
            "en-GB",
            null,
            "test",
            Array.Empty<ListeningSpeakerMetadata>(),
            new ListeningTranscriptContract("alpha", ListeningTranscriptAvailability.AfterReveal, Array.Empty<ListeningTranscriptTurn>()),
            ListeningReplayPolicy.OneReplayAssessment,
            new[] { new ListeningComprehensionPrompt("dictation:a", ListeningComprehensionKind.Dictation, "Transcribe.", new[] { "alpha" }) },
            ApprovedForProduction: true);
        contract.Validate();

        var exercise = new ListeningExercise("word:a", ListeningExerciseKind.Word, "alpha", "A1", new[] { "a" }, "a", contract);
        using var source = new FakeSource(new[] { exercise });
        var engine = new ListeningCoachEngine(package, new ListeningCoachState { ActiveScopeId = StudyScopeIds.A1 }, source);
        _ = engine.StartNext(false);

        Require(engine.TryPlayCurrent(countAsReplay: false, out _), "Initial audio play was unexpectedly blocked by replay policy.");
        Require(engine.TryPlayCurrent(countAsReplay: true, out _), "Allowed first replay was blocked.");
        Require(!engine.TryPlayCurrent(countAsReplay: true, out string? error) && !string.IsNullOrWhiteSpace(error),
            "Replay maximum was not enforced by the engine.");
        Require(engine.State.StatsByDictionary[package.Id]["word:a"].ReplayCount == 1,
            "Blocked replay incorrectly mutated replay statistics.");
    }

    private static void TestRevealDoesNotCreateCorrectMastery()
    {
        DictionaryPackage package = Package();
        var exercise = new ListeningExercise("word:a", ListeningExerciseKind.Word, "alpha", "A1", new[] { "a" }, "a");
        using var source = new FakeSource(new[] { exercise });
        var state = new ListeningCoachState { ActiveScopeId = StudyScopeIds.A1 };
        var engine = new ListeningCoachEngine(package, state, source);
        _ = engine.StartNext(false);
        string shown = engine.ShowAnswer();

        ListeningItemStats stats = state.StatsByDictionary[package.Id]["word:a"];
        Require(shown == "alpha", "Explicit reveal returned the wrong answer.");
        Require(stats.CompletedReviews == 1 && stats.CorrectReviews == 0 && stats.ShowAnswerUses == 1,
            "Reveal was incorrectly counted as a correct Listening review.");
        Require(engine.Mastery("word:a") == 0d,
            "Reveal incorrectly produced Listening mastery.");
        Require(state.History.Count == 1 && state.History[0].ShowedAnswer && !state.History[0].Correct,
            "Reveal history did not preserve separate non-mastery evidence.");
    }

    private static DictionaryPackage Package() => new()
    {
        Id = "test-dictionary",
        Name = "Test",
        SourceLanguage = "en",
        TargetLanguage = "uk",
        Entries = new[] { new DictionaryEntry("a", "A1", "alpha", "альфа") }
    };

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException("Listening hardening self-test failed: " + message);
    }

    private sealed class FakeSource : IListeningExerciseSource
    {
        private readonly IReadOnlyList<ListeningExercise> _items;
        public FakeSource(IReadOnlyList<ListeningExercise> items) => _items = items;
        public IReadOnlyList<ListeningExercise> GetAvailable(string scopeId) => _items;
        public bool TryPlay(ListeningExercise exercise, out string? error) { error = null; return true; }
        public void Dispose() { }
    }
}
