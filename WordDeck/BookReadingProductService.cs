using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Xml;

namespace WordDeck;

internal sealed record BookDeckVocabularySnapshot(
    IReadOnlySet<string> KnownEntryIds,
    IReadOnlySet<string> LearningEntryIds,
    string KnownDeckId,
    string LearningDeckId);

internal sealed record BookImportProductResult(
    BookDocument Document,
    string PrivateSourcePath,
    BookCoverageSummary Coverage,
    int ParagraphCount,
    string PrivacyStatement,
    string ExtractionStatement);

/// <summary>
/// Product boundary for private local reading. No method in this service uploads
/// book bytes or paths. Exact source bytes are retained under LOCALAPPDATA so
/// HTML/EPUB normalization never destroys the user's original file.
/// </summary>
internal sealed class BookReadingProductService
{
    public const long MaximumSourceBytes = 128L * 1024 * 1024;
    public const long MaximumEpubExpandedBytes = 384L * 1024 * 1024;
    public const long MaximumEpubEntryBytes = 48L * 1024 * 1024;
    public const int MaximumEpubEntries = 20000;
    public const long MaximumCompressionRatio = 500;

    private readonly string _root;
    private readonly string _sourceDirectory;
    private readonly string _databasePath;
    private readonly BookReadingStateStore _stateStore;
    private readonly BookReadingCorpusIndex _corpusIndex;

    public string DatabasePath => _databasePath;
    public string PrivateRoot => _root;

