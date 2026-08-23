using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class ContextTargetSpellingSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            ContextTargetSpellingSelfTest.Run();
    }
}

internal static class ContextTargetSpellingSelfTest
{
    public static void Run()
    {
        TestSingleTargetExactPhysicalForm();
        TestThreeTargetCardCreatesThreeExercises();
        TestMultiwordOrder();
        TestMorphologyFailsClosed();
        Console.WriteLine("Context target-spelling self-test PASS: target-only answers, 1/2/3 stable IDs, multiword order, ambiguity and morphology fail-closed verified.");
    }

    private static void TestSingleTargetExactPhysicalForm()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        var lexicon = new ContextTargetLexicon(dictionary);
        ContextPracticeCard card = Card(
            "s-improve",
            "Студенти щодня покращують навички",
            "Students improve practical skills every day",
            new[] { "ox-improve", "ox-skills" },
            new[] { "improve", "skills" });

        ContextTargetSpellingExercise exercise = ContextTargetSpellingService.Build(card, "ox-improve", lexicon, dictionary);
        Check(exercise.Prompt.FocusTargetEntryId == "ox-improve", "Target spelling lost the exact stable Oxford ID.");
        Check(exercise.Prompt.TargetMeaningUkrainian == "покращувати", "Target spelling lost the Ukrainian target meaning.");
        Check(exercise.Prompt.AmbiguousStableIdentity, "Same-written-form stable-ID ambiguity was not surfaced.");
        Check(exercise.Prompt.EnglishCloze.Contains("[blank]", StringComparison.Ordinal) && !exercise.Prompt.EnglishCloze.Contains("improve", StringComparison.OrdinalIgnoreCase), "Target spelling cloze leaks its answer.");
        Check(exercise.Check("IMPROVE!").Accepted, "Correct target form with harmless case/punctuation normalization was rejected.");
        Check(!exercise.Check("improves").Accepted, "Wrong inflected target form was accepted.");
        Check(!exercise.Check(card.EnglishAnswer).Accepted, "Target spelling accidentally accepted the whole English sentence.");
        Check(exercise.RevealExpectedForm() == "improve", "Show-answer target form is wrong.");
        Check(exercise.Prompt.SourceKind == ContextCorpusKind.SyntheticFixture && exercise.Prompt.Provenance.Contains("self-test", StringComparison.OrdinalIgnoreCase), "Test fixture provenance boundary was lost.");
    }

    private static void TestThreeTargetCardCreatesThreeExercises()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        var lexicon = new ContextTargetLexicon(dictionary);
        ContextPracticeCard card = Card(
            "s-three",
            "Студенти вивчають корисні слова",
            "Students learn useful words",
            new[] { "ox-students", "ox-learn", "ox-words" },
            new[] { "students", "learn", "words" });

        IReadOnlyList<ContextTargetSpellingExercise> all = ContextTargetSpellingService.BuildAllTargets(card, lexicon, dictionary);
        Check(all.Count == 3, "A natural three-target context card did not expose three target-form spelling exercises.");
        Check(all.Select(item => item.Prompt.FocusTargetEntryId).SequenceEqual(new[] { "ox-students", "ox-learn", "ox-words" }), "Three-target spelling changed stable target order/identity.");
        Check(all.All(item => item.Prompt.EnglishCloze.Contains("[blank]", StringComparison.Ordinal)), "One of the three target forms was not physically present in the sentence.");
    }

    private static void TestMultiwordOrder()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        var lexicon = new ContextTargetLexicon(dictionary);
        ContextPracticeCard card = Card(
            "s-full-time",
            "Вона сьогодні працює повний робочий день",
            "She works full-time today",
            new[] { "ox-full-time" },
            new[] { "full time" });

        ContextTargetSpellingExercise exercise = ContextTargetSpellingService.Build(card, "ox-full-time", lexicon, dictionary);
        Check(exercise.Check("full time").Accepted, "Canonical multiword physical target form was rejected.");
        ContextTargetSpellingResult wrongOrder = exercise.Check("time full");
        Check(!wrongOrder.Accepted && wrongOrder.SameWordsWrongOrder, "Multiword target spelling did not enforce phrase order.");
        Check(exercise.Prompt.EnglishCloze == "she works [blank] today", "Multiword target cloze did not replace the exact contiguous lexical form.");
    }

    private static void TestMorphologyFailsClosed()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        var lexicon = new ContextTargetLexicon(dictionary);
        ContextPracticeCard card = Card(
            "s-run",
            "Вона бігає щодня",
            "She runs daily",
            new[] { "ox-run" },
            new[] { "run" });

        bool rejected = false;
        try { _ = ContextTargetSpellingService.Build(card, "ox-run", lexicon, dictionary); }
        catch (InvalidDataException ex)
        {
            rejected = ex.Message.Contains("fails closed", StringComparison.OrdinalIgnoreCase);
        }
        Check(rejected, "Target spelling guessed an inflected/morphological realization that current SentencePack metadata does not prove.");
    }

    private static DictionaryPackage FixtureDictionary() => new()
    {
        Id = "context-target-spelling-self-test",
        Name = "Context target spelling self-test",
        SourceLanguage = "en",
        TargetLanguage = "uk",
        Entries = new DictionaryEntry[]
        {
            new("ox-improve", "B1", "improve", "покращувати"),
            new("ox-improve-alt", "B1", "improve", "поліпшувати"),
            new("ox-skills", "A2", "skills", "навички"),
            new("ox-students", "A2", "students", "студенти"),
            new("ox-learn", "A1", "learn", "вивчати"),
            new("ox-words", "A1", "words", "слова"),
            new("ox-full-time", "B2", "full-time", "повний робочий день"),
            new("ox-run", "A1", "run", "бігати")
        }
    };

    private static ContextPracticeCard Card(
        string sentenceId,
        string ukrainian,
        string english,
        IReadOnlyList<string> targetIds,
        IReadOnlyList<string> lexicalKeys) => new(
            sentenceId,
            ukrainian,
            english,
            targetIds,
            lexicalKeys,
            new ContextDifficultyBreakdown(0, 0, 0, 0, 1, SentenceTokenizer.Tokenize(english).Count, 1, "synthetic self-test only"),
            "context-target-spelling-self-test",
            ContextCorpusKind.SyntheticFixture,
            "Synthetic target-spelling self-test fixture",
            "internal-test-only",
            false,
            null,
            Array.Empty<string>(),
            false);

    private static void Check(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException(message);
    }
}
