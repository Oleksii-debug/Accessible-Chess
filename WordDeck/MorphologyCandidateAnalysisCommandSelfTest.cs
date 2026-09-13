namespace WordDeck;

internal static class MorphologyCandidateAnalysisCommandSelfTest
{
    public static void Run()
    {
        string root = Path.Combine(Path.GetTempPath(), "WordDeck-MorphologyCandidateCommandSelfTest-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            DictionaryPackage dictionary = DictionaryLoader.LoadEmbeddedOxford();
            Assert(dictionary.Entries.Count == 5446, "Exact embedded Oxford dictionary must contain 5,446 stable entries for the current Stage-18 candidate analyzer.");
            DictionaryEntry first = dictionary.Entries[0];
            DictionaryEntry second = dictionary.Entries[1];

            string validInput = Path.Combine(root, "valid.tsv");
            string validSummary = Path.Combine(root, "valid-summary.tsv");
            string validGaps = Path.Combine(root, "valid-gaps.tsv");
            File.WriteAllText(validInput, Candidate(first.Id, second.Id));
            int validExit = MorphologyCandidateAnalysisCommand.Run(new[] { "--analyze-morphology-candidate", validInput, validSummary, validGaps });
            Assert(validExit == 0, "Clean external candidate analysis should complete successfully without implying release approval.");
            string summary = File.ReadAllText(validSummary);
            Assert(summary.Contains("dictionaryEntries\t5446", StringComparison.Ordinal), "Candidate summary lost exact dictionary count.");
            Assert(summary.Contains("datasetClass\tExternalCandidate", StringComparison.Ordinal), "Candidate summary must remain ExternalCandidate.");
            Assert(summary.Contains("releaseEligible\tFalse", StringComparison.Ordinal), "Analyzer must never self-grant production release eligibility.");
            Assert(File.ReadLines(validGaps).Skip(1).Count() == 5444, "One explicit two-endpoint test relation should leave exactly 5,444 stable-ID gaps.");

            string badInput = Path.Combine(root, "bad.tsv");
            string badSummary = Path.Combine(root, "bad-summary.tsv");
            string badGaps = Path.Combine(root, "bad-gaps.tsv");
            File.WriteAllText(badInput, Candidate(first.Id, "missing:stable-id"));
            int badExit = MorphologyCandidateAnalysisCommand.Run(new[] { "--analyze-morphology-candidate", badInput, badSummary, badGaps });
            Assert(badExit == 1, "Candidate with an unknown stable ID must return a failing analysis code.");
            Assert(File.ReadAllText(badSummary).Contains("relation.unknown-to", StringComparison.Ordinal), "Quarantine evidence lost the unknown stable-ID defect.");

            int samePathExit = MorphologyCandidateAnalysisCommand.Run(new[] { "--analyze-morphology-candidate", validInput, validInput, validGaps });
            Assert(samePathExit == 1, "Analyzer must refuse to overwrite its input candidate with evidence output.");
        }
        finally
        {
            try { Directory.Delete(root, recursive: true); } catch { }
        }
    }

    private static string Candidate(string fromId, string toId) =>
        $"# schemaVersion=1\n" +
        $"# packageId=morph-command-test-only\n" +
        $"# sourceId=morph-command-test\n" +
        $"# sourceName=Synthetic command self-test\n" +
        $"# license=TEST-ONLY\n" +
        $"# attribution=WordDeck deterministic tests\n" +
        $"# sourceUri=https://example.invalid/morph-command-test\n" +
        $"relationId\tfamilyId\tfromEntryId\ttoEntryId\tkind\tmorpheme\tevidenceRef\n" +
        $"r1\tfamily-test\t{fromId}\t{toId}\tDerivation\t\tfixture:r1\n";

    private static void Assert(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException($"Morphology candidate command self-test failed: {message}");
    }
}
