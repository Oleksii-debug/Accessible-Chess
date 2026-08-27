namespace WordDeck;

internal sealed class ListeningCoachForm : Form
{
    private readonly DictionaryPackage _package;
    private readonly ShortcutManager _shortcuts;
    private readonly ListeningStateStore _store;
    private readonly WordAudioListeningExerciseSource _source;
    private ListeningCoachState _state;
    private ListeningCoachEngine _engine;
    private readonly ComboBox _scope = new() { DropDownStyle = ComboBoxStyle.DropDownList };
    private readonly TextBox _answer = new();
    private readonly Label _status = new() { AutoSize = true, MaximumSize = new Size(760, 0) };
    private readonly Button _replay = new() { AutoSize = true };
    private readonly Button _check = new() { Text = "&Check (Enter)", AutoSize = true };
    private readonly Button _show = new() { AutoSize = true };
    private readonly Button _next = new() { AutoSize = true };
    private readonly Label _keyboardHelp = new() { AutoSize = true, AccessibleName = "Listening keyboard help" };

    public ListeningCoachForm(DictionaryPackage package, ShortcutManager shortcuts, string? personalStateRoot = null)
    {
        _package = package ?? throw new ArgumentNullException(nameof(package));
        _shortcuts = shortcuts ?? throw new ArgumentNullException(nameof(shortcuts));
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
        RefreshShortcutPresentation();
        Load += (_, _) => StartOrResume();
        FormClosing += (_, _) => SafeSave();
        KeyDown += OnFormKeyDown;
    }

    private void BuildUi()
    {
        var menu = new MenuStrip();
        var progress = new ToolStripMenuItem("&Progress") { AccessibleName = "Listening progress" };
        var statistics = new ToolStripMenuItem("&Statistics...")
        {
            AccessibleName = "Listening statistics",
            AccessibleDescription = "Show Listening accuracy, mastery, attempts, replays, answer reveals and skips for the current study scope."
        };
        statistics.Click += (_, _) => ShowStatistics();
        var export = new ToolStripMenuItem("&Export Listening progress...") { AccessibleName = "Export Listening progress" };
        export.Click += (_, _) => ExportProgress();
        var import = new ToolStripMenuItem("&Import Listening progress...") { AccessibleName = "Import Listening progress" };
        import.Click += (_, _) => ImportProgress();
        progress.DropDownItems.Add(statistics);
        progress.DropDownItems.Add(new ToolStripSeparator());
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
        table.Controls.Add(_keyboardHelp);
        Controls.Add(table);
        table.BringToFront();
    }

    private void RefreshShortcutPresentation()
    {
        string replay = ShortcutFormatter.Format(_shortcuts.Get(ActionIds.ListeningReplay));
        string show = ShortcutFormatter.Format(_shortcuts.Get(ActionIds.ListeningShowAnswer));
        string next = ShortcutFormatter.Format(_shortcuts.Get(ActionIds.ListeningNext));
        _replay.Text = $"&Replay audio ({replay})";
        _show.Text = $"S&how answer ({show})";
        _next.Text = $"&Next ({next})";
        _keyboardHelp.Text = $"Keyboard: Enter check; {replay} replay; {show} show answer; {next} next; F1 help; Escape close.";
    }

    private void StartOrResume()
    {
        if (_engine.TryResumeCurrent(out ListeningExercise? exercise) && exercise is not null)
        {
            _answer.Clear();
            _answer.ReadOnly = false;
            SetStatus($"{StudyScopeIds.DisplayName(_state.ActiveScopeId)}. Resumed unfinished listening item. {ListeningCoachPresentation.BeforeCheck(exercise)}");
            SafeSave();
            _answer.Focus();
            BeginInvoke(new Action(() => PlayCurrent(countReplay: false)));
            return;
        }
        StartNext(autoPlay: true, recordSkip: false);
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
        if (!result.Completed)
        {
            SetStatus($"{result.Message} Replay: {ShortcutFormatter.Format(_shortcuts.Get(ActionIds.ListeningReplay))}; show answer: {ShortcutFormatter.Format(_shortcuts.Get(ActionIds.ListeningShowAnswer))}.");
            _answer.Focus();
        }
        else
        {
            SetStatus($"{result.Message} Next: {ShortcutFormatter.Format(_shortcuts.Get(ActionIds.ListeningNext))}.");
            _next.Focus();
        }
    }

    private void ShowAnswer()
    {
        try
        {
            _ = _engine.ShowAnswer();
            SafeSave();
            SetStatus($"{ListeningCoachPresentation.AfterShow(_engine.Current!)}. This review is recorded as needing more listening practice. Next: {ShortcutFormatter.Format(_shortcuts.Get(ActionIds.ListeningNext))}.");
            _next.Focus();
        }
        catch (Exception ex) { SetStatus(ex.Message); }
    }

    private void ShowStatistics()
    {
        try
        {
            ListeningStatistics stats = _engine.Statistics();
            string scope = StudyScopeIds.DisplayName(_state.ActiveScopeId);
            string message =
                $"Study scope: {scope}\n" +
                $"Available audio items: {stats.AvailableItems}\n" +
                $"Items reviewed: {stats.ReviewedItems}\n" +
                $"Completed reviews: {stats.CompletedReviews}\n" +
                $"Correct reviews: {stats.CorrectReviews}\n" +
                $"Accuracy: {stats.Accuracy:P1}\n" +
                $"Average mastery: {stats.AverageMastery:P1}\n" +
                $"Wrong attempts: {stats.WrongAttempts}\n" +
                $"Audio replays: {stats.ReplayCount}\n" +
                $"Answers shown: {stats.ShowAnswerUses}\n" +
                $"Skipped items: {stats.SkipCount}\n" +
                $"History entries in this scope: {stats.HistoryEntries}";
            MessageBox.Show(this, message, "Listening statistics", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        catch (Exception ex) { SetStatus($"Listening statistics could not be calculated: {ex.Message}"); }
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
            StartOrResume();
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
        if (e.KeyCode == Keys.F1 && e.Modifiers == Keys.None)
        {
            ShowHelp();
            e.Handled = true;
            return;
        }

        string? action = _shortcuts.FindAction(e.KeyData);
        switch (action)
        {
            case ActionIds.ListeningReplay:
                Replay();
                e.SuppressKeyPress = true;
                break;
            case ActionIds.ListeningShowAnswer:
                ShowAnswer();
                e.SuppressKeyPress = true;
                break;
            case ActionIds.ListeningNext:
                StartNext(autoPlay: true, recordSkip: true);
                e.SuppressKeyPress = true;
                break;
        }
    }

    private void ShowHelp()
    {
        string replay = ShortcutFormatter.Format(_shortcuts.Get(ActionIds.ListeningReplay));
        string show = ShortcutFormatter.Format(_shortcuts.Get(ActionIds.ListeningShowAnswer));
        string next = ShortcutFormatter.Format(_shortcuts.Get(ActionIds.ListeningNext));
        MessageBox.Show(this,
            $"Listening and Dictation uses installed offline British audio. The written answer is hidden until Enter checks it or the explicit Show answer command reveals it. Replay: {replay}. Show answer: {show}. Next: {next}. These commands can be changed in Training keyboard shortcuts. The Progress menu contains current-scope statistics and profile import/export. An unfinished item resumes after restart when its audio is still available. Listening progress is separate from Recall and Spelling.",
            "Listening and Dictation help", MessageBoxButtons.OK, MessageBoxIcon.Information);
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