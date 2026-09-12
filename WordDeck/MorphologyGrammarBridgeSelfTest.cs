namespace WordDeck;

internal static class MorphologyGrammarBridgeSelfTest
{
    public static void Run()
    {
        ValidateCanonicalSkillResolutionAndTargets();
        ValidateAmbiguityEvidenceHandoff();
        ValidateUnknownSkillFailsClosed();
    }

    private static void ValidateCanonicalSkillResolutionAndTargets()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        MorphologyOverlay overlay = BuildOverlay(dictionary);
        var bridge = new MorphologyGrammarBridge(overlay, dictionary);
        var pool = dictionary.Entries.Select(entry => entry.Id).ToHashSet(StringComparer.OrdinalIgnoreCase);

        MorphologyGrammarTargetPlan plan = bridge.Plan(
            "ox:act:v",
            "grammar.present-simple.statement",
            pool,
            new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "B2" });

        Assert(plan.GrammarSkillId == "present.simple.core", "Grammar legacy alias did not resolve through the canonical resolver.");
        Assert(plan.RelatedVocabularyTargets.Count == 1 && plan.RelatedVocabularyTargets[0].EntryId == "ox:action:n", "Grammar bridge returned the wrong safe morphology vocabulary target.");
        Assert(plan.ExcludedAmbiguousStableIds.Contains("ox:record:v", StringComparer.OrdinalIgnoreCase), "Grammar bridge did not expose the unresolved homograph exclusion ledger.");
    }

    private static void ValidateAmbiguityEvidenceHandoff()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        MorphologyOverlay overlay = BuildOverlay(dictionary);
        var bridge = new MorphologyGrammarBridge(overlay, dictionary);
        var pool = dictionary.Entries.Select(entry => entry.Id).ToHashSet(StringComparer.OrdinalIgnoreCase);
        var resolved = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "ox:record:v" };

        MorphologyGrammarTargetPlan plan = bridge.Plan(
            "ox:act:v",
            "present.simple.core",
            pool,
            null,
            16,
            resolved);
        Assert(plan.RelatedVocabularyTargets.Any(target => target.EntryId == "ox:record:v"), "Explicit upstream POS/sense resolution did not release the proven homograph stable ID.");

        bool blockedAnchor = false;
        try { _ = bridge.Plan("ox:record:v", "present.simple.core", pool); }
        catch (InvalidDataException ex) { blockedAnchor = ex.Message.Contains("ambiguity", StringComparison.OrdinalIgnoreCase); }
        Assert(blockedAnchor, "Unresolved homograph Grammar anchor must fail closed.");

        MorphologyGrammarTargetPlan resolvedAnchor = bridge.Plan("ox:record:v", "present.simple.core", pool, null, 16, resolved);
        Assert(resolvedAnchor.AnchorEntryId == "ox:record:v", "Explicit upstream resolution did not preserve the exact homograph stable ID.");
    }

    private static void ValidateUnknownSkillFailsClosed()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        MorphologyOverlay overlay = BuildOverlay(dictionary);
        var bridge = new MorphologyGrammarBridge(overlay, dictionary);
        bool rejected = false;
        try { _ = bridge.Plan("ox:act:v", "grammar.nonexistent-skill"); }
        catch (InvalidDataException) { rejected = true; }
        Assert(rejected, "Unknown Grammar skill reference must fail closed through the canonical resolver.");
    }

    private static DictionaryPackage FixtureDictionary() => new()
    {
        Id = "morph-grammar-bridge-fixture",
        Name = "Synthetic morphology Grammar bridge fixture",
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
            PackageId = "morph-grammar-bridge-test-only",
            Source = new MorphologySourceMetadata("grammar-bridge-test", "Synthetic Grammar bridge fixture", "TEST-ONLY", "WordDeck tests", "https://example.invalid/grammar-bridge"),
            Relations = new MorphologyRelation[]
            {
                new("r-act-action", "family-act", "ox:act:v", "ox:action:n", MorphologyRelationKind.Derivation, null, "fixture:1"),
                new("r-act-record", "family-cross", "ox:act:v", "ox:record:v", MorphologyRelationKind.Derivation, null, "fixture:2"),
                new("r-record-recording", "family-record", "ox:record:v", "ox:recording:n", MorphologyRelationKind.Suffix, "-ing", "fixture:3")
            }
        };
        MorphologyBuildResult build = MorphologyOverlayBuilder.Build(package, dictionary);
        Assert(build.Issues.Count == 0, "Grammar bridge fixture unexpectedly failed morphology validation.");
        return build.Overlay;
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException($"Morphology Grammar bridge self-test failed: {message}");
    }
}
