using Microsoft.Data.Sqlite;
using System.Globalization;
using System.Text.RegularExpressions;

namespace WordDeck;

internal sealed record BookReadingWritingResponse(
    string BookId,
    string SentenceId,
    string ResponseText,
    string FeedbackText,
    DateTimeOffset UpdatedUtc);

/// <summary>
/// Persists learner writing beside the existing private Reading corpus. The store
/// never uploads content and never turns a writing response into mastery evidence.
/// </summary>
internal sealed class BookReadingWritingStore
{
    public const int MaximumResponseCharacters = 12000;
    private readonly string _databasePath;

    public BookReadingWritingStore(string databasePath)
    {
        if (string.IsNullOrWhiteSpace(databasePath))
            throw new ArgumentException("Book-reading SQLite path is required.", nameof(databasePath));
        _databasePath = Path.GetFullPath(databasePath);
        Initialize();
    }

    public void Save(BookDocument document, BookSentenceRecord sentence, string responseText, string feedbackText)
    {
        ArgumentNullException.ThrowIfNull(document);
        ArgumentNullException.ThrowIfNull(sentence);
        document.Validate();
        string response = (responseText ?? string.Empty).Trim();
        string feedback = (feedbackText ?? string.Empty).Trim();
        if (response.Length == 0)
            throw new InvalidDataException("Write a response before saving Reading/Writing practice.");
        if (response.Length > MaximumResponseCharacters)
            throw new InvalidDataException($"Writing response exceeds the {MaximumResponseCharacters:N0}-character local-practice limit.");
        if (feedback.Length == 0)
            throw new InvalidDataException("Deterministic feedback is required before Reading/Writing practice can be persisted.");
        bool belongs = document.Chapters
            .SelectMany(chapter => chapter.Sentences)
            .Any(candidate => candidate.SentenceId.Equals(sentence.SentenceId, StringComparison.OrdinalIgnoreCase));
        if (!belongs)
            throw new InvalidDataException("Writing response sentence does not belong to the selected private book.");

        using SqliteConnection connection = Open();
        using SqliteCommand command = connection.CreateCommand();
        command.CommandText = """
            INSERT INTO book_writing_response(book_id,sentence_id,response_text,feedback_text,updated_utc)
            VALUES($book,$sentence,$response,$feedback,$utc)
            ON CONFLICT(book_id,sentence_id) DO UPDATE SET
              response_text=excluded.response_text,
              feedback_text=excluded.feedback_text,
              updated_utc=excluded.updated_utc;
            """;
        command.Parameters.AddWithValue("$book", document.BookId);
        command.Parameters.AddWithValue("$sentence", sentence.SentenceId);
        command.Parameters.AddWithValue("$response", response);
        command.Parameters.AddWithValue("$feedback", feedback);
        command.Parameters.AddWithValue("$utc", DateTimeOffset.UtcNow.ToString("O", CultureInfo.InvariantCulture));
        command.ExecuteNonQuery();
    }

    public BookReadingWritingResponse? Load(string bookId, string sentenceId)
    {
        string book = (bookId ?? string.Empty).Trim();
        string sentence = (sentenceId ?? string.Empty).Trim();
        if (book.Length == 0 || sentence.Length == 0) return null;
        using SqliteConnection connection = Open();
        using SqliteCommand command = connection.CreateCommand();
        command.CommandText = """
            SELECT book_id,sentence_id,response_text,feedback_text,updated_utc
            FROM book_writing_response
            WHERE book_id=$book AND sentence_id=$sentence;
            """;
        command.Parameters.AddWithValue("$book", book);
        command.Parameters.AddWithValue("$sentence", sentence);
        using SqliteDataReader reader = command.ExecuteReader();
        if (!reader.Read()) return null;
        return new BookReadingWritingResponse(
            reader.GetString(0),
            reader.GetString(1),
            reader.GetString(2),
            reader.GetString(3),
            DateTimeOffset.Parse(reader.GetString(4), CultureInfo.InvariantCulture));
    }

