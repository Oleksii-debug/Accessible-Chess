using Microsoft.Data.Sqlite;

namespace WordDeck;

internal sealed record BookParagraphRecord(
    string ParagraphId,
    string ChapterId,
    int ParagraphOrdinal,
    BookTextSpan Span,
    IReadOnlyList<string> SentenceIds);

internal static class BookParagraphIndexer
{
    public static IReadOnlyList<BookParagraphRecord> Build(BookDocument document)
    {
        ArgumentNullException.ThrowIfNull(document);
        document.Validate();
        var result = new List<BookParagraphRecord>();
        foreach (BookChapterRecord chapter in document.Chapters.OrderBy(x => x.ChapterOrdinal))
        {
            string chapterText = document.NormalizedText[(int)chapter.Span.StartOffset..(int)chapter.Span.EndOffset];
            int local = 0;
            int ordinal = 0;
            foreach (string raw in chapterText.Split("\n\n", StringSplitOptions.None))
            {
                string paragraph = raw.Trim();
                int rawStart = chapterText.IndexOf(raw, local, StringComparison.Ordinal);
                if (rawStart < 0) rawStart = local;
                local = rawStart + raw.Length;
                if (paragraph.Length == 0) continue;
                int trimStart = raw.IndexOf(paragraph, StringComparison.Ordinal);
                long start = chapter.Span.StartOffset + rawStart + Math.Max(0, trimStart);
                long end = start + paragraph.Length;
                string id = $"{chapter.ChapterId}:paragraph:{ordinal:D6}";
                string[] sentenceIds = chapter.Sentences
                    .Where(s => s.Span.StartOffset >= start && s.Span.EndOffset <= end)
                    .Select(s => s.SentenceId)
                    .ToArray();
                result.Add(new BookParagraphRecord(id, chapter.ChapterId, ordinal++, new BookTextSpan(start, end), sentenceIds));
            }
        }
        return result;
    }
}

internal enum BookReaderCommand
{
    NextSentence,
    PreviousSentence,
    NextParagraph,
    PreviousParagraph,
    NextChapter,
    PreviousChapter,
    RepeatCurrent,
    CaptureCurrentUnknownWords,
    ReturnToSavedContext
}

internal sealed record BookReaderCommandDefinition(
    BookReaderCommand Command,
    string AccessibleNameUk,
    bool RequiresCurrentSentence);

internal static class BookReaderCommandCatalog
{
    public static IReadOnlyList<BookReaderCommandDefinition> All { get; } = new[]
    {
        new BookReaderCommandDefinition(BookReaderCommand.NextSentence, "Наступне речення", false),
        new BookReaderCommandDefinition(BookReaderCommand.PreviousSentence, "Попереднє речення", false),
        new BookReaderCommandDefinition(BookReaderCommand.NextParagraph, "Наступний абзац", false),
        new BookReaderCommandDefinition(BookReaderCommand.PreviousParagraph, "Попередній абзац", false),
        new BookReaderCommandDefinition(BookReaderCommand.NextChapter, "Наступний розділ", false),
        new BookReaderCommandDefinition(BookReaderCommand.PreviousChapter, "Попередній розділ", false),
        new BookReaderCommandDefinition(BookReaderCommand.RepeatCurrent, "Повторити поточне речення", true),
        new BookReaderCommandDefinition(BookReaderCommand.CaptureCurrentUnknownWords, "Додати невідомі слова поточного речення до навчання", true),
        new BookReaderCommandDefinition(BookReaderCommand.ReturnToSavedContext, "Повернутися до збереженого місця читання", false)
    };
}

internal sealed record BookReaderLocation(
    string BookId,
    string ChapterId,
    string? ParagraphId,
    string? SentenceId,
    long Offset,
    string AnnouncementUk);

internal sealed class BookReadingNavigator
{
    private readonly BookDocument _document;
    private readonly BookParagraphRecord[] _paragraphs;
    private readonly BookSentenceRecord[] _sentences;

