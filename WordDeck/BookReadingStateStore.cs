using Microsoft.Data.Sqlite;

namespace WordDeck;

internal sealed record BookReadingPosition(string BookId, string ChapterId, long Offset, string? SentenceId, DateTimeOffset UpdatedUtc);
internal sealed record BookUnknownWord(string BookId, string StableEntryId, string SourceSentenceId, DateTimeOffset AddedUtc);

internal sealed class BookReadingStateStore
{
    private readonly string _databasePath;

    public BookReadingStateStore(string databasePath)
    {
        if (string.IsNullOrWhiteSpace(databasePath))
            throw new ArgumentException("Book-reading SQLite path is required.", nameof(databasePath));
        _databasePath = Path.GetFullPath(databasePath);
    }

    public void Initialize()
    {
        string? directory = Path.GetDirectoryName(_databasePath);
        if (!string.IsNullOrEmpty(directory))
            Directory.CreateDirectory(directory);
        using SqliteConnection connection = Open();
        using SqliteCommand command = connection.CreateCommand();
        command.CommandText = """
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS book_document (
                book_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                source_format INTEGER NOT NULL,
                extraction_quality INTEGER NOT NULL,
                provenance TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                original_text TEXT NOT NULL,
                normalized_text TEXT NOT NULL,
                private_local_only INTEGER NOT NULL CHECK(private_local_only = 1)
            );
            CREATE TABLE IF NOT EXISTS book_chapter (
                chapter_id TEXT PRIMARY KEY,
                book_id TEXT NOT NULL REFERENCES book_document(book_id) ON DELETE CASCADE,
                chapter_ordinal INTEGER NOT NULL,
                title TEXT NOT NULL,
                start_offset INTEGER NOT NULL,
                end_offset INTEGER NOT NULL,
                UNIQUE(book_id, chapter_ordinal)
            );
            CREATE TABLE IF NOT EXISTS book_sentence (
                sentence_id TEXT PRIMARY KEY,
                chapter_id TEXT NOT NULL REFERENCES book_chapter(chapter_id) ON DELETE CASCADE,
                sentence_ordinal INTEGER NOT NULL,
                start_offset INTEGER NOT NULL,
                end_offset INTEGER NOT NULL,
                sentence_text TEXT NOT NULL,
                stable_entry_ids TEXT NOT NULL,
                UNIQUE(chapter_id, sentence_ordinal)
            );
            CREATE INDEX IF NOT EXISTS ix_book_sentence_span ON book_sentence(chapter_id, start_offset, end_offset);
            CREATE TABLE IF NOT EXISTS book_reading_position (
                book_id TEXT PRIMARY KEY REFERENCES book_document(book_id) ON DELETE CASCADE,
                chapter_id TEXT NOT NULL,
                offset_value INTEGER NOT NULL,
                sentence_id TEXT NULL,
                updated_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS book_unknown_capture (
                book_id TEXT NOT NULL REFERENCES book_document(book_id) ON DELETE CASCADE,
                stable_entry_id TEXT NOT NULL,
                source_sentence_id TEXT NOT NULL,
                added_utc TEXT NOT NULL,
                PRIMARY KEY(book_id, stable_entry_id)
            );
            """;
        command.ExecuteNonQuery();
    }