    private void Initialize()
    {
        string? directory = Path.GetDirectoryName(_databasePath);
        if (!string.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);
        using SqliteConnection connection = Open(createSchema: false);
        using SqliteCommand command = connection.CreateCommand();
        command.CommandText = """
            CREATE TABLE IF NOT EXISTS book_writing_response (
                book_id TEXT NOT NULL REFERENCES book_document(book_id) ON DELETE CASCADE,
                sentence_id TEXT NOT NULL,
                response_text TEXT NOT NULL CHECK(length(response_text) BETWEEN 1 AND 12000),
                feedback_text TEXT NOT NULL,
                updated_utc TEXT NOT NULL,
                PRIMARY KEY(book_id,sentence_id)
            );
            CREATE INDEX IF NOT EXISTS ix_book_writing_response_sentence
                ON book_writing_response(sentence_id,book_id);
            """;
        command.ExecuteNonQuery();
    }

    private SqliteConnection Open(bool createSchema = true)
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
        pragma.CommandText = "PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000;";
        pragma.ExecuteNonQuery();
        return connection;
    }
}

internal static class BookReadingWritingFeedback
{
    private static readonly Regex WordRegex = new(@"[\p{L}\p{M}]+(?:['’\-][\p{L}\p{M}]+)*", RegexOptions.Compiled | RegexOptions.CultureInvariant);

    public static string Build(BookSentenceRecord sentence, string responseText, DictionaryPackage dictionary)
    {
        ArgumentNullException.ThrowIfNull(sentence);
        ArgumentNullException.ThrowIfNull(dictionary);
        string response = (responseText ?? string.Empty).Trim();
        if (response.Length == 0)
            throw new InvalidDataException("Write a response before requesting feedback.");
        if (response.Length > BookReadingWritingStore.MaximumResponseCharacters)
            throw new InvalidDataException($"Writing response exceeds the {BookReadingWritingStore.MaximumResponseCharacters:N0}-character local-practice limit.");

        string[] sourceWords = Words(sentence.Text);
        string[] responseWords = Words(response);
        var sourceSet = sourceWords.ToHashSet(StringComparer.OrdinalIgnoreCase);
        var responseSet = responseWords.ToHashSet(StringComparer.OrdinalIgnoreCase);
        int overlapping = responseSet.Count(sourceSet.Contains);
        double overlapPercent = responseSet.Count == 0 ? 0 : overlapping * 100.0 / responseSet.Count;

        var reused = new List<string>();
        foreach (string id in sentence.StableEntryIds.Distinct(StringComparer.OrdinalIgnoreCase))
        {
            DictionaryEntry? entry = dictionary.Entries.FirstOrDefault(item => item.Id.Equals(id, StringComparison.OrdinalIgnoreCase));
            if (entry is null) continue;
            string[] entryWords = Words(entry.Source);
            if (entryWords.Length > 0 && ContainsSequence(responseWords, entryWords))
                reused.Add($"{entry.Source} [{entry.Id}]");
        }

        bool startsWithLetter = response.EnumerateRunes().Any(rune => RuneIsLetter(rune.Value));
        bool terminalPunctuation = response.EndsWith('.') || response.EndsWith('!') || response.EndsWith('?');
        string vocabulary = reused.Count == 0
            ? "Mapped vocabulary reused from this sentence: none detected by exact written-form matching."
            : $"Mapped vocabulary reused from this sentence: {string.Join(", ", reused)}.";

        return
            "Structural feedback only — WordDeck does not judge meaning, factual accuracy, grammar correctness, CEFR level, assessment success, or mastery.\r\n" +
            $"Response words: {responseWords.Length}; distinct response words: {responseSet.Count}.\r\n" +
            $"Exact lexical overlap with the source sentence: {overlapping}/{responseSet.Count} distinct response words ({overlapPercent:0.#}%). This is a description, not a quality score.\r\n" +
            vocabulary + "\r\n" +
            $"Editing checks: contains a letter = {(startsWithLetter ? "yes" : "no")}; ends with . ! or ? = {(terminalPunctuation ? "yes" : "no")}.\r\n" +
            "Revision prompt: compare your response with the source sentence and revise anything you want to make clearer or more precise. Saving this practice does not change mastery or course progress.";
    }

