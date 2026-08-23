namespace WordDeck;

internal static class MorphologyDiagnosticsSelfTest
{
    public static void Run()
    {
        ValidateCoverageGapAndAmbiguityAccounting();
        ValidateReleaseBoundary();
        ValidateScaleAccounting();
    }

    private static void ValidateCoverageGapAndAmbiguityAccounting()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        MorphologyOverlayPackage package = FixturePackage(
            new MorphologyRelation("r-act-action", "family-act", "ox:act:v", "ox:action:n", MorphologyRelationKind.Derivation, null, "fixture:1"),
            new MorphologyRelation("r-record-recording", "family-record", "ox:record:v", "ox:recording:n", MorphologyRelationKind.Suffix, "-ing", "fixture:2"));
        MorphologyBuildResult build = MorphologyOverlayBuilder.Build(package, dictionary);
        var evidence = new MorphologyReleaseEvidence(
            MorphologyDatasetClass.TestFixture,
            new string('a', 64),
            false,
            string.Empty);

        MorphologyCandidateDiagnostics report = MorphologyDiagnostics.Analyze(package, build, dictionary, evidence);
        Assert(report.DictionaryEntries == 6, "Dictionary entry count is wrong.");
        Assert(report.CoveredStableIds == 4 && report.GapStableIds == 2, "Stable-ID coverage/gap partition is wrong.");
        Assert(report.FamilyCount == 2, "Family count is wrong.");
        Assert(report.RelationsByKind[MorphologyRelationKind.Derivation] == 1, "Derivation count is wrong.");
        Assert(report.RelationsByKind[MorphologyRelationKind.Suffix] == 1, "Suffix count is wrong.");
        Assert(report.AmbiguousSurfaceGroupsTouched == 1, "Touched homograph group was not accounted.");
        Assert(report.AmbiguousSurfaceStableIdsTouched == 1, "Only the explicitly related record stable ID should count as touched.");
        Assert(report.Gaps.Any(gap => gap.EntryId == "ox:record:n"), "Unrelated homograph must remain a coverage gap.");
        Assert(!report.ReleaseEligible, "Synthetic/test-only evidence must never become release eligible.");
        Assert(report.EvidenceBoundary.Contains("test-only", StringComparison.OrdinalIgnoreCase), "Synthetic boundary is not explicit.");