    public void SaveDocument(BookDocument document)
    {
        ArgumentNullException.ThrowIfNull(document);
        document.Validate();
        Initialize();
        using SqliteConnection connection = Open();
        using SqliteTransaction transaction = connection.BeginTransaction();
        try
        {
            using (SqliteCommand upsert = connection.CreateCommand())
            {
                upsert.Transaction = transaction;
                upsert.CommandText = """
                    INSERT INTO book_document(book_id,source_id,display_name,source_format,extraction_quality,provenance,content_sha256,original_text,normalized_text,private_local_only)
                    VALUES($book,$source,$name,$format,$quality,$provenance,$sha,$original,$normalized,1)
                    ON CONFLICT(book_id) DO UPDATE SET
                      source_id=excluded.source_id, display_name=excluded.display_name,
                      source_format=excluded.source_format, extraction_quality=excluded.extraction_quality,
                      provenance=excluded.provenance, content_sha256=excluded.content_sha256,
                      original_text=excluded.original_text, normalized_text=excluded.normalized_text,
                      private_local_only=1;
                    """;
                upsert.Parameters.AddWithValue("$book", document.BookId);
                upsert.Parameters.AddWithValue("$source", document.SourceId);
                upsert.Parameters.AddWithValue("$name", document.DisplayName);
                upsert.Parameters.AddWithValue("$format", (int)document.Format);
                upsert.Parameters.AddWithValue("$quality", (int)document.ExtractionQuality);
                upsert.Parameters.AddWithValue("$provenance", document.Provenance);
                upsert.Parameters.AddWithValue("$sha", document.ContentSha256);
                upsert.Parameters.AddWithValue("$original", document.OriginalText);
                upsert.Parameters.AddWithValue("$normalized", document.NormalizedText);
                upsert.ExecuteNonQuery();
            }

            using (SqliteCommand clear = connection.CreateCommand())
            {
                clear.Transaction = transaction;
                clear.CommandText = "DELETE FROM book_chapter WHERE book_id=$book";
                clear.Parameters.AddWithValue("$book", document.BookId);
                clear.ExecuteNonQuery();
            }

            foreach (BookChapterRecord chapter in document.Chapters)
            {
                using SqliteCommand chapterCommand = connection.CreateCommand();
                chapterCommand.Transaction = transaction;
                chapterCommand.CommandText = "INSERT INTO book_chapter(chapter_id,book_id,chapter_ordinal,title,start_offset,end_offset) VALUES($id,$book,$ord,$title,$start,$end)";
                chapterCommand.Parameters.AddWithValue("$id", chapter.ChapterId);
                chapterCommand.Parameters.AddWithValue("$book", document.BookId);
                chapterCommand.Parameters.AddWithValue("$ord", chapter.ChapterOrdinal);
                chapterCommand.Parameters.AddWithValue("$title", chapter.Title);
                chapterCommand.Parameters.AddWithValue("$start", chapter.Span.StartOffset);
                chapterCommand.Parameters.AddWithValue("$end", chapter.Span.EndOffset);
                chapterCommand.ExecuteNonQuery();

                foreach (BookSentenceRecord sentence in chapter.Sentences)
                {
                    using SqliteCommand sentenceCommand = connection.CreateCommand();
                    sentenceCommand.Transaction = transaction;
                    sentenceCommand.CommandText = "INSERT INTO book_sentence(sentence_id,chapter_id,sentence_ordinal,start_offset,end_offset,sentence_text,stable_entry_ids) VALUES($id,$chapter,$ord,$start,$end,$text,$ids)";
                    sentenceCommand.Parameters.AddWithValue("$id", sentence.SentenceId);
                    sentenceCommand.Parameters.AddWithValue("$chapter", chapter.ChapterId);
                    sentenceCommand.Parameters.AddWithValue("$ord", sentence.SentenceOrdinal);
                    sentenceCommand.Parameters.AddWithValue("$start", sentence.Span.StartOffset);
                    sentenceCommand.Parameters.AddWithValue("$end", sentence.Span.EndOffset);
                    sentenceCommand.Parameters.AddWithValue("$text", sentence.Text);
                    sentenceCommand.Parameters.AddWithValue("$ids", string.Join('\n', sentence.StableEntryIds));
                    sentenceCommand.ExecuteNonQuery();
                }
            }
            transaction.Commit();
        }
        catch
        {
            transaction.Rollback();
            throw;
        }
    }

    public void SavePosition(BookDocument document, string chapterId, long offset, string? sentenceId)
    {
        ArgumentNullException.ThrowIfNull(document);
        document.Validate();
        BookChapterRecord chapter = document.Chapters.FirstOrDefault(c => c.ChapterId.Equals(chapterId, StringComparison.OrdinalIgnoreCase))
            ?? throw new InvalidDataException("Reading position chapter does not belong to this book.");
        if (offset < chapter.Span.StartOffset || offset > chapter.Span.EndOffset)
            throw new InvalidDataException("Reading position offset is outside the selected chapter.");
        if (sentenceId is not null && !chapter.Sentences.Any(s => s.SentenceId.Equals(sentenceId, StringComparison.OrdinalIgnoreCase)))
            throw new InvalidDataException("Reading position sentence does not belong to the selected chapter.");
        Initialize();
        using SqliteConnection connection = Open();
        using SqliteCommand command = connection.CreateCommand();
        command.CommandText = """
            INSERT INTO book_reading_position(book_id,chapter_id,offset_value,sentence_id,updated_utc)
            VALUES($book,$chapter,$offset,$sentence,$utc)
            ON CONFLICT(book_id) DO UPDATE SET chapter_id=excluded.chapter_id,offset_value=excluded.offset_value,sentence_id=excluded.sentence_id,updated_utc=excluded.updated_utc;
            """;
        command.Parameters.AddWithValue("$book", document.BookId);
        command.Parameters.AddWithValue("$chapter", chapterId);
        command.Parameters.AddWithValue("$offset", offset);
        command.Parameters.AddWithValue("$sentence", (object?)sentenceId ?? DBNull.Value);
        command.Parameters.AddWithValue("$utc", DateTimeOffset.UtcNow.ToString("O"));
        command.ExecuteNonQuery();
    }

