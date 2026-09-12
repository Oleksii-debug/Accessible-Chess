namespace WordDeck;

internal static class StoryCourseRuntimeUi
{
    public static void Open(IWin32Window owner, DictionaryPackage dictionary)
    {
        ArgumentNullException.ThrowIfNull(dictionary);
        StoryCoursePackageDiscoveryResult discovery = StoryCoursePackageLoader.Discover(dictionary);
        if (discovery.Courses.Count == 0)
        {
            string detail = discovery.Errors.Count == 0
                ? "Схвалений локальний пакет курсу ще не встановлено. WordDeck не підмінює його тестовим або чернетковим контентом."
                : "Схвалений курс не відкрито. WordDeck відхилив небезпечний або невалідний пакет:\n\n" + string.Join("\n", discovery.Errors);
            MessageBox.Show(
                owner,
                detail,
                "WordDeck — курс недоступний",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information);
            return;
        }

        StoryCourseManifestContract? selected = discovery.Courses.Count == 1
            ? discovery.Courses[0]
            : SelectCourse(owner, discovery.Courses);
        if (selected is null) return;

        try
        {
            var store = new StoryCourseRuntimeStateStore(selected.CourseId);
            StoryCourseProgressContract progress = store.LoadOrCreate(selected);
            using var form = new StoryCourseRuntimeForm(selected, dictionary, store, progress, discovery.Errors);
            form.ShowDialog(owner);
        }
        catch (Exception ex)
        {
            MessageBox.Show(
                owner,
                "Курс не відкрито, бо WordDeck не зміг безпечно завантажити пакет або прогрес. Наявні файли прогресу не видалялися.\n\n" + ex.Message,
                "WordDeck захистив прогрес курсу",
                MessageBoxButtons.OK,
                MessageBoxIcon.Warning);
        }
    }

    private static StoryCourseManifestContract? SelectCourse(IWin32Window owner, IReadOnlyList<StoryCourseManifestContract> courses)
    {
        using var dialog = new Form
        {
            Text = "WordDeck — вибір курсу",
            Width = 620,
            Height = 180,
            StartPosition = FormStartPosition.CenterParent,
            MinimizeBox = false,
            MaximizeBox = false,
            AccessibleName = "Вибір курсу WordDeck"
        };
        var combo = new ComboBox
        {
            Dock = DockStyle.Top,
            DropDownStyle = ComboBoxStyle.DropDownList,
            AccessibleName = "Схвалений курс",
            TabIndex = 0
        };
        foreach (StoryCourseManifestContract course in courses) combo.Items.Add(new CourseChoice(course));
        combo.SelectedIndex = 0;

        var open = new Button
        {
            Text = "&Відкрити курс",
            AutoSize = true,
            AccessibleName = "Відкрити вибраний курс",
            TabIndex = 1
        };
        var cancel = new Button
        {
            Text = "&Скасувати",
            AutoSize = true,
            DialogResult = DialogResult.Cancel,
            AccessibleName = "Скасувати вибір курсу",
            TabIndex = 2
        };
        open.Click += (_, _) => dialog.DialogResult = DialogResult.OK;

        var buttons = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true };
        buttons.Controls.Add(open);
        buttons.Controls.Add(cancel);
        dialog.Controls.Add(buttons);
        dialog.Controls.Add(combo);
        dialog.AcceptButton = open;
        dialog.CancelButton = cancel;
        dialog.Shown += (_, _) => combo.Focus();

        return dialog.ShowDialog(owner) == DialogResult.OK && combo.SelectedItem is CourseChoice choice
            ? choice.Manifest
            : null;
    }

    private sealed record CourseChoice(StoryCourseManifestContract Manifest)
    {
        public override string ToString() => $"{Manifest.Title} ({Manifest.CourseId})";
    }
}

