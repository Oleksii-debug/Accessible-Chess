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
        Console.WriteLine("WordDeck DEV01 Recall/Spelling hardening passed: normal startup preserves pre-migration Spelling state and fail-closed recovery.");
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

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }
}
