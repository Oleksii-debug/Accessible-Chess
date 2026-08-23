using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class ContextStage11StudySpellingSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            ContextStage11StudySpellingSelfTest.Run();
    }
}

internal static class ContextStage11StudySpellingSelfTest
{
    public static void Run()
    {
        TestNamedStudyPools();
        TestResolvedTargetSpelling();
        TestAmbiguousTargetFailsClosed();
        TestMultiwordTargetSpelling();
        TestIndexedButMissingPhysicalFormFailsClosed();
        Console.WriteLine("Context Stage-11 study/spelling self-test PASS: 30/100/200/full pools and resolved target-form Sentence Spelling are deterministic and homographs fail closed.");
    }

    private static void TestNamedStudyPools()
    {
        string[] ids = Enumerable.Range(1, 250).Select(i => $"entry-{i:D4}").ToArray();
        ContextStudyPool thirty = ContextStudyPoolResolver.Create(ContextStudyPoolPreset.Thirty, ids);
        ContextStudyPool hundred = ContextStudyPoolResolver.Create(ContextStudyPoolPreset.Hundred, ids);
        ContextStudyPool twoHundred = ContextStudyPoolResolver.Create(ContextStudyPoolPreset.TwoHundred, ids);
        ContextStudyPool full = ContextStudyPoolResolver.Create(ContextStudyPoolPreset.Full, ids);

        Check(thirty.ActualEntryCount == 30 && thirty.Truncated && thirty.EntryIds[0] == "entry-0001" && thirty.EntryIds[^1] == "entry-0030", "30-word context pool is not deterministic.");
        Check(hundred.ActualEntryCount == 100 && hundred.Truncated, "100-word context pool size is wrong.");
        Check(twoHundred.ActualEntryCount == 200 && twoHundred.Truncated, "200-word context pool size is wrong.");
        Check(full.ActualEntryCount == 250 && !full.Truncated && full.RequestedLimit is null, "Full context pool should retain the complete ordered source scope.");

        ContextStudyPool shortPool = ContextStudyPoolResolver.Create(ContextStudyPoolPreset.Thirty, ids.Take(12));
        Check(shortPool.ActualEntryCount == 12 && !shortPool.Truncated, "A short deck must not invent filler entries to reach a preset limit.");

        string[] withDuplicate = ids.Take(40).Concat(new[] { "ENTRY-0001" }).ToArray();
        ContextStudyPool deduplicated = ContextStudyPoolResolver.Create(ContextStudyPoolPreset.Full, withDuplicate);
        Check(deduplicated.ActualEntryCount == 40, "Named context pools must deduplicate stable IDs deterministically.");
        Check(ContextStudyPoolResolver.ParsePersisted("hundred") == ContextStudyPoolPreset.Hundred, "Persisted study-pool preset parsing is not case-insensitive.");
        Check(ContextStudyPoolResolver.ParsePersisted("future-unknown-value") == ContextStudyPoolPreset.Full, "Unknown persisted study-pool preset must fail safely to Full.");

        ExpectInvalid(
            () => ContextStudyPoolResolver.Create(ContextStudyPoolPreset.Full, Enumerable.Range(1, ContextTargetIds.MaxOxfordTargetPool + 1).Select(i => $"overflow-{i}")),
            "Context pool accepted more than the exact 5446 Oxford bound.");
    }

    private static void TestResolvedTargetSpelling()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        var lexicon = new ContextTargetLexicon(dictionary);
        SentenceRecord sentence = MakeSentence(
            "s-target-form",
            "Students improve practical skills every day",
            "Студенти щодня покращують практичні навички",
            new[] { "ox-improve", "ox-skills" });
        RankedContextSentence ranked = Rank(sentence, new[] { "ox-skills" });

