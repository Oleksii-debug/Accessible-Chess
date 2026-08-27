using System.IO.Compression;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Xml.Linq;

namespace WordDeck;

internal enum BookSourceFormat
{
    Txt,
    Html,
    Epub,
    PdfDerivedText
}

internal enum BookExtractionQuality
{
    NativeText,
    StructuredHtml,
    EpubSpine,
    PdfDerivedUnverified,
    PdfDerivedReviewed
}

internal sealed record BookImportRequest(
    string SourceId,
    string DisplayName,
    BookSourceFormat Format,
    byte[] Content,
    string Provenance,
    BookExtractionQuality ExtractionQuality,
    bool PrivateLocalOnly = true)
{
    public void Validate()
    {
        RequireCanonical(SourceId, "Book source id");
        RequireCanonical(DisplayName, "Book display name");
        RequireCanonical(Provenance, "Book provenance");
        if (Content is null || Content.Length == 0)
            throw new InvalidDataException("Book import content is empty.");
        if (!PrivateLocalOnly)
            throw new InvalidDataException("User books are private local data by default and this importer never opts them into upload or redistribution.");
        if (Format == BookSourceFormat.PdfDerivedText && ExtractionQuality is not (BookExtractionQuality.PdfDerivedUnverified or BookExtractionQuality.PdfDerivedReviewed))
            throw new InvalidDataException("PDF-derived text must carry an explicit extraction-quality classification.");
        if (Format != BookSourceFormat.PdfDerivedText && ExtractionQuality is BookExtractionQuality.PdfDerivedUnverified or BookExtractionQuality.PdfDerivedReviewed)
            throw new InvalidDataException("PDF extraction quality may only be used for explicitly PDF-derived text.");
    }

    private static void RequireCanonical(string? value, string label)
    {
        if (string.IsNullOrWhiteSpace(value) || !string.Equals(value, value.Trim(), StringComparison.Ordinal))
            throw new InvalidDataException(label + " is required and must be canonical.");
    }
}

internal sealed record BookTextSpan(long StartOffset, long EndOffset)
{
    public void Validate(long length)
    {
        if (StartOffset < 0 || EndOffset < StartOffset || EndOffset > length)
            throw new InvalidDataException("Book text span is outside the normalized text boundary.");
    }
}

internal sealed record BookSentenceRecord(
    string SentenceId,
    string ChapterId,
    int SentenceOrdinal,
    BookTextSpan Span,
    string Text,
    IReadOnlyList<string> StableEntryIds)
{
    public void Validate(long normalizedLength)
    {
        if (string.IsNullOrWhiteSpace(SentenceId) || string.IsNullOrWhiteSpace(ChapterId) || SentenceOrdinal < 0 || string.IsNullOrWhiteSpace(Text))
            throw new InvalidDataException("Book sentence identity/text is invalid.");
        Span.Validate(normalizedLength);
    }
}

internal sealed record BookChapterRecord(
    string ChapterId,
    int ChapterOrdinal,
    string Title,
    BookTextSpan Span,
    IReadOnlyList<BookSentenceRecord> Sentences);

internal sealed record BookDocument(
    string BookId,
    string SourceId,
    string DisplayName,
    BookSourceFormat Format,
    BookExtractionQuality ExtractionQuality,
    string Provenance,
    string ContentSha256,
    string OriginalText,
    string NormalizedText,
    IReadOnlyList<BookChapterRecord> Chapters,
    bool PrivateLocalOnly = true)
{
    public void Validate()
    {
        if (!PrivateLocalOnly)
            throw new InvalidDataException("Imported books must remain private-local in the core model.");
        if (string.IsNullOrWhiteSpace(BookId) || string.IsNullOrWhiteSpace(SourceId) || string.IsNullOrWhiteSpace(ContentSha256))
            throw new InvalidDataException("Book identity is incomplete.");
        if (ContentSha256.Length != 64 || ContentSha256.Any(ch => !Uri.IsHexDigit(ch)))
            throw new InvalidDataException("Book SHA-256 identity is malformed.");
        foreach (BookChapterRecord chapter in Chapters)
        {
            chapter.Span.Validate(NormalizedText.Length);
            foreach (BookSentenceRecord sentence in chapter.Sentences)
                sentence.Validate(NormalizedText.Length);
        }
    }
}

internal interface IBookLexiconMapper
{
    IReadOnlyList<string> MapStableEntryIds(string normalizedSentenceText);
}

internal static class BookReadingImporter
{
    private static readonly Regex HtmlTagRegex = new("<[^>]+>", RegexOptions.Compiled | RegexOptions.CultureInvariant);
    private static readonly Regex ScriptStyleRegex = new("<(script|style)\\b[^>]*>.*?</\\1>", RegexOptions.Compiled | RegexOptions.IgnoreCase | RegexOptions.Singleline | RegexOptions.CultureInvariant);
    private static readonly Regex SentenceRegex = new(@"[^.!?\r\n]+(?:[.!?]+|(?=\r?$|\n))", RegexOptions.Compiled | RegexOptions.Multiline | RegexOptions.CultureInvariant);

