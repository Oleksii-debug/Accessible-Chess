using System.Runtime.CompilerServices;

namespace WordDeck;

internal static class SentencePackStructuralLimitsSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            SentencePackStructuralLimitsSelfTest.Run();
    }
}

internal static class SentencePackStructuralLimitsSelfTest
{
    public static void Run()
    {
        SentencePack baseline = BuildPack();
        SentencePackStructuralLimits.Validate(baseline);

        string tooLong = new('x', SentencePackStructuralLimits.MaxIdentifierChars + 1);

        ExpectRejected(
            BuildPack(sourceSentenceId: tooLong),
            "overlong upstream source sentence id");
        ExpectRejected(
            BuildPack(translationSentenceId: tooLong),
            "overlong upstream translation sentence id");

        SentencePack extraEntryLevel = BuildPack();
        SentenceRecord record = extraEntryLevel.Sentences.Single();
        record.EntryLevels[tooLong] = "A1";
        ExpectRejected(extraEntryLevel, "overlong extra EntryLevels key");

        SentencePack maxLength = BuildPack(
            sourceSentenceId: new string('s', SentencePackStructuralLimits.MaxIdentifierChars),
            translationSentenceId: new string('t', SentencePackStructuralLimits.MaxIdentifierChars));
        maxLength.Sentences.Single().EntryLevels[new string('e', SentencePackStructuralLimits.MaxIdentifierChars)] = "A1";
        SentencePackStructuralLimits.Validate(maxLength);

        string root = Path.Combine(Path.GetTempPath(), $"WordDeck-sentencepack-metadata-limits-{Guid.NewGuid():N}");
        try
        {
            Directory.CreateDirectory(root);
            string output = Path.Combine(root, "pack.json.gz");
            SentencePack overlongIoPack = BuildPack(sourceSentenceId: tooLong);
            bool writeRejected = false;
            try { SentencePackIo.WriteGZip(output, overlongIoPack); }
            catch (InvalidDataException) { writeRejected = true; }
            Require(writeRejected, "Portable SentencePack write path accepted overlong upstream metadata.");
            Require(!File.Exists(output) || new FileInfo(output).Length == 0,
                "Rejected overlong SentencePack left a usable-looking portable artifact.");
        }
        finally
        {
            try { if (Directory.Exists(root)) Directory.Delete(root, true); } catch { }
        }

        Console.WriteLine("SentencePack metadata structural-limits self-test passed.");
    }

    private static SentencePack BuildPack(
        string? sourceSentenceId = "123",
        string? translationSentenceId = "456")
    {
        const string english = "We learn words";
        List<string> tokens = SentenceTokenizer.Tokenize(english).ToList();
        return new SentencePack
        {
            PackId = "structural-limits-test",
            Provenance = "Synthetic structural-limits regression fixture",
            License = "CC0-1.0",
            Sentences = new List<SentenceRecord>
            {
                new()
                {
                    Id = "sentence-1",
                    English = english,
                    Ukrainian = "Ми вивчаємо слова",
                    Source = "Synthetic structural-limits regression fixture",
                    License = "CC0-1.0",
                    SourceSentenceId = sourceSentenceId,
                    TranslationSentenceId = translationSentenceId,
                    Tokens = tokens,
                    Lemmas = tokens.ToList(),
                    TargetEntryIds = new List<string> { "ox-learn" },
                    EntryLevels = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
                    {
                        ["ox-learn"] = "A1"
                    },
                    DifficultyLevel = "A1"
                }
            }
        };
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }

    private static void ExpectRejected(SentencePack pack, string description)
    {
        try
        {
            SentencePackStructuralLimits.Validate(pack);
        }
        catch (InvalidDataException)
        {
            return;
        }

        throw new InvalidDataException($"SentencePack structural limits accepted {description}.");
    }
}
