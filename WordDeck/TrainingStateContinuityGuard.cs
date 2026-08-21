using System.Text.Json;

namespace WordDeck;

internal sealed record SpellingStateSession(SpellingStateStore Store, SpellingState State);
internal sealed record SentenceStateSession(SentenceCoachStateStore Store, SentenceCoachState State);

internal static class TrainingStateContinuityGuard
{
    public static SpellingStateSession LoadSpelling()
    {
        string root = DefaultRoot();
        return LoadSpelling(root);
    }

    public static SentenceStateSession LoadSentence()
    {
        string root = DefaultRoot();
        return LoadSentence(root);
    }

    internal static SpellingStateSession LoadSpelling(string root)
    {
        Directory.CreateDirectory(root);
        string primary = Path.Combine(root, "spelling-state.json");
        string backup = Path.Combine(root, "spelling-state.backup.json");
        var store = new SpellingStateStore(root);

        if (!File.Exists(primary) && !File.Exists(backup))
            return new(store, store.Load());

        if (TryReadSpelling(primary, out SpellingState? state) || TryReadSpelling(backup, out state))
            return new(store, state!);

        throw new InvalidDataException(
            "Spelling learning state and its recovery backup are both unreadable. WordDeck stopped before creating fresh state so existing progress is not silently replaced.");
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

    private static bool TryReadSpelling(string path, out SpellingState? state)
    {
        state = null;
        if (!File.Exists(path)) return false;
        try
        {
            SpellingState? parsed = JsonSerializer.Deserialize<SpellingState>(File.ReadAllText(path));
            if (parsed is null) return false;
            state = SpellingStateStore.Normalize(parsed);
            return true;
        }
        catch
        {
            return false;
        }
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
        catch
        {
            return false;
        }
    }

    private static string DefaultRoot() =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WordDeck");
}
