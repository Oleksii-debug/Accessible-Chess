using System.Security.Cryptography;
using System.Text.Json;

namespace WordDeck;

internal static class TatoebaSentencePackSelfTest
{
    public static void Run()
    {
        TestSupportedPairLayouts();
        TestPackBuildAndStableIds();
        TestFinalOxford5000Integration();
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

    private static void TestFinalOxford5000Integration()
    {
        DictionaryPackage dictionary = DictionaryLoader.LoadEmbeddedOxford();
        Require(dictionary.Entries.Count == 5446,
            "SentencePack builder is not seeing the final 5,446-entry Oxford training dictionary.");

        DictionaryEntry addition = dictionary.Entries.Single(entry =>
            entry.Source.Equals("abolish", StringComparison.OrdinalIgnoreCase) &&
            entry.Level.Equals("C1", StringComparison.OrdinalIgnoreCase));

        (SentencePack pack, SentencePackBuildReport report) = TatoebaSentencePackBuilder.Build(
            new[] { new TatoebaSentencePair(501, "They abolish.", 601, "Вони скасовують.") },
            dictionary,
            "full-oxford5000-regression",
            "Synthetic full Oxford 5000 integration regression fixture",
            "CC0 1.0");

        Require(report.AcceptedPairs == 1 && pack.Sentences.Single().TargetEntryIds.Contains(addition.Id),
            "SentencePack indexing did not include an Oxford 5000 addition outside the frozen Oxford 3000 baseline.");
    }

    private static void TestLanguageAndMalformedInputRejection()
    {
        ExpectInvalid(new[] { "101\teng\tHello world.\t201\tdeu\tHallo Welt." }, "non EN-UA language pair");
        ExpectInvalid(new[] { "not-an-id\tHello world.\t201\tПривіт, світе." }, "invalid sentence id");
        ExpectInvalid(new[] { "101\tHello world." }, "wrong column count");
    }

    private static void TestVerifiedManifestProvenance()
    {
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck-tatoeba-manifest-Київ space-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            string pairPath = Path.Combine(root, "pairs.tsv");
            File.WriteAllText(pairPath, "english_id\tenglish_lang\tenglish\tukrainian_id\tukrainian_lang\tukrainian\n1\teng\tHello.\t2\tukr\tПривіт.\n");
            string hash = Hash(pairPath);
            string manifestPath = pairPath + ".manifest.json";
            WriteManifest(manifestPath, "CC0 1.0 on BOTH sentence sides", hash);

            TatoebaImportMetadata cc0 = TatoebaImportProvenance.Resolve(pairPath);
            Require(cc0.VerifiedCc0Manifest && cc0.License == "CC0 1.0", "Matching CC0 manifest/hash was not trusted.");

            WriteManifest(manifestPath, "CC BY 2.0 FR with BOTH sentence-owner usernames retained", hash, "CC BY 2.0 FR");
            TatoebaImportMetadata ccBy = TatoebaImportProvenance.Resolve(pairPath);
            Require(ccBy.VerifiedAttributedCcByManifest && ccBy.License == "CC BY 2.0 FR",
                "Matching attributed CC-BY manifest/hash was not trusted.");

            File.AppendAllText(pairPath, "3\teng\tChanged.\t4\tukr\tЗмінено.\n");
            ExpectInvalidProvenance(() => TatoebaImportProvenance.Resolve(pairPath), "hash-mismatched pair TSV");

            File.WriteAllText(pairPath, "english_id\tenglish_lang\tenglish\tukrainian_id\tukrainian_lang\tukrainian\n1\teng\tHello.\t2\tukr\tПривіт.\n");
            hash = Hash(pairPath);
            WriteManifest(manifestPath, "unapproved-license-filter", hash);
            ExpectInvalidProvenance(() => TatoebaImportProvenance.Resolve(pairPath), "unknown license filter");

            WriteManifest(manifestPath, "CC BY 2.0 FR with BOTH sentence-owner usernames retained", hash, "CC0 1.0");
            ExpectInvalidProvenance(() => TatoebaImportProvenance.Resolve(pairPath), "mismatched declared CC-BY license");

            WriteManifest(manifestPath, "CC0 1.0 on BOTH sentence sides", hash, badOfficialUrl: true);
            ExpectInvalidProvenance(() => TatoebaImportProvenance.Resolve(pairPath), "unofficial acquisition URL");

            WriteManifest(manifestPath, "CC0 1.0 on BOTH sentence sides", hash, omitInputHashes: true);
            ExpectInvalidProvenance(() => TatoebaImportProvenance.Resolve(pairPath), "missing upstream input hashes");

            File.WriteAllText(manifestPath, "{ broken json");
            ExpectInvalidProvenance(() => TatoebaImportProvenance.Resolve(pairPath), "malformed manifest JSON");

            File.Delete(manifestPath);
            ExpectInvalidProvenance(() => TatoebaImportProvenance.Resolve(pairPath), "missing manifest");
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

    private static void WriteManifest(
        string path,
        string licenseFilter,
        string hash,
        string? license = null,
        bool badOfficialUrl = false,
        bool omitInputHashes = false)
    {
        bool attributed = string.Equals(licenseFilter, "CC BY 2.0 FR with BOTH sentence-owner usernames retained", StringComparison.Ordinal);
        string[] inputKeys = attributed
            ? new[] { "english_detailed", "ukrainian_detailed", "links" }
            : new[] { "english_cc0", "ukrainian_cc0", "links" };
        string officialHost = badOfficialUrl ? "https://example.invalid/exports/" : "https://downloads.tatoeba.org/exports/";
        var urls = inputKeys.ToDictionary(key => key, key => officialHost + key + ".tsv.bz2", StringComparer.Ordinal);
        var inputHashes = inputKeys.ToDictionary(key => key, key => new string(key == "links" ? 'c' : key.StartsWith("english", StringComparison.Ordinal) ? 'a' : 'b', 64), StringComparer.Ordinal);
        string manifestSuffix = ".manifest.json";
        string outputName = path.EndsWith(manifestSuffix, StringComparison.Ordinal)
            ? Path.GetFileName(path[..^manifestSuffix.Length])
            : "pairs.tsv";

        var payload = new Dictionary<string, object?>
        {
            ["schema_version"] = 1,
            ["source"] = attributed
                ? "Tatoeba official weekly detailed sentence exports plus EN-UA links"
                : "Tatoeba official weekly exports",
            ["license_filter"] = licenseFilter,
            ["official_urls"] = urls,
            ["output"] = outputName,
            ["output_sha256"] = hash,
            ["stats"] = new Dictionary<string, int> { ["pairs_emitted"] = 1 }
        };
        if (!omitInputHashes) payload["input_sha256"] = inputHashes;
        if (license is not null) payload["license"] = license;
        if (attributed) payload["attribution_policy"] = "Both sentence-owner usernames and upstream IDs are retained.";
        File.WriteAllText(path, JsonSerializer.Serialize(payload));
    }

    private static void ExpectInvalidProvenance(Action action, string description)
    {
        try { action(); }
        catch (InvalidDataException) { return; }
        throw new InvalidDataException($"Tatoeba provenance accepted invalid input: {description}.");
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
