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
            var learnerStore = new LearnerCourseStateStore();
            var learnerBridge = new StoryCourseLearnerStateBridge(learnerStore);
            using var form = new StoryCourseRuntimeForm(
                selected,
                dictionary,
                store,
                progress,
                learnerStore,
                learnerBridge,
                discovery.Errors);
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

    private sealed record ProductiveChoice(StoryCourseProductiveTaskContract Task)
    {
        public override string ToString() => Task.Channel switch
        {
            StoryCourseProductiveChannel.Writing => $"Writing — {Task.TaskId}",
            StoryCourseProductiveChannel.Speaking => $"Speaking — {Task.TaskId}",
            StoryCourseProductiveChannel.Mixed => $"Speaking + Writing — {Task.TaskId}",
            _ => $"Productive task — {Task.TaskId}"
        };
    }

    private readonly StoryCourseManifestContract _manifest;
    private readonly DictionaryPackage _dictionary;
    private readonly StoryCourseRuntimeStateStore _store;
    private readonly LearnerCourseStateStore _learnerStore;
    private readonly StoryCourseLearnerStateBridge _learnerBridge;
    private StoryCourseProgressContract _progress;
    private StoryCourseProgressContract _lastPersistedProgress;
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
        AccessibleName = "Умова вправи на розуміння",
        TabStop = true,
        TabIndex = 6
    };
    private readonly TextBox _answer = new()
    {
        Dock = DockStyle.Top,
        AccessibleName = "Відповідь на вправу на розуміння",
        TabIndex = 7
    };
    private readonly Button _check = new()
    {
        Text = "&Перевірити відповідь",
        AutoSize = true,
        AccessibleName = "Перевірити відповідь",
        TabIndex = 8
    };
    private readonly ComboBox _productiveCombo = new()
    {
        Dock = DockStyle.Top,
        DropDownStyle = ComboBoxStyle.DropDownList,
        AccessibleName = "Продуктивна вправа Speaking або Writing",
        TabIndex = 9
    };
    private readonly TextBox _productivePrompt = new()
    {
        Dock = DockStyle.Fill,
        Multiline = true,
        ReadOnly = true,
        ScrollBars = ScrollBars.Vertical,
        AccessibleName = "Умова продуктивної вправи",
        TabStop = true,
        TabIndex = 10
    };
    private readonly TextBox _productiveResponse = new()
    {
        Dock = DockStyle.Fill,
        Multiline = true,
        AcceptsReturn = true,
        ScrollBars = ScrollBars.Vertical,
        AccessibleName = "Ваша відповідь на продуктивну вправу",
        TabIndex = 11
    };
    private readonly Button _submitProductive = new()
    {
        Text = "&Зберегти практику",
        AutoSize = true,
        AccessibleName = "Зберегти продуктивну практику",
        TabIndex = 12
    };
    private readonly Button _nextUnit = new()
    {
        Text = "&Наступний розділ",
        AutoSize = true,
        AccessibleName = "Перейти до наступного розділу курсу",
        TabIndex = 13
    };
    private readonly Button _close = new()
    {
        Text = "&Закрити",
        AutoSize = true,
        DialogResult = DialogResult.Cancel,
        AccessibleName = "Закрити курс",
        TabIndex = 14
    };
    private readonly TextBox _status = new()
    {
        Dock = DockStyle.Fill,
        Multiline = true,
        ReadOnly = true,
        ScrollBars = ScrollBars.Vertical,
        AccessibleName = "Результат і прогрес курсу",
        TabStop = true,
        TabIndex = 15
    };

    public StoryCourseRuntimeForm(
        StoryCourseManifestContract manifest,
        DictionaryPackage dictionary,
        StoryCourseRuntimeStateStore store,
        StoryCourseProgressContract progress,
        LearnerCourseStateStore learnerStore,
        StoryCourseLearnerStateBridge learnerBridge,
        IReadOnlyList<string>? packageWarnings = null)
    {
        _manifest = manifest ?? throw new ArgumentNullException(nameof(manifest));
        _dictionary = dictionary ?? throw new ArgumentNullException(nameof(dictionary));
        _store = store ?? throw new ArgumentNullException(nameof(store));
        _progress = progress ?? throw new ArgumentNullException(nameof(progress));
        _lastPersistedProgress = _progress;
        _learnerStore = learnerStore ?? throw new ArgumentNullException(nameof(learnerStore));
        _learnerBridge = learnerBridge ?? throw new ArgumentNullException(nameof(learnerBridge));
        _packageWarnings = packageWarnings ?? Array.Empty<string>();
        StoryCourseContractValidator.Validate(_manifest, _dictionary);
        _progress.Validate();
        if (!_progress.CourseId.Equals(_manifest.CourseId, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Прогрес належить іншому курсу.");

        _units = FlattenUnits(_manifest);
        if (_units.Count == 0) throw new InvalidDataException("Схвалений курс не містить доступних розділів.");

        Text = $"WordDeck — {_manifest.Title}";
        Width = 1000;
        Height = 860;
        MinimumSize = new Size(780, 680);
        StartPosition = FormStartPosition.CenterParent;
        AccessibleName = $"Курс WordDeck: {_manifest.Title}";
        KeyPreview = true;

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            Padding = new Padding(12),
            ColumnCount = 1,
            RowCount = 17,
            AutoScroll = true
        };
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 12));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 18));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 12));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 12));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 18));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 14));
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
        root.Controls.Add(_productiveCombo, 0, 10);
        root.Controls.Add(_productivePrompt, 0, 11);
        root.Controls.Add(_productiveResponse, 0, 12);
        root.Controls.Add(_submitProductive, 0, 13);

        var navigation = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true, WrapContents = true };
        navigation.Controls.Add(_nextUnit);
        navigation.Controls.Add(_close);
        root.Controls.Add(navigation, 0, 14);
        root.Controls.Add(_status, 0, 15);
        root.Controls.Add(new Label
        {
            AutoSize = true,
            Text = "Завершення матеріалу, практика або введений текст не означають mastery. Speaking не зараховується без реального мовленнєвого каналу. Mastery може встановити лише окрема схвалена assessment/adaptive policy.",
            AccessibleName = "Правило mastery та Speaking курсу"
        }, 0, 16);
        Controls.Add(root);

        AcceptButton = _check;
        CancelButton = _close;
        _unitCombo.SelectedIndexChanged += (_, _) => UnitChanged();
        _contextCombo.SelectedIndexChanged += (_, _) => ContextChanged();
        _taskCombo.SelectedIndexChanged += (_, _) => TaskChanged();
        _productiveCombo.SelectedIndexChanged += (_, _) => ProductiveTaskChanged();
        _markRead.Click += (_, _) => MarkContextRead();
        _check.Click += (_, _) => CheckAnswer();
        _submitProductive.Click += (_, _) => SubmitProductivePractice();
        _nextUnit.Click += (_, _) => MoveNextUnit();
        _close.Click += (_, _) => Close();
        FormClosing += (_, _) => { _ = PersistSafely(out _); };
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

    internal static ResolvedStoryCourseTargets ResolveUnitTargetsForDisplay(
        DictionaryPackage dictionary,
        StoryCourseManifestContract manifest,
        string unitId)
    {
        ArgumentNullException.ThrowIfNull(dictionary);
        ArgumentNullException.ThrowIfNull(manifest);
        StoryCourseContractId.Require(unitId, "learner runtime unit id");

        StoryCourseUnitContract[] matchingUnits = manifest.Levels
            .SelectMany(level => level.Modules)
            .SelectMany(module => module.Units)
            .Where(unit => unit.UnitId.Equals(unitId, StringComparison.OrdinalIgnoreCase))
            .ToArray();

        if (matchingUnits.Length != 1)
            throw new InvalidDataException(
                $"Learner runtime could not resolve exactly one manifest-owned unit '{unitId}'.");

        StoryCourseUnitContract unit = matchingUnits[0];
        return StoryCourseIdentityResolver.Resolve(
            dictionary,
            unit.Targets,
            unit.UnitId,
            manifest.CurriculumAuthority);
    }

    internal static StoryCourseProductiveSubmissionKind SubmissionKindForCurrentUi(StoryCourseProductiveChannel channel) =>
        channel switch
        {
            StoryCourseProductiveChannel.Writing => StoryCourseProductiveSubmissionKind.RequiredChannelPerformance,
            StoryCourseProductiveChannel.Speaking => StoryCourseProductiveSubmissionKind.TypedFallback,
            StoryCourseProductiveChannel.Mixed => StoryCourseProductiveSubmissionKind.TypedFallback,
            _ => throw new InvalidDataException($"Unsupported productive channel '{channel}'.")
        };

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
        string? learnerStateWarning = null;
        string? legacyProgressWarning = null;
        if (recordSelection)
        {
            _progress = StoryCourseRuntimeStateStore.SelectUnit(_progress, selected.Level, selected.Module, selected.Unit);
            if (!PersistSafely(out string? persistError))
                legacyProgressWarning = persistError;
            try
            {
                _learnerBridge.RecordUnitSelection(_manifest, selected.Module.ModuleId, selected.Unit.UnitId);
            }
            catch (Exception ex)
            {
                learnerStateWarning = "Закладку нового learner-state не збережено: " + ex.Message;
            }
        }

        ResolvedStoryCourseTargets targets = ResolveUnitTargetsForDisplay(
            _dictionary,
            _manifest,
            selected.Unit.UnitId);
        string targetLines = targets.LexicalEntries.Count == 0
            ? "Лексичних targets немає."
            : string.Join(Environment.NewLine, targets.LexicalEntries.Select(entry => $"{entry.Id}: {entry.Source} — {entry.Target} ({entry.Level})"));
        string grammarLines = targets.GrammarSkillIds.Count == 0
            ? "Граматичних targets немає."
            : string.Join(", ", targets.GrammarSkillIds);
        string courseTargetLines = targets.SkillTargets.Count == 0
            ? "Курсових target IDs немає."
            : string.Join(Environment.NewLine, targets.SkillTargets.Select(target => $"{target.Domain}: {target.TargetRef}"));
        string objectives = string.Join(", ", selected.Unit.ObjectiveIds);
        _unitInfo.Text =
            $"Рівень: {selected.Level.FrameworkLevel}. Модуль: {selected.Module.Title}. Розділ: {selected.Unit.Title}." + Environment.NewLine +
            $"Цілі: {objectives}." + Environment.NewLine +
            "Лексичні stable IDs:" + Environment.NewLine + targetLines + Environment.NewLine +
            "Grammar stable IDs: " + grammarLines + Environment.NewLine +
            "Course target IDs:" + Environment.NewLine + courseTargetLines + Environment.NewLine +
            $"Provenance: {selected.Unit.Provenance.Origin}; {selected.Unit.Provenance.SourceId}; rights: {selected.Unit.Provenance.LicenseOrRights}.";

        PopulateContexts(selected.Unit);
        PopulateTasks(selected.Unit);
        PopulateProductiveTasks(selected.Unit);
        string opened = "Розділ відкрито. Tab переходить між матеріалом, comprehension і productive practice. Поетапні productive-завдання з answer-bearing support з'являються лише після потрібної попередньої required-channel submission.";
        if (!string.IsNullOrWhiteSpace(legacyProgressWarning)) opened += Environment.NewLine + legacyProgressWarning;
        if (!string.IsNullOrWhiteSpace(learnerStateWarning)) opened += Environment.NewLine + learnerStateWarning;
        UpdateProgressStatus(opened);
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

    private void PopulateProductiveTasks(StoryCourseUnitContract unit, string? preferredTaskId = null)
    {
        _changing = true;
        try
        {
            _productiveCombo.Items.Clear();
            LearnerCourseState learnerState = _learnerStore.Load();
            IReadOnlyList<StoryCourseProductiveTaskContract> visible =
                StoryCourseProductiveRevealPolicy.VisibleTasks(_manifest, unit, learnerState);
            foreach (StoryCourseProductiveTaskContract task in visible)
                _productiveCombo.Items.Add(new ProductiveChoice(task));

            int preferred = -1;
            if (!string.IsNullOrWhiteSpace(preferredTaskId))
            {
                for (int index = 0; index < _productiveCombo.Items.Count; index++)
                {
                    if (_productiveCombo.Items[index] is ProductiveChoice choice &&
                        choice.Task.TaskId.Equals(preferredTaskId, StringComparison.OrdinalIgnoreCase))
                    {
                        preferred = index;
                        break;
                    }
                }
            }
            _productiveCombo.SelectedIndex = preferred >= 0
                ? preferred
                : (_productiveCombo.Items.Count == 0 ? -1 : 0);
        }
        finally { _changing = false; }
        ShowProductiveTask();
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
            UpdateProgressStatus("Це відкрита comprehension-відповідь. WordDeck не підмінює зовнішню evidence policy прихованим списком відповідей і не нараховує mastery автоматично.");
    }

    private void ProductiveTaskChanged()
    {
        if (_changing) return;
        ShowProductiveTask();
    }

    private void ShowProductiveTask()
    {
        _productiveResponse.Clear();
        if (_productiveCombo.SelectedItem is not ProductiveChoice selected)
        {
            _productivePrompt.Clear();
            _productiveResponse.Enabled = false;
            _submitProductive.Enabled = false;
            return;
        }

        _productiveResponse.Enabled = true;
        _submitProductive.Enabled = true;
        if (selected.Task.Channel == StoryCourseProductiveChannel.Writing)
        {
            _productivePrompt.Text = selected.Task.Prompt + Environment.NewLine + Environment.NewLine +
                "Канал: Writing. Напишіть власну відповідь нижче. Поточний runtime зберігає факт письмової практики, але не вигадує оцінку правильності або mastery.";
            _submitProductive.Text = "&Зберегти Writing практику";
            _submitProductive.AccessibleName = "Зберегти письмову практику без автоматичного mastery";
        }
        else
        {
            _productivePrompt.Text = selected.Task.Prompt + Environment.NewLine + Environment.NewLine +
                "Канал: " + selected.Task.Channel + ". Production microphone/capture provider ще не прив'язаний до цього learner-facing Course UI. Можна ввести текстову тренувальну відповідь, але вона буде збережена лише як typed fallback і НЕ як Speaking/Pronunciation evidence.";
            _submitProductive.Text = "Зберегти &текстову заміну (не Speaking)";
            _submitProductive.AccessibleName = "Зберегти текстову тренувальну заміну без зарахування Speaking";
        }
    }

    private void MarkContextRead()
    {
        if (_contextCombo.SelectedItem is not ContextChoice selected || _unitCombo.SelectedItem is not UnitChoice unit) return;
        try
        {
            _learnerBridge.RecordNarrativeExposure(
                _manifest,
                unit.Module.ModuleId,
                unit.Unit.UnitId,
                selected.Context.ContentId);
        }
        catch (Exception ex)
        {
            UpdateProgressStatus("Exposure не збережено в learner-state; старий completion не змінено. " + ex.Message);
            return;
        }

        _progress = StoryCourseRuntimeStateStore.RecordNarrativeCompletion(_progress, selected.Context);
        if (!PersistSafely(out string? persistError))
        {
            UpdateProgressStatus("Exposure збережено в learner-state, але legacy completion не вдалося зберегти. " + persistError);
            return;
        }
        UpdateProgressStatus("Матеріал позначено прочитаним. Exposure збережено окремо від mastery.");
    }

    private void CheckAnswer()
    {
        if (_taskCombo.SelectedItem is not TaskChoice selected ||
            selected.Task.Kind != StoryCourseComprehensionKind.BoundedResponse ||
            _unitCombo.SelectedItem is not UnitChoice unit)
            return;

        if (string.IsNullOrWhiteSpace(_answer.Text))
        {
            UpdateProgressStatus("Введіть відповідь. Порожнє натискання Enter не змінює навчальний прогрес.");
            _answer.Focus();
            return;
        }

        bool accepted = StoryCourseRuntimeStateStore.IsAcceptedBoundedAnswer(selected.Task, _answer.Text);
        try
        {
            _learnerBridge.RecordComprehensionPracticeAttempt(
                _manifest,
                unit.Module.ModuleId,
                unit.Unit.UnitId,
                selected.Task.TaskId,
                accepted,
                NextAttemptNumber(selected.Task.TaskId));
        }
        catch (Exception ex)
        {
            UpdateProgressStatus("Спробу не вдалося безпечно записати в learner-state; completion/mastery не змінено. " + ex.Message);
            return;
        }

        if (accepted)
        {
            _progress = StoryCourseRuntimeStateStore.RecordBoundedComprehensionSuccess(_progress, selected.Task);
            if (!PersistSafely(out string? persistError))
            {
                UpdateProgressStatus("Practice evidence збережено, але legacy comprehension completion не вдалося зберегти. Mastery не змінено. " + persistError);
            }
            else
            {
                UpdateProgressStatus("Правильно. Practice evidence збережено; legacy comprehension completion оновлено. Mastery не змінено.");
            }
        }
        else
        {
            UpdateProgressStatus("Відповідь поки не прийнята. Невдала спроба збережена як practice evidence, але не як completion або mastery.");
        }
        _answer.Focus();
        _answer.SelectAll();
    }

    private void SubmitProductivePractice()
    {
        if (_productiveCombo.SelectedItem is not ProductiveChoice selected ||
            _unitCombo.SelectedItem is not UnitChoice unit)
            return;

        if (string.IsNullOrWhiteSpace(_productiveResponse.Text))
        {
            UpdateProgressStatus("Введіть власну відповідь. Порожня productive-вправа не змінює learner-state.");
            _productiveResponse.Focus();
            return;
        }

        int visibleBefore = _productiveCombo.Items.Count;
        StoryCourseProductiveSubmissionKind submissionKind = SubmissionKindForCurrentUi(selected.Task.Channel);
        try
        {
            _learnerBridge.RecordProductivePracticeAttempt(
                _manifest,
                unit.Module.ModuleId,
                unit.Unit.UnitId,
                selected.Task.TaskId,
                submissionKind,
                NextAttemptNumber(selected.Task.TaskId));
        }
        catch (Exception ex)
        {
            UpdateProgressStatus("Productive practice не вдалося безпечно записати; mastery не змінено. " + ex.Message);
            return;
        }

        PopulateProductiveTasks(unit.Unit, selected.Task.TaskId);
        bool unlocked = _productiveCombo.Items.Count > visibleBefore;
        string message;
        if (submissionKind == StoryCourseProductiveSubmissionKind.RequiredChannelPerformance)
        {
            message = "Writing practice збережено як виконання потрібного каналу. Текст не отримав автоматичної оцінки правильності й не створив mastery.";
        }
        else
        {
            message = "Текстову заміну збережено лише як typed-fallback practice. Вона НЕ є Speaking/Pronunciation evidence і не створює mastery.";
        }
        if (unlocked)
            message += " Наступна поетапна productive-вправа тепер доступна у списку; answer-bearing support не розкривався до required-channel submission.";
        UpdateProgressStatus(message);

        if (unlocked)
            _productiveCombo.Focus();
        else
        {
            _productiveResponse.Focus();
            _productiveResponse.SelectAll();
        }
    }

    private int NextAttemptNumber(string itemId)
    {
        LearnerCourseState state = _learnerStore.Load();
        string pathId = StoryCourseLearnerStateBridge.BuildPathId(_manifest);
        int current = state.EvidenceHistory
            .Where(item => item.PathId.Equals(pathId, StringComparison.OrdinalIgnoreCase) &&
                           item.CourseId.Equals(_manifest.CourseId, StringComparison.OrdinalIgnoreCase) &&
                           string.Equals(item.ItemId, itemId, StringComparison.OrdinalIgnoreCase))
            .Select(item => item.AttemptNumber)
            .DefaultIfEmpty(0)
            .Max();
        if (current == int.MaxValue)
            throw new InvalidDataException($"Attempt counter for '{itemId}' cannot advance safely.");
        return current + 1;
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
        string learnerEvidence;
        try
        {
            LearnerCourseState state = _learnerStore.Load();
            string pathId = StoryCourseLearnerStateBridge.BuildPathId(_manifest);
            LearnerEvidenceEvent[] courseEvents = state.EvidenceHistory
                .Where(item => item.PathId.Equals(pathId, StringComparison.OrdinalIgnoreCase))
                .ToArray();
            int exposures = courseEvents.Count(item => item.ActivityKind == LearnerActivityKind.Exposure);
            int practiceAttempts = courseEvents
                .Where(item => item.ActivityKind == LearnerActivityKind.Practice)
                .Select(item => new { item.ItemId, item.AttemptNumber })
                .Distinct()
                .Count();
            int productive = courseEvents.Count(item => item.IsProductivePerformance);
            int typedFallback = courseEvents.Count(item => item.SkillId == "typed-fallback");
            learnerEvidence = $" Learner evidence: exposure {exposures}; practice attempts {practiceAttempts}; productive-channel events {productive}; typed fallbacks {typedFallback}.";
        }
        catch (Exception ex)
        {
            learnerEvidence = " Learner evidence зараз недоступний: " + ex.Message;
        }

        string warnings = _packageWarnings.Count == 0
            ? string.Empty
            : Environment.NewLine + "Інші локальні package-файли були відхилені: " + string.Join(" | ", _packageWarnings);
        _status.Text =
            message + Environment.NewLine +
            $"Legacy progress: матеріалів завершено {completedContexts}; вправ із валідним evidence {completedTasks}; mastery-рішень {mastery}." +
            learnerEvidence + warnings;
    }

    private bool PersistSafely(out string? error)
    {
        try
        {
            _store.Save(_progress);
            _lastPersistedProgress = _progress;
            error = null;
            return true;
        }
        catch (Exception ex)
        {
            _progress = _lastPersistedProgress;
            error = "Legacy прогрес курсу не вдалося безпечно зберегти. Наявні файли не видалялися. " + ex.Message;
            _status.Text = error;
            return false;
        }
    }
}
