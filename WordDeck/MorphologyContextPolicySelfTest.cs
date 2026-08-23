namespace WordDeck;

internal static class MorphologyContextPolicySelfTest
{
    public static void Run()
    {
        ValidateAmbiguousTargetsFailClosed();
        ValidateStudyPoolAndLevelFiltering();
    }

    private static void ValidateAmbiguousTargetsFailClosed()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        MorphologyOverlay overlay = BuildOverlay(dictionary,
            new MorphologyRelation("r-act-action", "family-act", "ox:act:v", "ox:action:n", MorphologyRelationKind.Derivation, null, "fixture:1"),
            new MorphologyRelation("r-act-record", "family-cross", "ox:act:v", "ox:record:v", MorphologyRelationKind.Derivation, null, "fixture:2"),
            new MorphologyRelation("r-act-recording", "family-cross", "ox:act:v", "ox:recording:n", MorphologyRelationKind.Derivation, null, "fixture:3"));
        var planner = new MorphologyContextTargetPlanner(overlay, dictionary);

        MorphologyContextTargetPlan plan = planner.Plan("ox:act:v");
        Assert(plan.SafeRelatedTargets.Any(target => target.EntryId == "ox:action:n"), "Safe related action target was lost.");
        Assert(plan.SafeRelatedTargets.Any(target => target.EntryId == "ox:recording:n"), "Safe related recording target was lost.");
        Assert(!plan.SafeRelatedTargets.Any(target => target.EntryId == "ox:record:v"), "Ambiguous record stable ID must not reach downstream Context targets.");
        Assert(plan.ExcludedAmbiguousStableIds.Contains("ox:record:v", StringComparer.OrdinalIgnoreCase), "Excluded ambiguity ledger lost record verb ID.");
        Assert(plan.PhysicalTargetPoolEntryIds.Count == 3, "Anchor plus two safe physically distinct targets expected.");

        bool threw = false;
        try { planner.Plan("ox:record:v"); }
        catch (InvalidDataException ex)
        {
            threw = ex.Message.Contains("ambiguity", StringComparison.OrdinalIgnoreCase);
        }
        Assert(threw, "Ambiguous homograph anchor must fail closed before corpus target selection.");
    }

    private static void ValidateStudyPoolAndLevelFiltering()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        MorphologyOverlay overlay = BuildOverlay(dictionary,
            new MorphologyRelation("r-act-action", "family-act", "ox:act:v", "ox:action:n", MorphologyRelationKind.Derivation, null, "fixture:1"),
            new MorphologyRelation("r-act-activate", "family-act", "ox:act:v", "ox:activate:v", MorphologyRelationKind.Derivation, null, "fixture:2"));
        var planner = new MorphologyContextTargetPlanner(overlay, dictionary);
        var pool = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "ox:act:v", "ox:action:n", "ox:activate:v" };
        var b2 = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "B2" };

        MorphologyContextTargetPlan b2Plan = planner.Plan("ox:act:v", pool, b2);
        Assert(b2Plan.SafeRelatedTargets.Count == 1 && b2Plan.SafeRelatedTargets[0].EntryId == "ox:action:n", "CEFR filter produced the wrong morphology Context target.");

        var reducedPool = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "ox:act:v", "ox:activate:v" };
        MorphologyContextTargetPlan reduced = planner.Plan("ox:act:v", reducedPool);
        Assert(reduced.SafeRelatedTargets.Count == 1 && reduced.SafeRelatedTargets[0].EntryId == "ox:activate:v", "Study-pool filter must preserve only active-deck morphology targets.");

        bool anchorRejected = false;
        try { planner.Plan("ox:act:v", new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "ox:action:n" }); }
        catch (InvalidDataException) { anchorRejected = true; }
        Assert(anchorRejected, "Anchor outside the active study pool must be rejected.");
    }

    private static DictionaryPackage FixtureDictionary() => new()
    {
        Id = "morph-context-policy-fixture",
        Name = "Synthetic morphology context policy fixture",
        SourceLanguage = "en",
        TargetLanguage = "uk",
        Entries = new DictionaryEntry[]
        {
            new("ox:act:v", "B2", "act", "діяти"),
            new("ox:action:n", "B2", "action", "дія"),
            new("ox:activate:v", "C1", "activate", "активувати"),
            new("ox:record:v", "B2", "record", "записувати"),
            new("ox:record:n", "B2", "record", "запис"),
            new("ox:recording:n", "B2", "recording", "записування")
        }
    };

    private static MorphologyOverlay BuildOverlay(DictionaryPackage dictionary, params MorphologyRelation[] relations)
    {
        var package = new MorphologyOverlayPackage
        {
            PackageId = "context-policy-test-only",
            Source = new MorphologySourceMetadata("context-policy-test", "Synthetic context policy fixture", "TEST-ONLY", "WordDeck tests", "https://example.invalid/context-policy"),
            Relations = relations
        };
        MorphologyBuildResult build = MorphologyOverlayBuilder.Build(package, dictionary);
        Assert(build.Issues.Count == 0, "Context policy fixture unexpectedly failed morphology validation.");
        return build.Overlay;
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException($"Morphology Context policy self-test failed: {message}");
    }
}
