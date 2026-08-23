using System.Text.Json;

namespace WordDeck;

internal sealed record SpellingStateSession(SpellingStateStore Store, SpellingState State);
internal sealed record SentenceStateSession(SentenceCoachStateStore Store, SentenceCoachState State);

internal static class TrainingStateContinuityGuard
{
    public static SpellingStateSession LoadSpelling() => LoadSpelling(DefaultRoot());

    public static SentenceStateSession LoadSentence() => LoadSentence(DefaultRoot());

    internal static SpellingStateSession LoadSpelling(string root)
    {
        Directory.CreateDirectory(root);
        var store = new SpellingStateStore(root);

        // SpellingStateStore.Load is the canonical continuity path. Besides
        // failing closed when both primary and backup are unreadable, it also
        // performs schema checks and creates the required timestamped
        // pre-migration backup before normalizing older state. Bypassing it with
        // a direct JSON deserialize would silently skip those migration safety
        // guarantees during normal application startup.
        return new(store, store.Load());
    }

    internal static SentenceStateSession LoadSentence(string root)
    {
        Directory.CreateDirectory(root);
        string primary = Path.Combine(root, "sentence-coach-state.json");
        string backup = Path.Combine(root, "sentence-coach-state.backup.json");
        var store = new SentenceCoachStateStore(root);

        if (!File.Exists(primary) && !File.Exists(backup))
            return new(store, store.Load());

        if (TryReadSentence(primary, out SentenceCoachState? state) || TryReadSentence(backup, out state))
            return new(store, state!);

        throw new InvalidDataException(
            "Sentence Spelling state and its recovery backup are both unreadable. WordDeck stopped before creating fresh state so existing progress is not silently replaced.");
    }

    private static bool TryReadSentence(string path, out SentenceCoachState? state)
    {
        state = null;
        if (!File.Exists(path)) return false;
        try
        {
            SentenceCoachState? parsed = JsonSerializer.Deserialize<SentenceCoachState>(File.ReadAllText(path));
            if (parsed is null) return false;
            state = SentenceCoachStateStore.Normalize(parsed);
            return true;
        }
        catch { return false; }
    }

    private static string DefaultRoot() =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WordDeck");
}
