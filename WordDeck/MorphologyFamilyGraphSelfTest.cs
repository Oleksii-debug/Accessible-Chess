namespace WordDeck;

internal static class MorphologyFamilyGraphSelfTest
{
    public static void Run()
    {
        ValidateFamilyScopedTraversalDoesNotLeakAcrossDownstreamFamily();
        ValidateExplicitAffixDirectionAndSharedRootSemantics();
        ValidateHomographLabelsPreserveExactStableIdentity();
        ValidatePracticePromptsDisambiguateHomographsAndReverseAffixDirection();
    }

    private static void ValidateFamilyScopedTraversalDoesNotLeakAcrossDownstreamFamily()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        MorphologyOverlay overlay = BuildOverlay(dictionary,
            new MorphologyRelation("r-act-action", "family-act", "ox:act:v", "ox:action:n", MorphologyRelationKind.Derivation, null, "fixture:1"),
            new MorphologyRelation("r-action-recording", "family-record", "ox:action:n", "ox:recording:n", MorphologyRelationKind.Derivation, null, "fixture:2"));
        var graph = new MorphologyFamilyGraph(overlay, dictionary);

        IReadOnlyList<string> actFamily = graph.GetFamilyMembers("ox:act:v", "family-act");
        Assert(actFamily.SequenceEqual(new[] { "ox:act:v", "ox:action:n" }, StringComparer.OrdinalIgnoreCase),
            "Family-scoped traversal must stay inside family-act.");

        IReadOnlyList<string> safeAggregate = graph.GetAnchorFamiliesWithoutCrossFamilyLeakage("ox:act:v");
        Assert(!safeAggregate.Contains("ox:recording:n", StringComparer.OrdinalIgnoreCase),
            "A second family attached only to a downstream member must not become a transitive bridge into the anchor family.");
    }

    private static void ValidateExplicitAffixDirectionAndSharedRootSemantics()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        MorphologyOverlay overlay = BuildOverlay(dictionary,
            new MorphologyRelation("r-happy-unhappy", "family-happy", "ox:happy:adj", "ox:unhappy:adj", MorphologyRelationKind.Prefix, "un-", "fixture:prefix"),
            new MorphologyRelation("r-active-activity", "family-act", "ox:active:adj", "ox:activity:n", MorphologyRelationKind.Suffix, "-ity", "fixture:suffix"),
            new MorphologyRelation("r-act-action-root", "family-act", "ox:act:v", "ox:action:n", MorphologyRelationKind.Root, "act", "fixture:root"));
        var graph = new MorphologyFamilyGraph(overlay, dictionary);

        MorphologyRelationSemantics prefix = graph.Describe("r-happy-unhappy");
        Assert(prefix.Description.Contains("happy», → «unhappy", StringComparison.Ordinal),
            "Prefix semantics must preserve declared FromEntryId -> ToEntryId direction.");
        Assert(prefix.Description.Contains("un-", StringComparison.Ordinal), "Prefix morpheme was lost.");

        MorphologyRelationSemantics suffix = graph.Describe("r-active-activity");
        Assert(suffix.Description.Contains("active», → «activity", StringComparison.Ordinal),
            "Suffix semantics must preserve declared FromEntryId -> ToEntryId direction.");
        Assert(suffix.Description.Contains("-ity", StringComparison.Ordinal), "Suffix morpheme was lost.");

        MorphologyRelationSemantics root = graph.Describe("r-act-action-root");
        Assert(root.Description.Contains("↔", StringComparison.Ordinal),
            "Root semantics must remain shared/non-directional rather than pretending an affix operation.");
    }

    private static void ValidateHomographLabelsPreserveExactStableIdentity()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        var formatter = new MorphologyLexicalIdentityFormatter(dictionary);

        Assert(formatter.IsAmbiguous("ox:record:v") && formatter.IsAmbiguous("ox:record:n"),
            "Equal-written-form record entries must remain marked ambiguous.");
        Assert(formatter.Format("ox:record:v") == "record — записувати",
            "Verb record label must use the canonical translation attached to that exact stable ID.");
        Assert(formatter.Format("ox:record:n") == "record — запис",
            "Noun record label must remain distinct from the verb label.");
        Assert(formatter.Format("ox:act:v") == "act", "Unambiguous surfaces should not gain unnecessary disambiguation text.");
    }

    private static void ValidatePracticePromptsDisambiguateHomographsAndReverseAffixDirection()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        MorphologyOverlay overlay = BuildOverlay(dictionary,
            new MorphologyRelation("r-record-recording", "family-record", "ox:record:v", "ox:recording:n", MorphologyRelationKind.Suffix, "-ing", "fixture:record"),
            new MorphologyRelation("r-happy-unhappy", "family-happy", "ox:happy:adj", "ox:unhappy:adj", MorphologyRelationKind.Prefix, "un-", "fixture:happy"));
        var practice = new MorphologyPracticeService(overlay, dictionary);

        MorphologyPracticeItem? record = practice.Create("ox:record:v", MorphologyPracticeKind.RelatedFormProduction);
        Assert(record is not null && record.Prompt.Contains("record — записувати", StringComparison.Ordinal),
            "Morphology practice must disambiguate a homograph source without exposing/merging its sibling ID.");

        MorphologyPracticeItem? reverse = practice.Create("ox:unhappy:adj", MorphologyPracticeKind.RelatedFormProduction);
        Assert(reverse is not null && reverse.ExpectedAnswer == "happy", "Reverse prefix practice target should preserve the exact opposite endpoint.");
        Assert(reverse!.Prompt.Contains("вихідну", StringComparison.OrdinalIgnoreCase),
            "Reverse prefix practice must not incorrectly describe the source as the forward affix-derived target.");
    }

    private static DictionaryPackage FixtureDictionary() => new()
    {
        Id = "morph-hardening-fixture",
        Name = "Synthetic morphology hardening fixture",
        SourceLanguage = "en",
        TargetLanguage = "uk",
        Entries = new DictionaryEntry[]
        {
            new("ox:act:v", "B2", "act", "діяти"),
            new("ox:action:n", "B2", "action", "дія"),
            new("ox:active:adj", "B2", "active", "активний"),
            new("ox:activity:n", "B2", "activity", "діяльність"),
            new("ox:record:v", "B2", "record", "записувати"),
            new("ox:record:n", "B2", "record", "запис"),
            new("ox:recording:n", "B2", "recording", "записування"),
            new("ox:happy:adj", "A2", "happy", "щасливий"),
            new("ox:unhappy:adj", "B1", "unhappy", "нещасливий")
        }
    };

    private static MorphologyOverlay BuildOverlay(DictionaryPackage dictionary, params MorphologyRelation[] relations)
    {
        var package = new MorphologyOverlayPackage
        {
            PackageId = "morph-hardening-test-only",
            Source = new MorphologySourceMetadata(
                "morph-hardening-test",
                "Synthetic morphology hardening fixture",
                "TEST-ONLY",
                "WordDeck deterministic self-test",
                "https://example.invalid/morph-hardening"),
            Relations = relations
        };
        MorphologyBuildResult build = MorphologyOverlayBuilder.Build(package, dictionary);
        Assert(build.Issues.Count == 0, "Hardening fixture unexpectedly failed source-backed morphology validation.");
        return build.Overlay;
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException($"Morphology family graph self-test failed: {message}");
    }
}