    public BookReadingNavigator(BookDocument document)
    {
        _document = document ?? throw new ArgumentNullException(nameof(document));
        _document.Validate();
        _paragraphs = BookParagraphIndexer.Build(document).OrderBy(x => x.Span.StartOffset).ToArray();
        _sentences = document.Chapters.SelectMany(x => x.Sentences).OrderBy(x => x.Span.StartOffset).ToArray();
    }

    public BookReaderLocation First() => LocationForSentence(_sentences.FirstOrDefault(), "Початок книги.");

    public BookReaderLocation Move(BookReaderLocation current, BookReaderCommand command)
    {
        ArgumentNullException.ThrowIfNull(current);
        if (!string.Equals(current.BookId, _document.BookId, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Book navigation location belongs to another book.");
        return command switch
        {
            BookReaderCommand.NextSentence => MoveSentence(current, +1),
            BookReaderCommand.PreviousSentence => MoveSentence(current, -1),
            BookReaderCommand.NextParagraph => MoveParagraph(current, +1),
            BookReaderCommand.PreviousParagraph => MoveParagraph(current, -1),
            BookReaderCommand.NextChapter => MoveChapter(current, +1),
            BookReaderCommand.PreviousChapter => MoveChapter(current, -1),
            BookReaderCommand.RepeatCurrent => Current(current, "Поточне речення повторено."),
            _ => Current(current, "Позицію читання не змінено.")
        };
    }

    public BookReaderLocation Restore(BookReadingPosition? saved)
    {
        if (saved is null) return First();
        if (!string.Equals(saved.BookId, _document.BookId, StringComparison.OrdinalIgnoreCase)) return First();
        BookSentenceRecord? sentence = saved.SentenceId is null ? null : _sentences.FirstOrDefault(x => x.SentenceId.Equals(saved.SentenceId, StringComparison.OrdinalIgnoreCase));
        if (sentence is not null) return LocationForSentence(sentence, "Повернуто збережене місце читання.");
        BookChapterRecord? chapter = _document.Chapters.FirstOrDefault(x => x.ChapterId.Equals(saved.ChapterId, StringComparison.OrdinalIgnoreCase));
        if (chapter is null) return First();
        sentence = chapter.Sentences.OrderBy(x => Math.Abs(x.Span.StartOffset - saved.Offset)).FirstOrDefault();
        return LocationForSentence(sentence, "Повернуто найближче доступне місце читання.");
    }

    private BookReaderLocation MoveSentence(BookReaderLocation current, int delta)
    {
        int index = current.SentenceId is null ? -1 : Array.FindIndex(_sentences, x => x.SentenceId.Equals(current.SentenceId, StringComparison.OrdinalIgnoreCase));
        int next = Math.Clamp(index + delta, 0, Math.Max(0, _sentences.Length - 1));
        string announcement = next == index ? (delta > 0 ? "Кінець книги." : "Початок книги.") : (delta > 0 ? "Наступне речення." : "Попереднє речення.");
        return LocationForSentence(_sentences.Length == 0 ? null : _sentences[next], announcement);
    }

    private BookReaderLocation MoveParagraph(BookReaderLocation current, int delta)
    {
        if (_paragraphs.Length == 0) return Current(current, "У книзі немає абзаців.");
        int index = Array.FindIndex(_paragraphs, x => x.ParagraphId.Equals(current.ParagraphId, StringComparison.OrdinalIgnoreCase));
        if (index < 0) index = Array.FindLastIndex(_paragraphs, x => x.Span.StartOffset <= current.Offset);
        int next = Math.Clamp(index + delta, 0, _paragraphs.Length - 1);
        BookParagraphRecord paragraph = _paragraphs[next];
        BookSentenceRecord? sentence = _sentences.FirstOrDefault(x => paragraph.SentenceIds.Contains(x.SentenceId, StringComparer.OrdinalIgnoreCase));
        return sentence is null
            ? new BookReaderLocation(_document.BookId, paragraph.ChapterId, paragraph.ParagraphId, null, paragraph.Span.StartOffset, delta > 0 ? "Наступний абзац." : "Попередній абзац.")
            : LocationForSentence(sentence, delta > 0 ? "Наступний абзац." : "Попередній абзац.");
    }

    private BookReaderLocation MoveChapter(BookReaderLocation current, int delta)
    {
        BookChapterRecord[] chapters = _document.Chapters.OrderBy(x => x.ChapterOrdinal).ToArray();
        int index = Array.FindIndex(chapters, x => x.ChapterId.Equals(current.ChapterId, StringComparison.OrdinalIgnoreCase));
        int next = Math.Clamp(index + delta, 0, Math.Max(0, chapters.Length - 1));
        BookSentenceRecord? sentence = chapters.Length == 0 ? null : chapters[next].Sentences.FirstOrDefault();
        return sentence is null
            ? Current(current, chapters.Length == 0 ? "У книзі немає розділів." : chapters[next].Title)
            : LocationForSentence(sentence, (delta > 0 ? "Наступний розділ: " : "Попередній розділ: ") + chapters[next].Title);
    }

    private BookReaderLocation Current(BookReaderLocation current, string announcement) => current with { AnnouncementUk = announcement };

    private BookReaderLocation LocationForSentence(BookSentenceRecord? sentence, string announcement)
    {
        if (sentence is null)
        {
            BookChapterRecord firstChapter = _document.Chapters.First();
            return new BookReaderLocation(_document.BookId, firstChapter.ChapterId, null, null, firstChapter.Span.StartOffset, announcement);
        }
        BookParagraphRecord? paragraph = _paragraphs.FirstOrDefault(x => x.SentenceIds.Contains(sentence.SentenceId, StringComparer.OrdinalIgnoreCase));
        return new BookReaderLocation(_document.BookId, sentence.ChapterId, paragraph?.ParagraphId, sentence.SentenceId, sentence.Span.StartOffset, announcement);
    }
}

internal static class BookReadingRecovery
{
    public static string Backup(string databasePath, string reason)
    {
        string sourcePath = Path.GetFullPath(databasePath);
        if (!File.Exists(sourcePath)) throw new FileNotFoundException("Book-reading database does not exist.", sourcePath);
        string safeReason = string.Concat((reason ?? "backup").Where(ch => char.IsLetterOrDigit(ch) || ch is '-' or '_'));
        if (safeReason.Length == 0) safeReason = "backup";
        string backupPath = sourcePath + $".{DateTimeOffset.UtcNow:yyyyMMddHHmmssfff}.{safeReason}.backup.sqlite";
        using SqliteConnection source = Open(sourcePath, SqliteOpenMode.ReadOnly);
        using SqliteConnection destination = Open(backupPath, SqliteOpenMode.ReadWriteCreate);
        source.BackupDatabase(destination);
        return backupPath;
    }

    public static void Restore(string databasePath, string backupPath)
    {
        string targetPath = Path.GetFullPath(databasePath);
        string sourcePath = Path.GetFullPath(backupPath);
        if (!File.Exists(sourcePath)) throw new FileNotFoundException("Book-reading backup does not exist.", sourcePath);
        if (File.Exists(targetPath)) Backup(targetPath, "before-restore");
        string tempPath = targetPath + ".restore-" + Guid.NewGuid().ToString("N") + ".sqlite";
        try
        {
            using (SqliteConnection source = Open(sourcePath, SqliteOpenMode.ReadOnly))
            using (SqliteConnection temp = Open(tempPath, SqliteOpenMode.ReadWriteCreate))
                source.BackupDatabase(temp);
            using (SqliteConnection validation = Open(tempPath, SqliteOpenMode.ReadOnly))
            using (SqliteCommand command = validation.CreateCommand())
            {
                command.CommandText = "PRAGMA integrity_check;";
                string result = Convert.ToString(command.ExecuteScalar()) ?? string.Empty;
                if (!string.Equals(result, "ok", StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("Book-reading backup failed SQLite integrity validation.");
            }
            File.Move(tempPath, targetPath, overwrite: true);
        }
        finally
        {
            try { if (File.Exists(tempPath)) File.Delete(tempPath); } catch { }
        }
    }

    private static SqliteConnection Open(string path, SqliteOpenMode mode)
    {
        var connection = new SqliteConnection(new SqliteConnectionStringBuilder { DataSource = path, Mode = mode }.ToString());
        connection.Open();
        return connection;
    }
}
