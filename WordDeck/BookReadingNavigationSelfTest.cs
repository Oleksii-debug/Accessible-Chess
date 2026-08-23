using System.Runtime.CompilerServices;
using System.Text;

namespace WordDeck;

internal static class BookReadingNavigationSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            BookReadingNavigationSelfTest.Run();
    }
}

internal static class BookReadingNavigationSelfTest
{
    public static void Run()
    {
        BookDocument book = BookReadingImporter.Import(new BookImportRequest(
            "navigation-fixture", "Navigation fixture", BookSourceFormat.Txt,
            Encoding.UTF8.GetBytes("First sentence. Second sentence.\n\nThird paragraph starts. Fourth sentence."),
            "test-only fixture", BookExtractionQuality.NativeText));
        IReadOnlyList<BookParagraphRecord> paragraphs = BookParagraphIndexer.Build(book);
        Require(paragraphs.Count == 2, "Paragraph indexing did not preserve blank-line paragraph boundaries.");
        Require(paragraphs.All(p => p.Span.EndOffset > p.Span.StartOffset), "Paragraph offsets are invalid.");

        var navigator = new BookReadingNavigator(book);
        BookReaderLocation first = navigator.First();
        BookReaderLocation second = navigator.Move(first, BookReaderCommand.NextSentence);
        Require(second.SentenceId != first.SentenceId, "Next-sentence navigation did not advance.");
        BookReaderLocation back = navigator.Move(second, BookReaderCommand.PreviousSentence);
        Require(back.SentenceId == first.SentenceId, "Previous-sentence navigation is not true history order.");
        BookReaderLocation paragraph = navigator.Move(first, BookReaderCommand.NextParagraph);
        Require(paragraph.ParagraphId != first.ParagraphId, "Next-paragraph navigation did not advance.");
        Require(!string.IsNullOrWhiteSpace(paragraph.AnnouncementUk), "Accessible navigation announcement is blank.");
        Require(BookReaderCommandCatalog.All.Select(x => x.Command).Distinct().Count() == BookReaderCommandCatalog.All.Count, "Book command catalog contains duplicate commands.");
        Require(BookReaderCommandCatalog.All.All(x => !string.IsNullOrWhiteSpace(x.AccessibleNameUk)), "Book command catalog contains blank accessible names.");

        BookSentenceRecord target = book.Chapters[0].Sentences.Last();
        BookReaderLocation restored = navigator.Restore(new BookReadingPosition(book.BookId, target.ChapterId, target.Span.StartOffset, target.SentenceId, DateTimeOffset.UtcNow));
        Require(restored.SentenceId == target.SentenceId, "Saved-context restore did not return to the exact sentence.");

        string temp = Path.Combine(Path.GetTempPath(), "WordDeck читання recovery " + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(temp);
        try
        {
            string db = Path.Combine(temp, "books.sqlite");
            var store = new BookReadingStateStore(db);
            store.SaveDocument(book);
            store.SavePosition(book, target.ChapterId, target.Span.StartOffset, target.SentenceId);
            string backup = BookReadingRecovery.Backup(db, "self-test");
            Require(File.Exists(backup) && new FileInfo(backup).Length > 0, "Book-reading backup was not created.");

            store.SavePosition(book, book.Chapters[0].Sentences[0].ChapterId, book.Chapters[0].Sentences[0].Span.StartOffset, book.Chapters[0].Sentences[0].SentenceId);
            BookReadingRecovery.Restore(db, backup);
            var restarted = new BookReadingStateStore(db);
            BookReadingPosition? recovered = restarted.LoadPosition(book.BookId);
            Require(recovered?.SentenceId == target.SentenceId, "Book-reading restore did not recover the backed-up reading position.");
        }
        finally
        {
            try { Directory.Delete(temp, true); } catch { }
        }
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException("Book navigation self-test failed: " + message);
    }
}
