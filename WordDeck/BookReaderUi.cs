namespace WordDeck;

internal static class BookReadingEntryPoints
{
    public static void Install(MainForm main)
    {
        MenuStrip? menu = main.Controls.OfType<MenuStrip>().FirstOrDefault();
        ToolStripMenuItem? tools = menu?.Items.OfType<ToolStripMenuItem>()
            .FirstOrDefault(item => (item.Text ?? string.Empty).Replace("&", string.Empty).Equals("Tools", StringComparison.OrdinalIgnoreCase));
        if (tools is null) return;

        var openReading = new ToolStripMenuItem("Open &Reading / book study...")
        {
            AccessibleName = "Open Reading and local book study",
            AccessibleDescription = "Import and read private local TXT, HTML, EPUB, or explicitly PDF-derived text using the keyboard."
        };
        openReading.Click += (_, _) =>
        {
            try
            {
                using var form = new BookReaderForm(
                    main.SharedAppStateForTraining,
                    main.ActivePackageForTraining,
                    new BookReadingProductService(),
                    main.SaveSharedStateAfterTraining);
                form.ShowDialog(main);
            }
            catch (Exception ex)
            {
                MessageBox.Show(main,
                    "Reading was not opened because WordDeck could not safely initialize the private local book store. Existing files were left untouched.\n\n" + ex.Message,
                    "WordDeck protected your private reading data",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Warning);
            }
        };
        tools.DropDownItems.Add(new ToolStripSeparator());
        tools.DropDownItems.Add(openReading);
    }
}

internal sealed class BookReaderForm : Form
{
    private sealed record DeckOption(string Id, string Name)
    {
        public override string ToString() => Name;
    }

    private sealed record BookOption(BookCatalogItem Item)
    {
        public override string ToString() => $"{Item.DisplayName} ({Item.Format})";
    }

    private sealed record OccurrenceOption(BookPhysicalOccurrence Item, string Label)
    {
        public override string ToString() => Label;
    }

    private readonly AppState _state;
    private readonly DictionaryPackage _dictionary;
    private readonly BookReadingProductService _service;
    private readonly Action _saveState;
    private readonly ComboBox _knownDeck;
    private readonly ComboBox _learningDeck;
    private readonly ListBox _books;
    private readonly TextBox _summary;
    private readonly TextBox _sentence;
    private readonly ListBox _occurrences;
    private readonly TextBox _status;
    private readonly Button _previous;
    private readonly Button _next;
    private readonly Button _addToLearning;
    private BookDocument? _document;
    private List<BookSentenceRecord> _sentences = new();
    private int _sentenceIndex = -1;

