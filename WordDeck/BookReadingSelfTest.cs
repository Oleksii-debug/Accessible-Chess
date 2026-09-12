using System.IO.Compression;
using System.Runtime.CompilerServices;
using System.Text;

namespace WordDeck;

internal static class BookReadingSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            BookReadingSelfTest.Run();
    }
}

internal static class BookReadingSelfTest
{
    public static void Run()
    {
        var mapper = new FixtureMapper();
        BookDocument txt = BookReadingImporter.Import(new BookImportRequest(
            "local-fixture-txt", "Fixture book", BookSourceFormat.Txt,
            Encoding.UTF8.GetBytes("Alpha is known. Beta is learning! Gamma is new?\nSecond paragraph."),
            "test-only local fixture", BookExtractionQuality.NativeText), mapper);
        Require(txt.PrivateLocalOnly, "TXT import lost private-local boundary.");
        Require(txt.OriginalText.Contains("Second paragraph", StringComparison.Ordinal), "Original TXT was not retained.");
        Require(txt.Chapters.SelectMany(c => c.Sentences).Count() >= 4, "TXT sentence indexing is incomplete.");

        BookDocument html = BookReadingImporter.Import(new BookImportRequest(
            "local-fixture-html", "HTML fixture", BookSourceFormat.Html,
            Encoding.UTF8.GetBytes("<html><body><h1>Title</h1><p>Alpha &amp; beta.</p><script>discard()</script><p>Gamma stays.</p></body></html>"),
            "test-only local fixture", BookExtractionQuality.StructuredHtml), mapper);
        Require(!html.NormalizedText.Contains("discard", StringComparison.OrdinalIgnoreCase), "HTML script content leaked into normalized reading text.");
        Require(html.NormalizedText.Contains("Alpha & beta", StringComparison.Ordinal), "HTML entity decoding failed.");

        BookDocument epub = BookReadingImporter.Import(new BookImportRequest(
            "local-fixture-epub", "EPUB fixture", BookSourceFormat.Epub,
            BuildMinimalEpub(), "test-only local fixture", BookExtractionQuality.EpubSpine), mapper);
        Require(epub.Chapters.Count == 2, "EPUB spine order/chapter extraction failed.");
        Require(epub.Chapters[0].NormalizedTitleOrText().Contains("One", StringComparison.OrdinalIgnoreCase), "EPUB first spine item is wrong.");

        BookDocument pdfText = BookReadingImporter.Import(new BookImportRequest(
            "local-fixture-pdf-derived", "PDF text fixture", BookSourceFormat.PdfDerivedText,
            Encoding.UTF8.GetBytes("Alpha came from an externally extracted PDF text stream."),
            "test-only externally extracted text", BookExtractionQuality.PdfDerivedUnverified), mapper);
        Require(pdfText.ExtractionQuality == BookExtractionQuality.PdfDerivedUnverified, "PDF extraction quality was not preserved.");
        ExpectFailure(() => BookReadingImporter.Import(new BookImportRequest(
            "bad-pdf", "bad", BookSourceFormat.PdfDerivedText, Encoding.UTF8.GetBytes("text"), "fixture", BookExtractionQuality.NativeText), mapper),
            "PDF-derived import accepted a false native-text quality claim.");

        var known = new HashSet<string>(new[] { "ox:alpha" }, StringComparer.OrdinalIgnoreCase);
        var learning = new HashSet<string>(new[] { "ox:beta" }, StringComparer.OrdinalIgnoreCase);
        BookVocabularyAnalysis analysis = BookVocabularyAnalyzer.Analyze(txt, known, learning);
        Require(analysis.Known > 0 && analysis.Learning > 0 && analysis.New > 0, "Known/learning/new analysis did not classify all states.");
        Require(analysis.FamiliarityPercent > 0 && analysis.FamiliarityPercent < 100, "Familiarity percentage is not bounded meaningfully.");

        string temp = Path.Combine(Path.GetTempPath(), "WordDeck Book читання " + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(temp);
        try
        {
            string db = Path.Combine(temp, "profile books.sqlite");
            var store = new BookReadingStateStore(db);
            store.SaveDocument(txt);
            BookSentenceRecord first = txt.Chapters[0].Sentences[0];
            store.SavePosition(txt, first.ChapterId, first.Span.StartOffset, first.SentenceId);
            if (first.StableEntryIds.Count > 0)
                store.CaptureUnknown(txt, first.StableEntryIds[0], first.SentenceId);

            var afterRestart = new BookReadingStateStore(db);
            BookReadingPosition? position = afterRestart.LoadPosition(txt.BookId);
            Require(position is not null && position.SentenceId == first.SentenceId, "Reading position did not survive store restart.");
            if (first.StableEntryIds.Count > 0)
                Require(afterRestart.LoadUnknowns(txt.BookId).Count == 1, "Unknown-word capture did not survive store restart.");
        }
        finally
        {
            try { Directory.Delete(temp, recursive: true); } catch { }
        }

        string large = string.Join(' ', Enumerable.Range(0, 3000).Select(i => $"Alpha sentence {i}."));
        BookDocument largeBook = BookReadingImporter.Import(new BookImportRequest(
            "large-fixture", "Large fixture", BookSourceFormat.Txt, Encoding.UTF8.GetBytes(large),
            "test-only generated fixture", BookExtractionQuality.NativeText), mapper);
        Require(largeBook.Chapters.SelectMany(c => c.Sentences).Count() == 3000, "Large-book sentence indexing lost records.");

        IReadOnlyList<BookSentenceExport> exports = BookSentenceIntegration.ExportForLearningEngines(txt);
        Require(exports.Count == txt.Chapters.Sum(c => c.Sentences.Count), "Sentence reuse export count mismatch.");
        Require(exports.All(x => x.PrivateLocalOnly), "Book sentence reuse escaped private-local boundary.");
    }

    private static byte[] BuildMinimalEpub()
    {
        using var stream = new MemoryStream();
        using (var zip = new ZipArchive(stream, ZipArchiveMode.Create, leaveOpen: true))
        {
            Write(zip, "META-INF/container.xml", "<?xml version=\"1.0\"?><container xmlns=\"urn:oasis:names:tc:opendocument:xmlns:container\"><rootfiles><rootfile full-path=\"OEBPS/content.opf\" media-type=\"application/oebps-package+xml\"/></rootfiles></container>");
            Write(zip, "OEBPS/content.opf", "<?xml version=\"1.0\"?><package xmlns=\"http://www.idpf.org/2007/opf\" version=\"3.0\"><manifest><item id=\"c1\" href=\"one.xhtml\" media-type=\"application/xhtml+xml\"/><item id=\"c2\" href=\"two.xhtml\" media-type=\"application/xhtml+xml\"/></manifest><spine><itemref idref=\"c1\"/><itemref idref=\"c2\"/></spine></package>");
            Write(zip, "OEBPS/one.xhtml", "<html><body><h1>One</h1><p>Alpha first.</p></body></html>");
            Write(zip, "OEBPS/two.xhtml", "<html><body><h1>Two</h1><p>Beta second.</p></body></html>");
        }
        return stream.ToArray();
    }

    private static void Write(ZipArchive zip, string path, string content)
    {
        ZipArchiveEntry entry = zip.CreateEntry(path);
        using var writer = new StreamWriter(entry.Open(), new UTF8Encoding(false));
        writer.Write(content);
    }

    private static void ExpectFailure(Action action, string message)
    {
        try { action(); }
        catch (InvalidDataException) { return; }
        throw new InvalidOperationException("Book-reading self-test failed: " + message);
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException("Book-reading self-test failed: " + message);
    }

    private sealed class FixtureMapper : IBookLexiconMapper
    {
        public IReadOnlyList<string> MapStableEntryIds(string text)
        {
            var result = new List<string>();
            if (text.Contains("alpha", StringComparison.OrdinalIgnoreCase)) result.Add("ox:alpha");
            if (text.Contains("beta", StringComparison.OrdinalIgnoreCase)) result.Add("ox:beta");
            if (text.Contains("gamma", StringComparison.OrdinalIgnoreCase)) result.Add("ox:gamma");
            return result;
        }
    }

    private static string NormalizedTitleOrText(this BookChapterRecord chapter) => chapter.Title + " " + string.Join(' ', chapter.Sentences.Select(s => s.Text));
}
