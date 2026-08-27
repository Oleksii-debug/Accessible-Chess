using System.IO.Compression;
using System.Runtime.CompilerServices;
using System.Text;

namespace WordDeck;

internal static class BookReadingAdvancedSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            BookReadingAdvancedSelfTest.Run();
    }
}

internal static class BookReadingAdvancedSelfTest
{
    public static void Run()
    {
        DictionaryPackage dictionary = BuildDictionary();
        AppState state = AppStateStore.Normalize(new AppState { ActiveDictionaryId = dictionary.Id, ActiveDeckId = DeckIds.Core(2) });
        state.DeckIdsByDictionary[dictionary.Id] = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["ox:record-n"] = DeckIds.Core(1),
            ["ox:record-v"] = DeckIds.Core(1),
            ["ox:alpha"] = DeckIds.Core(5),
            ["ox:beta"] = DeckIds.Core(2),
            ["user:take-care"] = DeckIds.Core(1)
        };
        BookDeckVocabularySnapshot snapshot = BookReadingProductService.BuildVocabularySnapshot(state, dictionary, DeckIds.Core(5), DeckIds.Core(2));

        string root = Path.Combine(Path.GetTempPath(), "WordDeck DEV03 читання з пробілами " + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            string input = Path.Combine(root, "Книжка test.txt");
            byte[] source = Encoding.UTF8.GetBytes("Record. record record. Alpha beta. Take care alpha.");
            File.WriteAllBytes(input, source);
            string privateRoot = Path.Combine(root, "private profile");
            var service = new BookReadingProductService(privateRoot);
            BookImportProductResult imported = service.ImportFile(input, dictionary, snapshot);

            Require(imported.Document.PrivateLocalOnly, "Product import lost the private-local boundary.");
            Require(File.ReadAllBytes(imported.PrivateSourcePath).SequenceEqual(source), "Exact original source bytes were not retained privately.");
            Require(Path.GetFullPath(imported.PrivateSourcePath).StartsWith(Path.GetFullPath(privateRoot), StringComparison.OrdinalIgnoreCase), "Private source escaped the configured profile root.");
            Require(imported.Coverage.PhysicalLexicalCount == 7, $"Expected 7 physical lexical occurrences, got {imported.Coverage.PhysicalLexicalCount}.");
            Require(imported.Coverage.Known == 2, "Repeated known alpha occurrences were not counted physically.");
            Require(imported.Coverage.Learning == 1, "Learning beta occurrence was not classified from the selected deck.");
            Require(imported.Coverage.New == 4 && imported.Coverage.OffList == 0, "New/off-list physical accounting is wrong.");

            var lexical = new BookLexicalFormIndex(dictionary);
            BookPhysicalAnalysis physical = lexical.Analyze(imported.Document, snapshot.KnownEntryIds, snapshot.LearningEntryIds);
            Require(physical.PhysicalLexicalCount == 7, "In-memory physical lexical accounting diverged from SQLite accounting.");
            Require(physical.AmbiguousOccurrences == 3, "Three physical 'record' occurrences should each preserve both matching stable IDs.");
            Require(physical.Sentences.SelectMany(sentence => sentence.Occurrences).Where(item => item.Surface.Equals("record", StringComparison.OrdinalIgnoreCase)).All(item => item.StableEntryIds.Count == 2), "Physical ambiguity metadata was lost.");

            IReadOnlyList<BookSentenceExport> ambiguousPair = service.FindBookSentences(new[] { "ox:record-n", "ox:record-v" }, 20);
            Require(ambiguousPair.Count == 1, "Two-target ambiguity query must require two distinct physical occurrences, not one ambiguous occurrence.");
            Require(ambiguousPair[0].EnglishText.Equals("record record.", StringComparison.OrdinalIgnoreCase), "Two-target ambiguity query returned the wrong physical context.");
            IReadOnlyList<BookSentenceExport> alphaBeta = service.FindBookSentences(new[] { "ox:alpha", "ox:beta" }, 20);
            Require(alphaBeta.Count == 1 && alphaBeta[0].EnglishText.Equals("Alpha beta.", StringComparison.Ordinal), "Natural two-target book lookup failed.");
            Require(service.FindBookSentences(new[] { "ox:record-n", "ox:record-v", "ox:alpha" }, 20).Count == 0, "Three-target query incorrectly combined targets across sentences.");

            BookDocument reloaded = new BookReadingProductService(privateRoot).LoadDocument(imported.Document.BookId);
            Require(reloaded.ContentSha256 == imported.Document.ContentSha256 && reloaded.Chapters.Sum(chapter => chapter.Sentences.Count) == 4, "Book document did not reconstruct correctly after service restart.");
            BookSentenceRecord firstSentence = reloaded.Chapters[0].Sentences[0];
            service.SavePosition(reloaded, firstSentence);
            BookReadingPosition? position = new BookReadingProductService(privateRoot).LoadPosition(reloaded.BookId);
            Require(position?.SentenceId == firstSentence.SentenceId, "Reading position did not survive a product-service restart.");

            BookSentenceRecord alphaSentence = reloaded.Chapters.SelectMany(chapter => chapter.Sentences).First(sentence => sentence.StableEntryIds.Contains("ox:alpha", StringComparer.OrdinalIgnoreCase));
            service.CaptureMappedOccurrenceToLearningDeck(reloaded, alphaSentence, "ox:alpha", state, dictionary, DeckIds.Core(2));
            Require(state.DeckIdsByDictionary[dictionary.Id]["ox:alpha"] == DeckIds.Core(2), "Capturing a mapped book occurrence did not move the stable dictionary entry into the chosen Learning deck.");
            Require(new BookReadingStateStore(service.DatabasePath).LoadUnknowns(reloaded.BookId).Any(item => item.StableEntryId == "ox:alpha" && item.SourceSentenceId == alphaSentence.SentenceId), "Book learning capture lost its source-sentence context.");

            TestTransactionalRecovery(service.DatabasePath, reloaded);
            TestUnsafeEpubRejection();
            TestDtdRejection();
            TestDirectPdfBoundary(root, service, dictionary, snapshot);
            TestLargePersistentCorpus(root, dictionary, snapshot);
        }
        finally
        {
            try { Directory.Delete(root, recursive: true); } catch { }
        }