internal sealed class StoryCourseRuntimeForm : Form
{
    private sealed record UnitChoice(
        StoryCourseLevelContract Level,
        StoryCourseModuleContract Module,
        StoryCourseUnitContract Unit)
    {
        public override string ToString() => $"{Level.FrameworkLevel} — {Unit.Title}";
    }

    private sealed record ContextChoice(StoryCourseNarrativeContract Context)
    {
        public override string ToString() => Context.Kind == StoryCourseNarrativeKind.Dialogue
            ? $"Діалог — {Context.ContentId}"
            : $"Історія — {Context.ContentId}";
    }

    private sealed record TaskChoice(StoryCourseComprehensionTaskContract Task)
    {
        public override string ToString() => Task.Kind == StoryCourseComprehensionKind.BoundedResponse
            ? $"Вправа з перевіркою — {Task.TaskId}"
            : $"Відкрита відповідь — {Task.TaskId}";
    }

    private readonly StoryCourseManifestContract _manifest;
    private readonly DictionaryPackage _dictionary;
    private readonly StoryCourseRuntimeStateStore _store;
    private StoryCourseProgressContract _progress;
    private readonly IReadOnlyList<string> _packageWarnings;
    private readonly List<UnitChoice> _units;
    private bool _changing;

    private readonly ComboBox _unitCombo = new()
    {
        Dock = DockStyle.Top,
        DropDownStyle = ComboBoxStyle.DropDownList,
        AccessibleName = "Розділ курсу",
        TabIndex = 0
    };
    private readonly TextBox _unitInfo = new()
    {
        Dock = DockStyle.Fill,
        Multiline = true,
        ReadOnly = true,
        ScrollBars = ScrollBars.Vertical,
        AccessibleName = "Цілі та навчальні об'єкти розділу",
        TabStop = true,
        TabIndex = 1
    };
    private readonly ComboBox _contextCombo = new()
    {
        Dock = DockStyle.Top,
        DropDownStyle = ComboBoxStyle.DropDownList,
        AccessibleName = "Навчальний матеріал",
        TabIndex = 2
    };
    private readonly TextBox _contextText = new()
    {
        Dock = DockStyle.Fill,
        Multiline = true,
        ReadOnly = true,
        ScrollBars = ScrollBars.Vertical,
        AccessibleName = "Текст навчального матеріалу",
        TabStop = true,
        TabIndex = 3
    };
    private readonly Button _markRead = new()
    {
        Text = "Позначити матеріал &прочитаним",
        AutoSize = true,
        AccessibleName = "Позначити поточний навчальний матеріал прочитаним",
        TabIndex = 4
    };
    private readonly ComboBox _taskCombo = new()
    {
        Dock = DockStyle.Top,
        DropDownStyle = ComboBoxStyle.DropDownList,
        AccessibleName = "Вправа на розуміння",
        TabIndex = 5
    };
    private readonly TextBox _taskPrompt = new()
    {
        Dock = DockStyle.Fill,
        Multiline = true,
        ReadOnly = true,
        ScrollBars = ScrollBars.Vertical,
        AccessibleName = "Умова вправи",
        TabStop = true,
        TabIndex = 6
    };
    private readonly TextBox _answer = new()
    {
        Dock = DockStyle.Top,
        AccessibleName = "Відповідь на вправу",
        TabIndex = 7
    };
    private readonly Button _check = new()
    {
        Text = "&Перевірити відповідь",
        AutoSize = true,
        AccessibleName = "Перевірити відповідь",
        TabIndex = 8
    };
    private readonly Button _nextUnit = new()
    {
        Text = "&Наступний розділ",
        AutoSize = true,
        AccessibleName = "Перейти до наступного розділу курсу",
        TabIndex = 9
    };
    private readonly Button _close = new()
    {
        Text = "&Закрити",
        AutoSize = true,
        DialogResult = DialogResult.Cancel,
        AccessibleName = "Закрити курс",
        TabIndex = 10
    };
    private readonly TextBox _status = new()
    {
        Dock = DockStyle.Fill,
        Multiline = true,
        ReadOnly = true,
        ScrollBars = ScrollBars.Vertical,
        AccessibleName = "Результат і прогрес курсу",
        TabStop = true,
        TabIndex = 11
    };