        ContextSentenceTargetSpellingExercise exercise = ContextSentenceTargetSpellingFactory.Create(ranked, "ox-skills", lexicon, dictionary);
        Check(exercise.Prompt.TargetEntryId == "ox-skills", "Target-form Sentence Spelling lost the exact stable Oxford ID.");
        Check(exercise.Prompt.TargetMeaningUkrainian == "навички", "Target-form Sentence Spelling lost the target meaning.");
        Check(!exercise.Prompt.AmbiguousStableIdentity, "A product-ready target-form exercise was incorrectly marked ambiguous.");
        Check(exercise.Prompt.EnglishCloze.Contains("[blank]", StringComparison.Ordinal) && !exercise.Prompt.EnglishCloze.Contains("skills", StringComparison.OrdinalIgnoreCase), "Target-form Sentence Spelling leaks the answer in its cloze.");
        Check(exercise.Check("SKILLS!").Accepted, "Correct target form with harmless case/punctuation normalization was rejected.");
        Check(!exercise.Check("skill").Accepted, "Wrong target form was accepted.");
        Check(!exercise.Check(sentence.English).Accepted, "Target-form Sentence Spelling accepted the whole sentence instead of only the target form.");
        Check(exercise.RevealExpectedForm() == "skills", "Explicit Show-answer contract returned the wrong target form.");
    }

    private static void TestAmbiguousTargetFailsClosed()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        var lexicon = new ContextTargetLexicon(dictionary);
        SentenceRecord sentence = MakeSentence(
            "s-ambiguous",
            "Students improve skills",
            "Студенти покращують навички",
            new[] { "ox-improve", "ox-improve-alt", "ox-skills" });
        RankedContextSentence ranked = Rank(sentence, new[] { "ox-improve" });

        bool blocked = false;
        try
        {
            _ = ContextSentenceTargetSpellingFactory.Create(ranked, "ox-improve", lexicon, dictionary);
        }
        catch (InvalidDataException ex)
        {
            blocked = ex.Message.Contains("POS/sense", StringComparison.OrdinalIgnoreCase) &&
                      ex.Message.Contains("ox-improve-alt", StringComparison.OrdinalIgnoreCase);
        }
        Check(blocked, "Sentence Spelling allowed a homographic stable ID to own progress without POS/sense evidence.");
    }

    private static void TestMultiwordTargetSpelling()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        var lexicon = new ContextTargetLexicon(dictionary);
        SentenceRecord sentence = MakeSentence(
            "s-multiword",
            "She works full-time today",
            "Вона сьогодні працює повний робочий день",
            new[] { "ox-full-time" });
        RankedContextSentence ranked = Rank(sentence, new[] { "ox-full-time" });
        ContextSentenceTargetSpellingExercise exercise = ContextSentenceTargetSpellingFactory.Create(ranked, "ox-full-time", lexicon, dictionary);

        Check(exercise.Check("full time").Accepted, "Canonical multiword physical target form was rejected.");
        ContextSentenceTargetSpellingResult wrongOrder = exercise.Check("time full");
        Check(!wrongOrder.Accepted && wrongOrder.SameWordsWrongOrder, "Multiword target spelling did not enforce phrase order.");
        Check(exercise.Prompt.EnglishCloze == "she works [blank] today", "Multiword target cloze did not replace the exact contiguous physical form.");
    }

    private static void TestIndexedButMissingPhysicalFormFailsClosed()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        var lexicon = new ContextTargetLexicon(dictionary);
        SentenceRecord sentence = MakeSentence(
            "s-mismatch",
            "They improve daily",
            "Вони вдосконалюються щодня",
            new[] { "ox-skills" });
        RankedContextSentence ranked = Rank(sentence, new[] { "ox-skills" });
        ExpectInvalid(
            () => ContextSentenceTargetSpellingFactory.Create(ranked, "ox-skills", lexicon, dictionary),
            "Sentence Spelling guessed a target form when the indexed lexical form was absent from the physical token stream.");
    }

    private static DictionaryPackage FixtureDictionary() => new()
    {
        Id = "context-stage11-spelling-fixture",
        Name = "Context Stage 11 spelling fixture",
        SourceLanguage = "en",
        TargetLanguage = "uk",
        Entries = new DictionaryEntry[]
        {
            new("ox-improve", "B1", "improve", "покращувати"),
            new("ox-improve-alt", "B1", "improve", "поліпшувати"),
            new("ox-skills", "A2", "skills", "навички"),
            new("ox-full-time", "B2", "full-time", "повний робочий день")
        }
    };

    private static SentenceRecord MakeSentence(
        string id,
        string english,
        string ukrainian,
        IReadOnlyList<string> targets)
    {
        IReadOnlyList<string> tokens = SentenceTokenizer.Tokenize(english);
        var levels = targets.ToDictionary(id => id, _ => "B1", StringComparer.OrdinalIgnoreCase);
        var sentence = new SentenceRecord
        {
            Id = id,
            English = english,
            Ukrainian = ukrainian,
            Source = "Synthetic Stage-11 study/spelling self-test fixture",
            License = "internal-test-only",
            Tokens = tokens.ToList(),
            Lemmas = tokens.ToList(),
            TargetEntryIds = targets.ToList(),
            EntryLevels = levels,
            DifficultyLevel = "B1",
            OffListTokenCount = 0,
            QualityFlags = new List<string>()
        };
        sentence.Validate();
        return sentence;
    }

    private static RankedContextSentence Rank(SentenceRecord sentence, IReadOnlyList<string> requiredTargets)
    {
        var source = new ContextSourceDescriptor(
            "context-stage11-study-spelling-self-test",
            ContextCorpusKind.SyntheticFixture,
            "Synthetic Stage-11 study/spelling self-test fixture",
            "internal-test-only");
        var envelope = new ContextSentenceEnvelope(sentence, source);
        var difficulty = new ContextDifficultyBreakdown(0, 0, 0, 0, 1, sentence.Length, 1, "fixture");
        return new RankedContextSentence(envelope, requiredTargets, difficulty);
    }

    private static void ExpectInvalid(Action action, string message)
    {
        bool rejected = false;
        try { action(); }
        catch (InvalidDataException) { rejected = true; }
        Check(rejected, message);
    }

    private static void Check(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException(message);
    }
}
