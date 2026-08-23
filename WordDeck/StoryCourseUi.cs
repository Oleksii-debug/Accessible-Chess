namespace WordDeck;

internal sealed class StoryCourseForm : Form
{
    private sealed record UnitChoice(StoryUnitDefinition Unit)
    {
        public override string ToString() => $"{Unit.Cefr} — {Unit.Title}";
    }

    private sealed record ChapterChoice(ResolvedStoryChapter Chapter)
    {
        public override string ToString() => Chapter.Definition.Title;
    }

    private sealed record TaskChoice(CourseTaskDefinition Task)
    {
        public override string ToString() => $"{Task.Kind}: {Task.Id}";
    }

    private readonly ResolvedStoryCatalog _catalog;
    private readonly StoryCourseStateStore _store;
    private readonly StoryCourseState _state;
    private readonly ComboBox _unitCombo = new()
    {
        DropDownStyle = ComboBoxStyle.DropDownList,
        Dock = DockStyle.Top,
        AccessibleName = "Narrative Course unit"
    };
    private readonly ComboBox _chapterCombo = new()
    {
        DropDownStyle = ComboBoxStyle.DropDownList,
        Dock = DockStyle.Top,
        AccessibleName = "Story chapter"
    };
    private readonly TextBox _overview = new()
    {
        ReadOnly = true,
        Multiline = true,
        Dock = DockStyle.Fill,
        ScrollBars = ScrollBars.Vertical,
        AccessibleName = "Ukrainian unit and chapter explanation",
        TabStop = true
    };
    private readonly TextBox _story = new()
    {
        ReadOnly = true,
        Multiline = true,
        Dock = DockStyle.Fill,
        ScrollBars = ScrollBars.Vertical,
        AccessibleName = "English story text",
        TabStop = true
    };
    private readonly TextBox _targets = new()
    {
        ReadOnly = true,
        Multiline = true,
        Dock = DockStyle.Fill,
        ScrollBars = ScrollBars.Vertical,
        AccessibleName = "Story target vocabulary",
        TabStop = true
    };
    private readonly Label _provenance = new()
    {
        AutoSize = true,
        MaximumSize = new Size(900, 0),
        AccessibleName = "Story source and provenance"
    };
    private readonly ComboBox _taskCombo = new()
    {
        DropDownStyle = ComboBoxStyle.DropDownList,
        Dock = DockStyle.Top,
        AccessibleName = "Narrative Course task"
    };
    private readonly TextBox _taskPrompt = new()
    {
        ReadOnly = true,
        Multiline = true,
        Dock = DockStyle.Fill,
        AccessibleName = "Ukrainian course task prompt",
        TabStop = true
    };
    private readonly TextBox _answer = new()
    {
        Dock = DockStyle.Top,
        AccessibleName = "Type the English course answer"
    };
    private readonly Label _status = new()
    {
        AutoSize = true,
        MaximumSize = new Size(900, 0),
        AccessibleName = "Story and Narrative Course status"
    };
    private readonly Button _check = new() { Text = "&Check task", AutoSize = true, AccessibleName = "Check Narrative Course task" };
    private readonly Button _previous = new() { Text = "&Previous chapter", AutoSize = true, AccessibleName = "Previous Story chapter" };
    private readonly Button _next = new() { Text = "&Next chapter", AutoSize = true, AccessibleName = "Next Story chapter" };
    private readonly Button _recommended = new() { Text = "Next &recommended", AutoSize = true, AccessibleName = "Open next recommended Story chapter" };
    private readonly Button _complete = new() { Text = "Mark &complete and route practice", AutoSize = true, AccessibleName = "Mark Story chapter complete and queue follow-up practice" };

    private bool _changingSelection;
    private bool _taskHadWrongAttempt;
    private ResolvedStoryChapter _current;