    public StoryCourseRuntimeForm(
        StoryCourseManifestContract manifest,
        DictionaryPackage dictionary,
        StoryCourseRuntimeStateStore store,
        StoryCourseProgressContract progress,
        IReadOnlyList<string>? packageWarnings = null)
    {
        _manifest = manifest ?? throw new ArgumentNullException(nameof(manifest));
        _dictionary = dictionary ?? throw new ArgumentNullException(nameof(dictionary));
        _store = store ?? throw new ArgumentNullException(nameof(store));
        _progress = progress ?? throw new ArgumentNullException(nameof(progress));
        _packageWarnings = packageWarnings ?? Array.Empty<string>();
        StoryCourseContractValidator.Validate(_manifest, _dictionary);
        _progress.Validate();
        if (!_progress.CourseId.Equals(_manifest.CourseId, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Прогрес належить іншому курсу.");

        _units = FlattenUnits(_manifest);
        if (_units.Count == 0) throw new InvalidDataException("Схвалений курс не містить доступних розділів.");

        Text = $"WordDeck — {_manifest.Title}";
        Width = 980;
        Height = 780;
        MinimumSize = new Size(760, 600);
        StartPosition = FormStartPosition.CenterParent;
        AccessibleName = $"Курс WordDeck: {_manifest.Title}";
        KeyPreview = true;

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            Padding = new Padding(12),
            ColumnCount = 1,
            RowCount = 13
        };
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 18));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 30));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 18));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 16));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));

        root.Controls.Add(new Label { Text = "&Розділ курсу:", AutoSize = true }, 0, 0);
        root.Controls.Add(_unitCombo, 0, 1);
        root.Controls.Add(_unitInfo, 0, 2);
        root.Controls.Add(_contextCombo, 0, 3);
        root.Controls.Add(_contextText, 0, 4);
        root.Controls.Add(_markRead, 0, 5);
        root.Controls.Add(_taskCombo, 0, 6);
        root.Controls.Add(_taskPrompt, 0, 7);
        root.Controls.Add(_answer, 0, 8);
        root.Controls.Add(_check, 0, 9);

        var navigation = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true, WrapContents = true };
        navigation.Controls.Add(_nextUnit);
        navigation.Controls.Add(_close);
        root.Controls.Add(navigation, 0, 10);
        root.Controls.Add(_status, 0, 11);
        root.Controls.Add(new Label
        {
            AutoSize = true,
            Text = "Завершення матеріалу або вправи не означає mastery. Mastery може встановити лише окрема схвалена assessment/adaptive policy.",
            AccessibleName = "Правило mastery курсу"
        }, 0, 12);
        Controls.Add(root);

        AcceptButton = _check;
        CancelButton = _close;
        _unitCombo.SelectedIndexChanged += (_, _) => UnitChanged();
        _contextCombo.SelectedIndexChanged += (_, _) => ContextChanged();
        _taskCombo.SelectedIndexChanged += (_, _) => TaskChanged();
        _markRead.Click += (_, _) => MarkContextRead();
        _check.Click += (_, _) => CheckAnswer();
        _nextUnit.Click += (_, _) => MoveNextUnit();
        _close.Click += (_, _) => Close();
        FormClosing += (_, _) => PersistSafely();
        Shown += (_, _) =>
        {
            PopulateUnits();
            _contextText.Focus();
            _contextText.SelectionStart = 0;
            _contextText.SelectionLength = 0;
        };
    }

    private static List<UnitChoice> FlattenUnits(StoryCourseManifestContract manifest) =>
        manifest.Levels
            .OrderBy(level => level.Sequence)
            .SelectMany(level => level.Modules.SelectMany(module => module.Units.Select(unit => new UnitChoice(level, module, unit))))
            .ToList();

    private void PopulateUnits()
    {
        _changing = true;
        try
        {
            _unitCombo.Items.Clear();
            foreach (UnitChoice unit in _units) _unitCombo.Items.Add(unit);
            int index = _units.FindIndex(unit => unit.Unit.UnitId.Equals(_progress.ActiveUnitId, StringComparison.OrdinalIgnoreCase));
            _unitCombo.SelectedIndex = index >= 0 ? index : 0;
        }
        finally { _changing = false; }
        DisplayUnit(recordSelection: true);
    }

    private void UnitChanged()
    {
        if (_changing) return;
        DisplayUnit(recordSelection: true);
    }

    private void DisplayUnit(bool recordSelection)
    {
        if (_unitCombo.SelectedItem is not UnitChoice selected) return;
        if (recordSelection)
        {
            _progress = StoryCourseRuntimeStateStore.SelectUnit(_progress, selected.Level, selected.Module, selected.Unit);
            PersistSafely();
        }

        ResolvedStoryCourseTargets targets = StoryCourseIdentityResolver.Resolve(_dictionary, selected.Unit.Targets, selected.Unit.UnitId);
        string targetLines = targets.LexicalEntries.Count == 0
            ? "Лексичних targets немає."
            : string.Join(Environment.NewLine, targets.LexicalEntries.Select(entry => $"{entry.Id}: {entry.Source} — {entry.Target} ({entry.Level})"));
        string grammarLines = targets.GrammarSkillIds.Count == 0
            ? "Граматичних targets немає."
            : string.Join(", ", targets.GrammarSkillIds);
        string objectives = string.Join(", ", selected.Unit.ObjectiveIds);
        _unitInfo.Text =
            $"Рівень: {selected.Level.FrameworkLevel}. Модуль: {selected.Module.Title}. Розділ: {selected.Unit.Title}." + Environment.NewLine +
            $"Цілі: {objectives}." + Environment.NewLine +
            "Лексичні stable IDs:" + Environment.NewLine + targetLines + Environment.NewLine +
            "Grammar stable IDs: " + grammarLines + Environment.NewLine +
            $"Provenance: {selected.Unit.Provenance.Origin}; {selected.Unit.Provenance.SourceId}; rights: {selected.Unit.Provenance.LicenseOrRights}.";

        PopulateContexts(selected.Unit);
        PopulateTasks(selected.Unit);
        UpdateProgressStatus("Розділ відкрито. Оберіть матеріал і вправу клавішею Tab.");
    }

    private void PopulateContexts(StoryCourseUnitContract unit)
    {
        _changing = true;
        try
        {
            _contextCombo.Items.Clear();
            foreach (StoryCourseNarrativeContract context in unit.DialogueOrStory) _contextCombo.Items.Add(new ContextChoice(context));
            _contextCombo.SelectedIndex = _contextCombo.Items.Count == 0 ? -1 : 0;
        }
        finally { _changing = false; }
        ShowContext();
    }

    private void PopulateTasks(StoryCourseUnitContract unit)
    {
        _changing = true;
        try
        {
            _taskCombo.Items.Clear();
            foreach (StoryCourseComprehensionTaskContract task in unit.ComprehensionTasks) _taskCombo.Items.Add(new TaskChoice(task));
            _taskCombo.SelectedIndex = _taskCombo.Items.Count == 0 ? -1 : 0;
        }
        finally { _changing = false; }
        ShowTask();
    }

    private void ContextChanged()
    {
        if (_changing) return;
        ShowContext();
    }

    private void ShowContext()
    {
        if (_contextCombo.SelectedItem is not ContextChoice selected)
        {
            _contextText.Clear();
            _markRead.Enabled = false;
            return;
        }
        _contextText.Text = selected.Context.Text;
        _markRead.Enabled = true;
    }

    private void TaskChanged()
    {
        if (_changing) return;
        ShowTask();
    }

    private void ShowTask()
    {
        if (_taskCombo.SelectedItem is not TaskChoice selected)
        {
            _taskPrompt.Clear();
            _answer.Enabled = false;
            _check.Enabled = false;
            return;
        }

        _taskPrompt.Text = selected.Task.Prompt;
        _answer.Clear();
        bool bounded = selected.Task.Kind == StoryCourseComprehensionKind.BoundedResponse;
        _answer.Enabled = bounded;
        _check.Enabled = bounded;
        if (!bounded)
            UpdateProgressStatus("Це відкрита відповідь. WordDeck не підмінює зовнішню evidence policy прихованим списком відповідей і не нараховує mastery автоматично.");
    }

    private void MarkContextRead()
    {
        if (_contextCombo.SelectedItem is not ContextChoice selected) return;
        _progress = StoryCourseRuntimeStateStore.RecordNarrativeCompletion(_progress, selected.Context);
        PersistSafely();
        UpdateProgressStatus("Матеріал позначено прочитаним. Це completion/exposure, а не доказ mastery.");
    }

    private void CheckAnswer()
    {
        if (_taskCombo.SelectedItem is not TaskChoice selected || selected.Task.Kind != StoryCourseComprehensionKind.BoundedResponse) return;
        if (string.IsNullOrWhiteSpace(_answer.Text))
        {
            UpdateProgressStatus("Введіть відповідь. Порожнє натискання Enter не змінює навчальний прогрес.");
            _answer.Focus();
            return;
        }

        bool accepted = StoryCourseRuntimeStateStore.IsAcceptedBoundedAnswer(selected.Task, _answer.Text);
        if (accepted)
        {
            _progress = StoryCourseRuntimeStateStore.RecordBoundedComprehensionSuccess(_progress, selected.Task);
            PersistSafely();
            UpdateProgressStatus("Правильно. Comprehension evidence збережено для цілей цієї вправи. Mastery не змінено.");
        }
        else
        {
            UpdateProgressStatus("Відповідь поки не прийнята. Прочитайте матеріал і спробуйте ще раз. Невдала спроба не перетворюється на mastery або completion.");
        }
        _answer.Focus();
        _answer.SelectAll();
    }

    private void MoveNextUnit()
    {
        if (_unitCombo.SelectedIndex < 0) return;
        int next = Math.Min(_unitCombo.SelectedIndex + 1, _unitCombo.Items.Count - 1);
        if (next == _unitCombo.SelectedIndex)
        {
            UpdateProgressStatus("Це останній встановлений розділ цього курсу.");
            return;
        }
        _unitCombo.SelectedIndex = next;
        _contextText.Focus();
        _contextText.SelectionStart = 0;
        _contextText.SelectionLength = 0;
    }

    private void UpdateProgressStatus(string message)
    {
        int completedContexts = _progress.CompletedContentIds.Count;
        int completedTasks = _progress.CompletedTaskIds.Count;
        int mastery = _progress.ObjectiveProgress.Values.Count(value => value.MasteryDecision == StoryCourseMasteryDecision.Mastered);
        string warnings = _packageWarnings.Count == 0
            ? string.Empty
            : Environment.NewLine + "Інші локальні package-файли були відхилені: " + string.Join(" | ", _packageWarnings);
        _status.Text =
            message + Environment.NewLine +
            $"Збережений прогрес: матеріалів завершено {completedContexts}; вправ із валідним evidence {completedTasks}; mastery-рішень {mastery}." +
            warnings;
    }

    private void PersistSafely()
    {
        try { _store.Save(_progress); }
        catch (Exception ex)
        {
            _status.Text = "Прогрес курсу не вдалося безпечно зберегти. Наявні файли не видалялися. " + ex.Message;
        }
    }
}