    public static BookDocument Import(BookImportRequest request, IBookLexiconMapper? mapper = null)
    {
        ArgumentNullException.ThrowIfNull(request);
        request.Validate();

        string sha = Convert.ToHexString(SHA256.HashData(request.Content)).ToLowerInvariant();
        string bookId = "book-" + sha[..24];
        IReadOnlyList<(string Title, string Original)> rawChapters = request.Format switch
        {
            BookSourceFormat.Txt => new[] { (request.DisplayName, DecodeText(request.Content)) },
            BookSourceFormat.Html => new[] { (request.DisplayName, HtmlToText(DecodeText(request.Content))) },
            BookSourceFormat.PdfDerivedText => new[] { (request.DisplayName, DecodeText(request.Content)) },
            BookSourceFormat.Epub => ReadEpubChapters(request.Content),
            _ => throw new ArgumentOutOfRangeException(nameof(request.Format))
        };

        if (rawChapters.Count == 0)
            throw new InvalidDataException("Book import produced no readable chapters.");

        string original = string.Join("\n\n", rawChapters.Select(x => x.Original));
        var normalizedBuilder = new StringBuilder();
        var chapters = new List<BookChapterRecord>(rawChapters.Count);
        for (int chapterOrdinal = 0; chapterOrdinal < rawChapters.Count; chapterOrdinal++)
        {
            var raw = rawChapters[chapterOrdinal];
            string normalizedChapter = NormalizeText(raw.Original);
            if (normalizedChapter.Length == 0)
                continue;
            if (normalizedBuilder.Length > 0)
                normalizedBuilder.Append("\n\n");
            int chapterStart = normalizedBuilder.Length;
            normalizedBuilder.Append(normalizedChapter);
            int chapterEnd = normalizedBuilder.Length;
            string chapterId = $"{bookId}:chapter:{chapterOrdinal:D5}";
            var sentences = BuildSentences(chapterId, chapterOrdinal, normalizedChapter, chapterStart, mapper);
            chapters.Add(new BookChapterRecord(
                chapterId,
                chapterOrdinal,
                string.IsNullOrWhiteSpace(raw.Title) ? $"Chapter {chapterOrdinal + 1}" : raw.Title.Trim(),
                new BookTextSpan(chapterStart, chapterEnd),
                sentences));
        }

        if (chapters.Count == 0)
            throw new InvalidDataException("Book import contained no usable normalized text.");

        var document = new BookDocument(
            bookId,
            request.SourceId,
            request.DisplayName,
            request.Format,
            request.ExtractionQuality,
            request.Provenance,
            sha,
            original,
            normalizedBuilder.ToString(),
            chapters,
            true);
        document.Validate();
        return document;
    }

    private static IReadOnlyList<BookSentenceRecord> BuildSentences(string chapterId, int chapterOrdinal, string text, int globalOffset, IBookLexiconMapper? mapper)
    {
        var result = new List<BookSentenceRecord>();
        int ordinal = 0;
        foreach (Match match in SentenceRegex.Matches(text))
        {
            string sentence = match.Value.Trim();
            if (sentence.Length == 0)
                continue;
            int trimStart = match.Value.IndexOf(sentence, StringComparison.Ordinal);
            int start = globalOffset + match.Index + Math.Max(trimStart, 0);
            int end = start + sentence.Length;
            IReadOnlyList<string> ids = mapper?.MapStableEntryIds(sentence) ?? Array.Empty<string>();
            string sentenceId = $"{chapterId}:sentence:{ordinal:D6}";
            result.Add(new BookSentenceRecord(sentenceId, chapterId, ordinal++, new BookTextSpan(start, end), sentence, CanonicalIds(ids)));
        }
        return result;
    }

    private static string[] CanonicalIds(IEnumerable<string> ids) => ids
        .Select(id => (id ?? string.Empty).Trim().ToLowerInvariant())
        .Where(id => id.Length > 0)
        .Distinct(StringComparer.OrdinalIgnoreCase)
        .OrderBy(id => id, StringComparer.Ordinal)
        .ToArray();

    private static string DecodeText(byte[] bytes)
    {
        using var reader = new StreamReader(new MemoryStream(bytes), new UTF8Encoding(false, true), true, leaveOpen: false);
        return reader.ReadToEnd();
    }

    internal static string NormalizeText(string value)
    {
        string normalized = value.Normalize(NormalizationForm.FormC).Replace("\r\n", "\n").Replace('\r', '\n');
        var lines = normalized.Split('\n').Select(line => Regex.Replace(line, @"[\t ]+", " ").TrimEnd()).ToArray();
        normalized = string.Join("\n", lines);
        normalized = Regex.Replace(normalized, "\\n{3,}", "\n\n");
        return normalized.Trim();
    }

