using System.Runtime.CompilerServices;

namespace WordDeck;

internal sealed record GovernedGrammarA106StudyItem(
    string ItemId,
    string ExerciseId,
    string Prompt,
    IReadOnlyList<string> AcceptedAnswers,
    GrammarExerciseKind Kind,
    bool IsDeepPractice,
    string? Explanation = null);

internal sealed record GovernedGrammarA106StudyEvaluation(
    string ItemId,
    bool Correct,
    string DefectCode,
    string Feedback,
    string ExpectedAnswer,
    string? RecommendedItemId);

internal sealed record GovernedGrammarA106PracticeSummary(
    int PracticeAttempts,
    int CorrectPracticeAttempts,
    string ResumeItemId);

/// <summary>
/// Learner-facing Study/Deep-Practice catalog for the already governed
/// G-A1-06 source. Protected Fast Track and unseen-transfer items are
/// intentionally absent from this catalog so ordinary UI cannot leak them.
/// </summary>
internal static class GovernedGrammarA106StudyCatalog
{
    public const string PrimaryItemId = "P06-06";
    public const string MissingBeRepairItemId = "DP-A06";
    public const string QuestionRepairItemId = "DP-B04";
    public const string IngRepairItemId = "DP-C01";

    private static readonly IReadOnlyDictionary<string, GovernedGrammarA106StudyItem> Items =
        new Dictionary<string, GovernedGrammarA106StudyItem>(StringComparer.OrdinalIgnoreCase)
        {
            [PrimaryItemId] = new(
                PrimaryItemId,
                "ga106.p06-06",
                "You hear typing in the next room. Ask your colleague whether they are working now.",
                new[] { "Are you working now?", "Are you working?" },
                GrammarExerciseKind.Question,
                IsDeepPractice: false),
            [MissingBeRepairItemId] = new(
                MissingBeRepairItemId,
                "ga106.dp-a06",
                "Ask what Anna is doing.",
                new[] { "What is Anna doing?" },
                GrammarExerciseKind.Question,
                IsDeepPractice: true,
                "Present Continuous needs am/is/are before the -ing form."),
            [QuestionRepairItemId] = new(
                QuestionRepairItemId,
                "ga106.dp-b04",
                "Ask whether Lena is driving now.",
                new[] { "Is Lena driving now?" },
                GrammarExerciseKind.Question,
                IsDeepPractice: true,
                "In a Present Continuous question, move am/is/are before the subject. Do not add do/does."),
            [IngRepairItemId] = new(
                IngRepairItemId,
                "ga106.dp-c01",
                "Complete the current-action form: She is ___ dinner. (make)",
                new[] { "making", "She is making dinner." },
                GrammarExerciseKind.Statement,
                IsDeepPractice: true,
                "After am/is/are, use the -ing form. Common final silent e drops before -ing: make → making.")
        };

    public static IReadOnlyCollection<GovernedGrammarA106StudyItem> All => Items.Values;

    public static GovernedGrammarA106StudyItem Get(string itemId)
    {
        if (string.IsNullOrWhiteSpace(itemId))
            throw new ArgumentException("G-A1-06 study item id is required.", nameof(itemId));
        string id = itemId.Trim();
        if (!Items.TryGetValue(id, out GovernedGrammarA106StudyItem? item))
            throw new InvalidDataException($"G-A1-06 learner UI does not own study item '{id}'.");
        return item;
    }

    public static bool Contains(string? itemId) =>
        !string.IsNullOrWhiteSpace(itemId) && Items.ContainsKey(itemId.Trim());

