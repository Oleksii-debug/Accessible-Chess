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

        string portableRoot = WithTrailingSeparator(Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "AudioPacks")));
        string localRoot = WithTrailingSeparator(Path.GetFullPath(Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "WordDeck",
            "AudioPacks")));
        Require(IsContained(traversal[0], portableRoot),
            "Portable pronunciation candidate escaped the AudioPacks root.");
        Require(IsContained(traversal[1], localRoot),
            "LocalAppData pronunciation candidate escaped the AudioPacks root.");

        string importRoot = Path.Combine(Path.GetTempPath(), $"WordDeck-audio-path-{Guid.NewGuid():N}");
        try
        {
            Directory.CreateDirectory(importRoot);
            string importedPath = Path.Combine(importRoot, "unsafe.tsv");
            File.WriteAllText(importedPath,
                "#id=..\n#name=Unsafe path fixture\nentryId\tlevel\tsource\ttarget\n../outside\tCUSTOM\ttest\tтест\n");
            DictionaryPackage imported = DictionaryLoader.LoadFromFile(importedPath);
            DictionaryEntry importedEntry = imported.Entries.Single();
            IReadOnlyList<string> importedCandidates = PronunciationAudio.CandidatePaths(imported.Id, importedEntry.Id);
            Require(IsContained(importedCandidates[0], portableRoot) && IsContained(importedCandidates[1], localRoot),
                "Imported dictionary/entry IDs must not escape either AudioPacks root.");
            Require(!Path.GetFullPath(importedCandidates[0]).Contains(
                    Path.Combine("AudioPacks", ".."),
                    StringComparison.OrdinalIgnoreCase),
                "Imported traversal metadata must not survive into the pronunciation path.");
        }
        finally
        {
            try { if (Directory.Exists(importRoot)) Directory.Delete(importRoot, true); } catch { }
        }

        IReadOnlyList<string> collisionA = PronunciationAudio.CandidatePaths("custom", "a:b");
        IReadOnlyList<string> collisionB = PronunciationAudio.CandidatePaths("custom", "a?b");
        Require(!string.Equals(collisionA[0], collisionB[0], StringComparison.OrdinalIgnoreCase),
            "Distinct unsafe entry IDs must not alias to the same pronunciation filename.");

        IReadOnlyList<string> builtInSafe = PronunciationAudio.CandidatePaths(
            "oxford-3000-en-uk",
            ReviewedOxford5000Bootstrap.LexicalEntryId("bold", "adjective", "B2"));
        Require(builtInSafe[0].EndsWith(
                Path.Combine(
                    "AudioPacks",
                    "oxford-3000-en-uk",
                    ReviewedOxford5000Bootstrap.LexicalEntryId("bold", "adjective", "B2") + ".mp3"),
                StringComparison.OrdinalIgnoreCase),
            "Safe existing pronunciation IDs must keep their established path names.");

        DictionaryPackage fullOxford = DictionaryLoader.LoadEmbeddedOxford();
        Require(fullOxford.Entries.Count == 5446,
            "Built-in Oxford audio compatibility regression must cover all 5446 canonical entries.");
        foreach (DictionaryEntry entry in fullOxford.Entries)
        {
            IReadOnlyList<string> paths = PronunciationAudio.CandidatePaths(fullOxford.Id, entry.Id);
            Require(string.Equals(Path.GetFileName(paths[0]), entry.Id + ".mp3", StringComparison.Ordinal),
                $"Built-in Oxford audio filename changed for {entry.Id}.");
            Require(IsContained(paths[0], portableRoot) && IsContained(paths[1], localRoot),
                $"Built-in Oxford audio path escaped its AudioPacks root for {entry.Id}.");
        }

        IReadOnlyList<string> reserved = PronunciationAudio.CandidatePaths("CON", "NUL");
        Require(!reserved[0].Contains(
                Path.Combine("AudioPacks", "CON", "NUL.mp3"),
                StringComparison.OrdinalIgnoreCase),
            "Reserved Windows device names must not be emitted as pronunciation path segments.");

        string longId = new('a', 300);
        IReadOnlyList<string> longPath = PronunciationAudio.CandidatePaths(longId, longId);
        Require(Path.GetFileNameWithoutExtension(longPath[0]).Length < longId.Length,
            "Excessively long pronunciation IDs must be reduced to bounded safe segments.");
        Require(IsContained(longPath[0], portableRoot) && IsContained(longPath[1], localRoot),
            "Long pronunciation IDs must remain inside both AudioPacks roots.");

        using (var firstAudio = new PronunciationAudio())
        using (var secondAudio = new PronunciationAudio())
        {
            Require(!string.Equals(firstAudio.AliasForTest, secondAudio.AliasForTest, StringComparison.Ordinal),
                "Concurrent pronunciation players reused the same Windows MCI alias.");
            Require(firstAudio.AliasForTest.StartsWith("worddeck_pronunciation_", StringComparison.Ordinal) &&
                    secondAudio.AliasForTest.StartsWith("worddeck_pronunciation_", StringComparison.Ordinal),
                "Pronunciation player aliases left the safe MCI identifier namespace.");
        }

        Console.WriteLine("Pronunciation audio path self-test passed: root containment, collision resistance and existing safe IDs verified.");
    }

    private static bool IsContained(string candidate, string root)
    {
        string full = Path.GetFullPath(candidate);
        return full.StartsWith(root, StringComparison.OrdinalIgnoreCase);
    }

    private static string WithTrailingSeparator(string path) =>
        path.EndsWith(Path.DirectorySeparatorChar) ? path : path + Path.DirectorySeparatorChar;

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException(message);
    }
}
