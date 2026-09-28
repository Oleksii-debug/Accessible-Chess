using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class SentenceTokenizerUnicodeSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            SentenceTokenizerUnicodeSelfTest.Run();
    }
}

internal static class SentenceTokenizerUnicodeSelfTest
{
    public static void Run()
    {
        TokenizesUnicodeLatinAndCombiningMarks();
        PreservesCanonicalPackTokenizerCompatibility();
        PreservesApostropheWords();
        RejectsDroppedDiacriticAsMisspelling();
        PreservesAsciiBehavior();
        Console.WriteLine("Sentence tokenizer Unicode self-test PASS: Unicode Latin letters, combining marks, pack-index compatibility, apostrophes, spelling discrimination and ASCII compatibility verified.");
    }

    private static void TokenizesUnicodeLatinAndCombiningMarks()
    {
        IReadOnlyList<string> composed = SentenceTokenizer.TokenizeForSpelling("We met at the café.");
        Require(composed.SequenceEqual(new[] { "we", "met", "at", "the", "café" }, StringComparer.Ordinal),
            "Composed Unicode Latin letters were truncated during sentence tokenization.");

        IReadOnlyList<string> decomposed = SentenceTokenizer.TokenizeForSpelling("We met at the cafe\u0301.");
        Require(decomposed.SequenceEqual(composed, StringComparer.Ordinal),
            "Canonically equivalent decomposed diacritics did not normalize to the same sentence tokens.");
    }

    private static void PreservesCanonicalPackTokenizerCompatibility()
    {
        IReadOnlyList<string> legacy = SentenceTokenizer.Tokenize("The café is open.");
        Require(legacy.SequenceEqual(new[] { "the", "caf", "is", "open" }, StringComparer.Ordinal),
            "SentencePack canonical tokenizer changed; existing persisted token indexes would require an explicit migration/rebuild.");
    }

    private static void PreservesApostropheWords()
    {
        IReadOnlyList<string> tokens = SentenceTokenizer.TokenizeForSpelling("L’école isn’t closed.");
        Require(tokens.SequenceEqual(new[] { "l'école", "isn't", "closed" }, StringComparer.Ordinal),
            "Unicode-letter tokenization broke straight/curly apostrophe word behavior.");
    }

    private static void RejectsDroppedDiacriticAsMisspelling()
    {
        SentenceAnswerResult exact = SentenceAnswerEvaluator.Evaluate("Order the café menu", "Order the café menu");
        Require(exact.Accepted, "Exact Unicode spelling was rejected.");

        SentenceAnswerResult missingAccent = SentenceAnswerEvaluator.Evaluate("Order the café menu", "Order the caf menu");
        Require(!missingAccent.Accepted, "Sentence Spelling accepted a target after silently dropping its accented letter.");
        Require(missingAccent.Missing.Contains("café", StringComparer.Ordinal) &&
                missingAccent.Extra.Contains("caf", StringComparer.Ordinal),
            "Unicode spelling mismatch did not remain visible in missing/extra evidence.");
    }

    private static void PreservesAsciiBehavior()
    {
        IReadOnlyList<string> tokens = SentenceTokenizer.TokenizeForSpelling("Students don't skip words.");
        Require(tokens.SequenceEqual(new[] { "students", "don't", "skip", "words" }, StringComparer.Ordinal),
            "Unicode tokenizer repair changed ordinary ASCII/apostrophe sentence tokenization.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException(message);
    }
}
