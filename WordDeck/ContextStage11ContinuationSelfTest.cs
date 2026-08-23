using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class ContextStage11ContinuationSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            ContextStage11ContinuationSelfTest.Run();
    }
}

internal static class ContextStage11ContinuationSelfTest
{
    public static void Run()
    {
        TestNamedStudyPools();
        TestTargetFormSentenceSpelling();
        TestMultiwordTargetSpelling();
        TestIntegrationPortsAndPrivateBookBoundary();
        Console.WriteLine("Context Stage-11 continuation self-test PASS: named 30/100/200/full pools, target-form Sentence Spelling, stable-ID ambiguity, and private Reading/Grammar/Story integration ports.");
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
        Check(deduplicated.ActualEntryCount == 40, "Named context pools must preserve stable-ID identity without duplicate rows.");

        ExpectInvalid(
            () => ContextStudyPoolResolver.Create(ContextStudyPoolPreset.Full, Enumerable.Range(1, ContextTargetIds.MaxOxfordTargetPool + 1).Select(i => $"overflow-{i}")),
            "Context pool accepted more than the exact 5446 Oxford bound.");
    }

    private static void TestTargetFormSentenceSpelling()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        var lexicon = new ContextTargetLexicon(dictionary);
        SentenceRecord sentence = MakeSentence(
            "s-target-form",
            "Students improve practical skills every day",
            "Студенти щодня покращують практичні навички",
            new[] { "ox-improve", "ox-skills" },
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                ["ox-improve"] = "B1",
                ["ox-skills"] = "A2"
            });
        RankedContextSentence ranked = Rank(sentence, new[] { "ox-improve", "ox-skills" });

        ContextSentenceTargetSpellingExercise exercise = ContextSentenceTargetSpellingFactory.Create(ranked, "ox-improve", lexicon, dictionary);
        Check(exercise.Prompt.TargetEntryId == "ox-improve", "Target-form Sentence Spelling lost the exact stable Oxford ID.");
        Check(exercise.Prompt.TargetMeaningUkrainian == "покращувати", "Target-form Sentence Spelling lost the target meaning.");
        Check(exercise.Prompt.AmbiguousStableIdentity, "Physical lexical-form ambiguity was not surfaced for a same-form stable-ID pair.");
        Check(exercise.Prompt.EnglishCloze.Contains("[blank]", StringComparison.Ordinal) && !exercise.Prompt.EnglishCloze.Contains("improve", StringComparison.OrdinalIgnoreCase), "Target-form Sentence Spelling leaks the answer in its cloze.");
        Check(exercise.Check("IMPROVE!").Accepted, "Correct target form with harmless case/punctuation normalization was rejected.");
        Check(!exercise.Check("improves").Accepted, "Wrong inflected target form was accepted.");
        Check(!exercise.Check(sentence.English).Accepted, "Target-form Sentence Spelling accidentally accepted the whole sentence instead of only the target form.");
        Check(exercise.RevealExpectedForm() == "improve", "Explicit Show-answer contract returned the wrong target form.");

        IReadOnlyList<ContextSentenceTargetSpellingExercise> all = ContextSentenceTargetSpellingFactory.CreateForAllTargets(ranked, lexicon, dictionary);
        Check(all.Count == 2 && all.Select(item => item.Prompt.TargetEntryId).SequenceEqual(new[] { "ox-improve", "ox-skills" }), "Multi-target context did not expose one stable target-form exercise per requested target.");
    }

    private static void TestMultiwordTargetSpelling()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        var lexicon = new ContextTargetLexicon(dictionary);
        SentenceRecord sentence = MakeSentence(
            "s-multiword",
            "She works full-time today",
            "Вона сьогодні працює повний робочий день",
            new[] { "ox-full-time" },
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase) { ["ox-full-time"] = "B2" });
        RankedContextSentence ranked = Rank(sentence, new[] { "ox-full-time" });
        ContextSentenceTargetSpellingExercise exercise = ContextSentenceTargetSpellingFactory.Create(ranked, "ox-full-time", lexicon, dictionary);

        Check(exercise.Check("full time").Accepted, "Canonical multiword physical target form was rejected.");
        ContextSentenceTargetSpellingResult wrongOrder = exercise.Check("time full");
        Check(!wrongOrder.Accepted && wrongOrder.SameWordsWrongOrder, "Multiword target spelling did not enforce phrase order.");
        Check(exercise.Prompt.EnglishCloze == "she works [blank] today", "Multiword target cloze did not replace the exact contiguous physical form.");
    }

    private static void TestIntegrationPortsAndPrivateBookBoundary()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        SentenceRecord sentence = MakeSentence(
            "s-integration",
            "Students improve skills",
            "Студенти покращують навички",
            new[] { "ox-improve", "ox-skills" },
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                ["ox-improve"] = "B1",
                ["ox-skills"] = "A2"
            },
            qualityFlags: new[] { "grammar:present-simple" });
        RankedContextSentence ranked = Rank(sentence, new[] { "ox-improve" });
        ContextLearningSentenceReference realReference = ContextIntegrationAdapter.FromRanked(ranked);
        Check(realReference.Supports(ContextIntegrationCapabilities.ReadingContext | ContextIntegrationCapabilities.GrammarExample | ContextIntegrationCapabilities.StoryContext), "Ranked real context is not reusable by Reading/Grammar/Story consumers.");
        Check(realReference.Supports(ContextIntegrationCapabilities.SentenceTargetSpelling | ContextIntegrationCapabilities.UkrainianTranslation), "Bilingual ranked context did not advertise Sentence target-spelling capability.");
        Check(realReference.Supports(ContextIntegrationCapabilities.GrammarMetadata) && realReference.GrammarSkillIds.Single() == "present-simple", "Grammar metadata was lost at the neutral context integration boundary.");

        ContextLearningSentenceReference localBook = ContextIntegrationAdapter.FromPrivateLocalReading(
            sentenceId: "book-1-ch-2-s-8",
            english: "A quiet local book sentence",
            stableEntryIds: new[] { "ox-skills" },
            sourceId: "local-book-1",
            provenance: "User-imported local book text",
            licenseOrRightsBasis: "private-local-user-content; redistribution-not-authorized",
            bookId: "book-1",
            chapterId: "chapter-2",
            startOffset: 120,
            endOffset: 147);
        Check(localBook.Source.Kind == ContextCorpusKind.LocalUserText && localBook.Source.PrivacyLocalOnly, "Book integration escaped the private-local default.");
        Check(localBook.Supports(ContextIntegrationCapabilities.ReadingContext | ContextIntegrationCapabilities.LocalReadingPosition), "Book integration lost reading-position capability.");
        Check(!localBook.Supports(ContextIntegrationCapabilities.SentenceTargetSpelling) && !localBook.Supports(ContextIntegrationCapabilities.UkrainianTranslation), "English-only local book text was incorrectly promoted to bilingual Sentence Spelling evidence.");
        Check(localBook.LocalTextLocation is not null && localBook.LocalTextLocation.StartOffset == 120 && localBook.LocalTextLocation.EndOffset == 147, "Book source/chapter/offset identity was lost at the context integration boundary.");

        _ = dictionary;
    }

    private static DictionaryPackage FixtureDictionary() => new()
    {
        Id = "context-stage11-fixture",
        Name = "Context Stage 11 fixture",
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
        IReadOnlyList<string> targets,
        Dictionary<string, string> levels,
        IReadOnlyList<string>? qualityFlags = null)
    {
        IReadOnlyList<string> tokens = SentenceTokenizer.Tokenize(english);
        var sentence = new SentenceRecord
        {
            Id = id,
            English = english,
            Ukrainian = ukrainian,
            Source = "Synthetic Stage-11 continuation self-test fixture",
            License = "internal-test-only",
            Tokens = tokens.ToList(),
            Lemmas = tokens.ToList(),
            TargetEntryIds = targets.ToList(),
            EntryLevels = levels,
            DifficultyLevel = "B1",
            OffListTokenCount = 0,
            QualityFlags = qualityFlags?.ToList() ?? new List<string>()
        };
        sentence.Validate();
        return sentence;
    }

    private static RankedContextSentence Rank(SentenceRecord sentence, IReadOnlyList<string> requiredTargets)
    {
        var source = new ContextSourceDescriptor(
            "context-stage11-self-test",
            ContextCorpusKind.SyntheticFixture,
            "Synthetic Stage-11 continuation self-test fixture",
            "internal-test-only");
        var envelope = new ContextSentenceEnvelope(
            sentence,
            source,
            null,
            ContextGrammarMetadata.ExtractFromQualityFlags(sentence.QualityFlags));
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
