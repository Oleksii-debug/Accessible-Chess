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

            Require(vocabulary.KnownEntryIds.Contains("rw:alpha") && vocabulary.LearningEntryIds.Contains("rw:beta"),
                "Reading vocabulary snapshot did not initialize from the authoritative All Oxford 5000 workspace.");

            RecallStudyScopeState allScope = state.RecallStudyScopesByDictionary[dictionary.Id].Scopes[StudyScopeIds.All];
            state.DeckIdsByDictionary[dictionary.Id]["rw:alpha"] = DeckIds.Core(2);
            state.DeckIdsByDictionary[dictionary.Id]["rw:beta"] = DeckIds.Core(5);
            BookDeckVocabularySnapshot staleLegacyProbe = BookReadingProductService.BuildVocabularySnapshot(
                state,
                dictionary,
                DeckIds.Core(5),
                DeckIds.Core(2));
            Require(staleLegacyProbe.KnownEntryIds.Contains("rw:alpha") &&
                    staleLegacyProbe.LearningEntryIds.Contains("rw:beta") &&
                    !staleLegacyProbe.KnownEntryIds.Contains("rw:beta"),
                "Reading vocabulary snapshot trusted the stale legacy deck mirror instead of authoritative All Oxford 5000.");

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

            // Regression: Learning capture spans authoritative Recall All state, its legacy mirror,
            // caller AppState persistence and the private Reading SQLite store.
            var readingState = new BookReadingStateStore(service.DatabasePath);

            // Establish a prior private Reading capture while keeping the authoritative
            // All workspace baseline at Known. The failed transaction must restore both.
            service.CaptureMappedOccurrenceToLearningDeck(
                imported.Document,
                sentence,
                "rw:alpha",
                state,
                dictionary,
                DeckIds.Core(2));
            BookUnknownWord priorAlphaCapture = readingState.LoadUnknowns(imported.Document.BookId)
                .Single(item => item.StableEntryId.Equals("rw:alpha", StringComparison.OrdinalIgnoreCase));
            allScope.DeckIds["rw:alpha"] = DeckIds.Core(5);
            allScope.RemainingShuffleEntryIds.RemoveAll(id => id.Equals("rw:alpha", StringComparison.OrdinalIgnoreCase));
            allScope.RemainingShuffleEntryIds.Add("rw:alpha");
            state.DeckIdsByDictionary[dictionary.Id] = new Dictionary<string, string>(allScope.DeckIds, StringComparer.OrdinalIgnoreCase);

            int failedPersistCalls = 0;
            ExpectFailure<IOException>(
                () => service.CaptureMappedOccurrenceToLearningDeckAndPersist(
                    imported.Document,
                    sentence,
                    "rw:alpha",
                    state,
                    dictionary,
                    DeckIds.Core(2),
                    () =>
                    {
                        failedPersistCalls++;
                        throw new IOException("simulated AppState persistence failure");
                    }),
                "Failed AppState persistence did not fail the cross-store Reading vocabulary capture.");
            Require(failedPersistCalls == 1, "Cross-store capture did not invoke caller persistence exactly once.");
            Require(allScope.DeckIds["rw:alpha"] == DeckIds.Core(5),
                "Failed persistence left the authoritative All Oxford 5000 assignment mutated.");
            Require(allScope.RemainingShuffleEntryIds.Contains("rw:alpha", StringComparer.OrdinalIgnoreCase),
                "Failed persistence did not restore the authoritative All Oxford 5000 shuffle state.");
            Require(state.DeckIdsByDictionary[dictionary.Id]["rw:alpha"] == DeckIds.Core(5),
                "Failed persistence did not restore the legacy All-scope mirror.");
            BookUnknownWord restoredAlphaCapture = readingState.LoadUnknowns(imported.Document.BookId)
                .Single(item => item.StableEntryId.Equals("rw:alpha", StringComparison.OrdinalIgnoreCase));
            Require(restoredAlphaCapture.SourceSentenceId == priorAlphaCapture.SourceSentenceId &&
                    restoredAlphaCapture.AddedUtc == priorAlphaCapture.AddedUtc,
                "Failed AppState persistence did not restore the exact prior private Reading capture.");

            Require(!readingState.LoadUnknowns(imported.Document.BookId)
                    .Any(item => item.StableEntryId.Equals("rw:beta", StringComparison.OrdinalIgnoreCase)),
                "Failure-path setup unexpectedly contained a prior beta Reading capture.");
            allScope.DeckIds["rw:beta"] = DeckIds.Core(2);
            allScope.RemainingShuffleEntryIds.RemoveAll(id => id.Equals("rw:beta", StringComparison.OrdinalIgnoreCase));
            allScope.RemainingShuffleEntryIds.Add("rw:beta");
            state.DeckIdsByDictionary[dictionary.Id] = new Dictionary<string, string>(allScope.DeckIds, StringComparer.OrdinalIgnoreCase);

            ExpectFailure<IOException>(
                () => service.CaptureMappedOccurrenceToLearningDeckAndPersist(
                    imported.Document,
                    sentence,
                    "rw:beta",
                    state,
                    dictionary,
                    DeckIds.Core(5),
                    () => throw new IOException("simulated first-capture persistence failure")),
                "Failed first capture did not surface the caller persistence error.");
            Require(allScope.DeckIds["rw:beta"] == DeckIds.Core(2),
                "Failed first capture did not restore the authoritative All Oxford 5000 assignment.");
            Require(allScope.RemainingShuffleEntryIds.Contains("rw:beta", StringComparer.OrdinalIgnoreCase),
                "Failed first capture did not restore the removed All Oxford 5000 shuffle entry.");
            Require(state.DeckIdsByDictionary[dictionary.Id]["rw:beta"] == DeckIds.Core(2),
                "Failed first capture did not restore the legacy All-scope mirror.");
            Require(!readingState.LoadUnknowns(imported.Document.BookId)
                    .Any(item => item.StableEntryId.Equals("rw:beta", StringComparison.OrdinalIgnoreCase)),
                "Failed first capture left a durable private Reading row behind.");

            int successfulPersistCalls = 0;
            service.CaptureMappedOccurrenceToLearningDeckAndPersist(
                imported.Document,
                sentence,
                "rw:beta",
                state,
                dictionary,
                DeckIds.Core(5),
                () => successfulPersistCalls++);
            Require(successfulPersistCalls == 1 &&
                    allScope.DeckIds["rw:beta"] == DeckIds.Core(5) &&
                    state.DeckIdsByDictionary[dictionary.Id]["rw:beta"] == DeckIds.Core(5) &&
                    !allScope.RemainingShuffleEntryIds.Contains("rw:beta", StringComparer.OrdinalIgnoreCase) &&
                    readingState.LoadUnknowns(imported.Document.BookId)
                        .Any(item => item.StableEntryId.Equals("rw:beta", StringComparison.OrdinalIgnoreCase)),
                "Successful cross-store capture did not commit authoritative All, legacy mirror and Reading evidence.");

            // Reconstructing the canonical scope service would overwrite a legacy-only
            // capture. The successful assignment must therefore survive this resync.
            var reopenedRecall = new RecallStudyScopeService(state, dictionary.Id, dictionary.Entries);
            Require(reopenedRecall.Assignments(StudyScopeIds.All)["rw:beta"] == DeckIds.Core(5) &&
                    state.DeckIdsByDictionary[dictionary.Id]["rw:beta"] == DeckIds.Core(5),
                "Successful Reading capture did not survive authoritative Recall All resynchronization.");

            Require(BookReadingWritingSelectionPolicy.CanUseActiveBook("book-a", "BOOK-A"),
                "Active-book guard rejected the same stable book identity with case-only differences.");
            Require(!BookReadingWritingSelectionPolicy.CanUseActiveBook("book-a", "book-b"),
                "Active-book guard allowed a different selected candidate to operate on the active book.");
            Require(!BookReadingWritingSelectionPolicy.CanUseActiveBook(null, "book-a") &&
                    !BookReadingWritingSelectionPolicy.CanUseActiveBook("book-a", null),
                "Active-book guard allowed actions without both authoritative active and selected book identities.");
            Require(BookReadingWritingSelectionPolicy.DescribeActiveBook("  Example Book ") == "Active private book: Example Book.",
                "Accessible active-book identity is not deterministic and explicit.");
            Require(BookReadingWritingSelectionPolicy.DescribeActiveBook(null) == "Active private book: none.",
                "Accessible active-book identity did not fail closed when no book is open.");
            _ = before;
        }
        finally
        {
            try { Directory.Delete(root, recursive: true); } catch { }
        }

        Console.WriteLine("BookReading writing self-test PASS: sentence grounding, deterministic non-mastery feedback, bounded input, local SQLite persistence, revision upsert, restart continuity, authoritative All-scope vocabulary/capture, cross-store rollback/commit and active-book identity guarding verified.");
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