    public BookReadingProductService()
        : this(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WordDeck", "Reading"))
    {
    }

    internal BookReadingProductService(string root)
    {
        if (string.IsNullOrWhiteSpace(root))
            throw new ArgumentException("Book-reading private root is required.", nameof(root));
        _root = Path.GetFullPath(root);
        _sourceDirectory = Path.Combine(_root, "Sources");
        _databasePath = Path.Combine(_root, "books.sqlite");
        Directory.CreateDirectory(_root);
        Directory.CreateDirectory(_sourceDirectory);
        _stateStore = new BookReadingStateStore(_databasePath);
        _corpusIndex = new BookReadingCorpusIndex(_databasePath);
        _stateStore.Initialize();
        _corpusIndex.Initialize();
    }

    public BookImportProductResult ImportFile(
        string path,
        DictionaryPackage dictionary,
        BookDeckVocabularySnapshot vocabulary)
    {
        if (string.IsNullOrWhiteSpace(path)) throw new ArgumentException("Book file path is required.", nameof(path));
        string fullPath = Path.GetFullPath(path);
        string extension = Path.GetExtension(fullPath).ToLowerInvariant();
        BookSourceFormat format = extension switch
        {
            ".txt" => BookSourceFormat.Txt,
            ".htm" or ".html" => BookSourceFormat.Html,
            ".epub" => BookSourceFormat.Epub,
            ".pdf" => throw new InvalidDataException("WordDeck does not silently extract PDF files. Export/extract the PDF to text first, then use the explicit PDF-derived text import so extraction quality is stated truthfully."),
            _ => throw new InvalidDataException("Supported local book formats are TXT, HTML and EPUB. PDF requires explicitly extracted text.")
        };
        byte[] bytes = ReadBounded(fullPath);
        return ImportBytes(
            Path.GetFileName(fullPath),
            format,
            bytes,
            dictionary,
            vocabulary,
            format switch
            {
                BookSourceFormat.Txt => BookExtractionQuality.NativeText,
                BookSourceFormat.Html => BookExtractionQuality.StructuredHtml,
                BookSourceFormat.Epub => BookExtractionQuality.EpubSpine,
                _ => throw new InvalidOperationException()
            },
            "private local user file; WordDeck does not upload it");
    }

    public BookImportProductResult ImportPdfDerivedTextFile(
        string extractedTextPath,
        DictionaryPackage dictionary,
        BookDeckVocabularySnapshot vocabulary,
        bool extractionReviewed)
    {
        if (string.IsNullOrWhiteSpace(extractedTextPath))
            throw new ArgumentException("PDF-derived text path is required.", nameof(extractedTextPath));
        string fullPath = Path.GetFullPath(extractedTextPath);
        byte[] bytes = ReadBounded(fullPath);
        return ImportBytes(
            Path.GetFileName(fullPath),
            BookSourceFormat.PdfDerivedText,
            bytes,
            dictionary,
            vocabulary,
            extractionReviewed ? BookExtractionQuality.PdfDerivedReviewed : BookExtractionQuality.PdfDerivedUnverified,
            extractionReviewed
                ? "private local text explicitly derived from PDF; user marked extraction as reviewed"
                : "private local text explicitly derived from PDF; extraction accuracy is unverified");
    }

    public IReadOnlyList<BookCatalogItem> ListBooks() => _corpusIndex.ListBooks();

    public BookDocument LoadDocument(string bookId) =>
        BookReadingDocumentLoader.Load(_databasePath, bookId)
        ?? throw new FileNotFoundException("The selected private book is no longer present in the WordDeck reading database.");

    public BookCoverageSummary GetCoverage(string bookId, BookDeckVocabularySnapshot vocabulary) =>
        _corpusIndex.GetCoverageSummary(bookId, vocabulary.KnownEntryIds, vocabulary.LearningEntryIds);

    public IReadOnlyList<BookPhysicalOccurrence> GetSentenceOccurrences(string sentenceId, BookDeckVocabularySnapshot vocabulary) =>
        _corpusIndex.LoadSentenceOccurrences(sentenceId, vocabulary.KnownEntryIds, vocabulary.LearningEntryIds);

    public IReadOnlyList<BookSentenceExport> FindBookSentences(IReadOnlyCollection<string> targetStableEntryIds, int maxResults = 200) =>
        BookReadingContextQuery.FindByTargets(_databasePath, targetStableEntryIds, maxResults);

    public IReadOnlyList<BookParagraphLocation> GetParagraphs(string bookId, string chapterId) =>
        _corpusIndex.LoadParagraphs(bookId, chapterId);

    public BookReadingPosition? LoadPosition(string bookId) => _stateStore.LoadPosition(bookId);

    public void SavePosition(BookDocument document, BookSentenceRecord sentence) =>
        _stateStore.SavePosition(document, sentence.ChapterId, sentence.Span.StartOffset, sentence.SentenceId);

    public void CaptureMappedOccurrenceToLearningDeck(
        BookDocument document,
        BookSentenceRecord sentence,
        string stableEntryId,
        AppState appState,
        DictionaryPackage dictionary,
        string learningDeckId)
    {
        ArgumentNullException.ThrowIfNull(document);
        ArgumentNullException.ThrowIfNull(sentence);
        ArgumentNullException.ThrowIfNull(appState);
        ArgumentNullException.ThrowIfNull(dictionary);
        string id = (stableEntryId ?? string.Empty).Trim().ToLowerInvariant();
        if (id.Length == 0) throw new InvalidDataException("A mapped stable dictionary ID is required before adding a word to learning.");
        if (!sentence.StableEntryIds.Contains(id, StringComparer.OrdinalIgnoreCase))
            throw new InvalidDataException("The selected stable ID is not present in the current book sentence. Ambiguous forms must be resolved explicitly before capture.");
        if (!dictionary.Entries.Any(entry => entry.Id.Equals(id, StringComparison.OrdinalIgnoreCase)))
            throw new InvalidDataException("The selected book word does not map to an entry in the active Oxford/user dictionary.");

        var decks = new DeckService(appState);
        if (decks.Find(learningDeckId) is null)
            throw new InvalidDataException("The selected learning deck no longer exists.");
        Dictionary<string, string> assignments = decks.EnsureDictionaryAssignments(dictionary.Id, dictionary.Entries.Select(entry => entry.Id));
        assignments[id] = learningDeckId;
        _stateStore.CaptureUnknown(document, id, sentence.SentenceId);
    }

    public static BookDeckVocabularySnapshot BuildVocabularySnapshot(
        AppState state,
        DictionaryPackage dictionary,
        string knownDeckId,
        string learningDeckId)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(dictionary);
        var deckService = new DeckService(state);
        if (deckService.Find(knownDeckId) is null) throw new InvalidDataException("Selected Known deck does not exist.");
        if (deckService.Find(learningDeckId) is null) throw new InvalidDataException("Selected Learning deck does not exist.");
        if (string.Equals(knownDeckId, learningDeckId, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Known and Learning must use different decks so book familiarity remains meaningful.");

        var known = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var learning = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if (state.DeckIdsByDictionary.TryGetValue(dictionary.Id, out Dictionary<string, string>? assignments))
        {
            foreach ((string entryId, string deckId) in assignments)
            {
                if (deckId.Equals(knownDeckId, StringComparison.OrdinalIgnoreCase)) known.Add(entryId);
                else if (deckId.Equals(learningDeckId, StringComparison.OrdinalIgnoreCase)) learning.Add(entryId);
            }
        }

        // Exact written-form matching cannot determine POS/sense for homographs.
        // Therefore a stable ID that shares its exact lexical form with another
        // dictionary ID is withheld from Known/Learning evidence for Reading.
        // The candidate IDs are still preserved on each physical occurrence and
        // the user can explicitly choose one when capturing a word to Learning.
        HashSet<string> ambiguousEntryIds = dictionary.Entries
            .Where(entry => entry is not null && !string.IsNullOrWhiteSpace(entry.Id) && !string.IsNullOrWhiteSpace(entry.Source))
            .Select(entry => new { Entry = entry, Form = BookLexicalFormIndex.NormalizeForm(entry.Source) })
            .Where(item => item.Form.Length > 0)
            .GroupBy(item => item.Form, StringComparer.OrdinalIgnoreCase)
            .Where(group => group.Select(item => item.Entry.Id).Distinct(StringComparer.OrdinalIgnoreCase).Skip(1).Any())
            .SelectMany(group => group.Select(item => item.Entry.Id.Trim().ToLowerInvariant()))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        known.ExceptWith(ambiguousEntryIds);
        learning.ExceptWith(ambiguousEntryIds);

        return new BookDeckVocabularySnapshot(known, learning, knownDeckId, learningDeckId);
    }

    private BookImportProductResult ImportBytes(
        string displayName,
        BookSourceFormat format,
        byte[] bytes,
        DictionaryPackage dictionary,
        BookDeckVocabularySnapshot vocabulary,
        BookExtractionQuality quality,
        string provenance)
    {
        ArgumentNullException.ThrowIfNull(dictionary);
        ArgumentNullException.ThrowIfNull(vocabulary);
        if (format == BookSourceFormat.Epub) ValidateEpubSafety(bytes);
        string hash = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
        string sourceId = "local-source-" + hash[..24];
        var lexicon = new BookLexicalFormIndex(dictionary);
        var request = new BookImportRequest(sourceId, displayName.Trim(), format, bytes, provenance, quality, true);
        BookDocument document = BookReadingImporter.Import(request, lexicon);

        string privateSource = SavePrivateSource(document, bytes, format);
        bool existedBeforeImport = _corpusIndex.ListBooks().Any(item => item.BookId.Equals(document.BookId, StringComparison.OrdinalIgnoreCase));
        try
        {
            _stateStore.SaveDocument(document);
            _corpusIndex.Rebuild(document, lexicon);
            BookCoverageSummary coverage = _corpusIndex.GetCoverageSummary(document.BookId, vocabulary.KnownEntryIds, vocabulary.LearningEntryIds);
            int paragraphs = document.Chapters.Sum(chapter => _corpusIndex.LoadParagraphs(document.BookId, chapter.ChapterId).Count);
            string extraction = format == BookSourceFormat.PdfDerivedText
                ? quality == BookExtractionQuality.PdfDerivedReviewed
                    ? "PDF-derived text: extraction was explicitly marked reviewed; WordDeck did not parse the PDF itself."
                    : "PDF-derived text: extraction quality is unverified; WordDeck did not parse the PDF itself."
                : $"{format} imported locally with {quality} extraction.";
            return new BookImportProductResult(
                document,
                privateSource,
                coverage,
                paragraphs,
                "Private local book: source bytes and reading database stay under the Windows user profile and are never packaged into the public WordDeck ZIP by this service.",
                extraction);
        }
        catch
        {
            if (!existedBeforeImport)
            {
                try { if (File.Exists(privateSource)) File.Delete(privateSource); } catch { }
            }
            throw;
        }
    }

    private string SavePrivateSource(BookDocument document, byte[] bytes, BookSourceFormat format)
    {
        string extension = format switch
        {
            BookSourceFormat.Txt => ".txt",
            BookSourceFormat.Html => ".html",
            BookSourceFormat.Epub => ".epub",
            BookSourceFormat.PdfDerivedText => ".pdf-derived.txt",
            _ => ".bin"
        };
        string destination = Path.Combine(_sourceDirectory, document.BookId + extension);
        string temp = destination + ".tmp-" + Guid.NewGuid().ToString("N");
        try
        {
            File.WriteAllBytes(temp, bytes);
            string savedHash = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(temp))).ToLowerInvariant();
            if (!savedHash.Equals(document.ContentSha256, StringComparison.Ordinal))
                throw new IOException("Private book source verification failed before commit.");
            File.Move(temp, destination, true);
            return destination;
        }
        finally
        {
            try { if (File.Exists(temp)) File.Delete(temp); } catch { }
        }
    }