        Console.WriteLine("BookReading advanced self-test PASS: physical lexical ambiguity, private source retention, 1/2/3 context lookup, restart, capture, recovery, EPUB safety and large persistent corpus verified.");
    }

    private static void TestTransactionalRecovery(string databasePath, BookDocument original)
    {
        BookChapterRecord chapter = original.Chapters[0];
        var malformed = new BookDocument(
            original.BookId,
            original.SourceId,
            "corrupt replacement attempt",
            original.Format,
            original.ExtractionQuality,
            original.Provenance,
            original.ContentSha256,
            original.OriginalText,
            original.NormalizedText,
            new[] { chapter, chapter },
            true);
        var store = new BookReadingStateStore(databasePath);
        ExpectFailure<Microsoft.Data.Sqlite.SqliteException>(() => store.SaveDocument(malformed), "Duplicate chapter transaction did not fail as expected.");
        BookDocument recovered = BookReadingDocumentLoader.Load(databasePath, original.BookId)
            ?? throw new InvalidOperationException("Book-reading recovery test lost the committed document.");
        Require(recovered.DisplayName == original.DisplayName, "Failed replacement transaction changed committed book metadata.");
        Require(recovered.Chapters.Count == original.Chapters.Count, "Failed replacement transaction destroyed committed chapters.");
    }

    private static void TestUnsafeEpubRejection()
    {
        byte[] malicious = BuildZip(new Dictionary<string, string>
        {
            ["META-INF/container.xml"] = "<?xml version=\"1.0\"?><container xmlns=\"urn:oasis:names:tc:opendocument:xmlns:container\"><rootfiles/></container>",
            ["../escape.xhtml"] = "<html><body>escape</body></html>"
        });
        ExpectFailure<InvalidDataException>(() => BookReadingProductService.ValidateEpubSafety(malicious), "EPUB traversal path was accepted.");
    }

    private static void TestDtdRejection()
    {
        byte[] malicious = BuildZip(new Dictionary<string, string>
        {
            ["META-INF/container.xml"] = "<?xml version=\"1.0\"?><!DOCTYPE container [<!ENTITY x \"bad\">]><container xmlns=\"urn:oasis:names:tc:opendocument:xmlns:container\">&x;</container>"
        });
        ExpectXmlFailure(() => BookReadingProductService.ValidateEpubSafety(malicious), "EPUB XML DTD was accepted.");
    }

    private static void TestDirectPdfBoundary(string root, BookReadingProductService service, DictionaryPackage dictionary, BookDeckVocabularySnapshot snapshot)
    {
        string pdf = Path.Combine(root, "sample.pdf");
        File.WriteAllText(pdf, "%PDF-test fixture only");
        ExpectFailure<InvalidDataException>(() => service.ImportFile(pdf, dictionary, snapshot), "Direct PDF import silently pretended to extract text.");
        string derived = Path.Combine(root, "sample-derived.txt");
        File.WriteAllText(derived, "Alpha beta.", new UTF8Encoding(false));
        BookImportProductResult result = service.ImportPdfDerivedTextFile(derived, dictionary, snapshot, extractionReviewed: false);
        Require(result.Document.ExtractionQuality == BookExtractionQuality.PdfDerivedUnverified, "Explicit PDF-derived text lost its unverified extraction-quality label.");
    }

    private static void TestLargePersistentCorpus(string root, DictionaryPackage dictionary, BookDeckVocabularySnapshot snapshot)
    {
        string path = Path.Combine(root, "large local book.txt");
        string content = string.Join(' ', Enumerable.Range(0, 1200).Select(index => index % 2 == 0 ? "Alpha beta." : "Take care alpha."));
        File.WriteAllText(path, content, new UTF8Encoding(false));
        var service = new BookReadingProductService(Path.Combine(root, "large private"));
        BookImportProductResult result = service.ImportFile(path, dictionary, snapshot);
        Require(result.Document.Chapters.Sum(chapter => chapter.Sentences.Count) == 1200, "Large persistent book lost sentence records.");
        Require(result.Coverage.PhysicalLexicalCount == 2400, "Large persistent book physical lexical count is wrong.");
        IReadOnlyList<BookSentenceExport> contexts = service.FindBookSentences(new[] { "ox:alpha", "ox:beta" }, 200);
        Require(contexts.Count == 200 && contexts.All(item => item.PrivateLocalOnly), "Large persistent target lookup did not respect bounded result count/private provenance.");
        BookDocument reloaded = new BookReadingProductService(Path.Combine(root, "large private")).LoadDocument(result.Document.BookId);
        Require(reloaded.Chapters.Sum(chapter => chapter.Sentences.Count) == 1200, "Large persistent book did not survive restart.");
    }

    private static byte[] BuildZip(IReadOnlyDictionary<string, string> entries)
    {
        using var stream = new MemoryStream();
        using (var archive = new ZipArchive(stream, ZipArchiveMode.Create, leaveOpen: true))
        {
            foreach ((string path, string text) in entries)
            {
                ZipArchiveEntry entry = archive.CreateEntry(path, CompressionLevel.Fastest);
                using var writer = new StreamWriter(entry.Open(), new UTF8Encoding(false));
                writer.Write(text);
            }
        }
        return stream.ToArray();
    }

    private static DictionaryPackage BuildDictionary() => new()
    {
        Id = "test-book-dictionary",
        Name = "Book test dictionary",
        SourceLanguage = "en",
        TargetLanguage = "uk",
        Entries = new DictionaryEntry[]
        {
            new("ox:record-n", "B1", "record", "запис"),
            new("ox:record-v", "B1", "record", "записувати"),
            new("ox:alpha", "A1", "alpha", "альфа"),
            new("ox:beta", "A1", "beta", "бета"),
            new("user:take-care", "CUSTOM", "take care", "піклуватися")
        }
    };

    private static void ExpectFailure<T>(Action action, string message) where T : Exception
    {
        try { action(); }
        catch (T) { return; }
        throw new InvalidOperationException("BookReading advanced self-test failed: " + message);
    }

    private static void ExpectXmlFailure(Action action, string message)
    {
        try { action(); }
        catch (System.Xml.XmlException) { return; }
        catch (InvalidDataException) { return; }
        throw new InvalidOperationException("BookReading advanced self-test failed: " + message);
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException("BookReading advanced self-test failed: " + message);
    }
}