    public StoryCourseForm(DictionaryPackage dictionary, StoryCourseStateStore store, StoryCourseState state)
    {
        _catalog = StoryCourseCatalog.Resolve(dictionary ?? throw new ArgumentNullException(nameof(dictionary)));
        _store = store ?? throw new ArgumentNullException(nameof(store));
        _state = StoryCourseStateStore.Normalize(state ?? throw new ArgumentNullException(nameof(state)));
        _current = ResolveInitialChapter();

        Text = "WordDeck Story and Narrative Course";
        Width = 1040;
        Height = 760;
        MinimumSize = new Size(760, 560);
        StartPosition = FormStartPosition.CenterParent;
        KeyPreview = true;
        AccessibleName = "WordDeck Story and Narrative Course";

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            Padding = new Padding(14),
            RowCount = 12,
            ColumnCount = 1
        };
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 20));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 35));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 15));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 15));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));

        var selectors = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, ColumnCount = 2, RowCount = 2 };
        selectors.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        selectors.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
        selectors.Controls.Add(new Label { Text = "Course &unit:", AutoSize = true }, 0, 0);
        selectors.Controls.Add(new Label { Text = "Story &chapter:", AutoSize = true }, 1, 0);
        selectors.Controls.Add(_unitCombo, 0, 1);
        selectors.Controls.Add(_chapterCombo, 1, 1);
        root.Controls.Add(selectors, 0, 0);
        root.Controls.Add(_provenance, 0, 1);
        root.Controls.Add(_overview, 0, 2);
        root.Controls.Add(_story, 0, 3);
        root.Controls.Add(_targets, 0, 4);
        root.Controls.Add(new Label { Text = "Course task:", AutoSize = true }, 0, 5);
        root.Controls.Add(_taskCombo, 0, 6);
        root.Controls.Add(_taskPrompt, 0, 7);
        root.Controls.Add(_answer, 0, 8);

        var taskButtons = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true, WrapContents = true };
        taskButtons.Controls.Add(_check);
        root.Controls.Add(taskButtons, 0, 9);

        var navigation = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true, WrapContents = true };
        navigation.Controls.Add(_previous);
        navigation.Controls.Add(_next);
        navigation.Controls.Add(_recommended);
        navigation.Controls.Add(_complete);
        root.Controls.Add(navigation, 0, 10);
        root.Controls.Add(_status, 0, 11);
        Controls.Add(root);

        AcceptButton = _check;
        _unitCombo.SelectedIndexChanged += (_, _) => UnitChanged();
        _chapterCombo.SelectedIndexChanged += (_, _) => ChapterChanged();
        _taskCombo.SelectedIndexChanged += (_, _) => TaskChanged();
        _check.Click += (_, _) => CheckTask();
        _previous.Click += (_, _) => MoveChapter(-1);
        _next.Click += (_, _) => MoveChapter(1);
        _recommended.Click += (_, _) => OpenRecommended();
        _complete.Click += (_, _) => CompleteCurrent();
        FormClosing += (_, _) => PersistSafely();
        Shown += (_, _) =>
        {
            PopulateUnitsAndSelectCurrent();
            _story.Focus();
            _story.SelectionStart = 0;
            _story.SelectionLength = 0;
        };
    }

    private ResolvedStoryChapter ResolveInitialChapter()
    {
        if (!string.IsNullOrWhiteSpace(_state.ActiveChapterId) && _catalog.ChaptersById.TryGetValue(_state.ActiveChapterId, out ResolvedStoryChapter? saved))
            return saved;
        return _catalog.Units
            .SelectMany(unit => unit.Chapters)
            .Select(chapter => _catalog.GetChapter(chapter.Id))
            .First();
    }

    private void PopulateUnitsAndSelectCurrent()
    {
        _changingSelection = true;
        try
        {
            _unitCombo.Items.Clear();
            foreach (StoryUnitDefinition unit in _catalog.Units) _unitCombo.Items.Add(new UnitChoice(unit));
            int unitIndex = _catalog.Units.ToList().FindIndex(unit => unit.Id.Equals(_current.Definition.UnitId, StringComparison.OrdinalIgnoreCase));
            _unitCombo.SelectedIndex = Math.Max(0, unitIndex);
            PopulateChapters(_catalog.Units[Math.Max(0, unitIndex)], _current.Definition.Id);
        }
        finally { _changingSelection = false; }
        DisplayCurrent(recordOpen: true);
    }

    private void PopulateChapters(StoryUnitDefinition unit, string? selectedChapterId = null)
    {
        _chapterCombo.Items.Clear();
        foreach (StoryChapterDefinition definition in unit.Chapters)
            _chapterCombo.Items.Add(new ChapterChoice(_catalog.GetChapter(definition.Id)));
        int chapterIndex = unit.Chapters.ToList().FindIndex(chapter => chapter.Id.Equals(selectedChapterId, StringComparison.OrdinalIgnoreCase));
        _chapterCombo.SelectedIndex = chapterIndex >= 0 ? chapterIndex : 0;
        if (_chapterCombo.SelectedItem is ChapterChoice selected) _current = selected.Chapter;
    }

    private void UnitChanged()
    {
        if (_changingSelection || _unitCombo.SelectedItem is not UnitChoice selected) return;
        _changingSelection = true;
        try { PopulateChapters(selected.Unit); }
        finally { _changingSelection = false; }
        DisplayCurrent(recordOpen: true);
    }

    private void ChapterChanged()
    {
        if (_changingSelection || _chapterCombo.SelectedItem is not ChapterChoice selected) return;
        _current = selected.Chapter;
        DisplayCurrent(recordOpen: true);
    }

    private void DisplayCurrent(bool recordOpen)
    {
        StoryUnitDefinition unit = _catalog.Units.First(x => x.Id.Equals(_current.Definition.UnitId, StringComparison.OrdinalIgnoreCase));
        if (recordOpen)
        {
            StoryCourseStateStore.RecordOpen(_state, _catalog, _current, DateTimeOffset.UtcNow);
            PersistSafely();
        }
        _overview.Text = unit.UkrainianOverview + Environment.NewLine + Environment.NewLine + _current.Definition.UkrainianExplanation;
        _story.Text = _current.Definition.EnglishStory;
        _targets.Text = "Target vocabulary:" + Environment.NewLine + string.Join(
            Environment.NewLine,
            _current.Targets.Select(target => $"{target.Entry.Source} — {target.Entry.Target} ({target.Entry.Level}); planned repetition: {target.MinimumRepetitions}+"));
        StoryProvenance source = _current.Definition.Provenance;
        _provenance.Text = $"Content status: {source.Origin}. Source: {source.SourceLabel}. License/status: {source.License}. Attribution: {source.Attribution}.";
        PopulateTasks();
        StoryChapterProgress progress = _state.ChapterProgress.GetValueOrDefault(_current.Definition.Id) ?? new StoryChapterProgress();
        _status.Text = $"{_current.Definition.Cefr} chapter. Opened {progress.Opens} time(s); completed {progress.Completions} time(s). All targets are bound to dictionary stable IDs. Story content is offline.";
    }

    private void PopulateTasks()
    {
        _changingSelection = true;
        try
        {
            _taskCombo.Items.Clear();
            foreach (CourseTaskDefinition task in _current.Definition.Tasks) _taskCombo.Items.Add(new TaskChoice(task));
            int savedIndex = _current.Definition.Tasks.ToList().FindIndex(task => task.Id.Equals(_state.ActiveTaskId, StringComparison.OrdinalIgnoreCase));
            _taskCombo.SelectedIndex = savedIndex >= 0 ? savedIndex : 0;
        }
        finally { _changingSelection = false; }
        _taskHadWrongAttempt = false;
        ShowSelectedTask();
    }

    private void TaskChanged()
    {
        if (_changingSelection) return;
        _taskHadWrongAttempt = false;
        ShowSelectedTask();
    }

    private void ShowSelectedTask()
    {
        if (_taskCombo.SelectedItem is not TaskChoice selected)
        {
            _taskPrompt.Clear();
            _answer.Enabled = false;
            _check.Enabled = false;
            return;
        }
        _state.ActiveTaskId = selected.Task.Id;
        _taskPrompt.Text = selected.Task.PromptUkrainian;
        _answer.Enabled = true;
        _check.Enabled = true;
        _answer.Clear();
        PersistSafely();
    }

    private void CheckTask()
    {
        if (_taskCombo.SelectedItem is not TaskChoice selected) return;
        if (string.IsNullOrWhiteSpace(_answer.Text))
        {
            _status.Text = "Type an English answer first. Blank Enter does not change learning progress.";
            _answer.Focus();
            return;
        }
        bool accepted = StoryTaskEvaluator.IsAccepted(selected.Task, _answer.Text);
        bool firstTry = accepted && !_taskHadWrongAttempt;
        StoryCourseStateStore.RecordTaskAttempt(_state, _current, selected.Task, firstTry);
        if (!accepted) _taskHadWrongAttempt = true;
        PersistSafely();
        _status.Text = accepted
            ? (firstTry ? "Correct on the first try." : "Correct after another attempt.")
            : "Not accepted yet. Read the story again and try once more; the answer was recorded only as a course-task attempt.";
        _answer.Focus();
        _answer.SelectAll();
    }

    private void CompleteCurrent()
    {
        DateTimeOffset now = DateTimeOffset.UtcNow;
        StoryCourseStateStore.RecordCompletion(_state, _current, now);
        IReadOnlyList<StoryPracticeRoute> routes = StoryCoursePracticeRouter.BuildPostStoryRoutes(_catalog, _current);
        _store.QueuePracticeRoutes(_state, routes);
        StoryChapterProgress progress = _state.ChapterProgress[_current.Definition.Id];
        _status.Text = $"Chapter completed {progress.Completions} time(s). Follow-up Recall, Spelling, Sentence and Grammar routes were queued with the same stable target IDs. Destinations may consume these routes as their worker lanes add deep-link support.";
    }

    private void OpenRecommended()
    {
        var context = new StorySchedulingContext(
            new Dictionary<string, double>(StringComparer.OrdinalIgnoreCase),
            new Dictionary<string, double>(StringComparer.OrdinalIgnoreCase));
        ResolvedStoryChapter next = StoryCourseScheduler.SelectNext(_catalog, _state, context);
        SelectChapter(next.Definition.Id);
        _status.Text = "Opened the deterministic next Story chapter. The scheduler prioritizes incomplete chapters now and accepts lexical/grammar weakness evidence when the shared learner router supplies it.";
    }

    private void MoveChapter(int delta)
    {
        List<ResolvedStoryChapter> chapters = _catalog.Units
            .SelectMany(unit => unit.Chapters)
            .Select(definition => _catalog.GetChapter(definition.Id))
            .ToList();
        int index = chapters.FindIndex(chapter => chapter.Definition.Id.Equals(_current.Definition.Id, StringComparison.OrdinalIgnoreCase));
        if (index < 0) return;
        int next = Math.Clamp(index + delta, 0, chapters.Count - 1);
        if (next == index)
        {
            _status.Text = delta < 0 ? "This is the first Story chapter." : "This is the last built-in Story chapter currently installed.";
            return;
        }
        SelectChapter(chapters[next].Definition.Id);
    }

    private void SelectChapter(string chapterId)
    {
        ResolvedStoryChapter target = _catalog.GetChapter(chapterId);
        _current = target;
        _changingSelection = true;
        try
        {
            int unitIndex = _catalog.Units.ToList().FindIndex(unit => unit.Id.Equals(target.Definition.UnitId, StringComparison.OrdinalIgnoreCase));
            _unitCombo.SelectedIndex = unitIndex;
            PopulateChapters(_catalog.Units[unitIndex], target.Definition.Id);
        }
        finally { _changingSelection = false; }
        DisplayCurrent(recordOpen: true);
        _story.Focus();
        _story.SelectionStart = 0;
        _story.SelectionLength = 0;
    }

    private void PersistSafely()
    {
        try { _store.Save(_state); }
        catch (Exception ex)
        {
            _status.Text = "Story/Course progress could not be saved safely. Existing state files were not intentionally deleted. " + ex.Message;
        }
    }
}
