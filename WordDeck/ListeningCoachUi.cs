namespace WordDeck;

internal sealed class ListeningCoachForm : Form
{
    private readonly DictionaryPackage _package;
    private readonly ListeningStateStore _store;
    private readonly WordAudioListeningExerciseSource _source;
    private ListeningCoachState _state;
    private ListeningCoachEngine _engine;
    private readonly ComboBox _scope = new() { DropDownStyle = ComboBoxStyle.DropDownList };
    private readonly TextBox _answer = new();
    private readonly Label _status = new() { AutoSize = true, MaximumSize = new Size(760, 0) };
    private readonly Button _replay = new() { Text = "&Replay audio (Ctrl+P)", AutoSize = true };
    private readonly Button _check = new() { Text = "&Check (Enter)", AutoSize = true };
    private readonly Button _show = new() { Text = "S&how answer (Ctrl+H)", AutoSize = true };
    private readonly Button _next = new() { Text = "&Next (Ctrl+N)", AutoSize = true };

    public ListeningCoachForm(DictionaryPackage package, string? personalStateRoot = null)
    {
        _package = package ?? throw new ArgumentNullException(nameof(package));
        _store = personalStateRoot is null ? new ListeningStateStore() : new ListeningStateStore(personalStateRoot);
        _state = _store.Load();
        _source = new WordAudioListeningExerciseSource(package);
        _engine = new ListeningCoachEngine(package, _state, _source);

        Text = "WordDeck Listening and Dictation";
        AccessibleName = "WordDeck Listening and Dictation trainer";
        AccessibleDescription = "Offline British word dictation. The answer stays hidden until you check or explicitly show it.";
        Width = 820;
        Height = 430;
        StartPosition = FormStartPosition.CenterParent;
        MinimizeBox = false;
        KeyPreview = true;

        BuildUi();
        Load += (_, _) => StartNext(autoPlay: true, recordSkip: false);
        FormClosing += (_, _) => SafeSave();
        KeyDown += OnFormKeyDown;
    }