    private static byte[] ReadBounded(string fullPath)
    {
        var info = new FileInfo(fullPath);
        if (!info.Exists) throw new FileNotFoundException("Book file was not found.", fullPath);
        if (info.Length <= 0) throw new InvalidDataException("Book file is empty.");
        if (info.Length > MaximumSourceBytes)
            throw new InvalidDataException($"Book file is larger than the {MaximumSourceBytes / (1024 * 1024)} MB local-import safety limit.");
        return File.ReadAllBytes(fullPath);
    }

    internal static void ValidateEpubSafety(byte[] bytes)
    {
        using var archive = new ZipArchive(new MemoryStream(bytes, writable: false), ZipArchiveMode.Read, leaveOpen: false);
        if (archive.Entries.Count == 0) throw new InvalidDataException("EPUB archive is empty.");
        if (archive.Entries.Count > MaximumEpubEntries) throw new InvalidDataException("EPUB contains too many archive entries.");
        long expanded = 0;
        foreach (ZipArchiveEntry entry in archive.Entries)
        {
            ValidateArchivePath(entry.FullName);
            if (entry.Length > MaximumEpubEntryBytes)
                throw new InvalidDataException("EPUB contains an entry larger than the per-entry safety limit.");
            expanded = checked(expanded + entry.Length);
            if (expanded > MaximumEpubExpandedBytes)
                throw new InvalidDataException("EPUB expanded size exceeds the local-import safety limit.");
            if (entry.CompressedLength > 0 && entry.Length > entry.CompressedLength * MaximumCompressionRatio)
                throw new InvalidDataException("EPUB contains a suspiciously high compression-ratio entry.");

            string extension = Path.GetExtension(entry.FullName).ToLowerInvariant();
            if (extension is ".xml" or ".opf" or ".ncx")
                ValidateXmlEntry(entry);
        }
        if (archive.GetEntry("META-INF/container.xml") is null)
            throw new InvalidDataException("EPUB container.xml is missing.");
    }

    private static void ValidateArchivePath(string value)
    {
        if (string.IsNullOrWhiteSpace(value)) return;
        string canonical = value.Replace('\\', '/');
        if (canonical.StartsWith("/", StringComparison.Ordinal) || canonical.Contains(':'))
            throw new InvalidDataException("EPUB contains an absolute/drive-qualified archive path.");
        foreach (string segment in canonical.Split('/', StringSplitOptions.RemoveEmptyEntries))
            if (segment is "..") throw new InvalidDataException("EPUB contains an unsafe traversal path.");
    }

    private static void ValidateXmlEntry(ZipArchiveEntry entry)
    {
        var settings = new XmlReaderSettings
        {
            DtdProcessing = DtdProcessing.Prohibit,
            XmlResolver = null,
            IgnoreComments = true,
            MaxCharactersInDocument = Math.Min(entry.Length + 4096, MaximumEpubEntryBytes + 4096)
        };
        using Stream stream = entry.Open();
        using XmlReader reader = XmlReader.Create(stream, settings);
        while (reader.Read()) { }
    }
}