    public BookReaderForm(AppState state, DictionaryPackage dictionary, BookReadingProductService service, Action saveState)
    {
        _state = state ?? throw new ArgumentNullException(nameof(state));
        _dictionary = dictionary ?? throw new ArgumentNullException(nameof(dictionary));
        _service = service ?? throw new ArgumentNullException(nameof(service));
        _saveState = saveState ?? throw new ArgumentNullException(nameof(saveState));

        Text = "WordDeck Reading — private local books";
        Width = 940;
        Height = 720;
        MinimumSize = new Size(720, 560);
        StartPosition = FormStartPosition.CenterParent;
        KeyPreview = true;
        AccessibleName = "WordDeck private local book reader";
        AccessibleDescription = "Keyboard-first reader. Books stay in the Windows user profile and are not silently uploaded.";

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 9,
            Padding = new Padding(10),
            AutoScroll = true
        };
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 25));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 18));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 22));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 20));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 15));

        var privacy = new TextBox
        {
            Dock = DockStyle.Top,
            Multiline = true,
            ReadOnly = true,
            TabStop = true,
            Height = 58,
            Text = "Private by default: imported books and exact source bytes stay under %LOCALAPPDATA%\\WordDeck\\Reading. WordDeck does not silently upload books. PDF files are not silently parsed; only explicitly extracted PDF-derived text is accepted.",
            AccessibleName = "Reading privacy and PDF extraction notice"
        };
        root.Controls.Add(privacy, 0, 0);

        var policy = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true, WrapContents = true };
        policy.Controls.Add(new Label { Text = "&Known deck:", AutoSize = true, TextAlign = ContentAlignment.MiddleLeft, AccessibleName = "Known deck label" });
        _knownDeck = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Width = 210, AccessibleName = "Deck treated as Known for book familiarity" };
        policy.Controls.Add(_knownDeck);
        policy.Controls.Add(new Label { Text = "&Learning deck:", AutoSize = true, TextAlign = ContentAlignment.MiddleLeft, AccessibleName = "Learning deck label" });
        _learningDeck = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Width = 210, AccessibleName = "Deck treated as Learning for book familiarity and capture" };
        policy.Controls.Add(_learningDeck);
        var refreshAnalysis = new Button { Text = "&Recalculate familiarity", AutoSize = true, AccessibleName = "Recalculate book familiarity using selected decks" };
        refreshAnalysis.Click += (_, _) => RefreshCurrentBookAnalysis();
        policy.Controls.Add(refreshAnalysis);
        root.Controls.Add(policy, 0, 1);

        _books = new ListBox
        {
            Dock = DockStyle.Fill,
            AccessibleName = "Private imported books",
            AccessibleDescription = "Choose a locally stored book, then activate Open selected book."
        };
        root.Controls.Add(_books, 0, 2);

        var bookButtons = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true, WrapContents = true };
        var import = new Button { Text = "&Import TXT, HTML or EPUB...", AutoSize = true, AccessibleName = "Import local TXT HTML or EPUB book" };
        import.Click += (_, _) => ImportBook();
        var importPdfText = new Button { Text = "Import &PDF-derived text...", AutoSize = true, AccessibleName = "Import explicitly PDF-derived text" };
        importPdfText.Click += (_, _) => ImportPdfDerivedText();
        var open = new Button { Text = "&Open selected book", AutoSize = true, AccessibleName = "Open selected private book" };
        open.Click += (_, _) => OpenSelectedBook();
        var refresh = new Button { Text = "Re&fresh book list", AutoSize = true, AccessibleName = "Refresh private book list" };
        refresh.Click += (_, _) => RefreshBookList();
        bookButtons.Controls.Add(import);
        bookButtons.Controls.Add(importPdfText);
        bookButtons.Controls.Add(open);
        bookButtons.Controls.Add(refresh);
        root.Controls.Add(bookButtons, 0, 3);

        _summary = new TextBox
        {
            Dock = DockStyle.Fill,
            Multiline = true,
            ReadOnly = true,
            ScrollBars = ScrollBars.Vertical,
            TabStop = true,
            AccessibleName = "Current book analysis summary"
        };
        root.Controls.Add(_summary, 0, 4);

        _sentence = new TextBox
        {
            Dock = DockStyle.Fill,
            Multiline = true,
            ReadOnly = true,
            ScrollBars = ScrollBars.Vertical,
            TabStop = true,
            AccessibleName = "Current book sentence",
            AccessibleDescription = "Ctrl+PageDown moves to the next sentence. Ctrl+PageUp moves to the previous sentence."
        };
        root.Controls.Add(_sentence, 0, 5);

        _occurrences = new ListBox
        {
            Dock = DockStyle.Fill,
            AccessibleName = "Words in current sentence",
            AccessibleDescription = "Each physical word or phrase is shown once. Ambiguous lexical forms list every matching stable dictionary ID."
        };
        _occurrences.SelectedIndexChanged += (_, _) => UpdateCaptureButton();
        root.Controls.Add(_occurrences, 0, 6);

        var navigation = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true, WrapContents = true };
        _previous = new Button { Text = "&Previous sentence", AutoSize = true, AccessibleName = "Previous book sentence" };
        _previous.Click += (_, _) => MoveSentence(-1);
        _next = new Button { Text = "&Next sentence", AutoSize = true, AccessibleName = "Next book sentence" };
        _next.Click += (_, _) => MoveSentence(1);
        _addToLearning = new Button { Text = "Add selected word to &Learning deck", AutoSize = true, AccessibleName = "Add selected mapped book word to chosen Learning deck" };
        _addToLearning.Click += (_, _) => CaptureSelectedOccurrence();
        navigation.Controls.Add(_previous);
        navigation.Controls.Add(_next);
        navigation.Controls.Add(_addToLearning);
        root.Controls.Add(navigation, 0, 7);

        _status = new TextBox
        {
            Dock = DockStyle.Fill,
            Multiline = true,
            ReadOnly = true,
            TabStop = true,
            AccessibleName = "Reading status and errors",
            AccessibleDescription = "Text status for screen readers."
        };
        root.Controls.Add(_status, 0, 8);
        Controls.Add(root);

        PopulateDeckSelectors();
        RefreshBookList();
        UpdateNavigation();
        Shown += (_, _) => _books.Focus();
    }

    protected override bool ProcessCmdKey(ref Message msg, Keys keyData)
    {
        if (keyData == (Keys.Control | Keys.PageDown)) { MoveSentence(1); return true; }
        if (keyData == (Keys.Control | Keys.PageUp)) { MoveSentence(-1); return true; }
        if (keyData == (Keys.Control | Keys.L)) { CaptureSelectedOccurrence(); return true; }
        if (keyData == Keys.F1) { ShowLocalHelp(); return true; }
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
        string active = _state.ActiveDeckId;
        int learningIndex = Array.FindIndex(decks, deck => deck.Id.Equals(active, StringComparison.OrdinalIgnoreCase));
        if (learningIndex < 0) learningIndex = 0;
        int knownIndex = decks.Length - 1;
        if (knownIndex == learningIndex && decks.Length > 1) knownIndex = learningIndex == 0 ? 1 : 0;
        _knownDeck.SelectedIndex = knownIndex;
        _learningDeck.SelectedIndex = learningIndex;
    }

    private BookDeckVocabularySnapshot CurrentVocabulary()
    {
        if (_knownDeck.SelectedItem is not DeckOption known || _learningDeck.SelectedItem is not DeckOption learning)
            throw new InvalidDataException("Choose both Known and Learning decks before analyzing a book.");
        return BookReadingProductService.BuildVocabularySnapshot(_state, _dictionary, known.Id, learning.Id);
    }

    private void RefreshBookList(string? selectBookId = null)
    {
        _books.Items.Clear();
        foreach (BookCatalogItem item in _service.ListBooks()) _books.Items.Add(new BookOption(item));
        if (_books.Items.Count == 0)
        {
            SetStatus("No private books have been imported yet. Use Alt+I on the import button or Tab to Import TXT, HTML or EPUB.");
            return;
        }
        int desired = 0;
        if (!string.IsNullOrWhiteSpace(selectBookId))
        {
            for (int i = 0; i < _books.Items.Count; i++)
                if ((_books.Items[i] as BookOption)?.Item.BookId.Equals(selectBookId, StringComparison.OrdinalIgnoreCase) == true) { desired = i; break; }
        }
        _books.SelectedIndex = desired;
        SetStatus($"{_books.Items.Count} private local book(s) available.");
    }

    private void ImportBook()
    {
        using var dialog = new OpenFileDialog
        {
            Title = "Import private local book",
            Filter = "Supported books (*.txt;*.html;*.htm;*.epub)|*.txt;*.html;*.htm;*.epub|Text (*.txt)|*.txt|HTML (*.html;*.htm)|*.html;*.htm|EPUB (*.epub)|*.epub",
            CheckFileExists = true,
            Multiselect = false
        };
        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        try
        {
            BookImportProductResult result = _service.ImportFile(dialog.FileName, _dictionary, CurrentVocabulary());
            RefreshBookList(result.Document.BookId);
            _document = result.Document;
            ShowImportedResult(result);
            LoadDocumentIntoReader(result.Document, restorePosition: true);
        }
        catch (Exception ex) { ShowError("Book import failed safely", ex); }
    }

    private void ImportPdfDerivedText()
    {
        using var dialog = new OpenFileDialog
        {
            Title = "Import text explicitly extracted from PDF",
            Filter = "Extracted text (*.txt)|*.txt|All files (*.*)|*.*",
            CheckFileExists = true,
            Multiselect = false
        };
        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        DialogResult reviewed = MessageBox.Show(this,
            "Did you manually review the extracted text for PDF extraction errors?\n\nYes = reviewed. No = keep it explicitly marked unverified. Cancel = do not import.",
            "PDF-derived text quality",
            MessageBoxButtons.YesNoCancel,
            MessageBoxIcon.Question);
        if (reviewed == DialogResult.Cancel) return;
        try
        {
            BookImportProductResult result = _service.ImportPdfDerivedTextFile(dialog.FileName, _dictionary, CurrentVocabulary(), reviewed == DialogResult.Yes);
            RefreshBookList(result.Document.BookId);
            _document = result.Document;
            ShowImportedResult(result);
            LoadDocumentIntoReader(result.Document, restorePosition: true);
        }
        catch (Exception ex) { ShowError("PDF-derived text import failed safely", ex); }
    }

    private void OpenSelectedBook()
    {
        if (_books.SelectedItem is not BookOption selected)
        {
            SetStatus("Choose a private book first.");
            return;
        }
        try
        {
            BookDocument document = _service.LoadDocument(selected.Item.BookId);
            LoadDocumentIntoReader(document, restorePosition: true);
            RefreshCurrentBookAnalysis();
        }
        catch (Exception ex) { ShowError("Could not open private book", ex); }
    }

    private void LoadDocumentIntoReader(BookDocument document, bool restorePosition)
    {
        _document = document;
        _sentences = document.Chapters.OrderBy(chapter => chapter.ChapterOrdinal).SelectMany(chapter => chapter.Sentences.OrderBy(sentence => sentence.SentenceOrdinal)).ToList();
        _sentenceIndex = _sentences.Count == 0 ? -1 : 0;
        if (restorePosition && _sentences.Count > 0)
        {
            BookReadingPosition? saved = _service.LoadPosition(document.BookId);
            if (!string.IsNullOrWhiteSpace(saved?.SentenceId))
            {
                int found = _sentences.FindIndex(sentence => sentence.SentenceId.Equals(saved.SentenceId, StringComparison.OrdinalIgnoreCase));
                if (found >= 0) _sentenceIndex = found;
            }
        }
        ShowCurrentSentence(focusSentence: true);
    }

    private void RefreshCurrentBookAnalysis()
    {
        if (_document is null) return;
        try
        {
            BookDeckVocabularySnapshot snapshot = CurrentVocabulary();
            BookCoverageSummary coverage = _service.GetCoverage(_document.BookId, snapshot);
            int paragraphs = _document.Chapters.Sum(chapter => _service.GetParagraphs(_document.BookId, chapter.ChapterId).Count);
            _summary.Text =
                $"Book: {_document.DisplayName}\r\n" +
                $"Chapters: {_document.Chapters.Count}; paragraphs: {paragraphs}; sentences: {_sentences.Count}.\r\n" +
                $"Physical lexical occurrences: {coverage.PhysicalLexicalCount}; Known: {coverage.Known}; Learning: {coverage.Learning}; New: {coverage.New}; off-list: {coverage.OffList}.\r\n" +
                $"Familiarity: {coverage.FamiliarityPercent:F1}%; difficulty: {coverage.DifficultyScore:F1}%.\r\n" +
                $"Mapping: exact lexical forms; repeated words count repeatedly; ambiguous physical forms count once while retaining all matching stable IDs.\r\n" +
                $"Known deck: {(_knownDeck.SelectedItem as DeckOption)?.Name}; Learning deck: {(_learningDeck.SelectedItem as DeckOption)?.Name}.";
            RefreshOccurrences(snapshot);
            SetStatus("Familiarity recalculated from the selected Known and Learning decks.");
        }
        catch (Exception ex) { ShowError("Could not recalculate familiarity", ex); }
    }

    private void MoveSentence(int delta)
    {
        if (_document is null || _sentences.Count == 0) { SetStatus("Open a book before moving between sentences."); return; }
        int next = Math.Clamp(_sentenceIndex + delta, 0, _sentences.Count - 1);
        if (next == _sentenceIndex)
        {
            SetStatus(delta > 0 ? "Already at the last sentence." : "Already at the first sentence.");
            return;
        }
        _sentenceIndex = next;
        ShowCurrentSentence(focusSentence: true);
    }

    private void ShowCurrentSentence(bool focusSentence)
    {
        _occurrences.Items.Clear();
        if (_document is null || _sentenceIndex < 0 || _sentenceIndex >= _sentences.Count)
        {
            _sentence.Text = "No readable sentence is selected.";
            UpdateNavigation();
            return;
        }
        BookSentenceRecord current = _sentences[_sentenceIndex];
        BookChapterRecord chapter = _document.Chapters.First(item => item.ChapterId.Equals(current.ChapterId, StringComparison.OrdinalIgnoreCase));
        _sentence.Text = $"Chapter {chapter.ChapterOrdinal + 1}: {chapter.Title}\r\nSentence {_sentenceIndex + 1} of {_sentences.Count}\r\n\r\n{current.Text}";
        try
        {
            _service.SavePosition(_document, current);
            RefreshOccurrences(CurrentVocabulary());
        }
        catch (Exception ex) { SetStatus("Sentence is readable, but progress/analysis could not be updated: " + ex.Message); }
        UpdateNavigation();
        if (focusSentence)
        {
            _sentence.Focus();
            _sentence.SelectionStart = 0;
            _sentence.SelectionLength = 0;
        }
    }

    private void RefreshOccurrences(BookDeckVocabularySnapshot snapshot)
    {
        _occurrences.Items.Clear();
        if (_sentenceIndex < 0 || _sentenceIndex >= _sentences.Count) return;
        foreach (BookPhysicalOccurrence item in _service.GetSentenceOccurrences(_sentences[_sentenceIndex].SentenceId, snapshot))
        {
            string mapping = item.StableEntryIds.Count switch
            {
                0 => "off-list exact form",
                1 => item.StableEntryIds[0],
                _ => "ambiguous: " + string.Join(", ", item.StableEntryIds)
            };
            _occurrences.Items.Add(new OccurrenceOption(item, $"{item.Surface} — {item.State}; {mapping}"));
        }
        if (_occurrences.Items.Count > 0) _occurrences.SelectedIndex = 0;
        UpdateCaptureButton();
    }

    private void CaptureSelectedOccurrence()
    {
        if (_document is null || _sentenceIndex < 0 || _sentenceIndex >= _sentences.Count) { SetStatus("Open a book and sentence first."); return; }
        if (_learningDeck.SelectedItem is not DeckOption learningDeck) { SetStatus("Choose a Learning deck first."); return; }
        if (_occurrences.SelectedItem is not OccurrenceOption selected) { SetStatus("Choose a word from the current sentence first."); return; }
        if (selected.Item.StableEntryIds.Count == 0)
        {
            SetStatus("That exact lexical form is off-list. WordDeck will not invent a translation or a stable ID; add a reviewed custom dictionary entry first.");
            return;
        }

        string? entryId = selected.Item.StableEntryIds.Count == 1 ? selected.Item.StableEntryIds[0] : ChooseAmbiguousEntry(selected.Item);
        if (entryId is null) return;
        try
        {
            BookSentenceRecord sentence = _sentences[_sentenceIndex];
            _service.CaptureMappedOccurrenceToLearningDeck(_document, sentence, entryId, _state, _dictionary, learningDeck.Id);
            _saveState();
            RefreshCurrentBookAnalysis();
            SetStatus($"Added {DescribeEntry(entryId)} to Learning deck '{learningDeck.Name}' from this exact book context.");
        }
        catch (Exception ex) { ShowError("Could not add book word to learning", ex); }
    }

    private string? ChooseAmbiguousEntry(BookPhysicalOccurrence occurrence)
    {
        using var dialog = new Form
        {
            Text = "Choose dictionary meaning for ambiguous book form",
            Width = 700,
            Height = 420,
            StartPosition = FormStartPosition.CenterParent,
            AccessibleName = "Choose stable dictionary entry for ambiguous lexical form"
        };
        var list = new ListBox { Dock = DockStyle.Fill, AccessibleName = "Matching stable dictionary entries" };
        foreach (string id in occurrence.StableEntryIds)
            list.Items.Add(new DeckOption(id, DescribeEntry(id)));
        if (list.Items.Count > 0) list.SelectedIndex = 0;
        var buttons = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 52, FlowDirection = FlowDirection.RightToLeft };
        var cancel = new Button { Text = "Cancel", DialogResult = DialogResult.Cancel, AutoSize = true };
        var choose = new Button { Text = "Choose", DialogResult = DialogResult.OK, AutoSize = true, AccessibleName = "Choose selected dictionary meaning" };
        buttons.Controls.Add(cancel);
        buttons.Controls.Add(choose);
        dialog.Controls.Add(list);
        dialog.Controls.Add(buttons);
        dialog.AcceptButton = choose;
        dialog.CancelButton = cancel;
        dialog.Shown += (_, _) => list.Focus();
        return dialog.ShowDialog(this) == DialogResult.OK && list.SelectedItem is DeckOption selected ? selected.Id : null;
    }

    private string DescribeEntry(string id)
    {
        DictionaryEntry? entry = _dictionary.Entries.FirstOrDefault(item => item.Id.Equals(id, StringComparison.OrdinalIgnoreCase));
        return entry is null ? id : $"{entry.Source} — {entry.Target} [{entry.Level}] ({entry.Id})";
    }

    private void ShowImportedResult(BookImportProductResult result)
    {
        _summary.Text =
            $"Imported: {result.Document.DisplayName}\r\n" +
            $"Chapters: {result.Document.Chapters.Count}; paragraphs: {result.ParagraphCount}; sentences: {result.Document.Chapters.Sum(chapter => chapter.Sentences.Count)}.\r\n" +
            $"Physical words/phrases: {result.Coverage.PhysicalLexicalCount}; familiarity: {result.Coverage.FamiliarityPercent:F1}%; difficulty: {result.Coverage.DifficultyScore:F1}%.\r\n" +
            result.ExtractionStatement + "\r\n" + result.PrivacyStatement;
        SetStatus("Book imported and indexed. The exact source bytes were retained privately so normalization did not destroy the original.");
    }

    private void UpdateNavigation()
    {
        _previous.Enabled = _sentenceIndex > 0;
        _next.Enabled = _sentenceIndex >= 0 && _sentenceIndex < _sentences.Count - 1;
        UpdateCaptureButton();
    }

    private void UpdateCaptureButton()
    {
        _addToLearning.Enabled = _document is not null && _sentenceIndex >= 0 && _occurrences.SelectedItem is OccurrenceOption;
    }

    private void SetStatus(string value)
    {
        _status.Text = value;
        _status.AccessibleDescription = value;
    }

    private void ShowError(string title, Exception ex)
    {
        SetStatus(title + ": " + ex.Message);
        MessageBox.Show(this, ex.Message, title, MessageBoxButtons.OK, MessageBoxIcon.Warning);
    }

    private void ShowLocalHelp()
    {
        MessageBox.Show(this,
            "WordDeck Reading keyboard help\n\n" +
            "Tab / Shift+Tab: move through controls.\n" +
            "Alt+I: activate the normal import button mnemonic when focus allows standard Windows mnemonics.\n" +
            "Ctrl+PageDown: next sentence.\n" +
            "Ctrl+PageUp: previous sentence.\n" +
            "Ctrl+L: add the selected mapped word to the chosen Learning deck.\n" +
            "F1: this help.\n\n" +
            "Known/Learning/New is based on the two deck selectors at the top. Exact lexical-form matching does not pretend to lemmatize inflected forms. Off-list words are never assigned invented translations or IDs. Ambiguous forms require an explicit dictionary-entry choice.\n\n" +
            "Books remain private local files under the Windows user profile. PDF import accepts only explicitly derived text and always states extraction quality.",
            "Reading help",
            MessageBoxButtons.OK,
            MessageBoxIcon.Information);
    }
}
