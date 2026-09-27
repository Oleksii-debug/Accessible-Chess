using System.Runtime.CompilerServices;
using Microsoft.Data.Sqlite;

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
        var plannerMastery = new Dictionary<string, GrammarSkillMastery>(StringComparer.OrdinalIgnoreCase)
        {
            ["verb.be.present"] = new GrammarSkillMastery("verb.be.present", 10, 9, 0.8, DateTimeOffset.UtcNow)
        };
        var plan = GrammarPracticePlanner.Plan(
            new[] { vocabularyExercise, GrammarExerciseBank.ForSkill("verb.be.present")[0] },
            plannerMastery,
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

            RequireThrowsInvalidData(
                () => restarted.ImportMasterySnapshot(new[]
                {
                    new GrammarSkillMastery("present.simple.core", 1, 1, double.NaN, DateTimeOffset.UtcNow)
                }),
                "Grammar mastery import accepted non-finite mastery.");

            using (var raw = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = db }.ToString()))
            {
                raw.Open();

                ExecuteRaw(raw,
                    "INSERT INTO grammar_mastery(skill_id,attempts,correct_count,mastery,updated_utc) VALUES('unknown.skill',1,1,0.5,$utc);",
                    ("$utc", DateTimeOffset.UtcNow.ToString("O")));
                RequireThrowsInvalidData(() => _ = restarted.LoadMastery(),
                    "Persisted unknown grammar skill was accepted as mastery state.");
                ExecuteRaw(raw, "DELETE FROM grammar_mastery WHERE skill_id='unknown.skill';");

                ExecuteRaw(raw,
                    "INSERT INTO grammar_attempt(exercise_id,skill_id,correct,error_kind,submitted_answer,expected_answer,attempted_utc) VALUES('grammar.verb.be.present.999','verb.be.present',0,999,'x','expected',$utc);",
                    ("$utc", DateTimeOffset.UtcNow.ToString("O")));
                RequireThrowsInvalidData(() => _ = restarted.LoadRecentAttempts(),
                    "Persisted undefined grammar error kind was accepted.");
                ExecuteRaw(raw, "DELETE FROM grammar_attempt WHERE exercise_id='grammar.verb.be.present.999';");

                ExecuteRaw(raw,
                    "INSERT INTO grammar_attempt(exercise_id,skill_id,correct,error_kind,submitted_answer,expected_answer,attempted_utc) VALUES('grammar.verb.be.present.998','verb.be.present',0,0,'x','expected',$utc);",
                    ("$utc", DateTimeOffset.UtcNow.ToString("O")));
                RequireThrowsInvalidData(() => _ = restarted.LoadRecentAttempts(),
                    "Persisted incorrect grammar attempt without an error kind was accepted.");
                ExecuteRaw(raw, "DELETE FROM grammar_attempt WHERE exercise_id='grammar.verb.be.present.998';");

                ExecuteRaw(raw,
                    "UPDATE grammar_mastery SET updated_utc='not-a-timestamp' WHERE skill_id='present.simple.core';");
                RequireThrowsInvalidData(() => _ = restarted.LoadMastery(),
                    "Persisted malformed grammar mastery timestamp was accepted.");
                ExecuteRaw(raw,
                    "UPDATE grammar_mastery SET updated_utc=$utc WHERE skill_id='present.simple.core';",
                    ("$utc", DateTimeOffset.UtcNow.ToString("O")));
            }

            Require(restarted.LoadMastery()["present.simple.core"].Attempts == 4,
                "Grammar state did not recover after corruption fixtures were removed.");
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

    private static void ExecuteRaw(SqliteConnection connection, string sql, params (string Name, object Value)[] parameters)
    {
        using SqliteCommand command = connection.CreateCommand();
        command.CommandText = sql;
        foreach ((string name, object value) in parameters)
            command.Parameters.AddWithValue(name, value);
        command.ExecuteNonQuery();
    }

    private static void RequireThrowsInvalidData(Action action, string message)
    {
        bool rejected = false;
        try { action(); }
        catch (InvalidDataException) { rejected = true; }
        Require(rejected, message);
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
