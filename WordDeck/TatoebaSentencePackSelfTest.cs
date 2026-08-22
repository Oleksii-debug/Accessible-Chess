using System.Security.Cryptography;
using System.Text.Json;

namespace WordDeck;

internal static class TatoebaSentencePackSelfTest
{
    public static void Run()
    {
        TestSupportedPairLayouts();
        TestPackBuildAndStableIds();
        TestLanguageAndMalformedInputRejection();
        TestVerifiedManifestProvenance();
    }

    private static void TestSupportedPairLayouts()
    {
        string[] lines =
        {
            "english_id\tenglish_lang\tenglish\tukrainian_id\tukrainian_lang\tukrainian",
            "101\teng\tI improve skills.\t201\tukr\tЯ покращую навички.",
            "102\tWe learn words.\t202\tМи вивчаємо слова."
        };
        List<TatoebaSentencePair> pairs = TatoebaPairTsv.ParseLines(lines).ToList();
        Require(pairs.Count == 2, "Tatoeba pair parser did not accept 4/6-column layouts.");
        Require(pairs[0].EnglishId == 101 && pairs[0].UkrainianId == 201, "Six-column parsing changed IDs.");

        string[] attributedLines =
        {
            "english_id\tenglish_lang\tenglish\tenglish_author\tukrainian_id\tukrainian_lang\tukrainian\tukrainian_author",
            "301\teng\tWe learn words.\tAlice\t401\tukr\tМи вивчаємо слова.\tOlena"
        };
        TatoebaSentencePair attributed = TatoebaPairTsv.ParseLines(attributedLines).Single();
        Require(attributed.EnglishAuthor == "Alice" && attributed.UkrainianAuthor == "Olena",
            "Attributed 8-column parser lost sentence-owner usernames.");
        ExpectInvalid(new[] { "301\teng\tHello.\t\\N\t401\tukr\tПривіт.\tOlena" }, "missing English author in attributed layout");
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
                new("ox-ice-cream", "A1", "ice cream", "морозиво"),
                new("ox-bank-money", "A1", "bank (money)", "банк")
            }
        };

        var pairs = new[]
        {
            new TatoebaSentencePair(101, "I improve skills.", 201, "Я покращую навички.", "Alice", "Olena"),
            new TatoebaSentencePair(102, "We learn words.", 202, "Ми вивчаємо слова."),
            new TatoebaSentencePair(103, "xylophone qwerty.", 203, "Ксилофон."),
            new TatoebaSentencePair(104, "I like ice cream.", 204, "Я люблю морозиво."),
            new TatoebaSentencePair(105, "I bank money.", 205, "Я кладу гроші до банку.")
        };

        (SentencePack pack, SentencePackBuildReport report) = TatoebaSentencePackBuilder.Build(
            pairs, dictionary, "tatoeba-en-uk-test-v1", "Synthetic Tatoeba-layout regression fixture", "CC BY 2.0 FR");

        Require(report.InputPairs == 5 && report.AcceptedPairs == 4 && report.RejectedPairs == 1,
            "Tatoeba SentencePack build accounting is incorrect.");
        SentenceRecord first = pack.Sentences.Single(sentence => sentence.SourceSentenceId == "101");
        Require(first.Id == "tatoeba-en-101-uk-201", "Tatoeba stable sentence ID changed.");
        Require(first.Source.Contains("Alice", StringComparison.Ordinal) && first.Source.Contains("Olena", StringComparison.Ordinal),
            "Attributed sentence authors were not preserved in SentenceRecord.Source.");
        Require(first.TargetEntryIds.Contains("ox-improve") && first.TargetEntryIds.Contains("ox-skills-n") && first.TargetEntryIds.Contains("ox-skills-v"),
            "Surface index did not preserve multiple Oxford entry IDs sharing a form.");
        Require(first.DifficultyLevel == "B1", "Sentence difficulty baseline did not reflect recognized context vocabulary.");
        Require(pack.LookupAllTargets(new[] { "ox-improve", "ox-skills-n" }).Count == 1,
            "Built SentencePack two-target index is not immediately usable offline.");

        SentenceRecord phrase = pack.Sentences.Single(sentence => sentence.SourceSentenceId == "104");
        Require(phrase.TargetEntryIds.Contains("ox-ice-cream"),
            "Safe exact multiword dictionary source was not indexed when its token sequence occurred contiguously.");
        SentenceRecord annotated = pack.Sentences.Single(sentence => sentence.SourceSentenceId == "105");
        Require(!annotated.TargetEntryIds.Contains("ox-bank-money"),
            "Sense-annotated dictionary source was incorrectly collapsed into an exact multiword target.");

        SentencePack reparsed = SentencePackJson.Parse(SentencePackJson.Serialize(pack));
        Require(reparsed.Sentences.Count == pack.Sentences.Count && reparsed.License == "CC BY 2.0 FR",
            "Built Tatoeba SentencePack did not survive JSON round-trip.");
    }

    private static void TestLanguageAndMalformedInputRejection()
    {
        ExpectInvalid(new[] { "101\teng\tHello world.\t201\tdeu\tHallo Welt." }, "non EN-UA language pair");
        ExpectInvalid(new[] { "not-an-id\tHello world.\t201\tПривіт, світе." }, "invalid sentence id");
        ExpectInvalid(new[] { "101\tHello world." }, "wrong column count");
    }

    private static void TestVerifiedManifestProvenance()
    {
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck-tatoeba-manifest-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            string pairPath = Path.Combine(root, "pairs.tsv");
            File.WriteAllText(pairPath, "english_id\tenglish_lang\tenglish\tukrainian_id\tukrainian_lang\tukrainian\n1\teng\tHello.\t2\tukr\tПривіт.\n");
            string hash = Hash(pairPath);
            string manifestPath = pairPath + ".manifest.json";
            WriteManifest(manifestPath, "CC0 1.0 on BOTH sentence sides", "CC0 1.0", hash);

            TatoebaImportMetadata cc0 = TatoebaImportProvenance.Resolve(pairPath);
            Require(cc0.VerifiedCc0Manifest && cc0.License == "CC0 1.0", "Matching CC0 manifest/hash was not trusted.");

            WriteManifest(manifestPath, "CC BY 2.0 FR with BOTH sentence-owner usernames retained", "CC BY 2.0 FR", hash);
            TatoebaImportMetadata ccBy = TatoebaImportProvenance.Resolve(pairPath);
            Require(ccBy.VerifiedAttributedCcByManifest && ccBy.License == "CC BY 2.0 FR",
                "Matching attributed CC-BY manifest/hash was not trusted.");

            File.AppendAllText(pairPath, "3\teng\tChanged.\t4\tukr\tЗмінено.\n");
            ExpectProvenanceInvalid(pairPath, "Hash-mismatched pair TSV was accepted.");

            File.Delete(manifestPath);
            ExpectProvenanceInvalid(pairPath, "Missing provenance manifest was accepted.");
        }
        finally
        {
            try { Directory.Delete(root, true); } catch { }
        }
    }

    private static string Hash(string path)
    {
        using FileStream stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }

    private static void WriteManifest(string path, string licenseFilter, string license, string hash) =>
        File.WriteAllText(path, JsonSerializer.Serialize(new { schema_version = 1, license_filter = licenseFilter, license, output_sha256 = hash }));

    private static void ExpectProvenanceInvalid(string pairPath, string message)
    {
        try { _ = TatoebaImportProvenance.Resolve(pairPath); }
        catch (InvalidDataException) { return; }
        throw new InvalidDataException(message);
    }

    private static void ExpectInvalid(IEnumerable<string> lines, string description)
    {
        try { _ = TatoebaPairTsv.ParseLines(lines).ToList(); }
        catch (InvalidDataException) { return; }
        throw new InvalidDataException($"Tatoeba parser accepted invalid input: {description}.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }
}