    internal static string HtmlToText(string html)
    {
        string withoutScripts = ScriptStyleRegex.Replace(html, " ");
        string structural = Regex.Replace(withoutScripts, @"</?(?:p|div|section|article|h[1-6]|li|br|tr)\b[^>]*>", "\n", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
        string noTags = HtmlTagRegex.Replace(structural, " ");
        return NormalizeText(WebUtility.HtmlDecode(noTags));
    }

    private static IReadOnlyList<(string Title, string Original)> ReadEpubChapters(byte[] bytes)
    {
        using var archive = new ZipArchive(new MemoryStream(bytes, writable: false), ZipArchiveMode.Read, leaveOpen: false);
        ZipArchiveEntry? container = archive.GetEntry("META-INF/container.xml") ?? throw new InvalidDataException("EPUB container.xml is missing.");
        XDocument containerXml;
        using (Stream stream = container.Open()) containerXml = XDocument.Load(stream, LoadOptions.None);
        XNamespace cns = "urn:oasis:names:tc:opendocument:xmlns:container";
        string rootFile = containerXml.Descendants(cns + "rootfile").Select(x => (string?)x.Attribute("full-path")).FirstOrDefault(x => !string.IsNullOrWhiteSpace(x))
            ?? throw new InvalidDataException("EPUB root package path is missing.");
        ZipArchiveEntry packageEntry = archive.GetEntry(rootFile) ?? throw new InvalidDataException("EPUB package document is missing.");
        XDocument package;
        using (Stream stream = packageEntry.Open()) package = XDocument.Load(stream, LoadOptions.None);
        XNamespace opf = package.Root?.Name.Namespace ?? XNamespace.None;
        var manifest = package.Descendants(opf + "item")
            .Where(x => ((string?)x.Attribute("media-type"))?.Contains("html", StringComparison.OrdinalIgnoreCase) == true)
            .ToDictionary(x => (string?)x.Attribute("id") ?? string.Empty, x => (string?)x.Attribute("href") ?? string.Empty, StringComparer.Ordinal);
        string packageDir = rootFile.Contains('/') ? rootFile[..(rootFile.LastIndexOf('/') + 1)] : string.Empty;
        var result = new List<(string, string)>();
        foreach (XElement itemref in package.Descendants(opf + "itemref"))
        {
            string idref = (string?)itemref.Attribute("idref") ?? string.Empty;
            if (!manifest.TryGetValue(idref, out string? href) || string.IsNullOrWhiteSpace(href))
                continue;
            string path = NormalizeZipPath(packageDir + Uri.UnescapeDataString(href.Split('#')[0]));
            ZipArchiveEntry? entry = archive.GetEntry(path);
            if (entry is null)
                continue;
            string html;
            using (var reader = new StreamReader(entry.Open(), Encoding.UTF8, detectEncodingFromByteOrderMarks: true)) html = reader.ReadToEnd();
            string text = HtmlToText(html);
            if (text.Length > 0)
                result.Add((Path.GetFileNameWithoutExtension(entry.Name), text));
        }
        return result;
    }

    private static string NormalizeZipPath(string path)
    {
        string normalized = path.Replace('\\', '/');
        if (normalized.StartsWith('/') || normalized.Split('/').Any(part => part == ".."))
            throw new InvalidDataException("EPUB contains an unsafe traversal path.");
        return string.Join('/', normalized.Split('/').Where(part => part.Length > 0 && part != "."));
    }
}

internal enum BookWordState
{
    Known,
    Learning,
    New
}

internal sealed record BookVocabularyAnalysis(int TotalMappedEntries, int Known, int Learning, int New, double FamiliarityPercent, double DifficultyScore);

internal static class BookVocabularyAnalyzer
{
    public static BookVocabularyAnalysis Analyze(BookDocument document, IReadOnlySet<string> known, IReadOnlySet<string> learning)
    {
        ArgumentNullException.ThrowIfNull(document);
        document.Validate();
        known ??= new HashSet<string>();
        learning ??= new HashSet<string>();
        string[] ids = document.Chapters.SelectMany(c => c.Sentences).SelectMany(s => s.StableEntryIds).Select(id => id.ToLowerInvariant()).ToArray();
        int total = ids.Length;
        int knownCount = ids.Count(known.Contains);
        int learningCount = ids.Count(id => !known.Contains(id) && learning.Contains(id));
        int newCount = total - knownCount - learningCount;
        double familiarity = total == 0 ? 100.0 : knownCount * 100.0 / total;
        double difficulty = total == 0 ? 0.0 : (newCount * 1.0 + learningCount * 0.35) / total * 100.0;
        return new BookVocabularyAnalysis(total, knownCount, learningCount, newCount, familiarity, difficulty);
    }
}

internal sealed record BookSentenceExport(
    string BookId,
    string SourceId,
    string ChapterId,
    string SentenceId,
    long StartOffset,
    long EndOffset,
    string EnglishText,
    IReadOnlyList<string> StableEntryIds,
    bool PrivateLocalOnly = true);

internal static class BookSentenceIntegration
{
    public static IReadOnlyList<BookSentenceExport> ExportForLearningEngines(BookDocument document) =>
        document.Chapters.SelectMany(chapter => chapter.Sentences.Select(sentence => new BookSentenceExport(
            document.BookId,
            document.SourceId,
            chapter.ChapterId,
            sentence.SentenceId,
            sentence.Span.StartOffset,
            sentence.Span.EndOffset,
            sentence.Text,
            sentence.StableEntryIds,
            true))).ToArray();
}
