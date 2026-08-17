using System.Security.Cryptography;
using System.Text.Json;

namespace WordDeck;

internal static class TatoebaSentencePackSelfTest
{
    public static void Run()
    {
        TestSixColumnAndCompactParsing();
        TestPackBuildAndStableIds();
        TestLanguageAndMalformedInputRejection();
        TestVerifiedCc0ManifestProvenance();
    }

    private static void TestSixColumnAndCompactParsing()
    {
        string[] lines =
        {
            "english_id\tenglish_lang\tenglish\tukrainian_id\tukrainian_lang\tukrainian",
            "101\teng\tI improve skills.\t201\tukr\tЯ покращую навички.",
            "102\tWe learn words.\t202\tМи вивчаємо слова."
        };

        List<TatoebaSentencePair> pairs = TatoebaPairTsv.ParseLines(lines).ToList();
        Require(pairs.Count == 2, "Tatoeba pair parser did not accept both supported export layouts.");
        Require(pairs[0].EnglishId == 101 && pairs[0].UkrainianId == 201 && pairs[0].English == "I improve skills.",
            "Six-column Tatoeba pair parsing changed IDs/text.");
        Require(pairs[1].EnglishId == 102 && pairs[1].UkrainianId == 202 && pairs[1].Ukrainian == "Ми вивчаємо слова.",
            "Compact Tatoeba pair parsing changed IDs/text.");
    }

    private static void TestPackBuildAndStableIds()
    {
        var dictionary = new DictionaryPackage
        {
            Id = "test-dictionary",
            Name = "Test",
            SourceLanguage = "en",
            TargetLanguage = "uk",
            Entries = new List<DictionaryEntry>
            {
                new("ox-i", "A1", "I", "я"),
                new("ox-improve", "B1", "improve", "покращувати"),
                new("ox-skills-n", "A2", "skills", "навички"),
                new("ox-skills-v", "B1", "skills", "вміння"),
                new("ox-learn", "A1", "learn", "вивчати"),
                new("ox-words", "A1", "words", "слова"),
                new("ox-multi", "B2", "take care", "піклуватися")
            }
        };

        var pairs = new[]
        {
            new TatoebaSentencePair(101, "I improve skills.", 201, "Я покращую навички."),
            new TatoebaSentencePair(102, "We learn words.", 202, "Ми вивчаємо слова."),
            new TatoebaSentencePair(103, "xylophone qwerty.", 203, "Ксилофон.")
        };

        (SentencePack pack, SentencePackBuildReport report) = TatoebaSentencePackBuilder.Build(
            pairs,
            dictionary,
            "tatoeba-en-uk-test-v1",
            "Synthetic Tatoeba-layout regression fixture",
            "CC0-1.0");

        Require(report.InputPairs == 3 && report.AcceptedPairs == 2 && report.RejectedPairs == 1,
            "Tatoeba SentencePack build accounting is incorrect.");
        Require(pack.Sentences.Count == 2, "Tatoeba SentencePack builder did not filter an unindexed sentence.");

        SentenceRecord first = pack.Sentences.Single(sentence => sentence.SourceSentenceId == "101");
        Require(first.Id == "tatoeba-en-101-uk-201", "Tatoeba stable sentence ID changed.");
        Require(first.TranslationSentenceId == "201" && first.Source.Contains("Tatoeba", StringComparison.Ordinal),
            "Tatoeba provenance/upstream IDs were not preserved.");
        Require(first.TargetEntryIds.Contains("ox-improve") && first.TargetEntryIds.Contains("ox-skills-n") && first.TargetEntryIds.Contains("ox-skills-v"),
            "Surface index did not preserve multiple Oxford entry IDs sharing a form.");
        Require(!first.TargetEntryIds.Contains("ox-multi"), "Baseline surface importer incorrectly indexed a multi-word dictionary entry as a unigram.");
        Require(first.DifficultyLevel == "B1", "Sentence difficulty baseline did not reflect recognized surrounding vocabulary levels.");
        Require(pack.LookupAllTargets(new[] { "ox-improve", "ox-skills-n" }).Count == 1,
            "Built SentencePack two-target index is not immediately usable offline.");

        string roundTrip = SentencePackJson.Serialize(pack);
        SentencePack reparsed = SentencePackJson.Parse(roundTrip);
        Require(reparsed.Sentences.Count == pack.Sentences.Count && reparsed.License == "CC0-1.0",
            "Built Tatoeba SentencePack did not survive versioned JSON round-trip.");
    }

    private static void TestLanguageAndMalformedInputRejection()
    {
        ExpectInvalid(new[] { "101\teng\tHello world.\t201\tdeu\tHallo Welt." }, "non EN-UA language pair");
        ExpectInvalid(new[] { "not-an-id\tHello world.\t201\tПривіт, світе." }, "invalid sentence id");
        ExpectInvalid(new[] { "101\tHello world." }, "wrong column count");
    }

    private static void TestVerifiedCc0ManifestProvenance()
    {
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck-tatoeba-manifest-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            string pairPath = Path.Combine(root, "pairs.tsv");
            File.WriteAllText(pairPath, "english_id\tenglish_lang\tenglish\tukrainian_id\tukrainian_lang\tukrainian\n1\teng\tHello.\t2\tukr\tПривіт.\n");
            string hash;
            using (FileStream stream = File.OpenRead(pairPath))
                hash = Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();

            string manifestPath = pairPath + ".manifest.json";
            File.WriteAllText(manifestPath, JsonSerializer.Serialize(new
            {
                schema_version = 1,
                license_filter = "CC0 1.0 on BOTH sentence sides",
                output_sha256 = hash
            }));

            TatoebaImportMetadata verified = TatoebaImportProvenance.Resolve(pairPath);
            Require(verified.VerifiedCc0Manifest && verified.License == "CC0 1.0",
                "Matching CC0 manifest/hash did not produce verified CC0 metadata.");

            File.AppendAllText(pairPath, "3\teng\tChanged.\t4\tukr\tЗмінено.\n");
            TatoebaImportMetadata tampered = TatoebaImportProvenance.Resolve(pairPath);
            Require(!tampered.VerifiedCc0Manifest && tampered.License.Contains("CC BY 2.0", StringComparison.Ordinal),
                "Hash-mismatched pair TSV was incorrectly trusted as CC0.");

            File.Delete(manifestPath);
            TatoebaImportMetadata missing = TatoebaImportProvenance.Resolve(pairPath);
            Require(!missing.VerifiedCc0Manifest && missing.License.Contains("CC BY 2.0", StringComparison.Ordinal),
                "Missing manifest was incorrectly trusted as CC0.");
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    private static void ExpectInvalid(IEnumerable<string> lines, string description)
    {
        try
        {
            _ = TatoebaPairTsv.ParseLines(lines).ToList();
        }
        catch (InvalidDataException)
        {
            return;
        }
        throw new InvalidDataException($"Tatoeba parser accepted invalid input: {description}.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidDataException(message);
    }
}
