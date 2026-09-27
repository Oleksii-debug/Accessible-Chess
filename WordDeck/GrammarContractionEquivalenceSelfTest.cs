using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class GrammarContractionEquivalenceSelfTest
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (!Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            return;
        Run();
    }

    internal static void Run()
    {
        AssertCorrect("verb.be.present", GrammarExerciseKind.Negative, "She isn't tired.");
        AssertCorrect("verb.be.present", GrammarExerciseKind.Negative, "She's not tired.");
        AssertCorrect("present.simple.questions-negatives", GrammarExerciseKind.Negative, "They don't understand.");
        AssertCorrect("present-perfect.core", GrammarExerciseKind.Negative, "She hasn't arrived yet.");
        AssertCorrect("present-perfect.core", GrammarExerciseKind.Negative, "She's not arrived yet.");
        AssertCorrect("future.will", GrammarExerciseKind.Negative, "She won't come.");

        GrammarExercise third = GrammarExerciseBank.ForSkill("conditionals.third").Single();
        GrammarEvaluation thirdContracted = GrammarAnswerEvaluator.Evaluate(
            third,
            "If I had known, I'd have told you.");
        Require(thirdContracted.Correct,
            "Context-valid subject contraction was rejected in Third Conditional.");
        Require(thirdContracted.ExpectedAnswer == GrammarAnswerEvaluator.Normalize(third.AcceptedEnglishAnswers[0]),
            "Contraction acceptance changed the canonical expected answer stored for feedback/evidence.");

        GrammarExercise beNegative = GrammarExerciseBank.ForSkill("verb.be.present")
            .Single(x => x.Kind == GrammarExerciseKind.Negative);
        Require(!GrammarAnswerEvaluator.Evaluate(beNegative, "She wasn't tired.").Correct,
            "Contraction equivalence incorrectly changed tense.");
        Require(!GrammarAnswerEvaluator.Evaluate(beNegative, "She is tired.").Correct,
            "Contraction equivalence incorrectly removed negation.");

        GrammarExercise question = GrammarExerciseBank.ForSkill("verb.be.present")
            .Single(x => x.Kind == GrammarExerciseKind.Question);
        Require(!GrammarAnswerEvaluator.Evaluate(question, "They're ready?").Correct,
            "Contraction equivalence incorrectly accepted statement word order as a question.");

        var punctuationExercise = new GrammarExercise(
            "grammar.test.contraction-punctuation",
            "verb.be.present",
            GrammarExerciseKind.Statement,
            "Вона, однак, не готова.",
            new[] { "She is not, however, ready." },
            Array.Empty<string>());
        Require(GrammarAnswerEvaluator.Evaluate(punctuationExercise, "She isn't, however, ready.").Correct,
            "A valid contraction immediately before punctuation was rejected.");

        Console.WriteLine("WordDeck grammar contraction self-test passed: natural contractions accepted without tense, negation or word-order drift.");
    }

    private static void AssertCorrect(string skillId, GrammarExerciseKind kind, string answer)
    {
        GrammarExercise exercise = GrammarExerciseBank.ForSkill(skillId).Single(x => x.Kind == kind);
        GrammarEvaluation evaluation = GrammarAnswerEvaluator.Evaluate(exercise, answer);
        Require(evaluation.Correct, $"Natural contraction was rejected for {exercise.ExerciseId}: {answer}");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException("Grammar contraction self-test failed: " + message);
    }
}
