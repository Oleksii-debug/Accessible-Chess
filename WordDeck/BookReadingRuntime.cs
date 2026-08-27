using Microsoft.Data.Sqlite;

namespace WordDeck;

internal static class BookReadingDocumentLoader
{
    public static BookDocument? Load(string databasePath, string bookId)
    {
        using SqliteConnection connection = OpenReadOnly(databasePath);
        string? sourceId;
        string? displayName;
        BookSourceFormat format;
        BookExtractionQuality quality;
        string? provenance;
        string? sha;
        string? original;
        string? normalized;
        bool privateOnly;
        using (SqliteCommand command = connection.CreateCommand())
        {
            command.CommandText = "SELECT source_id,display_name,source_format,extraction_quality,provenance,content_sha256,original_text,normalized_text,private_local_only FROM book_document WHERE book_id=$book";
            command.Parameters.AddWithValue("$book", bookId);
            using SqliteDataReader reader = command.ExecuteReader();
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

        var chapterRows = new List<(string Id, int Ordinal, string Title, long Start, long End)>();
        using (SqliteCommand command = connection.CreateCommand())
        {
            command.CommandText = "SELECT chapter_id,chapter_ordinal,title,start_offset,end_offset FROM book_chapter WHERE book_id=$book ORDER BY chapter_ordinal";
            command.Parameters.AddWithValue("$book", bookId);
            using SqliteDataReader reader = command.ExecuteReader();
            while (reader.Read())
                chapterRows.Add((reader.GetString(0), reader.GetInt32(1), reader.GetString(2), reader.GetInt64(3), reader.GetInt64(4)));
        }

        var chapters = new List<BookChapterRecord>(chapterRows.Count);
        foreach (var chapter in chapterRows)
        {
            var sentences = new List<BookSentenceRecord>();
            using SqliteCommand command = connection.CreateCommand();
            command.CommandText = "SELECT sentence_id,sentence_ordinal,start_offset,end_offset,sentence_text,stable_entry_ids FROM book_sentence WHERE chapter_id=$chapter ORDER BY sentence_ordinal";
            command.Parameters.AddWithValue("$chapter", chapter.Id);
            using SqliteDataReader reader = command.ExecuteReader();
            while (reader.Read())
            {
                string[] ids = reader.GetString(5).Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
                sentences.Add(new BookSentenceRecord(
                    reader.GetString(0),
                    chapter.Id,
                    reader.GetInt32(1),
                    new BookTextSpan(reader.GetInt64(2), reader.GetInt64(3)),
                    reader.GetString(4),
                    ids));
            }
            chapters.Add(new BookChapterRecord(chapter.Id, chapter.Ordinal, chapter.Title, new BookTextSpan(chapter.Start, chapter.End), sentences));
        }

        var document = new BookDocument(bookId, sourceId!, displayName!, format, quality, provenance!, sha!, original!, normalized!, chapters, privateOnly);
        document.Validate();
        return document;
    }

    private static SqliteConnection OpenReadOnly(string databasePath)
    {
        var builder = new SqliteConnectionStringBuilder
        {
            DataSource = Path.GetFullPath(databasePath),
            Mode = SqliteOpenMode.ReadOnly,
            Cache = SqliteCacheMode.Private,
            Pooling = false
        };
        var connection = new SqliteConnection(builder.ToString());
        connection.Open();
        using SqliteCommand pragma = connection.CreateCommand();
        pragma.CommandText = "PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000;";
        pragma.ExecuteNonQuery();
        return connection;
    }
}

/// <summary>
/// Natural target lookup for private book sentences. Distinct target IDs must
/// be satisfiable by distinct physical lexical occurrences. In addition, every
/// target occurrence must map to exactly one stable dictionary ID. Unresolved
/// homographs are therefore preserved for reading/capture choice but are never
/// reused as if they were verified context for a specific stable lexical sense.
/// </summary>
internal static class BookReadingContextQuery
{
    public static IReadOnlyList<BookSentenceExport> FindByTargets(
        string databasePath,
        IReadOnlyCollection<string> stableEntryIds,
        int maxResults = 200)
    {
        string[] targets = stableEntryIds
            .Where(value => !string.IsNullOrWhiteSpace(value))
            .Select(value => value.Trim().ToLowerInvariant())
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(value => value, StringComparer.Ordinal)
            .ToArray();
        if (targets.Length == 0) return Array.Empty<BookSentenceExport>();
        if (targets.Length > BookReadingCorpusIndex.MaximumTargetCount)
            throw new ArgumentOutOfRangeException(nameof(stableEntryIds), "Private book context lookup supports one, two or three target IDs.");
        if (maxResults is < 1 or > BookReadingCorpusIndex.MaximumQueryResults)
            throw new ArgumentOutOfRangeException(nameof(maxResults));

        using SqliteConnection connection = OpenReadOnly(databasePath);
        using SqliteCommand command = connection.CreateCommand();
        for (int i = 0; i < targets.Length; i++) command.Parameters.AddWithValue("$t" + i, targets[i]);
        command.Parameters.AddWithValue("$limit", maxResults);

        const string UniqueOccurrence0 = "(SELECT COUNT(*) FROM book_occurrence_entry u0 WHERE u0.sentence_id=e0.sentence_id AND u0.occurrence_ordinal=e0.occurrence_ordinal)=1";
        const string UniqueOccurrence1 = "(SELECT COUNT(*) FROM book_occurrence_entry u1 WHERE u1.sentence_id=e1.sentence_id AND u1.occurrence_ordinal=e1.occurrence_ordinal)=1";
        const string UniqueOccurrence2 = "(SELECT COUNT(*) FROM book_occurrence_entry u2 WHERE u2.sentence_id=e2.sentence_id AND u2.occurrence_ordinal=e2.occurrence_ordinal)=1";

        string matchedSql = targets.Length switch
        {
            1 => $"SELECT DISTINCT e0.sentence_id FROM book_occurrence_entry e0 WHERE e0.stable_entry_id=$t0 AND {UniqueOccurrence0} ORDER BY e0.sentence_id LIMIT $limit",
            2 => $"""
                SELECT DISTINCT e0.sentence_id
                FROM book_occurrence_entry e0
                JOIN book_occurrence_entry e1
                  ON e1.sentence_id=e0.sentence_id
                 AND e1.occurrence_ordinal<>e0.occurrence_ordinal
                WHERE e0.stable_entry_id=$t0 AND e1.stable_entry_id=$t1
                  AND {UniqueOccurrence0} AND {UniqueOccurrence1}
                ORDER BY e0.sentence_id LIMIT $limit
                """,
            3 => $"""
                SELECT DISTINCT e0.sentence_id
                FROM book_occurrence_entry e0
                JOIN book_occurrence_entry e1
                  ON e1.sentence_id=e0.sentence_id
                 AND e1.occurrence_ordinal<>e0.occurrence_ordinal
                JOIN book_occurrence_entry e2
                  ON e2.sentence_id=e0.sentence_id
                 AND e2.occurrence_ordinal<>e0.occurrence_ordinal
                 AND e2.occurrence_ordinal<>e1.occurrence_ordinal
                WHERE e0.stable_entry_id=$t0 AND e1.stable_entry_id=$t1 AND e2.stable_entry_id=$t2
                  AND {UniqueOccurrence0} AND {UniqueOccurrence1} AND {UniqueOccurrence2}
                ORDER BY e0.sentence_id LIMIT $limit
                """,
            _ => throw new InvalidOperationException()
        };
        command.CommandText = $"""
            WITH matched AS ({matchedSql})
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
                throw new InvalidDataException("Private book context query encountered a non-private source row.");
            string[] ids = reader.GetString(7).Split('\n', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
            result.Add(new BookSentenceExport(
                reader.GetString(0), reader.GetString(1), reader.GetString(2), reader.GetString(3),
                reader.GetInt64(4), reader.GetInt64(5), reader.GetString(6), ids, true));
        }
        return result;
    }

    private static SqliteConnection OpenReadOnly(string databasePath)
    {
        var builder = new SqliteConnectionStringBuilder
        {
            DataSource = Path.GetFullPath(databasePath),
            Mode = SqliteOpenMode.ReadOnly,
            Cache = SqliteCacheMode.Private,
            Pooling = false
        };
        var connection = new SqliteConnection(builder.ToString());
        connection.Open();
        using SqliteCommand pragma = connection.CreateCommand();
        pragma.CommandText = "PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000;";
        pragma.ExecuteNonQuery();
        return connection;
    }
}
