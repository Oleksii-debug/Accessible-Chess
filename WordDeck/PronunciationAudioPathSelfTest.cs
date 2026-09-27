namespace WordDeck;

internal static class PronunciationAudioPathSelfTest
{
    public static void Run()
    {
        IReadOnlyList<string> traversal = PronunciationAudio.CandidatePaths("..", "probe");
        Require(traversal.Count == 2, "Pronunciation path resolution must expose portable and LocalAppData candidates.");

        foreach (string path in traversal)
        {
            string full = Path.GetFullPath(path);
            string? audioRoot = Path.GetDirectoryName(Path.GetDirectoryName(full));
            Require(audioRoot is not null, "Pronunciation path root could not be resolved.");
            Require(Path.GetFileName(Path.GetDirectoryName(full)) != "..",
                "Pronunciation dictionary segment must never remain '..'.");
        }

        string portableRoot = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "AudioPacks")) +
                              Path.DirectorySeparatorChar;
        string portableTraversal = Path.GetFullPath(traversal[0]);
        Require(portableTraversal.StartsWith(portableRoot, StringComparison.OrdinalIgnoreCase),
            "Portable pronunciation candidate escaped the AudioPacks root.");

        IReadOnlyList<string> collisionA = PronunciationAudio.CandidatePaths("custom", "a:b");
        IReadOnlyList<string> collisionB = PronunciationAudio.CandidatePaths("custom", "a?b");
        Require(!string.Equals(collisionA[0], collisionB[0], StringComparison.OrdinalIgnoreCase),
            "Distinct unsafe entry IDs must not alias to the same pronunciation filename.");

        IReadOnlyList<string> builtInSafe = PronunciationAudio.CandidatePaths(
            "oxford-3000-en-uk",
            "o5000-b2-bold-adj");
        Require(builtInSafe[0].EndsWith(
                Path.Combine("AudioPacks", "oxford-3000-en-uk", "o5000-b2-bold-adj.mp3"),
                StringComparison.OrdinalIgnoreCase),
            "Safe existing pronunciation IDs must keep their established path names.");

        IReadOnlyList<string> reserved = PronunciationAudio.CandidatePaths("CON", "NUL");
        Require(!reserved[0].Contains(
                Path.Combine("AudioPacks", "CON", "NUL.mp3"),
                StringComparison.OrdinalIgnoreCase),
            "Reserved Windows device names must not be emitted as pronunciation path segments.");

        Console.WriteLine("Pronunciation audio path self-test passed: root containment, collision resistance and existing safe IDs verified.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }
}