    public static GovernedGrammarA106StudyEvaluation Evaluate(string itemId, string? submitted)
    {
        GovernedGrammarA106StudyItem item = Get(itemId);
        GrammarExercise exercise = ToGrammarExercise(item);
        GrammarEvaluation evaluation = GrammarAnswerEvaluator.Evaluate(exercise, submitted);

        if (evaluation.Correct)
        {
            string next = item.IsDeepPractice
                ? $" Correct. Return to {PrimaryItemId} for an independent current-action question with different vocabulary."
                : " Correct. This Study attempt was saved as practice; it does not by itself award mastery or a CEFR level.";
            return new(item.ItemId, true, "NONE", "Correct." + next, evaluation.ExpectedAnswer,
                item.IsDeepPractice ? PrimaryItemId : null);
        }

        if (evaluation.ErrorKind == GrammarErrorKind.Blank)
            return new(item.ItemId, false, "BLANK", "Type an answer before checking. No learning evidence was recorded.", evaluation.ExpectedAnswer, null);

        if (!item.ItemId.Equals(PrimaryItemId, StringComparison.OrdinalIgnoreCase))
        {
            string explanation = string.IsNullOrWhiteSpace(item.Explanation)
                ? evaluation.FeedbackUk
                : item.Explanation!;
            return new(item.ItemId, false, "TARGET_DEFICIT_REMAINS_ACTIVE",
                explanation + $" Expected practice form: {evaluation.ExpectedAnswer}", evaluation.ExpectedAnswer, item.ItemId);
        }

        string normalized = evaluation.NormalizedAnswer;
        string[] tokens = normalized.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        bool hasDoSupport = tokens.Any(token => token is "do" or "does");
        bool hasAre = tokens.Contains("are", StringComparer.Ordinal);
        bool hasWorking = tokens.Contains("working", StringComparer.Ordinal);
        bool hasBareWork = tokens.Contains("work", StringComparer.Ordinal);

        if (hasDoSupport)
            return Route("EXTRA_DO_WITH_BE",
                "Do/does is not used before are in this Present Continuous question. Move are before the subject: Are you ...?",
                evaluation.ExpectedAnswer,
                QuestionRepairItemId);

        if (hasWorking && !hasAre)
            return Route("CONTINUOUS_BE_OMISSION",
                "Present Continuous needs both parts: am/is/are + verb-ing. Your question is missing the finite be auxiliary.",
                evaluation.ExpectedAnswer,
                MissingBeRepairItemId);

        if (hasAre && hasBareWork && !hasWorking)
            return Route("ING_FORM_MISSING",
                "After am/is/are, the current-action verb needs the -ing form.",
                evaluation.ExpectedAnswer,
                IngRepairItemId);

        if (evaluation.ErrorKind is GrammarErrorKind.WordOrder or GrammarErrorKind.QuestionForm ||
            (hasAre && hasWorking && !normalized.StartsWith("are ", StringComparison.Ordinal)))
            return Route("QUESTION_WORD_ORDER",
                "In this question, are comes before the subject: Are you ...?",
                evaluation.ExpectedAnswer,
                QuestionRepairItemId);

        return Route("AUXILIARY_DEFECT",
            "Build the question with are + subject + verb-ing. Use the targeted question practice before trying a fresh item.",
            evaluation.ExpectedAnswer,
            QuestionRepairItemId);
    }

    private static GovernedGrammarA106StudyEvaluation Route(
        string defect,
        string feedback,
        string expected,
        string nextItemId) =>
        new(PrimaryItemId, false, defect, feedback + $" Expected study form: {expected}", expected, nextItemId);

    private static GrammarExercise ToGrammarExercise(GovernedGrammarA106StudyItem item) => new(
        item.ExerciseId,
        GovernedGrammarA106Runtime.GrammarSkillId,
        item.Kind,
        item.Prompt,
        item.AcceptedAnswers,
        Array.Empty<string>(),
        ContrastTag: "G-A1-06",
        ExplanationUk: item.Explanation);
}

/// <summary>
/// Narrow runtime consumer for ordinary governed G-A1-06 practice. It persists
/// exposure/practice and a resumable next activity in the existing course-state
/// sidecar. It never creates mastery, CEFR estimates, protected evidence, or an
/// AdaptiveRouteDecision.
/// </summary>
internal sealed class GovernedGrammarA106StudyRuntime
{
    private const string AtomicSkillId = "present.continuous-form";
    private readonly LearnerCourseStateStore _store;
    private readonly Func<string> _eventIdFactory;
    private readonly Func<DateTimeOffset> _clock;

    public GovernedGrammarA106StudyRuntime()
        : this(new LearnerCourseStateStore(),
            () => "ga106.study." + Guid.NewGuid().ToString("N"),
            () => DateTimeOffset.UtcNow)
    {
    }

