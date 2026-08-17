namespace WordDeck;

internal static class SentenceCoachSelfTest
{
    public static void Run()
    {
        TestPackVersioningAndProvenance();
        TestTokenizationAndAnswerEvaluation();
        TestOneAndTwoTargetLookup();
        TestPersonalDifficultyRankingAndScope();
        TestRecentAvoidance();
        TestGeneratorFallbackContract();
    }

    private static SentencePack BuildPack()
    {
        var pack = new SentencePack
        {
            PackId = "test-en-uk-v1",
            Provenance = "Synthetic regression data",
            License = "CC0-1.0",
            Sentences = new List<SentenceRecord>
            {
                Make("s1", "I improve my skills", "Я покращую свої навички", new[] { "i", "improve", "my", "skills" }, new[] { "ox-improve", "ox-skills" },
                    new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase) { ["ox-improve"]="B1", ["ox-skills"]="A2" }),
                Make("s2", "Students improve practical skills every day", "Студенти щодня покращують практичні навички", new[] { "students", "improve", "practical", "skills", "every", "day" },
                    new[] { "ox-student", "ox-improve", "ox-practical", "ox-skills", "ox-every", "ox-day" },
                    new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase) { ["ox-student"]="A2", ["ox-improve"]="B1", ["ox-practical"]="B2", ["ox-skills"]="A2", ["ox-every"]="A1", ["ox-day"]="A1" }),
                Make("s3", "Skills improve", "Навички покращуються", new[] { "skills", "improve" }, new[] { "ox-skills", "ox-improve" },
                    new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase) { ["ox-skills"]="A2", ["ox-improve"]="B1" })
            }
        };
        pack.Validate();
        return pack;
    }

    private static SentenceRecord Make(string id, string en, string uk, IEnumerable<string> lemmas, IEnumerable<string> ids, Dictionary<string,string> levels)
    {
        return new SentenceRecord
        {
            Id = id,
            English = en,
            Ukrainian = uk,
            Source = "test",
            License = "CC0-1.0",
            Tokens = SentenceTokenizer.Tokenize(en).ToList(),
            Lemmas = lemmas.Select(SentenceTokenizer.NormalizeToken).ToList(),
            TargetEntryIds = ids.ToList(),
            EntryLevels = levels,
            DifficultyLevel = "B1",
            OffListTokenCount = 0
        };
    }

    private static void TestPackVersioningAndProvenance()
    {
        SentencePack pack = BuildPack();
        string json = SentencePackJson.Serialize(pack);
        SentencePack roundTrip = SentencePackJson.Parse(json);
        Require(roundTrip.Version == SentencePack.CurrentVersion && roundTrip.PackId == pack.PackId, "SentencePack version/id did not round-trip.");
        Require(roundTrip.Provenance == "Synthetic regression data" && roundTrip.License == "CC0-1.0", "SentencePack provenance/license did not round-trip.");

        bool rejected = false;
        try
        {
            new SentencePack { Version = 999, PackId = "bad", Provenance = "x", License = "x", Sentences = new() }.Validate();
        }
        catch (InvalidDataException) { rejected = true; }
        Require(rejected, "Unsupported SentencePack version was accepted.");
    }

    private static void TestTokenizationAndAnswerEvaluation()
    {
        IReadOnlyList<string> tokens = SentenceTokenizer.Tokenize("  Student’s   skills improve. ");
        Require(tokens.SequenceEqual(new[] { "student's", "skills", "improve" }), "Token normalization failed for apostrophe/whitespace/case.");

        SentenceAnswerResult exact = SentenceAnswerEvaluator.Evaluate("Oxford University improves the skills of students", "Oxford University improves the skills of students");
        Require(exact.Accepted && !exact.WordOrderIgnored, "Exact Sentence Spelling answer was rejected.");

        SentenceAnswerResult reordered = SentenceAnswerEvaluator.Evaluate("Oxford University improves the skills of students", "students skills the of improves University Oxford");
        Require(reordered.Accepted && reordered.WordOrderIgnored, "Correct token multiset in a different order was not accepted.");

        SentenceAnswerResult strictForm = SentenceAnswerEvaluator.Evaluate("She improves skills", "She improve skills");
        Require(!strictForm.Accepted && strictForm.Missing.Contains("improves") && strictForm.Extra.Contains("improve"), "Required inflected form was not enforced.");

        SentenceAnswerResult duplicate = SentenceAnswerEvaluator.Evaluate("we learn words", "we learn learn");
        Require(!duplicate.Accepted && duplicate.Missing.Contains("words") && duplicate.Extra.Contains("learn"), "Missing/duplicated token diagnosis failed.");

        SentenceAnswerResult misspelled = SentenceAnswerEvaluator.Evaluate("students improve", "studnts improve");
        Require(!misspelled.Accepted && misspelled.PossibleMisspellings.Count == 1, "Misspelling was not rejected/diagnosed.");
    }

    private static void TestOneAndTwoTargetLookup()
    {
        SentencePack pack = BuildPack();
        Require(pack.LookupByEntryId("ox-improve").Count == 3, "One-target inverted index lookup returned the wrong count.");
        IReadOnlyList<SentenceRecord> both = pack.LookupAllTargets(new[] { "ox-improve", "ox-skills" });
        Require(both.Count == 3 && both.All(s => s.TargetEntryIds.Contains("ox-improve") && s.TargetEntryIds.Contains("ox-skills")), "Two-target intersection did not require both targets.");
        Require(pack.LookupAllTargets(new[] { "ox-improve", "not-present" }).Count == 0, "Intersection lookup invented a missing target.");
    }

    private static void TestPersonalDifficultyRankingAndScope()
    {
        SentencePack pack = BuildPack();
        var selector = new SentenceSelector(pack);
        var allowed = new HashSet<string>(new[] { "ox-improve", "ox-skills" }, StringComparer.OrdinalIgnoreCase);
        var levels = new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase) { ["ox-improve"]="B1", ["ox-skills"]="A2", ["ox-practical"]="B2", ["ox-student"]="A2", ["ox-every"]="A1", ["ox-day"]="A1" };
        var context = new SentenceSelectionContext(allowed, new HashSet<string>(StringComparer.OrdinalIgnoreCase), new HashSet<string>(StringComparer.OrdinalIgnoreCase), levels);
        SentenceSelectionResult? result = selector.Select(new[] { "ox-improve", "ox-skills" }, context);
        Require(result?.Sentence.Id == "s1", "Selector did not prefer the clear low-unknown context sentence closest to its preferred practice length.");

        var known = new HashSet<string>(new[] { "ox-practical", "ox-student", "ox-every", "ox-day" }, StringComparer.OrdinalIgnoreCase);
        var knownContext = context with { KnownEntryIds = known, RecentSentenceIds = new HashSet<string>(new[] { "s1" }, StringComparer.OrdinalIgnoreCase) };
        SentenceSelectionResult? knownResult = selector.Select(new[] { "ox-improve", "ox-skills" }, knownContext);
        Require(knownResult is not null && knownResult.Sentence.Id == "s2", "Known context vocabulary plus recent avoidance did not promote a richer but now-personally-easy sentence.");

        bool leakageRejected = false;
        try { selector.Select(new[] { "ox-practical" }, context); } catch (InvalidOperationException) { leakageRejected = true; }
        Require(leakageRejected, "Sentence selector allowed a target outside the user-selected training scope.");
    }

    private static void TestRecentAvoidance()
    {
        SentencePack pack = BuildPack();
        var selector = new SentenceSelector(pack);
        var allowed = new HashSet<string>(new[] { "ox-improve" }, StringComparer.OrdinalIgnoreCase);
        var context = new SentenceSelectionContext(allowed, new HashSet<string>(StringComparer.OrdinalIgnoreCase), new HashSet<string>(new[] { "s1" }, StringComparer.OrdinalIgnoreCase), new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase) { ["ox-improve"]="B1" });
        SentenceSelectionResult? result = selector.Select(new[] { "ox-improve" }, context);
        Require(result is not null && result.Sentence.Id != "s1", "Recent-sentence penalty did not avoid an immediate repeat when alternatives existed.");
    }

    private static void TestGeneratorFallbackContract()
    {
        SentencePack pack = BuildPack();
        var fallback = new StubGenerator();
        var selector = new SentenceSelector(pack, fallback);
        var allowed = new HashSet<string>(new[] { "missing-a", "missing-b" }, StringComparer.OrdinalIgnoreCase);
        var context = new SentenceSelectionContext(allowed, new HashSet<string>(StringComparer.OrdinalIgnoreCase), new HashSet<string>(StringComparer.OrdinalIgnoreCase), new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase));
        SentenceSelectionResult? result = selector.Select(new[] { "missing-a", "missing-b" }, context);
        Require(result is not null && result.Generated && result.Sentence.TargetEntryIds.Count == 2, "Controlled generator fallback contract failed for a missing two-target corpus intersection.");
    }

    private sealed class StubGenerator : IControlledSentenceGenerator
    {
        public SentenceRecord? TryGenerate(IReadOnlyList<string> targetEntryIds, SentenceSelectionContext context)
        {
            string english = "alpha beta";
            return new SentenceRecord
            {
                Id = "generated-test",
                English = english,
                Ukrainian = "альфа бета",
                Source = "controlled-test-generator",
                License = "internal-generated",
                Tokens = SentenceTokenizer.Tokenize(english).ToList(),
                Lemmas = new List<string> { "alpha", "beta" },
                TargetEntryIds = targetEntryIds.ToList(),
                EntryLevels = targetEntryIds.ToDictionary(id => id, _ => "A1", StringComparer.OrdinalIgnoreCase)
            };
        }
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }
}
