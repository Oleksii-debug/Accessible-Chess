using System.Text.Json;

namespace WordDeck;

internal static class ReleaseStateFailureSelfTest
{
    public static void Run()
    {
        TestSpellingRecoveryAndFailClosed();
        TestSentenceRecoveryAndFailClosed();
        TestUnknownSpellingDeckIdFallsBackSafely();
    }

    private static void TestSpellingRecoveryAndFailClosed()
    {
        string root = TempRoot("spelling");
        try
        {
            string primary = Path.Combine(root, "spelling-state.json");
            string backup = Path.Combine(root, "spelling-state.backup.json");
            SpellingState good = SpellingStateStore.Normalize(new SpellingState { CoachEnabled = false });
            File.WriteAllText(backup, JsonSerializer.Serialize(good));
            File.WriteAllText(primary, "{broken-primary");

            SpellingStateSession recovered = TrainingStateContinuityGuard.LoadSpelling(root);
            Require(!recovered.State.CoachEnabled, "Spelling did not recover the valid backup after primary corruption.");

            File.WriteAllText(backup, "{broken-backup");
            string primaryBefore = File.ReadAllText(primary);
            string backupBefore = File.ReadAllText(backup);
            bool rejected = false;
            try { _ = TrainingStateContinuityGuard.LoadSpelling(root); }
            catch (InvalidDataException) { rejected = true; }
            Require(rejected, "Corrupt Spelling primary plus backup silently produced fresh state.");
            Require(File.ReadAllText(primary) == primaryBefore && File.ReadAllText(backup) == backupBefore,
                "Fail-closed Spelling recovery changed the unreadable user files.");
        }
        finally { DeleteTree(root); }
    }

    private static void TestSentenceRecoveryAndFailClosed()
    {
        string root = TempRoot("sentence");
        try
        {
            string primary = Path.Combine(root, "sentence-coach-state.json");
            string backup = Path.Combine(root, "sentence-coach-state.backup.json");
            SentenceCoachState good = SentenceCoachStateStore.Normalize(new SentenceCoachState { TargetCount = 2, ActivePackId = "known-pack" });
            File.WriteAllText(backup, JsonSerializer.Serialize(good));
            File.WriteAllText(primary, "{broken-primary");

            SentenceStateSession recovered = TrainingStateContinuityGuard.LoadSentence(root);
            Require(recovered.State.TargetCount == 2 && recovered.State.ActivePackId == "known-pack",
                "Sentence Spelling did not recover the valid backup after primary corruption.");

            File.WriteAllText(backup, "{broken-backup");
            string primaryBefore = File.ReadAllText(primary);
            string backupBefore = File.ReadAllText(backup);
            bool rejected = false;
            try { _ = TrainingStateContinuityGuard.LoadSentence(root); }
            catch (InvalidDataException) { rejected = true; }
            Require(rejected, "Corrupt Sentence primary plus backup silently produced fresh state.");
            Require(File.ReadAllText(primary) == primaryBefore && File.ReadAllText(backup) == backupBefore,
                "Fail-closed Sentence recovery changed the unreadable user files.");
        }
        finally { DeleteTree(root); }
    }

    private static void TestUnknownSpellingDeckIdFallsBackSafely()
    {
        var state = new SpellingState
        {
            ActiveDeckId = "deleted-user-deck",
            DeckIdsByDictionary = new Dictionary<string, Dictionary<string, string>>(StringComparer.OrdinalIgnoreCase)
            {
                ["dict"] = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
                {
                    ["entry"] = "deleted-user-deck"
                }
            }
        };
        SpellingState normalized = SpellingStateStore.Normalize(state);
        Require(normalized.ActiveDeckId == SpellingDeckIds.Core(1),
            "Unknown imported active Spelling deck did not fall back to core deck 1.");
        Require(normalized.DeckIdsByDictionary["dict"]["entry"] == SpellingDeckIds.Core(1),
            "Word assigned to a deleted/unknown Spelling deck was not preserved via safe fallback.");
    }

    private static string TempRoot(string suffix)
    {
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck-r2-{suffix}-{Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        return root;
    }

    private static void DeleteTree(string root)
    {
        try { if (Directory.Exists(root)) Directory.Delete(root, true); } catch { }
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }
}