    internal GovernedGrammarA106StudyRuntime(
        LearnerCourseStateStore store,
        Func<string> eventIdFactory,
        Func<DateTimeOffset> clock)
    {
        _store = store ?? throw new ArgumentNullException(nameof(store));
        _eventIdFactory = eventIdFactory ?? throw new ArgumentNullException(nameof(eventIdFactory));
        _clock = clock ?? throw new ArgumentNullException(nameof(clock));
        RequireCanonicalBinding();
    }

    public string GetResumeItemId()
    {
        LearnerCourseState state = _store.Load();
        if (state.CoursePositionsByPathId.TryGetValue(GovernedGrammarA106Runtime.PathId, out CoursePositionBookmark? bookmark) &&
            bookmark is not null && GovernedGrammarA106StudyCatalog.Contains(bookmark.ActivityId))
            return bookmark.ActivityId!;
        return GovernedGrammarA106StudyCatalog.PrimaryItemId;
    }

    public GovernedGrammarA106PracticeSummary GetSummary()
    {
        LearnerCourseState state = _store.Load();
        LearnerEvidenceEvent[] attempts = state.EvidenceHistory
            .Where(IsThisModulePractice)
            .ToArray();
        return new(
            attempts.Length,
            attempts.Count(e => e.Correct == true),
            ResolveResumeItemId(state));
    }

    public LearnerCourseState RecordExposure(string itemId)
    {
        GovernedGrammarA106StudyItem item = GovernedGrammarA106StudyCatalog.Get(itemId);
        LearnerCourseState state = _store.Load();
        int attemptNumber = NextAttemptNumber(state, item.ItemId, LearnerActivityKind.Exposure);
        state.EvidenceHistory.Add(NewEvidence(item.ItemId, LearnerActivityKind.Exposure, correct: null,
            revealUses: 0, attemptNumber));
        SetBookmark(state, item.ItemId);
        _store.Save(state);
        return state;
    }

    public LearnerCourseState RecordPracticeAttempt(
        string itemId,
        bool correct,
        string? nextActivityId,
        int revealUses)
    {
        GovernedGrammarA106StudyItem item = GovernedGrammarA106StudyCatalog.Get(itemId);
        if (revealUses < 0)
            throw new ArgumentOutOfRangeException(nameof(revealUses));

        string resumeItem = string.IsNullOrWhiteSpace(nextActivityId) ? item.ItemId : nextActivityId.Trim();
        _ = GovernedGrammarA106StudyCatalog.Get(resumeItem);

        LearnerCourseState state = _store.Load();
        int attemptNumber = NextAttemptNumber(state, item.ItemId, LearnerActivityKind.Practice);
        state.EvidenceHistory.Add(NewEvidence(item.ItemId, LearnerActivityKind.Practice, correct,
            revealUses, attemptNumber));
        SetBookmark(state, resumeItem);
        _store.Save(state);
        return state;
    }

    private LearnerEvidenceEvent NewEvidence(
        string itemId,
        LearnerActivityKind activityKind,
        bool? correct,
        int revealUses,
        int attemptNumber)
    {
        string eventId = (_eventIdFactory() ?? string.Empty).Trim();
        if (eventId.Length == 0)
            throw new InvalidDataException("G-A1-06 Study evidence requires a non-blank event id.");

        return new LearnerEvidenceEvent
        {
            EventId = eventId,
            ActivityKind = activityKind,
            PathId = GovernedGrammarA106Runtime.PathId,
            CourseId = GovernedGrammarA106Runtime.CourseId,
            ModuleId = GovernedGrammarA106Runtime.ModuleId,
            ObjectiveId = AtomicSkillId,
            SkillId = GovernedGrammarA106Runtime.GrammarSkillId,
            ItemId = itemId,
            Completed = true,
            Correct = correct,
            IsUnseenMaterial = false,
            IsProductivePerformance = false,
            IsTransferPerformance = false,
            HintUses = 0,
            RevealUses = revealUses,
            AttemptNumber = attemptNumber,
            OccurredAtUtc = _clock()
        };
    }

