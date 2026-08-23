using System.Runtime.CompilerServices;
using System.Text.Json;

namespace WordDeck;

internal static class Dev01RecallSpellingHardeningSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (!Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            return;
        Dev01RecallSpellingHardeningSelfTest.Run();
    }
}

internal static class Dev01RecallSpellingHardeningSelfTest
{
    public static void Run()
    {
        TestNormalStartupUsesProtectedSpellingMigrationPath();
        TestFullCorpusShuffleCoverage();
        TestSpellingEvidenceBoundary();
        Console.WriteLine("WordDeck DEV01 Recall/Spelling hardening passed: protected Spelling migration/recovery, full-corpus fair shuffle coverage including restart/resume, and read-only platform-neutral learning evidence verified.");
    }

    private static void TestNormalStartupUsesProtectedSpellingMigrationPath()
    {
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck-dev01-migration-{Guid.NewGuid():N}");
        try
        {
            Directory.CreateDirectory(root);
            string primary = Path.Combine(root, "spelling-state.json");
            string recovery = Path.Combine(root, "spelling-state.backup.json");
            File.WriteAllText(primary, "{\"SchemaVersion\":0,\"ActiveDeckId\":\"spelling-core-1\",\"Decks\":[]}");

            SpellingStateSession session = TrainingStateContinuityGuard.LoadSpelling(root);
            Require(session.State.SchemaVersion == SpellingStateStore.CurrentSchemaVersion,
                "Normal Spelling startup did not migrate an older state schema.");

            string[] migrationBackups = Directory.GetFiles(Path.Combine(root, "Backups"), "spelling-state-*-pre-migration.json");
            Require(migrationBackups.Length == 1,
                "Normal Spelling startup did not create exactly one timestamped pre-migration backup.");

            using (JsonDocument document = JsonDocument.Parse(File.ReadAllText(migrationBackups[0])))
            {
                Require(document.RootElement.GetProperty(nameof(SpellingState.SchemaVersion)).GetInt32() == 0,
                    "Pre-migration backup was created after migration instead of preserving the original state.");
            }

            using (JsonDocument document = JsonDocument.Parse(File.ReadAllText(primary)))
            {
                Require(document.RootElement.GetProperty(nameof(SpellingState.SchemaVersion)).GetInt32() == SpellingStateStore.CurrentSchemaVersion,
                    "Migrated Spelling primary state was not persisted after protected startup migration.");
            }

            File.WriteAllText(primary, "{ broken primary");
            File.WriteAllText(recovery, "{ broken recovery");
            bool rejected = false;
            try { _ = TrainingStateContinuityGuard.LoadSpelling(root); }
            catch (InvalidDataException) { rejected = true; }
            Require(rejected,
                "Normal Spelling startup silently created fresh state when both primary and recovery files were unreadable.");
        }
        finally
        {
            try { if (Directory.Exists(root)) Directory.Delete(root, true); } catch { }
        }
    }

