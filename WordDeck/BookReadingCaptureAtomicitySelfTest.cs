using System.Runtime.CompilerServices;
using System.Text;

namespace WordDeck;

internal static class BookReadingCaptureAtomicitySelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            BookReadingCaptureAtomicitySelfTest.Run();
    }
}

internal static class BookReadingCaptureAtomicitySelfTest
{
    public static void Run()
    {
        DictionaryPackage dictionary = BuildDictionary();
        AppState seedState = NewState(dictionary.Id);
        seedState.DeckIdsByDictionary[dictionary.Id] = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["ox:alpha"] = DeckIds.Core(5),
            ["ox:beta"] = DeckIds.Core(2)
        };
        BookDeckVocabularySnapshot snapshot = BookReadingProductService.BuildVocabularySnapshot(
            seedState,
            dictionary,
            DeckIds.Core(5),
            DeckIds.Core(2));

        string root = Path.Combine(Path.GetTempPath(), "WordDeck Reading capture atomicity " + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            string sourcePath = Path.Combine(root, "capture.txt");
            File.WriteAllText(sourcePath, "Alpha beta.", new UTF8Encoding(false));
            var service = new BookReadingProductService(Path.Combine(root, "private"));
            BookImportProductResult imported = service.ImportFile(sourcePath, dictionary, snapshot);
            BookSentenceRecord alphaSentence = imported.Document.Chapters
                .SelectMany(chapter => chapter.Sentences)
                .First(sentence => sentence.StableEntryIds.Contains("ox:alpha", StringComparer.OrdinalIgnoreCase));

            MakeDatabasePathUnopenable(service.DatabasePath);

            AppState existingState = NewState(dictionary.Id);
            var originalAssignments = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                ["ox:alpha"] = DeckIds.Core(5),
                ["ox:beta"] = "invalid-deck-that-normalization-would-rewrite",
                ["legacy:stale"] = DeckIds.Core(3)
            };
            existingState.DeckIdsByDictionary[dictionary.Id] = originalAssignments;
            KeyValuePair<string, string>[] before = originalAssignments.ToArray();

            ExpectSqliteFailure(
                () => service.CaptureMappedOccurrenceToLearningDeck(
                    imported.Document,
                    alphaSentence,
                    "ox:alpha",
                    existingState,
                    dictionary,
                    DeckIds.Core(2)),
                "Capture unexpectedly succeeded against an unopenable SQLite path.");

            Require(
                existingState.DeckIdsByDictionary.TryGetValue(dictionary.Id, out Dictionary<string, string>? restored)
                && ReferenceEquals(restored, originalAssignments),
                "Failed capture replaced or lost the caller's pre-existing assignment map.");
            Require(
                originalAssignments.Count == before.Length
                && before.All(pair => originalAssignments.TryGetValue(pair.Key, out string? value)
                    && string.Equals(value, pair.Value, StringComparison.Ordinal)),
                "Failed capture did not restore the exact pre-call assignment contents after normalization/move mutations.");

            AppState absentState = NewState(dictionary.Id);
            absentState.DeckIdsByDictionary.Remove(dictionary.Id);
            ExpectSqliteFailure(
                () => service.CaptureMappedOccurrenceToLearningDeck(
                    imported.Document,
                    alphaSentence,
                    "ox:alpha",
                    absentState,
                    dictionary,
                    DeckIds.Core(2)),
                "Capture unexpectedly succeeded for the map-absence rollback fixture.");
            Require(
                !absentState.DeckIdsByDictionary.ContainsKey(dictionary.Id),
                "Failed capture left behind a dictionary assignment map that did not exist before the call.");
        }
        finally
        {
            try { Directory.Delete(root, recursive: true); } catch { }
        }

        Console.WriteLine("BookReading capture atomicity self-test PASS: durable capture failure restores exact existing assignment state and pre-call map absence.");
    }

    private static AppState NewState(string dictionaryId) =>
        AppStateStore.Normalize(new AppState
        {
            ActiveDictionaryId = dictionaryId,
            ActiveDeckId = DeckIds.Core(2)
        });

    private static void MakeDatabasePathUnopenable(string databasePath)
    {
        foreach (string path in new[] { databasePath, databasePath + "-wal", databasePath + "-shm" })
        {
            if (File.Exists(path))
                File.Delete(path);
        }
        Directory.CreateDirectory(databasePath);
    }

    private static DictionaryPackage BuildDictionary() => new()
    {
        Id = "capture-atomicity-dictionary",
        Name = "Capture atomicity dictionary",
        SourceLanguage = "en",
        TargetLanguage = "uk",
        Entries = new DictionaryEntry[]
        {
            new("ox:alpha", "A1", "alpha", "альфа"),
            new("ox:beta", "A1", "beta", "бета")
        }
    };

    private static void ExpectSqliteFailure(Action action, string message)
    {
        try
        {
            action();
        }
        catch (Microsoft.Data.Sqlite.SqliteException)
        {
            return;
        }
        throw new InvalidOperationException("BookReading capture atomicity self-test failed: " + message);
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException("BookReading capture atomicity self-test failed: " + message);
    }
}