    private void BuildUi()
    {
        var menu = new MenuStrip();
        var progress = new ToolStripMenuItem("&Progress") { AccessibleName = "Listening progress" };
        var export = new ToolStripMenuItem("&Export Listening progress...") { AccessibleName = "Export Listening progress" };
        export.Click += (_, _) => ExportProgress();
        var import = new ToolStripMenuItem("&Import Listening progress...") { AccessibleName = "Import Listening progress" };
        import.Click += (_, _) => ImportProgress();
        progress.DropDownItems.Add(export);
        progress.DropDownItems.Add(import);
        menu.Items.Add(progress);
        MainMenuStrip = menu;
        Controls.Add(menu);

        _scope.AccessibleName = "Listening study scope";
        _scope.AccessibleDescription = "Choose All Oxford 5000 or one CEFR level for listening practice.";
        foreach (string scopeId in StudyScopeIds.Ordered) _scope.Items.Add(new ScopeChoice(scopeId));
        int activeIndex = StudyScopeIds.Ordered.ToList().FindIndex(id => string.Equals(id, _state.ActiveScopeId, StringComparison.OrdinalIgnoreCase));
        _scope.SelectedIndex = Math.Max(0, activeIndex);
        _scope.SelectedIndexChanged += (_, _) => ChangeScope();

        _answer.AccessibleName = "Type English listening answer";
        _answer.AccessibleDescription = "The answer is not displayed before checking. Type what you heard and press Enter.";
        _status.AccessibleName = "Listening status";
        _status.AccessibleDescription = "Current Listening trainer status and feedback.";
        _replay.AccessibleName = "Replay listening audio";
        _check.AccessibleName = "Check listening answer";
        _show.AccessibleName = "Show listening answer";
        _next.AccessibleName = "Next listening item";

        _replay.Click += (_, _) => Replay();
        _check.Click += (_, _) => Check();
        _show.Click += (_, _) => ShowAnswer();
        _next.Click += (_, _) => StartNext(autoPlay: true, recordSkip: true);
        AcceptButton = _check;

        var table = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoScroll = true,
            Padding = new Padding(16),
            ColumnCount = 1,
            RowCount = 8
        };
        table.RowStyles.Clear();
        table.Controls.Add(new Label { Text = "Study scope:", AutoSize = true, AccessibleName = "Study scope label" });
        table.Controls.Add(_scope);
        table.Controls.Add(new Label
        {
            Text = "Listen first. The English answer is intentionally hidden until checking.",
            AutoSize = true,
            AccessibleName = "Listening instruction"
        });
        table.Controls.Add(_answer);
        table.Controls.Add(_status);
        var buttons = new FlowLayoutPanel { AutoSize = true, WrapContents = true, Dock = DockStyle.Top };
        buttons.Controls.AddRange(new Control[] { _replay, _check, _show, _next });
        table.Controls.Add(buttons);
        table.Controls.Add(new Label
        {
            Text = "Keyboard: Enter check; Ctrl+P replay; Ctrl+H show answer; Ctrl+N next; F1 help; Escape close.",
            AutoSize = true,
            AccessibleName = "Listening keyboard help"
        });
        Controls.Add(table);
        table.BringToFront();
    }

    private void ChangeScope()
    {
        if (_scope.SelectedItem is not ScopeChoice selected) return;
        _engine.CancelCurrent();
        _state.ActiveScopeId = selected.Id;
        SafeSave();
        if (Visible) StartNext(autoPlay: true, recordSkip: false);
    }

    private void StartNext(bool autoPlay, bool recordSkip)
    {
        try
        {
            ListeningExercise exercise = _engine.StartNext(recordSkip);
            _answer.Clear();
            _answer.ReadOnly = false;
            string prompt = ListeningCoachPresentation.BeforeCheck(exercise);
            SetStatus($"{StudyScopeIds.DisplayName(_state.ActiveScopeId)}. {prompt}");
            SafeSave();
            _answer.Focus();
            if (autoPlay) BeginInvoke(new Action(() => PlayCurrent(countReplay: false)));
        }
        catch (Exception ex)
        {
            _answer.ReadOnly = true;
            SetStatus(ex.Message);
        }
    }

    private void Replay() => PlayCurrent(countReplay: true);

    private void PlayCurrent(bool countReplay)
    {
        if (!_engine.TryPlayCurrent(countReplay, out string? error))
        {
            SetStatus(error ?? "Listening audio could not be played.");
            return;
        }
        if (countReplay)
        {
            SafeSave();
            SetStatus("Audio replayed. The answer remains hidden.");
        }
    }

    private void Check()
    {
        ListeningCheckResult result = _engine.Check(_answer.Text);
        SafeSave();
        SetStatus(result.Message);
        if (!result.Completed) _answer.Focus();
        else _next.Focus();
    }

    private void ShowAnswer()
    {
        try
        {
            string answer = _engine.ShowAnswer();
            SafeSave();
            SetStatus($"{ListeningCoachPresentation.AfterShow(_engine.Current!)}. This review is recorded as needing more listening practice. Press Ctrl+N for the next item.");
            _next.Focus();
        }
        catch (Exception ex) { SetStatus(ex.Message); }
    }

    private void ExportProgress()
    {
        using var dialog = new SaveFileDialog
        {
            Title = "Export WordDeck Listening progress",
            Filter = "WordDeck Listening profile (*.json)|*.json",
            FileName = "WordDeck-listening-profile-v1.json",
            AddExtension = true,
            DefaultExt = "json"
        };
        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        try
        {
            SafeSave();
            new ListeningProfileService(_store).Export(_state, dialog.FileName);
            SetStatus($"Listening progress exported to {dialog.FileName}. Recall, Spelling, dictionary and audio files were not copied.");
        }
        catch (Exception ex) { SetStatus($"Listening export failed: {ex.Message}"); }
    }

    private void ImportProgress()
    {
        using var dialog = new OpenFileDialog
        {
            Title = "Import WordDeck Listening progress",
            Filter = "WordDeck Listening profile (*.json)|*.json|All files (*.*)|*.*"
        };
        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        try
        {
            string? backup = new ListeningProfileService(_store).Import(dialog.FileName);
            _state = _store.Load();
            _engine = new ListeningCoachEngine(_package, _state, _source);
            int activeIndex = StudyScopeIds.Ordered.ToList().FindIndex(id => string.Equals(id, _state.ActiveScopeId, StringComparison.OrdinalIgnoreCase));
            _scope.SelectedIndex = Math.Max(0, activeIndex);
            StartNext(autoPlay: true, recordSkip: false);
            SetStatus(backup is null
                ? "Listening progress imported. There was no earlier Listening state to back up."
                : "Listening progress imported. A recovery backup of the previous Listening state was created.");
        }
        catch (Exception ex) { SetStatus($"Listening import failed; existing progress was preserved: {ex.Message}"); }
    }

    private void OnFormKeyDown(object? sender, KeyEventArgs e)
    {
        if (e.KeyCode == Keys.Escape)
        {
            Close();
            e.Handled = true;
            return;
        }
        if (e.KeyCode == Keys.F1)
        {
            MessageBox.Show(this,
                "Listening and Dictation uses installed offline British audio. The written answer is hidden until Enter checks it or Ctrl+H explicitly shows it. Ctrl+P replays audio. Ctrl+N moves to the next item. Listening progress is separate from Recall and Spelling.",
                "Listening and Dictation help", MessageBoxButtons.OK, MessageBoxIcon.Information);
            e.Handled = true;
            return;
        }
        if (e.Control && e.KeyCode == Keys.P) { Replay(); e.SuppressKeyPress = true; }
        else if (e.Control && e.KeyCode == Keys.H) { ShowAnswer(); e.SuppressKeyPress = true; }
        else if (e.Control && e.KeyCode == Keys.N) { StartNext(autoPlay: true, recordSkip: true); e.SuppressKeyPress = true; }
    }

    private void SafeSave()
    {
        try { _store.Save(_state); }
        catch (Exception ex) { SetStatus($"Listening progress could not be saved safely: {ex.Message}"); }
    }

    private void SetStatus(string message)
    {
        _status.Text = message;
        AccessibilityAnnouncer.Announce(_status, message);
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) _source.Dispose();
        base.Dispose(disposing);
    }

    private sealed record ScopeChoice(string Id)
    {
        public override string ToString() => StudyScopeIds.DisplayName(Id);
    }
}