    private static void TestFullCorpusShuffleCoverage()
    {
        DictionaryPackage package = DictionaryLoader.LoadEmbeddedOxford();
        Require(package.Entries.Count == 5446, $"Expected 5446 canonical entries, got {package.Entries.Count}.");

        int seed = 20260823;
        foreach (string scopeId in StudyScopeIds.Ordered)
        {
            string[] ids = package.Entries
                .Where(entry => StudyScopeIds.Includes(scopeId, entry))
                .Select(entry => entry.Id)
                .ToArray();
            Require(ids.Length > 0, $"Spelling shuffle scope {scopeId} is unexpectedly empty.");

            Queue<string> queue = ShuffleBag.Create(ids, new Random(seed++));
            string[] cycle = queue.ToArray();
            Require(cycle.Length == ids.Length,
                $"Spelling shuffle scope {scopeId} changed the active-card count.");
            Require(cycle.Distinct(StringComparer.OrdinalIgnoreCase).Count() == ids.Length,
                $"Spelling shuffle scope {scopeId} repeated a card before covering the active set.");
            Require(new HashSet<string>(cycle, StringComparer.OrdinalIgnoreCase).SetEquals(ids),
                $"Spelling shuffle scope {scopeId} omitted or invented stable entry IDs.");

            string last = cycle[^1];
            Queue<string> refill = ShuffleBag.Create(ids, new Random(seed++), last);
            Require(refill.Count == ids.Length,
                $"Spelling shuffle refill for {scopeId} changed the active-card count.");
            if (ids.Length > 1)
                Require(!string.Equals(refill.Peek(), last, StringComparison.OrdinalIgnoreCase),
                    $"Spelling shuffle scope {scopeId} immediately repeated the previous card at a same-deck refill boundary.");

            string restoredCurrent = cycle[0];
            string[] remainingAfterRestore = ShuffleBag.Create(ids, new Random(seed++), restoredCurrent)
                .Where(id => !string.Equals(id, restoredCurrent, StringComparison.OrdinalIgnoreCase))
                .ToArray();
            string[] expectedAfterRestore = ids
                .Where(id => !string.Equals(id, restoredCurrent, StringComparison.OrdinalIgnoreCase))
                .ToArray();
            Require(remainingAfterRestore.Length == expectedAfterRestore.Length,
                $"Spelling restart/resume shuffle for {scopeId} did not remove exactly the restored current card.");
            Require(new HashSet<string>(remainingAfterRestore, StringComparer.OrdinalIgnoreCase).SetEquals(expectedAfterRestore),
                $"Spelling restart/resume shuffle for {scopeId} lost or repeated another card while excluding the restored current card.");
        }
    }

    private static void TestSpellingEvidenceBoundary()
    {
        const string dictionaryId = "evidence-dictionary";
        var state = new SpellingState
        {
            StatsByDictionary = new Dictionary<string, Dictionary<string, SpellingEntryStats>>(StringComparer.OrdinalIgnoreCase)
            {
                [dictionaryId] = new Dictionary<string, SpellingEntryStats>(StringComparer.OrdinalIgnoreCase)
                {
                    ["word-b"] = new SpellingEntryStats
                    {
                        CompletedReviews = 4,
                        FirstTrySuccesses = 3,
                        WrongAttempts = 2,
                        HintUses = 1,
                        CurrentStreak = 2,
                        LastReviewedUtc = DateTimeOffset.Parse("2026-08-23T10:00:00Z")
                    },
                    ["word-a"] = new SpellingEntryStats
                    {
                        CompletedReviews = 2,
                        FirstTrySuccesses = 2,
                        WrongAttempts = 0,
                        HintUses = 0,
                        CurrentStreak = 2
                    }
                }
            }
        };

        var source = new SpellingLearningEvidenceSource(state);
        IReadOnlyList<LearningEvidenceRecord> evidence = source.Snapshot(dictionaryId);
        Require(evidence.Count == 2, "Spelling evidence snapshot omitted persisted word statistics.");
        Require(evidence[0].EntryId == "word-a" && evidence[1].EntryId == "word-b",
            "Spelling evidence snapshot is not deterministic by stable entry ID.");
        Require(evidence.All(item => item.DictionaryId == dictionaryId && item.ModeId == SpellingLearningEvidenceSource.ModeId),
            "Spelling evidence lost dictionary or mode identity.");
        Require(Math.Abs(evidence[1].FirstTryRate - 0.75) < 0.000001,
            "Spelling evidence computed an incorrect first-try rate.");
        Require(state.StatsByDictionary[dictionaryId]["word-b"].CompletedReviews == 4,
            "Read-only Spelling evidence projection mutated source statistics.");
        Require(source.Snapshot("missing-dictionary").Count == 0,
            "Missing dictionary evidence did not fail closed to an empty snapshot.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }
}
