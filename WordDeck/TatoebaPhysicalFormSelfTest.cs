using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class TatoebaPhysicalFormSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            TatoebaPhysicalFormSelfTest.Run();
    }
}

internal static class TatoebaPhysicalFormSelfTest
{
    public static void Run()
    {
        var dictionary = new DictionaryPackage
        {
            Id = "tatoeba-physical-form-self-test",
            Name = "Tatoeba physical-form self-test",
            SourceLanguage = "en",
            TargetLanguage = "uk",
            Entries = new List<DictionaryEntry>
            {
                new("ox-i", "A1", "I", "я"),
                new("ox-full-time-adj", "B2", "full-time", "повний робочий день"),
                new("ox-full-time-adv", "B2", "full-time", "повний робочий день")
            }
        };

        var pairs = new[]
        {
            new TatoebaSentencePair(701, "I work full-time today.", 801, "Я сьогодні працюю повний робочий день."),
            new TatoebaSentencePair(702, "I work full time today.", 802, "Я сьогодні працюю повний робочий день.")
        };

        (SentencePack pack, SentencePackBuildReport report) = TatoebaSentencePackBuilder.Build(
            pairs,
            dictionary,
            "tatoeba-physical-form-self-test",
            "Synthetic physical-form regression fixture",
            "internal-test-only");

        if (report.AcceptedPairs != 2)
            throw new InvalidOperationException("Physical-form regression fixture did not preserve both sentences for comparison.");

        SentenceRecord hyphenated = pack.Sentences.Single(sentence => sentence.SourceSentenceId == "701");
        if (!hyphenated.TargetEntryIds.Contains("ox-full-time-adj") || !hyphenated.TargetEntryIds.Contains("ox-full-time-adv"))
            throw new InvalidOperationException("Exact hyphenated dictionary form was not indexed when physically present.");

        SentenceRecord spaced = pack.Sentences.Single(sentence => sentence.SourceSentenceId == "702");
        if (spaced.TargetEntryIds.Contains("ox-full-time-adj") || spaced.TargetEntryIds.Contains("ox-full-time-adv"))
            throw new InvalidOperationException("Token-only matching falsely indexed 'full time' as the physical Oxford form 'full-time'.");

        Console.WriteLine("Tatoeba physical-form self-test PASS: hyphenated Oxford forms require a matching physical sentence occurrence.");
    }
}