    private void SetBookmark(LearnerCourseState state, string activityId)
    {
        state.CoursePositionsByPathId[GovernedGrammarA106Runtime.PathId] = new CoursePositionBookmark
        {
            PathId = GovernedGrammarA106Runtime.PathId,
            CourseId = GovernedGrammarA106Runtime.CourseId,
            ModuleId = GovernedGrammarA106Runtime.ModuleId,
            ActivityId = activityId,
            UpdatedAtUtc = _clock()
        };
    }

    private static int NextAttemptNumber(
        LearnerCourseState state,
        string itemId,
        LearnerActivityKind activityKind) =>
        checked(state.EvidenceHistory.Count(e =>
            e is not null &&
            e.ActivityKind == activityKind &&
            string.Equals(e.CourseId, GovernedGrammarA106Runtime.CourseId, StringComparison.OrdinalIgnoreCase) &&
            string.Equals(e.ModuleId, GovernedGrammarA106Runtime.ModuleId, StringComparison.OrdinalIgnoreCase) &&
            string.Equals(e.ItemId, itemId, StringComparison.OrdinalIgnoreCase)) + 1);

    private static bool IsThisModulePractice(LearnerEvidenceEvent e) =>
        e is not null &&
        e.ActivityKind == LearnerActivityKind.Practice &&
        string.Equals(e.CourseId, GovernedGrammarA106Runtime.CourseId, StringComparison.OrdinalIgnoreCase) &&
        string.Equals(e.ModuleId, GovernedGrammarA106Runtime.ModuleId, StringComparison.OrdinalIgnoreCase) &&
        GovernedGrammarA106StudyCatalog.Contains(e.ItemId);

    private static string ResolveResumeItemId(LearnerCourseState state)
    {
        if (state.CoursePositionsByPathId.TryGetValue(GovernedGrammarA106Runtime.PathId, out CoursePositionBookmark? bookmark) &&
            bookmark is not null && GovernedGrammarA106StudyCatalog.Contains(bookmark.ActivityId))
            return bookmark.ActivityId!;
        return GovernedGrammarA106StudyCatalog.PrimaryItemId;
    }

    private static void RequireCanonicalBinding()
    {
        if (!GrammarSkillCatalog.ById.ContainsKey(GovernedGrammarA106Runtime.GrammarSkillId))
            throw new InvalidDataException("Canonical present.continuous grammar skill is missing.");
        GovernedGrammarAtomicCeiling ceiling = GovernedGrammarA106Runtime.GetAtomicCeiling(AtomicSkillId);
        if (!ceiling.LevelId.Equals("A1", StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("G-A1-06 Study runtime atomic ceiling drifted away from A1.");
        if (string.IsNullOrWhiteSpace(GovernedGrammarA106Runtime.SourceRevision) ||
            string.IsNullOrWhiteSpace(GovernedGrammarA106Runtime.IntegrationRevision))
            throw new InvalidDataException("G-A1-06 governed source/integration pins are missing.");
    }
}

internal static class GovernedGrammarA106RuntimeUi
{
    internal const string AnswerAccessibleName = "Grammar answer";

    internal static IReadOnlyList<(string AccessibleName, int TabIndex)> AccessibilityContract { get; } = new[]
    {
        ("Grammar task prompt", 0),
        (AnswerAccessibleName, 1),
        ("Check grammar answer", 2),
        ("Grammar feedback", 3),
        ("Open recommended grammar practice", 4),
        ("Grammar practice progress", 5),
        ("Close Deep Grammar practice", 6)
    };

    public static void Open(IWin32Window owner)
    {
        var runtime = new GovernedGrammarA106StudyRuntime();
        using Form form = CreateForm(runtime);
        using var blankSubmitGuard = BlankLearningSubmissionGuard.Attach(form, AnswerAccessibleName);
        form.ShowDialog(owner);
    }

    internal static Form CreateForm(GovernedGrammarA106StudyRuntime runtime)
    {
        ArgumentNullException.ThrowIfNull(runtime);

        var form = new Form
        {
            Text = "WordDeck — Deep Grammar A1 — Present Continuous",
            AccessibleName = "Deep Grammar A1 Present Continuous practice",
            StartPosition = FormStartPosition.CenterParent,
            Width = 820,
            Height = 660,
            MinimumSize = new Size(680, 560),
            AutoScaleMode = AutoScaleMode.Font,
            KeyPreview = true
        };

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoScroll = true,
            Padding = new Padding(12),
            ColumnCount = 1,
            RowCount = 8
        };
        root.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100F));

