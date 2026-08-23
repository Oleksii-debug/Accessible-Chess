namespace WordDeck;

internal static class MorphologySelfTest
{
    public static void Run()
    {
        ValidateSourceBackedOverlayAndQuarantine();
        ValidatePhysicalLexicalAmbiguityIsNotCollapsed();
        ValidateTsvIngestionBoundary();
        ValidateDeterministicPracticeAndIntegrationTargets();
        ValidateOxfordScaleIndexingContract();
    }

    private static void ValidateSourceBackedOverlayAndQuarantine()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        var package = new MorphologyOverlayPackage
        {
            PackageId = "fixture-morphology-v1",
            Source = FixtureSource(),
            Relations = new MorphologyRelation[]
            {
                new("r-act-action", "family-act", "ox:act:v", "ox:action:n", MorphologyRelationKind.Derivation, null, "fixture:1", 1),
                new("r-act-active", "family-act", "ox:act:v", "ox:active:adj", MorphologyRelationKind.Derivation, null, "fixture:2", 2),
                new("r-active-activity", "family-act", "ox:active:adj", "ox:activity:n", MorphologyRelationKind.Suffix, "-ity", "fixture:3", 3),
                new("r-active-activate", "family-act", "ox:active:adj", "ox:activate:v", MorphologyRelationKind.Suffix, "-ate", "fixture:4", 4),
                new("r-self", "family-act", "ox:act:v", "ox:act:v", MorphologyRelationKind.Root, "act", "fixture:bad-self", 5),
                new("r-unknown", "family-act", "ox:act:v", "ox:missing", MorphologyRelationKind.Derivation, null, "fixture:bad-missing", 6),
                new("r-act-action-duplicate", "family-act", "ox:act:v", "ox:action:n", MorphologyRelationKind.Derivation, null, "fixture:duplicate", 7)
            }
        };

        MorphologyBuildResult result = MorphologyOverlayBuilder.Build(package, dictionary);
        Assert(result.AcceptedRelations == 4, $"Expected four accepted source-backed relations, got {result.AcceptedRelations}.");
        Assert(result.Issues.Any(issue => issue.Code == "relation.self-link"), "Self-links must fail closed.");
        Assert(result.Issues.Any(issue => issue.Code == "relation.unknown-to"), "Unknown stable IDs must fail closed.");
        Assert(result.Issues.Any(issue => issue.Code == "relation.duplicate-edge"), "Duplicate relation edges must be quarantined.");

        IReadOnlyList<string> family = result.Overlay.GetFamilyMembers("ox:act:v");
        Assert(family.Count == 5, $"Expected five distinct canonical IDs in act family, got {family.Count}.");
        Assert(family.Contains("ox:activity:n", StringComparer.OrdinalIgnoreCase), "Family traversal lost activity stable ID.");
        Assert(family.Contains("ox:activate:v", StringComparer.OrdinalIgnoreCase), "Family traversal lost activate stable ID.");