    private static string[] Words(string text) => WordRegex.Matches(text ?? string.Empty)
        .Select(match => match.Value.Normalize().ToLowerInvariant())
        .ToArray();

    private static bool ContainsSequence(IReadOnlyList<string> haystack, IReadOnlyList<string> needle)
    {
        if (needle.Count == 0 || needle.Count > haystack.Count) return false;
        for (int start = 0; start <= haystack.Count - needle.Count; start++)
        {
            bool match = true;
            for (int offset = 0; offset < needle.Count; offset++)
            {
                if (!haystack[start + offset].Equals(needle[offset], StringComparison.OrdinalIgnoreCase))
                {
                    match = false;
                    break;
                }
            }
            if (match) return true;
        }
        return false;
    }

    private static bool RuneIsLetter(int scalar) =>
        scalar <= char.MaxValue && char.IsLetter((char)scalar) ||
        scalar > char.MaxValue;
}

internal static class BookReadingWritingEntryPoints
{
    public static void Install(MainForm main)
    {
        ArgumentNullException.ThrowIfNull(main);
        MenuStrip? menu = main.Controls.OfType<MenuStrip>().FirstOrDefault();
        ToolStripMenuItem? tools = menu?.Items.OfType<ToolStripMenuItem>()
            .FirstOrDefault(item => (item.Text ?? string.Empty).Replace("&", string.Empty).Equals("Tools", StringComparison.OrdinalIgnoreCase));
        if (tools is null) return;

        var open = new ToolStripMenuItem("Open Reading + &Writing workbench...")
        {
            AccessibleName = "Open Reading and Writing workbench",
            AccessibleDescription = "Use an already imported private book sentence for vocabulary context, a local writing response, deterministic feedback, and restart-safe persistence."
        };
        open.Click += (_, _) =>
        {
            try
            {
                using var form = new BookReadingWritingWorkbenchForm(
                    main.SharedAppStateForTraining,
                    main.ActivePackageForTraining,
                    new BookReadingProductService(),
                    main.SaveSharedStateAfterTraining);
                form.ShowDialog(main);
            }
            catch (Exception ex)
            {
                MessageBox.Show(
                    main,
                    "The Reading + Writing workbench was not opened because WordDeck could not safely initialize the private local Reading store. Existing files were left untouched.\n\n" + ex.Message,
                    "WordDeck protected your private Reading data",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Warning);
            }
        };
        tools.DropDownItems.Add(open);
    }
}

internal sealed class BookReadingWritingWorkbenchForm : Form
{
    private sealed record DeckOption(string Id, string Name)
    {
        public override string ToString() => Name;
    }

    private sealed record BookOption(BookCatalogItem Item)
    {
        public override string ToString() => $"{Item.DisplayName} ({Item.Format})";
    }

    private sealed record VocabularyOption(string Id, string Label)
    {
        public override string ToString() => Label;
    }