        var heading = new Label
        {
            AutoSize = true,
            Text = "Deep Grammar A1 — G-A1-06 Present Continuous",
            AccessibleName = "Deep Grammar module heading"
        };

        var boundary = new Label
        {
            AutoSize = true,
            MaximumSize = new Size(760, 0),
            Text = "Цей екран зберігає звичайну практику та рекомендований наступний крок. Практика не дорівнює mastery, CEFR-рівню або Fast Track.",
            AccessibleName = "Grammar evidence boundary"
        };

        var prompt = new TextBox
        {
            ReadOnly = true,
            Multiline = true,
            ScrollBars = ScrollBars.Vertical,
            Dock = DockStyle.Fill,
            Height = 92,
            TabStop = true,
            TabIndex = 0,
            AccessibleName = "Grammar task prompt",
            AccessibleDescription = "Full learner-facing task text. Read with standard text navigation."
        };

        var answer = new TextBox
        {
            Dock = DockStyle.Top,
            TabIndex = 1,
            AccessibleName = AnswerAccessibleName,
            AccessibleDescription = "Type the English answer for the current grammar practice task."
        };

        var check = new Button
        {
            AutoSize = true,
            Text = "Перевірити &відповідь",
            TabIndex = 2,
            AccessibleName = "Check grammar answer"
        };

        var feedback = new TextBox
        {
            ReadOnly = true,
            Multiline = true,
            ScrollBars = ScrollBars.Vertical,
            Dock = DockStyle.Fill,
            Height = 110,
            TabStop = true,
            TabIndex = 3,
            AccessibleName = "Grammar feedback",
            AccessibleDescription = "Text feedback and deficit-specific next-step explanation."
        };

        var next = new Button
        {
            AutoSize = true,
            Text = "Відкрити &рекомендовану вправу",
            Enabled = false,
            TabIndex = 4,
            AccessibleName = "Open recommended grammar practice",
            AccessibleDescription = "Opens the deterministic Deep Practice item selected from the current deficit."
        };

        var progress = new TextBox
        {
            ReadOnly = true,
            Multiline = true,
            Dock = DockStyle.Fill,
            Height = 64,
            TabStop = true,
            TabIndex = 5,
            AccessibleName = "Grammar practice progress",
            AccessibleDescription = "Persisted practice-only history and resume position."
        };

        var close = new Button
        {
            AutoSize = true,
            Text = "&Закрити",
            DialogResult = DialogResult.Cancel,
            TabIndex = 6,
            AccessibleName = "Close Deep Grammar practice"
        };

        string currentItemId = runtime.GetResumeItemId();
        string? recommendedItemId = null;

        void RefreshProgress()
        {
            GovernedGrammarA106PracticeSummary summary = runtime.GetSummary();
            progress.Text = $"Збережено практичних спроб: {summary.PracticeAttempts}; правильних: {summary.CorrectPracticeAttempts}. " +
                $"Точка відновлення: {summary.ResumeItemId}. Mastery/CEFR з цих лічильників не виводяться.";
        }

        void LoadItem(string itemId, bool recordExposure)
        {
            GovernedGrammarA106StudyItem item = GovernedGrammarA106StudyCatalog.Get(itemId);
            currentItemId = item.ItemId;
            recommendedItemId = null;
            if (recordExposure)
                runtime.RecordExposure(item.ItemId);
            prompt.Text = $"{item.ItemId}. {item.Prompt}";
            answer.Clear();
            feedback.Text = item.IsDeepPractice
                ? "Це цільова Deep Practice вправа. Після правильної відповіді WordDeck поверне вас до нового контексту основного завдання."
                : "Введіть англійське питання. Натисніть Enter або кнопку «Перевірити відповідь».";
            next.Enabled = false;
            RefreshProgress();
        }

