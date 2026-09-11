using Microsoft.Data.Sqlite;

namespace WordDeck;

internal sealed record BookCatalogItem(
    string BookId,
    string DisplayName,
    BookSourceFormat Format,
    BookExtractionQuality ExtractionQuality,
    string ContentSha256,
    bool PrivateLocalOnly);

internal sealed record BookCoverageSummary(
    string BookId,
    int PhysicalLexicalCount,
    int Known,
    int Learning,
    int New,
    int OffList,
    double FamiliarityPercent,
    double DifficultyScore);

internal sealed record BookParagraphLocation(
    string BookId,
    string ChapterId,
    int ParagraphOrdinal,
    long StartOffset,
    long EndOffset);

/// <summary>
/// Supplemental, rebuildable indexes over the private book database. The base
/// BookReadingStateStore remains the durable source of imported text/progress;
/// these tables make large-book paragraph navigation, lexical accounting and
/// 1/2/3-target sentence lookup bounded without loading whole books into RAM.
/// </summary>
internal sealed class BookReadingCorpusIndex
{
    public const int MaximumTargetCount = 3;
    public const int MaximumQueryResults = 4096;
    private readonly string _databasePath;

    public BookReadingCorpusIndex(string databasePath)
    {
        if (string.IsNullOrWhiteSpace(databasePath))
            throw new ArgumentException("Book-reading SQLite path is required.", nameof(databasePath));
        _databasePath = Path.GetFullPath(databasePath);
    }

    public void Initialize()
    {
        string? directory = Path.GetDirectoryName(_databasePath);
        if (!string.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);
        using SqliteConnection connection = Open();
        using SqliteCommand command = connection.CreateCommand();
        command.CommandText = """
            CREATE TABLE IF NOT EXISTS book_paragraph_index (
                book_id TEXT NOT NULL REFERENCES book_document(book_id) ON DELETE CASCADE,
                chapter_id TEXT NOT NULL REFERENCES book_chapter(chapter_id) ON DELETE CASCADE,
                paragraph_ordinal INTEGER NOT NULL,
                start_offset INTEGER NOT NULL,
                end_offset INTEGER NOT NULL,
                PRIMARY KEY(book_id, chapter_id, paragraph_ordinal)
            );
            CREATE INDEX IF NOT EXISTS ix_book_paragraph_span
                ON book_paragraph_index(book_id, chapter_id, start_offset, end_offset);

            CREATE TABLE IF NOT EXISTS book_sentence_target_index (
                sentence_id TEXT NOT NULL REFERENCES book_sentence(sentence_id) ON DELETE CASCADE,
                stable_entry_id TEXT NOT NULL,
                PRIMARY KEY(sentence_id, stable_entry_id)
            );
            CREATE INDEX IF NOT EXISTS ix_book_sentence_target_entry
                ON book_sentence_target_index(stable_entry_id, sentence_id);

            CREATE TABLE IF NOT EXISTS book_lexical_occurrence (
                sentence_id TEXT NOT NULL REFERENCES book_sentence(sentence_id) ON DELETE CASCADE,
                occurrence_ordinal INTEGER NOT NULL,
                start_offset INTEGER NOT NULL,
                end_offset INTEGER NOT NULL,
                surface TEXT NOT NULL,
                normalized_form TEXT NOT NULL,
                PRIMARY KEY(sentence_id, occurrence_ordinal)
            );
            CREATE INDEX IF NOT EXISTS ix_book_occurrence_span
                ON book_lexical_occurrence(sentence_id, start_offset, end_offset);

            CREATE TABLE IF NOT EXISTS book_occurrence_entry (
                sentence_id TEXT NOT NULL,
                occurrence_ordinal INTEGER NOT NULL,
                stable_entry_id TEXT NOT NULL,
                PRIMARY KEY(sentence_id, occurrence_ordinal, stable_entry_id),
                FOREIGN KEY(sentence_id, occurrence_ordinal)
                    REFERENCES book_lexical_occurrence(sentence_id, occurrence_ordinal) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS ix_book_occurrence_entry_id
                ON book_occurrence_entry(stable_entry_id, sentence_id, occurrence_ordinal);
            """;
        command.ExecuteNonQuery();
    }

