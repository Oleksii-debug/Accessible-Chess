using System.Text.Json;

namespace WordDeck;

internal static class ReleaseRegressionSelfTest
{
    public static void Run()
    {
        TestIncompatibleCorpusProfileFailsClosed();
        TestNewerStateSchemaFailsClosed();
        TestCorruptPrimaryRecoversOnlyFromParseableBackup();
    }

    private static void TestIncompatibleCorpusProfileFailsClosed()
    {
        string root = TempRoot("profile-corpus");
        try
        {
            var store = new AppStateStore(root);
            AppState state = AppStateStore.Normalize(new AppState());
            state.HiddenEntryIds.Add("known-id");
            store.Save(state);

            string profile = Path.Combine(root, "profile.json");
            store.ExportProfile(state, profile);
            string text = File.ReadAllText(profile);
            text = text.Replace(AppStateStore.CorpusIdentity, "incompatible-corpus:999", StringComparison.Ordinal);
            File.WriteAllText(profile, text);

            int before = state.HiddenEntryIds.Count;
            bool rejected = false;
            try
            {
                store.ImportProfile(profile, state, new[] { "known-id" }, new[] { "oxford-3000-en-uk" });
            }
            catch (InvalidDataException)
            {
                rejected = true;
            }

            Require(rejected, "A personal profile for an incompatible corpus was accepted.");
            Require(state.HiddenEntryIds.Count == before && state.HiddenEntryIds.Contains("known-id"),
                "Rejected incompatible profile mutated current personal state.");
        }
        finally
        {
            DeleteTree(root);
        }
    }

    private static void TestNewerStateSchemaFailsClosed()
    {
        string root = TempRoot("newer-schema");
        try
        {
            string path = Path.Combine(root, "state.json");
            Directory.CreateDirectory(root);
            File.WriteAllText(path, JsonSerializer.Serialize(new AppState
            {
                SchemaVersion = AppStateStore.CurrentSchemaVersion + 100,
                HiddenEntryIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "future-id" }
            }));
            string original = File.ReadAllText(path);

            bool rejected = false;
            try
            {
                _ = new AppStateStore(root).Load();
            }
            catch (InvalidDataException)
            {
                rejected = true;
            }

            Require(rejected, "A newer incompatible state schema was not rejected.");
            Require(File.ReadAllText(path) == original, "Rejecting a newer state schema rewrote the user's file.");
        }
        finally
        {
            DeleteTree(root);
        }
    }

    private static void TestCorruptPrimaryRecoversOnlyFromParseableBackup()
    {
        string root = TempRoot("backup-recovery");
        try
        {
            var store = new AppStateStore(root);
            AppState first = AppStateStore.Normalize(new AppState());
            first.HiddenEntryIds.Add("backup-id");
            store.Save(first);

            AppState second = AppStateStore.Normalize(first);
            second.HiddenEntryIds.Add("newer-id");
            store.Save(second);

            string primary = Path.Combine(root, "state.json");
            string backup = Path.Combine(root, "state.backup.json");
            Require(File.Exists(backup), "Expected parseable state backup was not created.");
            File.WriteAllText(primary, "{broken-json");

            AppState recovered = new AppStateStore(root).Load();
            Require(recovered.HiddenEntryIds.Contains("backup-id"), "Parseable backup was not used after primary corruption.");

            File.WriteAllText(backup, "{also-broken");
            bool rejected = false;
            try
            {
                _ = new AppStateStore(root).Load();
            }
            catch (InvalidDataException)
            {
                rejected = true;
            }
            Require(rejected, "Corrupt primary plus corrupt backup silently created fresh state.");
        }
        finally
        {
            DeleteTree(root);
        }
    }

    private static string TempRoot(string name)
    {
        string root = Path.Combine(Path.GetTempPath(), $"WordDeck-release-{name}-{Guid.NewGuid():N}");
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