    public BookReadingPosition? LoadPosition(string bookId)
    {
        Initialize();
        using SqliteConnection connection = Open();
        using SqliteCommand command = connection.CreateCommand();
        command.CommandText = "SELECT book_id,chapter_id,offset_value,sentence_id,updated_utc FROM book_reading_position WHERE book_id=$book";
        command.Parameters.AddWithValue("$book", bookId);
        using SqliteDataReader reader = command.ExecuteReader();
        if (!reader.Read()) return null;
        return new BookReadingPosition(reader.GetString(0), reader.GetString(1), reader.GetInt64(2), reader.IsDBNull(3) ? null : reader.GetString(3), DateTimeOffset.Parse(reader.GetString(4)));
    }

    public void CaptureUnknown(BookDocument document, string stableEntryId, string sourceSentenceId)
    {
        ArgumentNullException.ThrowIfNull(document);
        string id = (stableEntryId ?? string.Empty).Trim().ToLowerInvariant();
        if (id.Length == 0) throw new InvalidDataException("Unknown-word stable id is required.");
        if (!document.Chapters.SelectMany(c => c.Sentences).Any(s => s.SentenceId.Equals(sourceSentenceId, StringComparison.OrdinalIgnoreCase) && s.StableEntryIds.Contains(id, StringComparer.OrdinalIgnoreCase)))
            throw new InvalidDataException("Unknown word must be captured from a sentence that actually maps to the stable id.");
        Initialize();
        using SqliteConnection connection = Open();
        using SqliteCommand command = connection.CreateCommand();
        command.CommandText = """
            INSERT INTO book_unknown_capture(book_id,stable_entry_id,source_sentence_id,added_utc)
            VALUES($book,$id,$sentence,$utc)
            ON CONFLICT(book_id,stable_entry_id) DO UPDATE SET source_sentence_id=excluded.source_sentence_id,added_utc=excluded.added_utc;
            """;
        command.Parameters.AddWithValue("$book", document.BookId);
        command.Parameters.AddWithValue("$id", id);
        command.Parameters.AddWithValue("$sentence", sourceSentenceId);
        command.Parameters.AddWithValue("$utc", DateTimeOffset.UtcNow.ToString("O"));
        command.ExecuteNonQuery();
    }

    public IReadOnlyList<BookUnknownWord> LoadUnknowns(string bookId)
    {
        Initialize();
        using SqliteConnection connection = Open();
        using SqliteCommand command = connection.CreateCommand();
        command.CommandText = "SELECT book_id,stable_entry_id,source_sentence_id,added_utc FROM book_unknown_capture WHERE book_id=$book ORDER BY added_utc,stable_entry_id";
        command.Parameters.AddWithValue("$book", bookId);
        using SqliteDataReader reader = command.ExecuteReader();
        var result = new List<BookUnknownWord>();
        while (reader.Read()) result.Add(new BookUnknownWord(reader.GetString(0), reader.GetString(1), reader.GetString(2), DateTimeOffset.Parse(reader.GetString(3))));
        return result;
    }

    private SqliteConnection Open()
    {
        var builder = new SqliteConnectionStringBuilder { DataSource = _databasePath, Mode = SqliteOpenMode.ReadWriteCreate, Cache = SqliteCacheMode.Shared };
        var connection = new SqliteConnection(builder.ToString());
        connection.Open();
        using SqliteCommand pragma = connection.CreateCommand();
        pragma.CommandText = "PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000;";
        pragma.ExecuteNonQuery();
        return connection;
    }
}