    public void Rebuild(BookDocument document, BookLexicalFormIndex lexicon)
    {
        ArgumentNullException.ThrowIfNull(document);
        ArgumentNullException.ThrowIfNull(lexicon);
        document.Validate();
        Initialize();

        using SqliteConnection connection = Open();
        using SqliteTransaction transaction = connection.BeginTransaction();
        try
        {
            DeleteBookIndexes(connection, transaction, document.BookId);
            foreach (BookChapterRecord chapter in document.Chapters.OrderBy(item => item.ChapterOrdinal))
            {
                foreach (BookParagraphLocation paragraph in BuildParagraphs(document, chapter))
                    InsertParagraph(connection, transaction, paragraph);

                foreach (BookSentenceRecord sentence in chapter.Sentences.OrderBy(item => item.SentenceOrdinal))
                {
                    foreach (string entryId in sentence.StableEntryIds.Distinct(StringComparer.OrdinalIgnoreCase))
                        InsertSentenceTarget(connection, transaction, sentence.SentenceId, entryId);
                    foreach (BookPhysicalOccurrence occurrence in lexicon.AnalyzeSentence(sentence))
                        InsertOccurrence(connection, transaction, occurrence);
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

    public IReadOnlyList<BookSentenceExport> FindSentencesByStableIds(
        IReadOnlyCollection<string> stableEntryIds,
        int maxResults = 200)
    {
        string[] requested = NormalizeTargetIds(stableEntryIds);
        if (requested.Length == 0) return Array.Empty<BookSentenceExport>();
        if (requested.Length > MaximumTargetCount)
            throw new ArgumentOutOfRangeException(nameof(stableEntryIds), "Book sentence lookup supports one, two, or three target stable IDs.");
        if (maxResults is < 1 or > MaximumQueryResults)
            throw new ArgumentOutOfRangeException(nameof(maxResults), $"Book sentence lookup supports 1..{MaximumQueryResults} results.");
        Initialize();

        using SqliteConnection connection = Open();
        using SqliteCommand command = connection.CreateCommand();
        var placeholders = new List<string>();
        for (int i = 0; i < requested.Length; i++)
        {
            string parameter = "$target" + i;
            placeholders.Add(parameter);
            command.Parameters.AddWithValue(parameter, requested[i]);
        }
        command.Parameters.AddWithValue("$required", requested.Length);
        command.Parameters.AddWithValue("$limit", maxResults);
        command.CommandText = $"""
            WITH matched AS (
                SELECT sentence_id
                FROM book_sentence_target_index
                WHERE stable_entry_id IN ({string.Join(',', placeholders)})
                GROUP BY sentence_id
                HAVING COUNT(DISTINCT stable_entry_id) = $required
                ORDER BY sentence_id
                LIMIT $limit
            )
            SELECT d.book_id,d.source_id,c.chapter_id,s.sentence_id,s.start_offset,s.end_offset,s.sentence_text,s.stable_entry_ids,d.private_local_only
            FROM matched m
            JOIN book_sentence s ON s.sentence_id=m.sentence_id
            JOIN book_chapter c ON c.chapter_id=s.chapter_id
            JOIN book_document d ON d.book_id=c.book_id
            ORDER BY d.book_id,c.chapter_ordinal,s.sentence_ordinal;
            """;
        using SqliteDataReader reader = command.ExecuteReader();
        var result = new List<BookSentenceExport>();
        while (reader.Read())
        {
            if (reader.GetInt32(8) != 1)
                throw new InvalidDataException("A non-private book row was encountered in the local corpus index.");
            string[] ids = reader.GetString(7).Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
            result.Add(new BookSentenceExport(
                reader.GetString(0),
                reader.GetString(1),
                reader.GetString(2),
                reader.GetString(3),
                reader.GetInt64(4),
                reader.GetInt64(5),
                reader.GetString(6),
                ids,
                true));
        }
        return result;
    }

    public BookCoverageSummary GetCoverageSummary(
        string bookId,
        IReadOnlyCollection<string>? knownEntryIds,
        IReadOnlyCollection<string>? learningEntryIds)
    {
        Initialize();
        using SqliteConnection connection = Open();
        CreateTemporaryVocabularyTable(connection, "temp_known", knownEntryIds);
        CreateTemporaryVocabularyTable(connection, "temp_learning", learningEntryIds);
        using SqliteCommand command = connection.CreateCommand();
        command.CommandText = """
            WITH classified AS (
                SELECT o.sentence_id,o.occurrence_ordinal,
                    CASE WHEN EXISTS (
                        SELECT 1 FROM book_occurrence_entry oe JOIN temp_known k ON k.id=oe.stable_entry_id
                        WHERE oe.sentence_id=o.sentence_id AND oe.occurrence_ordinal=o.occurrence_ordinal
                    ) THEN 1 ELSE 0 END AS is_known,
                    CASE WHEN EXISTS (
                        SELECT 1 FROM book_occurrence_entry oe JOIN temp_learning l ON l.id=oe.stable_entry_id
                        WHERE oe.sentence_id=o.sentence_id AND oe.occurrence_ordinal=o.occurrence_ordinal
                    ) THEN 1 ELSE 0 END AS is_learning,
                    CASE WHEN EXISTS (
                        SELECT 1 FROM book_occurrence_entry oe
                        WHERE oe.sentence_id=o.sentence_id AND oe.occurrence_ordinal=o.occurrence_ordinal
                    ) THEN 0 ELSE 1 END AS is_off_list
                FROM book_lexical_occurrence o
                JOIN book_sentence s ON s.sentence_id=o.sentence_id
                JOIN book_chapter c ON c.chapter_id=s.chapter_id
                WHERE c.book_id=$book
            )
            SELECT COUNT(*),
                   COALESCE(SUM(is_known),0),
                   COALESCE(SUM(CASE WHEN is_known=0 AND is_learning=1 THEN 1 ELSE 0 END),0),
                   COALESCE(SUM(is_off_list),0)
            FROM classified;
            """;
        command.Parameters.AddWithValue("$book", bookId);
        using SqliteDataReader reader = command.ExecuteReader();
        if (!reader.Read()) return new BookCoverageSummary(bookId, 0, 0, 0, 0, 0, 100.0, 0.0);
        int total = reader.GetInt32(0);
        int known = reader.GetInt32(1);
        int learning = reader.GetInt32(2);
        int offList = reader.GetInt32(3);
        int @new = Math.Max(0, total - known - learning);
        double familiarity = total == 0 ? 100.0 : known * 100.0 / total;
        double difficulty = total == 0 ? 0.0 : (@new + learning * 0.35) * 100.0 / total;
        return new BookCoverageSummary(bookId, total, known, learning, @new, offList, familiarity, difficulty);
    }

    public IReadOnlyList<BookPhysicalOccurrence> LoadSentenceOccurrences(
        string sentenceId,
        IReadOnlyCollection<string>? knownEntryIds = null,
        IReadOnlyCollection<string>? learningEntryIds = null)
    {
        Initialize();
        var known = new HashSet<string>(NormalizeTargetIds(knownEntryIds ?? Array.Empty<string>()), StringComparer.OrdinalIgnoreCase);
        var learning = new HashSet<string>(NormalizeTargetIds(learningEntryIds ?? Array.Empty<string>()), StringComparer.OrdinalIgnoreCase);
        learning.ExceptWith(known);
        using SqliteConnection connection = Open();
        using SqliteCommand command = connection.CreateCommand();
        command.CommandText = """
            SELECT o.occurrence_ordinal,o.start_offset,o.end_offset,o.surface,o.normalized_form,
                   GROUP_CONCAT(oe.stable_entry_id, char(10))
            FROM book_lexical_occurrence o
            LEFT JOIN book_occurrence_entry oe
              ON oe.sentence_id=o.sentence_id AND oe.occurrence_ordinal=o.occurrence_ordinal
            WHERE o.sentence_id=$sentence
            GROUP BY o.occurrence_ordinal,o.start_offset,o.end_offset,o.surface,o.normalized_form
            ORDER BY o.occurrence_ordinal;
            """;
        command.Parameters.AddWithValue("$sentence", sentenceId);
        using SqliteDataReader reader = command.ExecuteReader();
        var result = new List<BookPhysicalOccurrence>();
        while (reader.Read())
        {
            string[] ids = reader.IsDBNull(5)
                ? Array.Empty<string>()
                : reader.GetString(5).Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
            BookWordState state = ids.Any(known.Contains)
                ? BookWordState.Known
                : ids.Any(learning.Contains) ? BookWordState.Learning : BookWordState.New;
            result.Add(new BookPhysicalOccurrence(
                sentenceId,
                reader.GetInt32(0),
                reader.GetInt64(1),
                reader.GetInt64(2),
                reader.GetString(3),
                reader.GetString(4),
                ids,
                state));
        }
        return result;
    }

    public IReadOnlyList<BookParagraphLocation> LoadParagraphs(string bookId, string chapterId)
    {
        Initialize();
        using SqliteConnection connection = Open();
        using SqliteCommand command = connection.CreateCommand();
        command.CommandText = "SELECT book_id,chapter_id,paragraph_ordinal,start_offset,end_offset FROM book_paragraph_index WHERE book_id=$book AND chapter_id=$chapter ORDER BY paragraph_ordinal";
        command.Parameters.AddWithValue("$book", bookId);
        command.Parameters.AddWithValue("$chapter", chapterId);
        using SqliteDataReader reader = command.ExecuteReader();
        var result = new List<BookParagraphLocation>();
        while (reader.Read())
            result.Add(new BookParagraphLocation(reader.GetString(0), reader.GetString(1), reader.GetInt32(2), reader.GetInt64(3), reader.GetInt64(4)));
        return result;
    }

    public IReadOnlyList<BookCatalogItem> ListBooks()
    {
        Initialize();
        using SqliteConnection connection = Open();
        using SqliteCommand command = connection.CreateCommand();
        command.CommandText = "SELECT book_id,display_name,source_format,extraction_quality,content_sha256,private_local_only FROM book_document ORDER BY display_name,book_id";
        using SqliteDataReader reader = command.ExecuteReader();
        var result = new List<BookCatalogItem>();
        while (reader.Read())
            result.Add(new BookCatalogItem(reader.GetString(0), reader.GetString(1), (BookSourceFormat)reader.GetInt32(2), (BookExtractionQuality)reader.GetInt32(3), reader.GetString(4), reader.GetInt32(5) == 1));
        return result;
    }

    public BookDocument? LoadDocument(string bookId)
    {
        Initialize();
        using SqliteConnection connection = Open();
        string? sourceId = null;
        string? displayName = null;
        BookSourceFormat format = default;
        BookExtractionQuality quality = default;
        string? provenance = null;
        string? sha = null;
        string? original = null;
        string? normalized = null;
        bool privateOnly = false;
        using (SqliteCommand documentCommand = connection.CreateCommand())
        {
            documentCommand.CommandText = "SELECT source_id,display_name,source_format,extraction_quality,provenance,content_sha256,original_text,normalized_text,private_local_only FROM book_document WHERE book_id=$book";
            documentCommand.Parameters.AddWithValue("$book", bookId);
            using SqliteDataReader reader = documentCommand.ExecuteReader();
            if (!reader.Read()) return null;
            sourceId = reader.GetString(0);
            displayName = reader.GetString(1);
            format = (BookSourceFormat)reader.GetInt32(2);
            quality = (BookExtractionQuality)reader.GetInt32(3);
            provenance = reader.GetString(4);
            sha = reader.GetString(5);
            original = reader.GetString(6);
            normalized = reader.GetString(7);
            privateOnly = reader.GetInt32(8) == 1;
        }

        var chapters = new List<BookChapterRecord>();
        using SqliteCommand chapterCommand = connection.CreateCommand();
        chapterCommand.CommandText = "SELECT chapter_id,chapter_ordinal,title,start_offset,end_offset FROM book_chapter WHERE book_id=$book ORDER BY chapter_ordinal";
        chapterCommand.Parameters.AddWithValue("$book", bookId);
        using SqliteDataReader chapterReader = chapterCommand.ExecuteReader();
        while (chapterReader.Read())
        {
            string chapterId = chapterReader.GetString(0);
            var sentences = new List<BookSentenceRecord>();
            using SqliteCommand sentenceCommand = connection.CreateCommand();
            sentenceCommand.CommandText = "SELECT sentence_id,sentence_ordinal,start_offset,end_offset,sentence_text,stable_entry_ids FROM book_sentence WHERE chapter_id=$chapter ORDER BY sentence_ordinal";
            sentenceCommand.Parameters.AddWithValue("$chapter", chapterId);
            using SqliteDataReader sentenceReader = sentenceCommand.ExecuteReader();
            while (sentenceReader.Read())
            {
                string[] ids = sentenceReader.GetString(5).Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
                sentences.Add(new BookSentenceRecord(
                    sentenceReader.GetString(0),
                    chapterId,
                    sentenceReader.GetInt32(1),
                    new BookTextSpan(sentenceReader.GetInt64(2), sentenceReader.GetInt64(3)),
                    sentenceReader.GetString(4),
                    ids));
            }
            chapters.Add(new BookChapterRecord(
                chapterId,
                chapterReader.GetInt32(1),
                chapterReader.GetString(2),
                new BookTextSpan(chapterReader.GetInt64(3), chapterReader.GetInt64(4)),
                sentences));
        }
        var document = new BookDocument(bookId, sourceId!, displayName!, format, quality, provenance!, sha!, original!, normalized!, chapters, privateOnly);
        document.Validate();
        return document;
    }

    private static IReadOnlyList<BookParagraphLocation> BuildParagraphs(BookDocument document, BookChapterRecord chapter)
    {
        string chapterText = document.NormalizedText[(int)chapter.Span.StartOffset..(int)chapter.Span.EndOffset];
        var result = new List<BookParagraphLocation>();
        int local = 0;
        int ordinal = 0;
        while (local < chapterText.Length)
        {
            while (local < chapterText.Length && chapterText[local] == '\n') local++;
            if (local >= chapterText.Length) break;
            int separator = chapterText.IndexOf("\n\n", local, StringComparison.Ordinal);
            int end = separator < 0 ? chapterText.Length : separator;
            while (end > local && char.IsWhiteSpace(chapterText[end - 1])) end--;
            if (end > local)
                result.Add(new BookParagraphLocation(document.BookId, chapter.ChapterId, ordinal++, chapter.Span.StartOffset + local, chapter.Span.StartOffset + end));
            local = separator < 0 ? chapterText.Length : separator + 2;
        }
        return result;
    }

    private static void InsertParagraph(SqliteConnection connection, SqliteTransaction transaction, BookParagraphLocation paragraph)
    {
        using SqliteCommand command = connection.CreateCommand();
        command.Transaction = transaction;
        command.CommandText = "INSERT INTO book_paragraph_index(book_id,chapter_id,paragraph_ordinal,start_offset,end_offset) VALUES($book,$chapter,$ordinal,$start,$end)";
        command.Parameters.AddWithValue("$book", paragraph.BookId);
        command.Parameters.AddWithValue("$chapter", paragraph.ChapterId);
        command.Parameters.AddWithValue("$ordinal", paragraph.ParagraphOrdinal);
        command.Parameters.AddWithValue("$start", paragraph.StartOffset);
        command.Parameters.AddWithValue("$end", paragraph.EndOffset);
        command.ExecuteNonQuery();
    }

    private static void InsertSentenceTarget(SqliteConnection connection, SqliteTransaction transaction, string sentenceId, string entryId)
    {
        using SqliteCommand command = connection.CreateCommand();
        command.Transaction = transaction;
        command.CommandText = "INSERT OR IGNORE INTO book_sentence_target_index(sentence_id,stable_entry_id) VALUES($sentence,$entry)";
        command.Parameters.AddWithValue("$sentence", sentenceId);
        command.Parameters.AddWithValue("$entry", entryId.Trim().ToLowerInvariant());
        command.ExecuteNonQuery();
    }

    private static void InsertOccurrence(SqliteConnection connection, SqliteTransaction transaction, BookPhysicalOccurrence occurrence)
    {
        using (SqliteCommand command = connection.CreateCommand())
        {
            command.Transaction = transaction;
            command.CommandText = "INSERT INTO book_lexical_occurrence(sentence_id,occurrence_ordinal,start_offset,end_offset,surface,normalized_form) VALUES($sentence,$ordinal,$start,$end,$surface,$form)";
            command.Parameters.AddWithValue("$sentence", occurrence.SentenceId);
            command.Parameters.AddWithValue("$ordinal", occurrence.OccurrenceOrdinal);
            command.Parameters.AddWithValue("$start", occurrence.StartOffset);
            command.Parameters.AddWithValue("$end", occurrence.EndOffset);
            command.Parameters.AddWithValue("$surface", occurrence.Surface);
            command.Parameters.AddWithValue("$form", occurrence.NormalizedForm);
            command.ExecuteNonQuery();
        }
        foreach (string entryId in occurrence.StableEntryIds.Distinct(StringComparer.OrdinalIgnoreCase))
        {
            using SqliteCommand command = connection.CreateCommand();
            command.Transaction = transaction;
            command.CommandText = "INSERT OR IGNORE INTO book_occurrence_entry(sentence_id,occurrence_ordinal,stable_entry_id) VALUES($sentence,$ordinal,$entry)";
            command.Parameters.AddWithValue("$sentence", occurrence.SentenceId);
            command.Parameters.AddWithValue("$ordinal", occurrence.OccurrenceOrdinal);
            command.Parameters.AddWithValue("$entry", entryId.Trim().ToLowerInvariant());
            command.ExecuteNonQuery();
        }
    }

    private static void DeleteBookIndexes(SqliteConnection connection, SqliteTransaction transaction, string bookId)
    {
        using SqliteCommand command = connection.CreateCommand();
        command.Transaction = transaction;
        command.CommandText = """
            DELETE FROM book_lexical_occurrence WHERE sentence_id IN (
                SELECT s.sentence_id FROM book_sentence s JOIN book_chapter c ON c.chapter_id=s.chapter_id WHERE c.book_id=$book
            );
            DELETE FROM book_sentence_target_index WHERE sentence_id IN (
                SELECT s.sentence_id FROM book_sentence s JOIN book_chapter c ON c.chapter_id=s.chapter_id WHERE c.book_id=$book
            );
            DELETE FROM book_paragraph_index WHERE book_id=$book;
            """;
        command.Parameters.AddWithValue("$book", bookId);
        command.ExecuteNonQuery();
    }

    private static void CreateTemporaryVocabularyTable(SqliteConnection connection, string tableName, IEnumerable<string>? values)
    {
        using (SqliteCommand command = connection.CreateCommand())
        {
            command.CommandText = $"CREATE TEMP TABLE IF NOT EXISTS {tableName}(id TEXT PRIMARY KEY); DELETE FROM {tableName};";
            command.ExecuteNonQuery();
        }
        foreach (string id in NormalizeTargetIds(values ?? Array.Empty<string>()))
        {
            using SqliteCommand insert = connection.CreateCommand();
            insert.CommandText = $"INSERT OR IGNORE INTO {tableName}(id) VALUES($id)";
            insert.Parameters.AddWithValue("$id", id);
            insert.ExecuteNonQuery();
        }
    }

    private static string[] NormalizeTargetIds(IEnumerable<string> values) => values
        .Where(value => !string.IsNullOrWhiteSpace(value))
        .Select(value => value.Trim().ToLowerInvariant())
        .Distinct(StringComparer.OrdinalIgnoreCase)
        .OrderBy(value => value, StringComparer.Ordinal)
        .ToArray();

    private SqliteConnection Open()
    {
        var builder = new SqliteConnectionStringBuilder
        {
            DataSource = _databasePath,
            Mode = SqliteOpenMode.ReadWriteCreate,
            Cache = SqliteCacheMode.Shared,
            Pooling = false
        };
        var connection = new SqliteConnection(builder.ToString());
        connection.Open();
        using SqliteCommand pragma = connection.CreateCommand();
        pragma.CommandText = "PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000; PRAGMA journal_mode=WAL;";
        pragma.ExecuteNonQuery();
        return connection;
    }
}
