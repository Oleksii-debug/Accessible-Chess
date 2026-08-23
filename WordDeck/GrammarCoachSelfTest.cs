using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class GrammarCoachSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            GrammarCoachSelfTest.Run();
    }
}

internal static class GrammarCoachSelfTest
{
    public static void Run()
    {
        Require(GrammarSkillCatalog.All.Count >= 30, "Grammar skill catalog is too narrow for Stage 13.");
        Require(GrammarSkillCatalog.All.Select(x => x.FamilyId).Distinct(StringComparer.OrdinalIgnoreCase).Count() >= 12, "Grammar family coverage is too narrow.");
        AssertAcyclicGraph();

        foreach (GrammarSkill skill in GrammarSkillCatalog.All)
        {
            IReadOnlyList<GrammarExercise> exercises = GrammarExerciseBank.ForSkill(skill.SkillId);
            Require(exercises.Count > 0, "Grammar skill has no deterministic exercises: " + skill.SkillId);
            foreach (GrammarExercise exercise in exercises)
            {
                exercise.Validate();
                GrammarEvaluation exact = GrammarAnswerEvaluator.Evaluate(exercise, exercise.AcceptedEnglishAnswers[0]);
                Require(exact.Correct && exact.ErrorKind == GrammarErrorKind.None, "Accepted answer was rejected for " + exercise.ExerciseId);
                GrammarEvaluation blank = GrammarAnswerEvaluator.Evaluate(exercise, "   ");
                Require(!blank.Correct && blank.ErrorKind == GrammarErrorKind.Blank, "Blank answer taxonomy failed.");
            }
        }

        GrammarExercise question = GrammarExerciseBank.ForSkill("present.simple.questions-negatives").First(x => x.Kind == GrammarExerciseKind.Question);
        GrammarEvaluation malformedQuestion = GrammarAnswerEvaluator.Evaluate(question, "your brother works here");
        Require(!malformedQuestion.Correct && malformedQuestion.ErrorKind is GrammarErrorKind.QuestionForm or GrammarErrorKind.Auxiliary or GrammarErrorKind.Other,
            "Question error was not rejected deterministically.");

        GrammarExercise negative = GrammarExerciseBank.ForSkill("present.simple.questions-negatives").First(x => x.Kind == GrammarExerciseKind.Negative);
        GrammarEvaluation malformedNegative = GrammarAnswerEvaluator.Evaluate(negative, "they understand");
        Require(!malformedNegative.Correct && malformedNegative.ErrorKind is GrammarErrorKind.Negation or GrammarErrorKind.Auxiliary or GrammarErrorKind.Other,
            "Negative error was not rejected deterministically.");

        var current = GrammarSkillMastery.Empty("present.simple.core");
        GrammarEvaluation correct = GrammarAnswerEvaluator.Evaluate(GrammarExerciseBank.ForSkill("present.simple.core")[0], "I work every day.");
        GrammarSkillMastery learned = GrammarMasteryEngine.Apply(current, correct);
        Require(learned.Attempts == 1 && learned.Correct == 1 && learned.Mastery > 0, "Mastery did not increase after a correct answer.");

        var vocabularyExercise = new GrammarExercise(
            "grammar.test.vocabulary-weakness", "present.simple.core", GrammarExerciseKind.UkrainianToEnglish,
            "Я використовую слово target.", new[] { "I use the target word." }, new[] { "ox:weak" });
        var plan = GrammarPracticePlanner.Plan(
            new[] { vocabularyExercise, GrammarExerciseBank.ForSkill("verb.be.present")[0] },
            new Dictionary<string, GrammarSkillMastery>(StringComparer.OrdinalIgnoreCase),
            new HashSet<string>(new[] { "ox:weak" }, StringComparer.OrdinalIgnoreCase), 10);
        Require(plan.Count == 2 && plan[0].Exercise.ExerciseId == vocabularyExercise.ExerciseId, "Weak-vocabulary overlap did not influence deterministic grammar planning.");

        string temp = Path.Combine(Path.GetTempPath(), "WordDeck граматика " + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(temp);
        try
        {
            string db = Path.Combine(temp, "grammar profile.sqlite");
            var store = new GrammarCoachStateStore(db);
            GrammarExercise exercise = GrammarExerciseBank.ForSkill("verb.be.present")[0];
            GrammarEvaluation evaluation = GrammarAnswerEvaluator.Evaluate(exercise, exercise.AcceptedEnglishAnswers[0]);
            GrammarSkillMastery saved = store.RecordAttempt(exercise, evaluation, exercise.AcceptedEnglishAnswers[0]);
            Require(saved.Attempts == 1, "Grammar attempt was not persisted.");

            var restarted = new GrammarCoachStateStore(db);
            IReadOnlyDictionary<string, GrammarSkillMastery> mastery = restarted.LoadMastery();
            Require(mastery.TryGetValue(exercise.SkillId, out GrammarSkillMastery? restored) && restored.Attempts == 1 && restored.Correct == 1,
                "Grammar mastery did not survive restart.");
            Require(restarted.LoadRecentAttempts().Count == 1, "Grammar attempt history did not survive restart.");

            string backup = restarted.CreateBackup("self-test");
            Require(File.Exists(backup) && new FileInfo(backup).Length > 0, "Grammar backup was not created.");
            restarted.ImportMasterySnapshot(new[] { new GrammarSkillMastery("present.simple.core", 4, 3, 0.7, DateTimeOffset.UtcNow) });
            Require(restarted.LoadMastery()["present.simple.core"].Attempts == 4, "Grammar mastery import failed.");
            Require(Directory.GetFiles(temp, "*.backup.sqlite").Length >= 2, "Risky grammar import did not create its own backup.");
        }
        finally
        {
            try { Directory.Delete(temp, true); } catch { }
        }

        var privateEvidence = new GrammarSentenceEvidence(
            "local-book", "user-local book", "private-local", "The book sentence is local.",
            new[] { "present.simple.core" }, new[] { "ox:book" }, true);
        privateEvidence.Validate();
        Require(privateEvidence.PrivateLocalOnly, "Private book sentence evidence lost its privacy boundary.");
    }

    private static void AssertAcyclicGraph()
    {
        var visiting = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var visited = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (GrammarSkill skill in GrammarSkillCatalog.All) Visit(skill.SkillId, visiting, visited);
    }

    private static void Visit(string id, HashSet<string> visiting, HashSet<string> visited)
    {
        if (visited.Contains(id)) return;
        if (!visiting.Add(id)) throw new InvalidOperationException("Grammar self-test failed: cycle detected at " + id);
        foreach (string prerequisite in GrammarSkillCatalog.ById[id].PrerequisiteSkillIds) Visit(prerequisite, visiting, visited);
        visiting.Remove(id);
        visited.Add(id);
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException("Grammar self-test failed: " + message);
    }
}
