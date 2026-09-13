using System.Runtime.CompilerServices;
using System.Text;

namespace WordDeck;

internal static class BookReadingWritingSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            BookReadingWritingSelfTest.Run();
    }
}

internal static class BookReadingWritingSelfTest
{
    public static void Run()
    {
        string root = Path.Combine(Path.GetTempPath(), "WordDeck G3 reading writing з пробілами " + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            DictionaryPackage dictionary = BuildDictionary();
            AppState state = AppStateStore.Normalize(new AppState
            {
                ActiveDictionaryId = dictionary.Id,
                ActiveDeckId = DeckIds.Core(2)
            });
            state.DeckIdsByDictionary[dictionary.Id] = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
            {
                ["rw:alpha"] = DeckIds.Core(5),
                ["rw:beta"] = DeckIds.Core(2)
            };
            BookDeckVocabularySnapshot vocabulary = BookReadingProductService.BuildVocabularySnapshot(
                state,
                dictionary,
                DeckIds.Core(5),
                DeckIds.Core(2));

            string source = Path.Combine(root, "private source.txt");
            File.WriteAllText(source, "Alpha beta. Beta alpha.", new UTF8Encoding(false));
            string privateRoot = Path.Combine(root, "private reading");
            var service = new BookReadingProductService(privateRoot);
            BookImportProductResult imported = service.ImportFile(source, dictionary, vocabulary);
            BookSentenceRecord sentence = imported.Document.Chapters[0].Sentences[0];
            var store = new BookReadingWritingStore(service.DatabasePath);

            string firstResponse = "Alpha helps beta.";
            string firstFeedback = BookReadingWritingFeedback.Build(sentence, firstResponse, dictionary);
            Require(firstFeedback.Contains("Structural feedback only", StringComparison.Ordinal), "Feedback lost its explicit non-assessment boundary.");
            Require(firstFeedback.Contains("alpha [rw:alpha]", StringComparison.OrdinalIgnoreCase), "Feedback did not report sentence-mapped vocabulary reused in the response.");
            Require(firstFeedback.Contains("does not judge meaning", StringComparison.OrdinalIgnoreCase), "Feedback implied semantic judgment instead of a deterministic structural boundary.");
            store.Save(imported.Document, sentence, firstResponse, firstFeedback);

            BookReadingWritingResponse? restored = new BookReadingWritingStore(service.DatabasePath).Load(imported.Document.BookId, sentence.SentenceId);
            Require(restored is not null, "Persisted sentence-linked writing response did not survive store restart.");
            Require(restored!.ResponseText.Equals(firstResponse, StringComparison.Ordinal), "Restart changed the learner writing response.");
            Require(restored.FeedbackText.Equals(firstFeedback, StringComparison.Ordinal), "Restart changed the deterministic feedback text.");

            string revisedResponse = "Beta helps alpha!";
            string revisedFeedback = BookReadingWritingFeedback.Build(sentence, revisedResponse, dictionary);
            store.Save(imported.Document, sentence, revisedResponse, revisedFeedback);
            BookReadingWritingResponse? revised = store.Load(imported.Document.BookId, sentence.SentenceId);
            Require(revised?.ResponseText == revisedResponse, "Saving a revision did not replace the previous response for the same book sentence.");
            Require(revised?.UpdatedUtc >= restored.UpdatedUtc, "Revision persistence did not advance the local update timestamp.");

            ExpectFailure<InvalidDataException>(
                () => store.Save(imported.Document, sentence, "   ", "feedback"),
                "Blank learner writing was persisted.");
            ExpectFailure<InvalidDataException>(
                () => BookReadingWritingFeedback.Build(sentence, new string('x', BookReadingWritingStore.MaximumResponseCharacters + 1), dictionary),
                "Oversized learner writing bypassed the bounded local-practice limit.");

            BookSentenceRecord foreign = sentence with { SentenceId = sentence.SentenceId + ":foreign" };
            ExpectFailure<InvalidDataException>(
                () => store.Save(imported.Document, foreign, "A valid-looking response.", "Structural feedback only."),
                "Writing persistence accepted a sentence outside the selected book.");

            BookReadingPosition? before = service.LoadPosition(imported.Document.BookId);
            service.SavePosition(imported.Document, sentence);
            BookReadingPosition? after = new BookReadingProductService(privateRoot).LoadPosition(imported.Document.BookId);
            Require(after?.SentenceId == sentence.SentenceId, "Reading position no longer shares restart-safe persistence with the sentence-linked writing journey.");
            Require(new BookReadingWritingStore(service.DatabasePath).Load(imported.Document.BookId, sentence.SentenceId)?.ResponseText == revisedResponse,
                "Writing response was lost after the Reading product service restarted.");
            _ = before;
        }
        finally
        {
            try { Directory.Delete(root, recursive: true); } catch { }
        }

        Console.WriteLine("BookReading writing self-test PASS: sentence grounding, deterministic non-mastery feedback, bounded input, local SQLite persistence, revision upsert and restart continuity verified.");
    }

    private static DictionaryPackage BuildDictionary() => new()
    {
        Id = "test-reading-writing-dictionary",
        Name = "Reading writing test dictionary",
        SourceLanguage = "en",
        TargetLanguage = "uk",
        Entries = new DictionaryEntry[]
        {
            new("rw:alpha", "A1", "alpha", "альфа"),
            new("rw:beta", "A1", "beta", "бета")
        }
    };

    private static void ExpectFailure<T>(Action action, string message) where T : Exception
    {
        try { action(); }
        catch (T) { return; }
        throw new InvalidOperationException("BookReading writing self-test failed: " + message);
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException("BookReading writing self-test failed: " + message);
    }
}