        var missingProvenance = new MorphologyOverlayPackage
        {
            PackageId = "untrusted",
            Source = new MorphologySourceMetadata("", "", "", ""),
            Relations = package.Relations.Take(1).ToArray()
        };
        MorphologyBuildResult rejectedPackage = MorphologyOverlayBuilder.Build(missingProvenance, dictionary);
        Assert(rejectedPackage.AcceptedRelations == 0, "A package without provenance/license/attribution must not accept relations.");
        Assert(rejectedPackage.Issues.Any(issue => issue.Code == "source.license"), "Missing license must be explicit.");
        Assert(rejectedPackage.Issues.Any(issue => issue.Code == "source.attribution"), "Missing attribution must be explicit.");
    }

    private static void ValidatePhysicalLexicalAmbiguityIsNotCollapsed()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        var package = new MorphologyOverlayPackage
        {
            PackageId = "fixture-ambiguity-v1",
            Source = FixtureSource(),
            Relations = new MorphologyRelation[]
            {
                new("r-record-recording", "family-record-verb", "ox:record:v", "ox:recording:n", MorphologyRelationKind.Suffix, "-ing", "fixture:recording", 1)
            }
        };

        MorphologyOverlay overlay = MorphologyOverlayBuilder.Build(package, dictionary).Overlay;
        IReadOnlyList<string> verbFamily = overlay.GetFamilyMembers("ox:record:v");
        IReadOnlyList<string> nounFamily = overlay.GetFamilyMembers("ox:record:n");

        Assert(verbFamily.Contains("ox:recording:n", StringComparer.OrdinalIgnoreCase), "Explicit verb relation was not indexed.");
        Assert(!verbFamily.Contains("ox:record:n", StringComparer.OrdinalIgnoreCase), "Equal surface form incorrectly merged noun and verb stable IDs.");
        Assert(nounFamily.Count == 1 && nounFamily[0].Equals("ox:record:n", StringComparison.OrdinalIgnoreCase), "Unrelated homograph must remain an independent canonical entry.");
    }

    private static void ValidateTsvIngestionBoundary()
    {
        string tsv = string.Join('\n', new[]
        {
            "# schemaVersion=1",
            "# packageId=approved-source-v1",
            "# sourceId=source-fixture",
            "# sourceName=Curated fixture source",
            "# license=CC-BY-4.0 fixture only",
            "# attribution=Fixture author",
            "# sourceUri=https://example.invalid/morphology",
            "relationId\tfamilyId\tfromEntryId\ttoEntryId\tkind\tmorpheme\tevidenceRef",
            "r1\tfamily-act\tox:act:v\tox:action:n\tDerivation\t\trow:1",
            "bad-kind\tfamily-act\tox:act:v\tox:active:adj\tGuess\t\trow:2",
            "bad-columns\tfamily-act\tox:act:v",
            "r2\tfamily-act\tox:active:adj\tox:activity:n\tSuffix\t-ity\trow:3"
        });

        MorphologyImportResult import = MorphologyOverlayTsv.Parse(tsv);
        Assert(import.Package is not null, "Valid metadata/header should create an import package.");
        Assert(import.Issues.Count == 2, $"Expected two parser quarantines, got {import.Issues.Count}.");
        Assert(import.Issues.Any(issue => issue.Code == "tsv.kind"), "Unknown relation kind must be quarantined.");
        Assert(import.Issues.Any(issue => issue.Code == "tsv.columns"), "Malformed row must be quarantined.");

        MorphologyBuildResult built = MorphologyOverlayBuilder.Build(import.Package!, FixtureDictionary());
        Assert(built.AcceptedRelations == 2, "Valid rows must continue after malformed/uncertain rows.");
        Assert(import.Package!.Source.License.Contains("CC-BY", StringComparison.OrdinalIgnoreCase), "License metadata did not survive ingestion.");
        Assert(import.Package.Source.Attribution == "Fixture author", "Attribution metadata did not survive ingestion.");
    }

    private static void ValidateDeterministicPracticeAndIntegrationTargets()
    {
        var package = new MorphologyOverlayPackage
        {
            PackageId = "fixture-practice-v1",
            Source = FixtureSource(),
            Relations = new MorphologyRelation[]
            {
                new("r-act-action", "family-act", "ox:act:v", "ox:action:n", MorphologyRelationKind.Derivation, null, "fixture:1"),
                new("r-act-active", "family-act", "ox:act:v", "ox:active:adj", MorphologyRelationKind.Derivation, null, "fixture:2")
            }
        };
        MorphologyOverlay overlay = MorphologyOverlayBuilder.Build(package, FixtureDictionary()).Overlay;

        MorphologyExercise? first = overlay.CreateRecallExercise("ox:act:v", 0);
        MorphologyExercise? firstAgain = overlay.CreateRecallExercise("ox:act:v", 0);
        Assert(first is not null && firstAgain is not null, "Practice exercise was not created.");
        Assert(first!.RelationId == firstAgain!.RelationId && first.TargetEntryId == firstAgain.TargetEntryId, "Exercise selection must be deterministic for the same sequence.");
        Assert(first.Check(first.AcceptedAnswer.ToUpperInvariant()), "Exact target form checking should be case-insensitive.");
        Assert(!first.Check("unrelated"), "Unrelated answer must fail deterministic checking.");

        IReadOnlyList<MorphologyIntegrationTarget> targets = overlay.GetIntegrationTargets("ox:act:v");
        Assert(targets.Count == 2, "Sentence/Grammar/Reading integration target projection lost explicit relations.");
        Assert(targets.All(target => target.EntryId != "ox:act:v"), "Integration targets must preserve distinct related IDs, not echo/collapse the source ID.");
    }

    private static void ValidateOxfordScaleIndexingContract()
    {
        const int count = 5446;
        var entries = Enumerable.Range(1, count)
            .Select(index => new DictionaryEntry($"scale:{index:D4}", index <= 4000 ? "B2" : "C1", $"word{index}", $"слово{index}"))
            .ToArray();
        var dictionary = new DictionaryPackage
        {
            Id = "scale-fixture",
            Name = "5446-entry synthetic test fixture",
            SourceLanguage = "en",
            TargetLanguage = "uk",
            Entries = entries
        };
        MorphologyRelation[] relations = Enumerable.Range(1, count - 1)
            .Select(index => new MorphologyRelation(
                $"scale-r:{index:D4}",
                "scale-family",
                $"scale:{index:D4}",
                $"scale:{index + 1:D4}",
                MorphologyRelationKind.Derivation,
                null,
                $"fixture:{index}"))
            .ToArray();
        var package = new MorphologyOverlayPackage
        {
            PackageId = "scale-fixture-v1",
            Source = FixtureSource(),
            Relations = relations
        };

        MorphologyBuildResult result = MorphologyOverlayBuilder.Build(package, dictionary);
        Assert(result.AcceptedRelations == count - 1, "5446-scale relation indexing dropped valid explicit edges.");
        Assert(result.Issues.Count == 0, "5446-scale valid fixture unexpectedly produced validation issues.");
        IReadOnlyList<string> bounded = result.Overlay.GetFamilyMembers("scale:0001", 64);
        Assert(bounded.Count == 64, $"Bounded family traversal must stop at 64 nodes, got {bounded.Count}.");
    }

    private static DictionaryPackage FixtureDictionary()
    {
        return new DictionaryPackage
        {
            Id = "fixture-dictionary",
            Name = "Morphology synthetic test fixture",
            SourceLanguage = "en",
            TargetLanguage = "uk",
            Entries = new DictionaryEntry[]
            {
                new("ox:act:v", "B2", "act", "діяти"),
                new("ox:action:n", "B2", "action", "дія"),
                new("ox:active:adj", "B2", "active", "активний"),
                new("ox:activity:n", "B2", "activity", "діяльність"),
                new("ox:activate:v", "C1", "activate", "активувати"),
                new("ox:record:v", "B2", "record", "записувати"),
                new("ox:record:n", "B2", "record", "запис"),
                new("ox:recording:n", "B2", "recording", "записування")
            }
        };
    }

    private static MorphologySourceMetadata FixtureSource() =>
        new(
            "synthetic-test-fixture",
            "Synthetic morphology fixture",
            "TEST-ONLY",
            "WordDeck deterministic self-test fixture",
            "https://example.invalid/test-fixture",
            "1");

    private static void Assert(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException($"Morphology self-test failed: {message}");
    }
}