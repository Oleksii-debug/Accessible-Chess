namespace WordDeck;

internal static class MorphologyPracticeSelfTest
{
    public static void Run()
    {
        ValidateExplanationAndPracticeModes();
        ValidateContextFiltering();
        ValidateFutureUserVocabularyIdsRemainOpaque();
    }

    private static void ValidateExplanationAndPracticeModes()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        MorphologyOverlay overlay = BuildOverlay(dictionary,
            new MorphologyRelation("r-active-activity", "family-act", "ox:active:adj", "ox:activity:n", MorphologyRelationKind.Suffix, "-ity", "fixture:42"),
            new MorphologyRelation("r-act-action", "family-act", "ox:act:v", "ox:action:n", MorphologyRelationKind.Derivation, null, "fixture:43"));
        var service = new MorphologyPracticeService(overlay, dictionary);

        IReadOnlyList<MorphologyRelationExplanation> explanations = service.ExplainEntry("ox:active:adj");
        Assert(explanations.Count == 1, "Expected one explicit explanation for active.");
        Assert(explanations[0].Explanation.Contains("-ity", StringComparison.Ordinal), "Suffix explanation lost explicit source morpheme.");
        Assert(explanations[0].Explanation.Contains("fixture:42", StringComparison.Ordinal), "Explanation lost evidence reference.");

        MorphologyPracticeItem? related = service.Create("ox:active:adj", MorphologyPracticeKind.RelatedFormProduction, 0);
        Assert(related is not null && related.ExpectedAnswer == "activity", "Related-form production target is incorrect.");
        Assert(related!.Check(" ACTIVITY "), "Related-form checking should normalize whitespace/case.");
        Assert(!related.Check("active"), "Source form must not pass as target form.");

        MorphologyPracticeItem? morpheme = service.Create("ox:active:adj", MorphologyPracticeKind.MorphemeProduction, 0);
        Assert(morpheme is not null && morpheme.ExpectedAnswer == "-ity", "Morpheme production target is incorrect.");
        Assert(morpheme!.Check("-ITY"), "Morpheme checking should be case-insensitive.");

        MorphologyPracticeItem? absentMorpheme = service.Create("ox:act:v", MorphologyPracticeKind.MorphemeProduction, 0);
        Assert(absentMorpheme is null, "Derivation without explicit morpheme must not invent a morphology answer.");
    }

    private static void ValidateContextFiltering()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        MorphologyOverlay overlay = BuildOverlay(dictionary,
            new MorphologyRelation("r-act-action", "family-act", "ox:act:v", "ox:action:n", MorphologyRelationKind.Derivation, null, "fixture:1"),
            new MorphologyRelation("r-act-active", "family-act", "ox:act:v", "ox:active:adj", MorphologyRelationKind.Derivation, null, "fixture:2"),
            new MorphologyRelation("r-act-activate", "family-act", "ox:act:v", "ox:activate:v", MorphologyRelationKind.Derivation, null, "fixture:3"));
        var service = new MorphologyPracticeService(overlay, dictionary);

        var knownIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "ox:action:n", "ox:activate:v"
        };
        var b2Only = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "B2" };
        IReadOnlyList<MorphologyIntegrationTarget> filtered = service.SelectContextTargets("ox:act:v", knownIds, b2Only);
        Assert(filtered.Count == 1 && filtered[0].EntryId == "ox:action:n", "Known-vocabulary/CEFR filtering returned the wrong downstream context target.");

        var c1Only = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "C1" };
        IReadOnlyList<MorphologyIntegrationTarget> c1 = service.SelectContextTargets("ox:act:v", null, c1Only);
        Assert(c1.Count == 1 && c1[0].EntryId == "ox:activate:v", "CEFR filtering must preserve exact target stable ID.");
    }

    private static void ValidateFutureUserVocabularyIdsRemainOpaque()
    {
        var dictionary = new DictionaryPackage
        {
            Id = "user-vocabulary-fixture",
            Name = "Synthetic user vocabulary fixture",
            SourceLanguage = "en",
            TargetLanguage = "uk",
            Entries = new DictionaryEntry[]
            {
                new("user:entry:001", "CUSTOM", "playful", "грайливий"),
                new("user:entry:002", "CUSTOM", "playfulness", "грайливість")
            }
        };
        var package = new MorphologyOverlayPackage
        {
            PackageId = "user-overlay-fixture",
            Source = FixtureSource(),
            Relations = new MorphologyRelation[]
            {
                new("user-r-001", "user-family-001", "user:entry:001", "user:entry:002", MorphologyRelationKind.Suffix, "-ness", "user-fixture:1")
            }
        };

        MorphologyBuildResult result = MorphologyOverlayBuilder.Build(package, dictionary);
        Assert(result.Issues.Count == 0 && result.AcceptedRelations == 1, "Opaque future user-vocabulary IDs should work when explicitly source-backed.");
        IReadOnlyList<MorphologyIntegrationTarget> targets = result.Overlay.GetIntegrationTargets("user:entry:001");
        Assert(targets.Count == 1 && targets[0].EntryId == "user:entry:002", "User-vocabulary stable ID changed or collapsed in integration projection.");
    }

    private static DictionaryPackage FixtureDictionary() => new()
    {
        Id = "practice-fixture",
        Name = "Synthetic morphology practice fixture",
        SourceLanguage = "en",
        TargetLanguage = "uk",
        Entries = new DictionaryEntry[]
        {
            new("ox:act:v", "B2", "act", "діяти"),
            new("ox:action:n", "B2", "action", "дія"),
            new("ox:active:adj", "B2", "active", "активний"),
            new("ox:activity:n", "B2", "activity", "діяльність"),
            new("ox:activate:v", "C1", "activate", "активувати")
        }
    };

    private static MorphologyOverlay BuildOverlay(DictionaryPackage dictionary, params MorphologyRelation[] relations)
    {
        var package = new MorphologyOverlayPackage
        {
            PackageId = "practice-overlay-fixture",
            Source = FixtureSource(),
            Relations = relations
        };
        MorphologyBuildResult result = MorphologyOverlayBuilder.Build(package, dictionary);
        Assert(result.Issues.Count == 0, "Practice fixture unexpectedly failed morphology validation.");
        return result.Overlay;
    }

    private static MorphologySourceMetadata FixtureSource() =>
        new("practice-test-fixture", "Synthetic practice fixture", "TEST-ONLY", "WordDeck tests", "https://example.invalid/practice");

    private static void Assert(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException($"Morphology practice self-test failed: {message}");
    }
}