        check.Click += (_, _) =>
        {
            GovernedGrammarA106StudyEvaluation evaluation =
                GovernedGrammarA106StudyCatalog.Evaluate(currentItemId, answer.Text);
            if (evaluation.DefectCode == "BLANK")
            {
                feedback.Text = evaluation.Feedback;
                AccessibilityAnnouncer.Announce(answer, evaluation.Feedback);
                answer.Focus();
                return;
            }

            recommendedItemId = evaluation.RecommendedItemId;
            string resume = recommendedItemId ?? currentItemId;
            runtime.RecordPracticeAttempt(
                currentItemId,
                evaluation.Correct,
                resume,
                revealUses: evaluation.Correct ? 0 : 1);

            feedback.Text = evaluation.Correct
                ? evaluation.Feedback
                : $"{evaluation.Feedback}\r\nDeficit: {evaluation.DefectCode}." +
                  (recommendedItemId is null ? string.Empty : $"\r\nРекомендований наступний крок: {recommendedItemId}.");
            next.Enabled = recommendedItemId is not null;
            RefreshProgress();
            feedback.Focus();
            AccessibilityAnnouncer.Announce(feedback, feedback.Text);
        };

        next.Click += (_, _) =>
        {
            if (recommendedItemId is null)
                return;
            LoadItem(recommendedItemId, recordExposure: true);
            prompt.Focus();
            AccessibilityAnnouncer.Announce(prompt, prompt.Text);
        };

        close.Click += (_, _) => form.Close();
        form.AcceptButton = check;
        form.CancelButton = close;

        root.Controls.Add(heading, 0, 0);
        root.Controls.Add(boundary, 0, 1);
        root.Controls.Add(prompt, 0, 2);
        root.Controls.Add(answer, 0, 3);

        var actionRow = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            AutoSize = true,
            FlowDirection = FlowDirection.LeftToRight,
            WrapContents = true
        };
        actionRow.Controls.Add(check);
        actionRow.Controls.Add(next);
        actionRow.Controls.Add(close);
        root.Controls.Add(actionRow, 0, 4);
        root.Controls.Add(feedback, 0, 5);
        root.Controls.Add(progress, 0, 6);
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 100F));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 120F));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 72F));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100F));

        form.Controls.Add(root);
        LoadItem(currentItemId, recordExposure: true);
        form.Shown += (_, _) => prompt.Focus();
        return form;
    }
}

internal static class GovernedGrammarA106RuntimeUiSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            GovernedGrammarA106RuntimeUiSelfTest.Run();
    }
}

internal static class GovernedGrammarA106RuntimeUiSelfTest
{
    public static void Run()
    {
        CatalogIsGovernedAndProtectedPoolsStayAbsent();
        DeterministicDeficitRouting();
        PracticeStateSurvivesRestartWithoutMasteryInflation();
        AccessibilityContractIsDeterministic();
        Console.WriteLine("Governed Grammar A1 runtime UI self-test PASS: governed Study content, deficit routing, restart state and accessibility contract verified; protected pools/mastery/CEFR remain excluded.");
    }

    private static void CatalogIsGovernedAndProtectedPoolsStayAbsent()
    {
        _ = GovernedGrammarA106Runtime.GetAtomicCeiling("present.continuous-form");
        Require(GovernedGrammarA106StudyCatalog.All.Count == 4, "Unexpected learner-facing governed Study item count.");
        Require(GovernedGrammarA106StudyCatalog.All.All(item =>
                !item.ItemId.StartsWith("FT", StringComparison.OrdinalIgnoreCase) &&
                !item.ItemId.StartsWith("UT", StringComparison.OrdinalIgnoreCase)),
            "Protected Fast Track or unseen-transfer item leaked into ordinary Study UI.");
    }

