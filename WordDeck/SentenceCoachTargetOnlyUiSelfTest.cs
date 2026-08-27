using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class SentenceCoachTargetOnlyUiSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            SentenceCoachTargetOnlyUiSelfTest.Run();
    }
}

internal static class SentenceCoachTargetOnlyUiSelfTest
{
    public static void Run()
    {
        TestThreeTargetSequentialSession();
        TestThreeTargetResumePosition();
        TestThreeTargetStateNormalization();
        TestPlannerRejectsAmbiguousHomograph();
        Console.WriteLine("Sentence Coach target-only UI self-test PASS: reachable sequential 1/2/3 target semantics, restart position, state normalization and homograph fail-closed planning verified.");
    }

    private static void TestThreeTargetSequentialSession()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        var lexicon = new ContextTargetLexicon(dictionary);
        SentenceRecord sentence = Sentence(
            "s-three",
            "Students learn useful words",
            "Студенти вивчають корисні слова",
            new[] { "ox-students", "ox-learn", "ox-words" });
        List<DictionaryEntry> targets = TargetEntries(dictionary);

        SentenceCoachTargetOnlySession session = BuildSession(sentence, targets, lexicon, dictionary);
        if (session.TargetCount != 3 || session.CurrentPrompt().TargetNumber != 1 || session.CurrentTargetIndex != 0)
            throw new InvalidOperationException("Three-target UI session did not start at target 1 of 3.");
        if (session.Check(sentence.English).Accepted)
            throw new InvalidOperationException("Target-only UI session accepted the whole English sentence.");
        if (!session.Check("students").Accepted || session.CurrentPrompt().TargetNumber != 2)
            throw new InvalidOperationException("Target-only UI session did not advance to target 2 after an exact target answer.");
        if (!session.Check("learn").Accepted || session.CurrentPrompt().TargetNumber != 3)
            throw new InvalidOperationException("Target-only UI session did not advance to target 3.");
        SentenceCoachTargetOnlyCheck final = session.Check("words");
        if (!final.Accepted || !final.SentenceComplete || !session.Complete)
            throw new InvalidOperationException("Target-only UI session did not complete after all three exact target forms.");
    }

    private static void TestThreeTargetResumePosition()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        var lexicon = new ContextTargetLexicon(dictionary);
        SentenceRecord sentence = Sentence(
            "s-resume",
            "Students learn useful words",
            "Студенти вивчають корисні слова",
            new[] { "ox-students", "ox-learn", "ox-words" });
        SentenceCoachTargetOnlySession resumed = BuildSession(sentence, TargetEntries(dictionary), lexicon, dictionary, startTargetIndex: 1);
        if (resumed.CurrentTargetIndex != 1 || resumed.CurrentPrompt().TargetNumber != 2 || resumed.CurrentPrompt().TargetEntryId != "ox-learn")
            throw new InvalidOperationException("Target-only session did not restore the persisted second target.");
        if (!resumed.Check("learn").Accepted || resumed.CurrentPrompt().TargetEntryId != "ox-words")
            throw new InvalidOperationException("Resumed target-only session did not continue from the persisted position.");
    }

    private static void TestThreeTargetStateNormalization()
    {
        var state = new SentenceCoachState
        {
            TargetCount = 3,
            CurrentSentenceId = "s-state",
            CurrentTargetEntryIds = new List<string> { "ox-students", "ox-learn", "ox-words", "ignored-fourth" },
            CurrentTargetIndex = 2,
            CurrentTargetHadWrong = true,
            CurrentTargetUsedHint = true
        };
        SentenceCoachStateStore.Normalize(state);
        if (state.TargetCount != 3 || state.CurrentTargetEntryIds.Count != 3 || state.CurrentTargetIndex != 2 ||
            !state.CurrentTargetHadWrong || !state.CurrentTargetUsedHint)
            throw new InvalidOperationException("Sentence Coach state normalization did not preserve a valid three-target restart position and learning flags.");

        state.CurrentTargetEntryIds.Clear();
        state.CurrentTargetEntryId = null;
        SentenceCoachStateStore.Normalize(state);
        if (state.CurrentTargetIndex != 0 || state.CurrentTargetHadWrong || state.CurrentTargetUsedHint)
            throw new InvalidOperationException("Sentence Coach state normalization did not clear stale per-target restart flags with an empty current exercise.");
    }

    private static void TestPlannerRejectsAmbiguousHomograph()
    {
        DictionaryPackage dictionary = FixtureDictionary(includeAmbiguousRun: true);
        var lexicon = new ContextTargetLexicon(dictionary);
        SentenceRecord sentence = Sentence(
            "s-run",
            "Students run daily",
            "Студенти бігають щодня",
            new[] { "ox-students", "ox-run-verb", "ox-run-noun" });
        var pack = new SentencePack
        {
            PackId = "fixture-pack",
            Provenance = "Synthetic target-only planner fixture",
            License = "internal-test-only",
            Sentences = new List<SentenceRecord> { sentence }
        };
        pack.Validate();

        IReadOnlyList<DictionaryEntry> resolved = SentenceCoachTargetOnlyPlanner.ResolvedScope(dictionary.Entries, lexicon);
        if (resolved.Any(entry => entry.Id.StartsWith("ox-run-", StringComparison.Ordinal)))
            throw new InvalidOperationException("Resolved UI scope retained an unresolved same-written-form homograph.");
        DictionaryEntry ambiguousAnchor = dictionary.Entries.Single(entry => entry.Id == "ox-run-verb");
        if (SentenceCoachTargetOnlyPlanner.FindNaturalTargetSets(pack, ambiguousAnchor, dictionary.Entries, lexicon, 1).Count != 0)
            throw new InvalidOperationException("Reachable target-only UI planner allowed an unresolved homograph anchor to earn a target set.");
    }

    private static SentenceCoachTargetOnlySession BuildSession(
        SentenceRecord sentence,
        IReadOnlyList<DictionaryEntry> targets,
        ContextTargetLexicon lexicon,
        DictionaryPackage dictionary,
        int startTargetIndex = 0) =>
        SentenceCoachTargetOnlySession.Build(
            sentence,
            targets,
            lexicon,
            dictionary,
            "fixture-pack",
            ContextCorpusKind.SyntheticFixture,
            "Synthetic target-only UI fixture",
            "internal-test-only",
            startTargetIndex);

    private static List<DictionaryEntry> TargetEntries(DictionaryPackage dictionary) => new()
    {
        dictionary.Entries.Single(entry => entry.Id == "ox-students"),
        dictionary.Entries.Single(entry => entry.Id == "ox-learn"),
        dictionary.Entries.Single(entry => entry.Id == "ox-words")
    };

    private static DictionaryPackage FixtureDictionary(bool includeAmbiguousRun = false)
    {
        var entries = new List<DictionaryEntry>
        {
            new("ox-students", "A2", "students", "студенти"),
            new("ox-learn", "A1", "learn", "вивчати"),
            new("ox-words", "A1", "words", "слова")
        };
        if (includeAmbiguousRun)
        {
            entries.Add(new DictionaryEntry("ox-run-verb", "A1", "run", "бігати"));
            entries.Add(new DictionaryEntry("ox-run-noun", "B1", "run", "пробіжка"));
        }
        return new DictionaryPackage
        {
            Id = "target-only-ui-self-test",
            Name = "Target-only UI self-test",
            SourceLanguage = "en",
            TargetLanguage = "uk",
            Entries = entries
        };
    }

    private static SentenceRecord Sentence(string id, string english, string ukrainian, IReadOnlyList<string> ids)
    {
        IReadOnlyList<string> tokens = SentenceTokenizer.Tokenize(english);
        return new SentenceRecord
        {
            Id = id,
            English = english,
            Ukrainian = ukrainian,
            Source = "Synthetic target-only UI self-test fixture",
            License = "internal-test-only",
            Tokens = tokens.ToList(),
            Lemmas = tokens.ToList(),
            TargetEntryIds = ids.ToList(),
            EntryLevels = ids.ToDictionary(entryId => entryId, _ => "A2", StringComparer.OrdinalIgnoreCase),
            DifficultyLevel = "A2",
            OffListTokenCount = 0,
            QualityFlags = new List<string>()
        };
    }
}