    private readonly AppState _state;
    private readonly DictionaryPackage _dictionary;
    private readonly BookReadingProductService _service;
    private readonly BookReadingWritingStore _writingStore;
    private readonly Action _saveState;
    private readonly ComboBox _knownDeck = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 210, AccessibleName = "Known deck for Reading familiarity" };
    private readonly ComboBox _learningDeck = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 210, AccessibleName = "Learning deck for Reading vocabulary capture" };
    private readonly ComboBox _books = new() { DropDownStyle = ComboBoxStyle.DropDownList, Dock = DockStyle.Top, AccessibleName = "Private imported book for Reading and Writing" };
    private readonly TextBox _sentence = new() { Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical, Dock = DockStyle.Fill, TabStop = true, AccessibleName = "Current source sentence" };
    private readonly ListBox _vocabulary = new() { Dock = DockStyle.Fill, AccessibleName = "Mapped vocabulary and context from current sentence" };
    private readonly TextBox _response = new() { Multiline = true, AcceptsReturn = true, ScrollBars = ScrollBars.Vertical, Dock = DockStyle.Fill, AccessibleName = "Your writing response to the current sentence", AccessibleDescription = "Write a paraphrase, reaction, inference, or note. Ctrl+S saves and refreshes deterministic structural feedback." };
    private readonly TextBox _feedback = new() { Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical, Dock = DockStyle.Fill, TabStop = true, AccessibleName = "Deterministic Reading and Writing feedback" };
    private readonly TextBox _status = new() { Multiline = true, ReadOnly = true, Dock = DockStyle.Fill, TabStop = true, AccessibleName = "Reading and Writing status" };
    private readonly Button _previous = new() { Text = "&Previous sentence", AutoSize = true, AccessibleName = "Previous source sentence" };
    private readonly Button _next = new() { Text = "&Next sentence", AutoSize = true, AccessibleName = "Next source sentence" };
    private readonly Button _save = new() { Text = "&Save response + feedback", AutoSize = true, AccessibleName = "Save writing response and deterministic feedback locally" };
    private readonly Button _capture = new() { Text = "Add selected word to &Learning", AutoSize = true, AccessibleName = "Add selected mapped vocabulary item to Learning deck" };
    private BookDocument? _document;
    private List<BookSentenceRecord> _sentences = new();
    private int _sentenceIndex = -1;
    private string _loadedResponse = string.Empty;

    public BookReadingWritingWorkbenchForm(AppState state, DictionaryPackage dictionary, BookReadingProductService service, Action saveState)
    {
        _state = state ?? throw new ArgumentNullException(nameof(state));
        _dictionary = dictionary ?? throw new ArgumentNullException(nameof(dictionary));
        _service = service ?? throw new ArgumentNullException(nameof(service));
        _saveState = saveState ?? throw new ArgumentNullException(nameof(saveState));
        _writingStore = new BookReadingWritingStore(_service.DatabasePath);

        Text = "WordDeck Reading + Writing — private local workbench";
        Width = 980;
        Height = 820;
        MinimumSize = new Size(760, 640);
        StartPosition = FormStartPosition.CenterParent;
        KeyPreview = true;
        AccessibleName = "WordDeck private Reading and Writing workbench";
        AccessibleDescription = "Sentence-grounded Reading and Writing practice. Private book text and responses stay local; feedback is deterministic and does not grant mastery.";

        var root = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 12, Padding = new Padding(10), AutoScroll = true };
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 17));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 16));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 23));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 24));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 12));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));

        root.Controls.Add(new Label
        {
            Text = "Private local practice. Select a book already imported through Reading. The current sentence supplies semantic context; mapped dictionary IDs supply vocabulary context. Saved writing and feedback stay in the same private Reading SQLite store. Practice does not imply mastery.",
            AutoSize = true,
            MaximumSize = new Size(900, 0),
            AccessibleName = "Reading and Writing privacy and evidence boundary"
        }, 0, 0);

        var policy = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true, WrapContents = true };
        policy.Controls.Add(new Label { Text = "&Known deck:", AutoSize = true });
        policy.Controls.Add(_knownDeck);
        policy.Controls.Add(new Label { Text = "&Learning deck:", AutoSize = true });
        policy.Controls.Add(_learningDeck);
        root.Controls.Add(policy, 0, 1);

        root.Controls.Add(_books, 0, 2);
        root.Controls.Add(_sentence, 0, 3);
        root.Controls.Add(_vocabulary, 0, 4);

        var navigation = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true, WrapContents = true };
        navigation.Controls.Add(_previous);
        navigation.Controls.Add(_next);
        navigation.Controls.Add(_capture);
        root.Controls.Add(navigation, 0, 5);

        root.Controls.Add(_response, 0, 6);
        var savePanel = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true, WrapContents = true };
        savePanel.Controls.Add(_save);
        root.Controls.Add(savePanel, 0, 7);
        root.Controls.Add(_feedback, 0, 8);
        root.Controls.Add(new Label
        {
            Text = "Keyboard: Ctrl+PageUp/Ctrl+PageDown previous/next sentence; Ctrl+S save + feedback; Ctrl+L add selected mapped word to Learning; F1 help.",
            AutoSize = true,
            AccessibleName = "Reading and Writing keyboard help summary"
        }, 0, 9);
        root.Controls.Add(_status, 0, 10);
        var close = new Button { Text = "&Close", AutoSize = true, DialogResult = DialogResult.Cancel, AccessibleName = "Close Reading and Writing workbench" };
        root.Controls.Add(close, 0, 11);
        Controls.Add(root);

        CancelButton = close;
        _books.SelectedIndexChanged += (_, _) => OpenSelectedBook();
        _knownDeck.SelectedIndexChanged += (_, _) => RefreshSentenceContext();
        _learningDeck.SelectedIndexChanged += (_, _) => RefreshSentenceContext();
        _previous.Click += (_, _) => MoveSentence(-1);
        _next.Click += (_, _) => MoveSentence(1);
        _save.Click += (_, _) => SaveWriting();
        _capture.Click += (_, _) => CaptureSelectedVocabulary();
        FormClosing += (_, e) =>
        {
            if (!ConfirmDiscardIfDirty()) e.Cancel = true;
        };

        PopulateDeckSelectors();
        RefreshBooks();
        UpdateNavigation();
        Shown += (_, _) => (_books.Items.Count > 0 ? _books : _status).Focus();
    }

    protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
    {
        if (keyData == (Keys.Control | Keys.PageDown)) { MoveSentence(1); return true; }
        if (keyData == (Keys.Control | Keys.PageUp)) { MoveSentence(-1); return true; }
        if (keyData == (Keys.Control | Keys.S)) { SaveWriting(); return true; }
        if (keyData == (Keys.Control | Keys.L)) { CaptureSelectedVocabulary(); return true; }
        if (keyData == Keys.F1) { ShowHelp(); return true; }
        return base.ProcessCmdKey(ref msg, keyData);
    }

    private void PopulateDeckSelectors()
    {
        DeckDefinition[] decks = new DeckService(_state).Decks.ToArray();
        foreach (DeckDefinition deck in decks)
        {
            _knownDeck.Items.Add(new DeckOption(deck.Id, deck.Name));
            _learningDeck.Items.Add(new DeckOption(deck.Id, deck.Name));
        }
        if (decks.Length == 0) return;
        string active = _state.ActiveDeckId ?? string.Empty;
        int learning = Array.FindIndex(decks, deck => deck.Id.Equals(active, StringComparison.OrdinalIgnoreCase));
        if (learning < 0) learning = 0;
        int known = decks.Length - 1;
        if (known == learning && decks.Length > 1) known = learning == 0 ? 1 : 0;
        _knownDeck.SelectedIndex = known;
        _learningDeck.SelectedIndex = learning;
    }

    private BookDeckVocabularySnapshot CurrentVocabulary()
    {
        if (_knownDeck.SelectedItem is not DeckOption known || _learningDeck.SelectedItem is not DeckOption learning)
            throw new InvalidDataException("Choose distinct Known and Learning decks before using vocabulary context.");
        return BookReadingProductService.BuildVocabularySnapshot(_state, _dictionary, known.Id, learning.Id);
    }

    private void RefreshBooks()
    {
        _books.Items.Clear();
        foreach (BookCatalogItem item in _service.ListBooks()) _books.Items.Add(new BookOption(item));
        if (_books.Items.Count == 0)
        {
            SetStatus("No private books are available. Open Tools > Reading / book study first and import a TXT, HTML, EPUB, or explicitly PDF-derived text file. This workbench intentionally reuses that Reading engine instead of creating another importer.");
            return;
        }
        _books.SelectedIndex = 0;
    }

    private void OpenSelectedBook()
    {
        if (_books.SelectedItem is not BookOption selected) return;
        if (!ConfirmDiscardIfDirty()) return;
        try
        {
            _document = _service.LoadDocument(selected.Item.BookId);
            _sentences = _document.Chapters
                .OrderBy(chapter => chapter.ChapterOrdinal)
                .SelectMany(chapter => chapter.Sentences.OrderBy(sentence => sentence.SentenceOrdinal))
                .ToList();
            _sentenceIndex = _sentences.Count == 0 ? -1 : 0;
            BookReadingPosition? saved = _service.LoadPosition(_document.BookId);
            if (!string.IsNullOrWhiteSpace(saved?.SentenceId))
            {
                int found = _sentences.FindIndex(item => item.SentenceId.Equals(saved.SentenceId, StringComparison.OrdinalIgnoreCase));
                if (found >= 0) _sentenceIndex = found;
            }
            ShowCurrentSentence(focusResponse: true);
        }
        catch (Exception ex) { ShowError("Could not open the private book", ex); }
    }

    private void MoveSentence(int delta)
    {
        if (_document is null || _sentences.Count == 0) return;
        if (!ConfirmDiscardIfDirty()) return;
        int next = Math.Clamp(_sentenceIndex + delta, 0, _sentences.Count - 1);
        if (next == _sentenceIndex) return;
        _sentenceIndex = next;
        ShowCurrentSentence(focusResponse: true);
    }

    private void ShowCurrentSentence(bool focusResponse)
    {
        _vocabulary.Items.Clear();
        if (_document is null || _sentenceIndex < 0 || _sentenceIndex >= _sentences.Count)
        {
            _sentence.Text = string.Empty;
            _response.Text = string.Empty;
            _feedback.Text = string.Empty;
            _loadedResponse = string.Empty;
            UpdateNavigation();
            return;
        }

        BookSentenceRecord current = _sentences[_sentenceIndex];
        _sentence.Text = $"Sentence {_sentenceIndex + 1} of {_sentences.Count}\r\n\r\n{current.Text}";
        try
        {
            _service.SavePosition(_document, current);
            RefreshSentenceContext();
            BookReadingWritingResponse? saved = _writingStore.Load(_document.BookId, current.SentenceId);
            _response.Text = saved?.ResponseText ?? string.Empty;
            _feedback.Text = saved?.FeedbackText ?? "No saved writing response for this sentence yet. Write a response, then press Ctrl+S for deterministic structural feedback.";
            _loadedResponse = _response.Text;
            SetStatus(saved is null
                ? "Sentence context loaded. Writing has not yet been saved for this sentence."
                : $"Restored local writing practice saved {saved.UpdatedUtc.ToLocalTime():g}.");
        }
        catch (Exception ex) { ShowError("Could not load Reading + Writing context", ex); }
        UpdateNavigation();
        if (focusResponse) _response.Focus();
    }

    private void RefreshSentenceContext()
    {
        _vocabulary.Items.Clear();
        if (_document is null || _sentenceIndex < 0 || _sentenceIndex >= _sentences.Count) return;
        try
        {
            BookSentenceRecord current = _sentences[_sentenceIndex];
            BookDeckVocabularySnapshot snapshot = CurrentVocabulary();
            foreach (string id in current.StableEntryIds.Distinct(StringComparer.OrdinalIgnoreCase))
            {
                DictionaryEntry? entry = _dictionary.Entries.FirstOrDefault(item => item.Id.Equals(id, StringComparison.OrdinalIgnoreCase));
                if (entry is null) continue;
                string state = snapshot.KnownEntryIds.Contains(id) ? "Known" : snapshot.LearningEntryIds.Contains(id) ? "Learning" : "New or ambiguous";
                _vocabulary.Items.Add(new VocabularyOption(id, $"{entry.Source} — {entry.Target} — {state} — [{entry.Id}]"));
            }
            if (_vocabulary.Items.Count == 0)
                _vocabulary.Items.Add(new VocabularyOption(string.Empty, "No safely mapped dictionary vocabulary in this sentence."));
            _vocabulary.SelectedIndex = 0;
        }
        catch (Exception ex) { SetStatus("Vocabulary context is unavailable: " + ex.Message); }
    }

    private void SaveWriting()
    {
        if (_document is null || _sentenceIndex < 0 || _sentenceIndex >= _sentences.Count)
        {
            SetStatus("Choose a private book and sentence before writing.");
            return;
        }
        try
        {
            BookSentenceRecord current = _sentences[_sentenceIndex];
            string feedback = BookReadingWritingFeedback.Build(current, _response.Text, _dictionary);
            _writingStore.Save(_document, current, _response.Text, feedback);
            _feedback.Text = feedback;
            _loadedResponse = _response.Text.Trim();
            SetStatus("Writing response and deterministic feedback saved locally in the private Reading store. No mastery, CEFR, assessment, or course-progress credit was granted.");
            _feedback.Focus();
        }
        catch (Exception ex) { ShowError("Writing response was not saved", ex); }
    }

    private void CaptureSelectedVocabulary()
    {
        if (_document is null || _sentenceIndex < 0 || _sentenceIndex >= _sentences.Count || _vocabulary.SelectedItem is not VocabularyOption option || string.IsNullOrWhiteSpace(option.Id))
        {
            SetStatus("Select a mapped vocabulary item from the current sentence first.");
            return;
        }
        if (_learningDeck.SelectedItem is not DeckOption learning)
        {
            SetStatus("Choose a Learning deck first.");
            return;
        }
        try
        {
            _service.CaptureMappedOccurrenceToLearningDeck(_document, _sentences[_sentenceIndex], option.Id, _state, _dictionary, learning.Id);
            _saveState();
            RefreshSentenceContext();
            SetStatus($"Captured {option.Id} from the current sentence into Learning. Ambiguous written forms require the explicit stable ID you selected; capture does not imply mastery.");
        }
        catch (Exception ex) { ShowError("Vocabulary capture failed safely", ex); }
    }

    private bool ConfirmDiscardIfDirty()
    {
        if (_response.Text.Trim().Equals(_loadedResponse.Trim(), StringComparison.Ordinal)) return true;
        DialogResult result = MessageBox.Show(
            this,
            "This sentence has unsaved writing changes. Leave the sentence and discard those changes?",
            "Unsaved Reading + Writing response",
            MessageBoxButtons.YesNo,
            MessageBoxIcon.Warning,
            MessageBoxDefaultButton.Button2);
        return result == DialogResult.Yes;
    }

    private void UpdateNavigation()
    {
        _previous.Enabled = _sentenceIndex > 0;
        _next.Enabled = _sentenceIndex >= 0 && _sentenceIndex < _sentences.Count - 1;
        _save.Enabled = _sentenceIndex >= 0;
        _capture.Enabled = _sentenceIndex >= 0;
    }

    private void ShowHelp()
    {
        MessageBox.Show(
            this,
            "Reading + Writing reuses your private local Reading books. The current sentence is the semantic context; the vocabulary list uses mapped stable dictionary IDs. Write a paraphrase, reaction, inference, or note. Ctrl+S saves the response and deterministic structural feedback in the same local Reading SQLite store. Ctrl+PageUp/PageDown changes sentence. Ctrl+L captures the selected mapped stable ID to Learning. Feedback does not judge semantic correctness or grant mastery/CEFR/assessment credit. Automated accessibility is not physical NVDA verification.",
            "Reading + Writing keyboard help",
            MessageBoxButtons.OK,
            MessageBoxIcon.Information);
    }

    private void SetStatus(string text) => _status.Text = text;

    private void ShowError(string title, Exception ex)
    {
        SetStatus(title + ": " + ex.Message);
        MessageBox.Show(this, ex.Message, title, MessageBoxButtons.OK, MessageBoxIcon.Warning);
    }
}