    private static void DeterministicDeficitRouting()
    {
        GovernedGrammarA106StudyEvaluation accepted =
            GovernedGrammarA106StudyCatalog.Evaluate("P06-06", "Are you working now?");
        Require(accepted.Correct && accepted.RecommendedItemId is null, "Canonical P06-06 answer did not pass cleanly.");

        GovernedGrammarA106StudyEvaluation extraDo =
            GovernedGrammarA106StudyCatalog.Evaluate("P06-06", "Do you are working?");
        Require(!extraDo.Correct && extraDo.DefectCode == "EXTRA_DO_WITH_BE" &&
                extraDo.RecommendedItemId == GovernedGrammarA106StudyCatalog.QuestionRepairItemId,
            "P06-06 extra-do defect did not route to DP-B04.");

        GovernedGrammarA106StudyEvaluation missingBe =
            GovernedGrammarA106StudyCatalog.Evaluate("P06-06", "You working now?");
        Require(missingBe.DefectCode == "CONTINUOUS_BE_OMISSION" &&
                missingBe.RecommendedItemId == GovernedGrammarA106StudyCatalog.MissingBeRepairItemId,
            "P06-06 missing-be defect did not route to Pack A practice.");

        GovernedGrammarA106StudyEvaluation missingIng =
            GovernedGrammarA106StudyCatalog.Evaluate("P06-06", "Are you work now?");
        Require(missingIng.DefectCode == "ING_FORM_MISSING" &&
                missingIng.RecommendedItemId == GovernedGrammarA106StudyCatalog.IngRepairItemId,
            "P06-06 missing-ing defect did not route to Pack C practice.");
    }

    private static void PracticeStateSurvivesRestartWithoutMasteryInflation()
    {
        string root = Path.Combine(Path.GetTempPath(), "WordDeck GA106 UI " + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        try
        {
            int eventNumber = 0;
            DateTimeOffset now = new(2026, 9, 13, 10, 45, 0, TimeSpan.Zero);
            var store = new LearnerCourseStateStore(root);
            var runtime = new GovernedGrammarA106StudyRuntime(
                store,
                () => "ga106.ui." + (++eventNumber).ToString("D4"),
                () => now.AddSeconds(eventNumber));

            runtime.RecordExposure("P06-06");
            runtime.RecordPracticeAttempt("P06-06", correct: false,
                GovernedGrammarA106StudyCatalog.QuestionRepairItemId, revealUses: 1);

            var reopened = new GovernedGrammarA106StudyRuntime(
                new LearnerCourseStateStore(root),
                () => "ga106.ui.reopen." + (++eventNumber).ToString("D4"),
                () => now.AddSeconds(eventNumber));
            Require(reopened.GetResumeItemId() == GovernedGrammarA106StudyCatalog.QuestionRepairItemId,
                "Deficit-specific resume item did not survive restart.");

            LearnerCourseState state = store.Load();
            LearnerEvidenceEvent practice = state.EvidenceHistory.Single(e => e.ActivityKind == LearnerActivityKind.Practice);
            Require(practice.Correct == false && practice.RevealUses == 1 &&
                    !practice.IsProductivePerformance && !practice.IsTransferPerformance,
                "Ordinary Study attempt was mislabeled as independent productive/transfer evidence.");
            Require(state.MasteryByObjectiveId.Count == 0 && state.SkillLevelsBySkillId.Count == 0 &&
                    state.AdaptiveRouteByPathId.Count == 0,
                "Study UI activity synthesized mastery, CEFR, or a formal adaptive route.");

            reopened.RecordPracticeAttempt(GovernedGrammarA106StudyCatalog.QuestionRepairItemId,
                correct: true, GovernedGrammarA106StudyCatalog.PrimaryItemId, revealUses: 0);
            Require(new GovernedGrammarA106StudyRuntime(new LearnerCourseStateStore(root),
                    () => "unused", () => now).GetResumeItemId() == GovernedGrammarA106StudyCatalog.PrimaryItemId,
                "Successful Deep Practice did not preserve the return-to-independent-practice resume point.");
        }
        finally
        {
            try { Directory.Delete(root, recursive: true); } catch { }
        }
    }

    private static void AccessibilityContractIsDeterministic()
    {
        IReadOnlyList<(string AccessibleName, int TabIndex)> contract = GovernedGrammarA106RuntimeUi.AccessibilityContract;
        Require(contract.Count == 7, "Accessibility contract control count drifted.");
        Require(contract.All(x => !string.IsNullOrWhiteSpace(x.AccessibleName)), "Accessibility contract has a blank accessible name.");
        Require(contract.Select(x => x.AccessibleName).Distinct(StringComparer.Ordinal).Count() == contract.Count,
            "Accessibility contract has duplicate accessible names.");
        Require(contract.Select(x => x.TabIndex).SequenceEqual(Enumerable.Range(0, contract.Count)),
            "Accessibility contract tab order is not deterministic.");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException("GovernedGrammarA106RuntimeUiSelfTest: " + message);
    }
}