        string gapTsv = MorphologyDiagnostics.WriteGapTsv(report);
        Assert(gapTsv.StartsWith("entryId\tlevel\tsource", StringComparison.Ordinal), "Gap TSV header is wrong.");
        Assert(gapTsv.Contains("ox:record:n\tB2\trecord", StringComparison.Ordinal), "Gap TSV lost exact stable-ID ambiguity gap.");
    }

    private static void ValidateReleaseBoundary()
    {
        DictionaryPackage dictionary = FixtureDictionary();
        MorphologyOverlayPackage package = FixturePackage(
            new MorphologyRelation("r-act-action", "family-act", "ox:act:v", "ox:action:n", MorphologyRelationKind.Derivation, null, "fixture:1"));
        MorphologyBuildResult clean = MorphologyOverlayBuilder.Build(package, dictionary);

        var malformedEvidence = new MorphologyReleaseEvidence(
            MorphologyDatasetClass.ApprovedProduction,
            "not-a-sha",
            true,
            "approval:test");
        MorphologyCandidateDiagnostics malformed = MorphologyDiagnostics.Analyze(package, clean, dictionary, malformedEvidence);
        Assert(!malformed.ReleaseEligible, "Malformed source hash must block release eligibility.");
        Assert(malformed.ReleaseEvidenceIssues.Any(issue => issue.Contains("SHA-256", StringComparison.OrdinalIgnoreCase)), "Malformed hash issue is missing.");

        var structurallyComplete = new MorphologyReleaseEvidence(
            MorphologyDatasetClass.ApprovedProduction,
            new string('b', 64),
            true,
            "synthetic-structural-test-only");
        MorphologyCandidateDiagnostics eligible = MorphologyDiagnostics.Analyze(package, clean, dictionary, structurallyComplete);
        Assert(eligible.ReleaseEligible, "Structurally complete approved evidence should pass the machine release-evidence gate.");
        Assert(eligible.EvidenceBoundary.Contains("Independent", StringComparison.OrdinalIgnoreCase), "Machine gate must not masquerade as independent source/license approval.");

        MorphologyBuildResult quarantined = MorphologyOverlayBuilder.Build(
            FixturePackage(
                new MorphologyRelation("r-act-action", "family-act", "ox:act:v", "ox:action:n", MorphologyRelationKind.Derivation, null, "fixture:1"),
                new MorphologyRelation("bad", "family-act", "ox:act:v", "missing", MorphologyRelationKind.Derivation, null, "fixture:bad")),
            dictionary);
        MorphologyCandidateDiagnostics blocked = MorphologyDiagnostics.Analyze(package, quarantined, dictionary, structurallyComplete);
        Assert(!blocked.ReleaseEligible && blocked.QuarantinedIssues > 0, "Any quarantined candidate relation must block release eligibility.");
    }

    private static void ValidateScaleAccounting()
    {
        const int count = 5446;
        DictionaryEntry[] entries = Enumerable.Range(1, count)
            .Select(index => new DictionaryEntry($"scale:{index:D4}", index <= 4042 ? "B2" : "C1", $"word{index}", $"слово{index}"))
            .ToArray();
        var dictionary = new DictionaryPackage
        {
            Id = "scale-diagnostics-fixture",
            Name = "5446-entry synthetic diagnostics fixture",
            SourceLanguage = "en",
            TargetLanguage = "uk",
            Entries = entries
        };
        MorphologyRelation[] relations = Enumerable.Range(1, 2723)
            .Select(index => new MorphologyRelation(
                $"scale-r:{index:D4}",
                $"family:{index:D4}",
                $"scale:{index * 2 - 1:D4}",
                $"scale:{index * 2:D4}",
                MorphologyRelationKind.Derivation,
                null,
                $"fixture:{index}"))
            .ToArray();
        MorphologyOverlayPackage package = new()
        {
            PackageId = "scale-diagnostics-v1",
            Source = FixtureSource(),
            Relations = relations
        };
        MorphologyBuildResult build = MorphologyOverlayBuilder.Build(package, dictionary);
        MorphologyCandidateDiagnostics report = MorphologyDiagnostics.Analyze(package, build, dictionary);
        Assert(report.DictionaryEntries == 5446, "Diagnostics scale fixture lost Oxford-baseline entry count.");
        Assert(report.CoveredStableIds == 5446 && report.GapStableIds == 0, "Diagnostics scale fixture should cover every synthetic stable ID exactly through explicit edges.");
        Assert(report.CoverageByLevel.Sum(item => item.TotalEntries) == 5446, "Level coverage partition does not sum to the full dictionary.");
    }

    private static DictionaryPackage FixtureDictionary() => new()
    {
        Id = "morph-diagnostics-fixture",
        Name = "Synthetic morphology diagnostics fixture",
        SourceLanguage = "en",
        TargetLanguage = "uk",
        Entries = new DictionaryEntry[]
        {
            new("ox:act:v", "B2", "act", "діяти"),
            new("ox:action:n", "B2", "action", "дія"),
            new("ox:active:adj", "B2", "active", "активний"),
            new("ox:record:v", "B2", "record", "записувати"),
            new("ox:record:n", "B2", "record", "запис"),
            new("ox:recording:n", "B2", "recording", "записування")
        }
    };

    private static MorphologyOverlayPackage FixturePackage(params MorphologyRelation[] relations) => new()
    {
        PackageId = "morph-diagnostics-test-only",
        Source = FixtureSource(),
        Relations = relations
    };

    private static MorphologySourceMetadata FixtureSource() =>
        new("diagnostics-test-fixture", "Synthetic diagnostics fixture", "TEST-ONLY", "WordDeck tests", "https://example.invalid/diagnostics");

    private static void Assert(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException($"Morphology diagnostics self-test failed: {message}");
    }
}
