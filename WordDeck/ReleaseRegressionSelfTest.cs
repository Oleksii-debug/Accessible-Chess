using System.Text.Json;

namespace WordDeck;

internal static class ReleaseRegressionSelfTest
{
    public static void Run()
    {
        TestIncompatibleCorpusProfileFailsClosed();
        TestCompatibleOlderSameCorpusProfileMigrates();
        TestCompatibleProfileUnknownIdsAreQuarantined();
        TestNewerStateSchemaFailsClosed();
        TestCorruptStateRecoveryContract();
    }

    private static void TestIncompatibleCorpusProfileFailsClosed()
    {
        string root = TempRoot("incompatible-corpus");
        try
        {
            var store = new AppStateStore(root);
            AppState current = AppStateStore.Normalize(new AppState());
            current.HiddenEntryIds.Add("known-id");
            store.Save(current);
            string statePath = Path.Combine(root, "state.json");
            string stateBytesBefore = File.ReadAllText(statePath);
            string logicalBefore = JsonSerializer.Serialize(current);
            int backupsBefore = Directory.GetFiles(Path.Combine(root, "Backups")).Length;

            string profilePath = Path.Combine(root, "incompatible.json");
            var incompatible = new WordDeckProfile
            {
                ProfileSchemaVersion = AppStateStore.ProfileSchemaVersion,
                StateSchemaVersion = AppStateStore.CurrentSchemaVersion,
                SourceAppVersion = AppStateStore.SourceAppVersion,
                CorpusIdentity = "different-corpus:999",
                State = current
            };
            File.WriteAllText(profilePath, JsonSerializer.Serialize(incompatible));

            bool rejected = false;
            try
            {
                store.ImportProfile(profilePath, current, new[] { "known-id" }, new[] { "oxford-3000-en-uk" });
            }
            catch (InvalidDataException ex)
            {
                rejected = ex.Message.Contains("profile", StringComparison.OrdinalIgnoreCase) ||
                           ex.Message.Contains("corpus", StringComparison.OrdinalIgnoreCase);
            }

            Require(rejected, "An incompatible-corpus personal profile was accepted.");
            Require(JsonSerializer.Serialize(current) == logicalBefore,
                "Rejecting an incompatible-corpus profile mutated the in-memory current state.");
            Require(File.ReadAllText(statePath) == stateBytesBefore,
                "Rejecting an incompatible-corpus profile rewrote state.json.");
            Require(Directory.GetFiles(Path.Combine(root, "Backups")).Length == backupsBefore,
                "Rejecting an incompatible-corpus profile created persistent recovery metadata before compatibility was proven.");
        }
        finally { DeleteTree(root); }
    }

    private static void TestCompatibleOlderSameCorpusProfileMigrates()
    {
        string root = TempRoot("compatible-older");
        try
        {
            var store = new AppStateStore(root);
            AppState current = AppStateStore.Normalize(new AppState());
            store.Save(current);

            string profilePath = Path.Combine(root, "older-compatible.json");
            AppState older = AppStateStore.Normalize(new AppState());
            older.SchemaVersion = 0;
            older.HiddenEntryIds.Add("known-id");
            var profile = new WordDeckProfile
            {
                ProfileSchemaVersion = AppStateStore.ProfileSchemaVersion,
                StateSchemaVersion = 0,
                SourceAppVersion = "0.1-older",
                CorpusIdentity = AppStateStore.CorpusIdentity,
                State = older
            };
            File.WriteAllText(profilePath, JsonSerializer.Serialize(profile));

            ProfileImportResult result = store.ImportProfile(
                profilePath, current, new[] { "known-id" }, new[] { "oxford-3000-en-uk" });

            Require(current.SchemaVersion == AppStateStore.CurrentSchemaVersion,
                "Compatible older same-corpus profile did not migrate to current schema.");
            Require(current.HiddenEntryIds.Contains("known-id"),
                "Compatible older same-corpus profile lost progress.");
            Require(File.Exists(result.BackupPath),
                "Compatible profile import did not create a pre-import recovery profile.");
        }
        finally { DeleteTree(root); }
    }

    private static void TestCompatibleProfileUnknownIdsAreQuarantined()
    {
        string root = TempRoot("unknown-id");
        try
        {
            var store = new AppStateStore(root);
            AppState current = AppStateStore.Normalize(new AppState());
            store.Save(current);
            AppState incoming = AppStateStore.Normalize(new AppState());
            incoming.HiddenEntryIds.Add("future-stable-id");
            string profilePath = Path.Combine(root, "future-id-compatible.json");
            store.ExportProfile(incoming, profilePath);

            ProfileImportResult result = store.ImportProfile(
                profilePath, current, new[] { "known-id" }, new[] { "oxford-3000-en-uk" });

            Require(result.QuarantinedIds.Contains("future-stable-id", StringComparer.OrdinalIgnoreCase),
                "Unknown stable ID inside a compatible profile was discarded instead of quarantined.");
            Require(current.HiddenEntryIds.Contains("future-stable-id"),
                "Unknown stable ID was not preserved in imported personal state.");
        }
        finally { DeleteTree(root); }
    }

    private static void TestNewerStateSchemaFailsClosed()
    {
        string root = TempRoot("newer-schema");
        try
        {
            string statePath = Path.Combine(root, "state.json");
            File.WriteAllText(statePath, JsonSerializer.Serialize(new AppState
            {
                SchemaVersion = AppStateStore.CurrentSchemaVersion + 50,
                HiddenEntryIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "future-id" }
            }));
            string before = File.ReadAllText(statePath);

            bool rejected = false;
            try { _ = new AppStateStore(root).Load(); }
            catch (InvalidDataException) { rejected = true; }

            Require(rejected, "A newer incompatible state schema was accepted.");
            Require(File.ReadAllText(statePath) == before,
                "Rejecting a newer state schema rewrote the user's state file.");
        }
        finally { DeleteTree(root); }
    }

    private static void TestCorruptStateRecoveryContract()
    {
        string root = TempRoot("corrupt-state");
        try
        {
            var store = new AppStateStore(root);
            AppState first = AppStateStore.Normalize(new AppState());
            first.HiddenEntryIds.Add("last-known-good");
            store.Save(first);
            AppState second = AppStateStore.Normalize(new AppState());
            second.HiddenEntryIds.Add("newer-value");
            store.Save(second);

            string primary = Path.Combine(root, "state.json");
            string backup = Path.Combine(root, "state.backup.json");
            Require(File.Exists(backup), "State backup was not created.");
            File.WriteAllText(primary, "{broken-json");
            AppState recovered = new AppStateStore(root).Load();
            Require(recovered.HiddenEntryIds.Contains("last-known-good"),
                "Corrupt primary state did not recover the last parseable backup.");

            File.WriteAllText(backup, "{broken-backup");
            bool rejected = false;
            try { _ = new AppStateStore(root).Load(); }
            catch (InvalidDataException) { rejected = true; }
            Require(rejected, "Corrupt primary and corrupt backup silently reset progress.");
        }
        finally { DeleteTree(root); }
    }

    private static string TempRoot(string suffix)
    {
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck-r3-release-{suffix}-{Guid.NewGuid():N}");
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
