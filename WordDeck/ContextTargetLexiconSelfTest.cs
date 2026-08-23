using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class ContextTargetLexiconSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            ContextTargetLexiconSelfTest.Run();
    }
}

internal static class ContextTargetLexiconSelfTest
{
    public static void Run()
    {
        var lexicon = new ContextTargetLexicon(
            "context-target-lexicon-self-test",
            new[]
            {
                ("ox-run-verb", "run"),
                ("ox-run-noun", "run"),
                ("ox-skills", "skills")
            });

        IReadOnlyList<string> scopedAmbiguity = lexicon.AmbiguousStableIds(new[] { "ox-run-verb", "ox-skills" });
        if (!scopedAmbiguity.SequenceEqual(new[] { "ox-run-verb" }, StringComparer.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException(
                "Scoped Context coverage lost a globally ambiguous stable ID when its homographic sibling was outside the measured scope.");
        }

        Console.WriteLine("Context target-lexicon self-test PASS: global homograph ambiguity remains visible inside partial study scopes.");
    }
}
