namespace WordDeck;

internal static class MorphologyReadingBridgeSelfTest
{
    public static void Run()
    {
        ValidateSentenceProjectionAndPrivacyBoundary();
        ValidateExplicitAmbiguityProof();
        ValidateStudyPoolFiltering();
    }

    private static void ValidateSentenceProjectionAndPrivacyBoundary()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        MorphologyOverlay overlay = BuildOverlay(dictionary);
        var bridge = new MorphologyReadingBridge(overlay, dictionary);

        MorphologyReadingProjection projection = bridge.ProjectSentence(new[] { "ox:act:v", "ox:record:v" });
        Assert(projection.Suggestions.Any(item => item.AnchorEntryId == "ox:act:v"), "Unambiguous sentence anchor did not produce a Reading morphology suggestion.");
        Assert(!projection.Suggestions.Any(item => item.AnchorEntryId == "ox:record:v"), "Unresolved homograph sentence anchor must fail closed.");
        Assert(projection.ExcludedAmbiguousStableIds.Contains("ox:record:v", StringComparer.OrdinalIgnoreCase), "Reading ambiguity ledger lost the unresolved record verb ID.");
        MorphologyReadingSuggestion act = projection.Suggestions.Single(item => item.AnchorEntryId == "ox:act:v");
        Assert(act.RelatedTargets.Any(target => target.EntryId == "ox:action:n"), "Reading projection lost the source-backed related action target.");
        Assert(!act.RelatedTargets.Any(target => target.EntryId == "ox:record:v"), "Reading projection leaked an unresolved homograph target.");
    }

    private static void ValidateExplicitAmbiguityProof()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        MorphologyOverlay overlay = BuildOverlay(dictionary);
        var bridge = new MorphologyReadingBridge(overlay, dictionary);
        var resolved = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "ox:record:v" };

        MorphologyReadingProjection projection = bridge.ProjectSentence(
            new[] { "ox:record:v", "ox:record:n" },
            resolvedAmbiguousEntryIds: resolved);
        Assert(projection.Suggestions.Any(item => item.AnchorEntryId == "ox:record:v"), "Explicit upstream identity proof did not release the exact Reading anchor stable ID.");
        Assert(!projection.Suggestions.Any(item => item.AnchorEntryId == "ox:record:n"), "Proof for record verb must not resolve record noun.");
        Assert(projection.ExcludedAmbiguousStableIds.Contains("ox:record:n", StringComparer.OrdinalIgnoreCase), "Unresolved sibling homograph is missing from Reading exclusion evidence.");
    }

    private static void ValidateStudyPoolFiltering()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        MorphologyOverlay overlay = BuildOverlay(dictionary);
        var bridge = new MorphologyReadingBridge(overlay, dictionary);
        var pool = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "ox:action:n" };

        MorphologyReadingProjection projection = bridge.ProjectSentence(new[] { "ox:act:v" }, pool);
        MorphologyReadingSuggestion suggestion = projection.Suggestions.Single();
        Assert(suggestion.RelatedTargets.Count == 1 && suggestion.RelatedTargets[0].EntryId == "ox:action:n", "Reading study-pool filter returned a target outside the selected learning pool.");
    }

    private static DictionaryPackage FixtureDictionary() => new()
    {
        Id = "morph-reading-bridge-fixture",
        Name = "Synthetic morphology Reading bridge fixture",
        SourceLanguage = "en",
        TargetLanguage = "uk",
        Entries = new DictionaryEntry[]
        {
            new("ox:act:v", "B2", "act", "діяти"),
            new("ox:action:n", "B2", "action", "дія"),
            new("ox:record:v", "B2", "record", "записувати"),
            new("ox:record:n", "B2", "record", "запис"),
            new("ox:recording:n", "B2", "recording", "записування")
        }
    };

    private static MorphologyOverlay BuildOverlay(DictionaryPackage dictionary)
    {
        var package = new MorphologyOverlayPackage
        {
            PackageId = "morph-reading-bridge-test-only",
            Source = new MorphologySourceMetadata("reading-bridge-test", "Synthetic Reading bridge fixture", "TEST-ONLY", "WordDeck tests", "https://example.invalid/reading-bridge"),
            Relations = new MorphologyRelation[]
            {
                new("r-act-action", "family-act", "ox:act:v", "ox:action:n", MorphologyRelationKind.Derivation, null, "fixture:1"),
                new("r-act-record", "family-cross", "ox:act:v", "ox:record:v", MorphologyRelationKind.Derivation, null, "fixture:2"),
                new("r-record-recording", "family-record", "ox:record:v", "ox:recording:n", MorphologyRelationKind.Suffix, "-ing", "fixture:3")
            }
        };
        MorphologyBuildResult build = MorphologyOverlayBuilder.Build(package, dictionary);
        Assert(build.Issues.Count == 0, "Reading bridge fixture unexpectedly failed morphology validation.");
        return build.Overlay;
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException($"Morphology Reading bridge self-test failed: {message}");
    }
}
