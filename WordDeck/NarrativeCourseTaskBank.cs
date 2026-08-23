namespace WordDeck;

/// <summary>
/// Deterministic, offline task bank layered on top of Story chapters. The bank
/// deliberately keeps canonical progress outside any free-form AI response: each
/// production task has a stable ID, a bounded answer set and explicit grammar
/// skill references.
/// </summary>
internal static class NarrativeCourseTaskBank
{
    private static readonly IReadOnlyDictionary<string, IReadOnlyList<CourseTaskDefinition>> Supplemental = Build();

    public static IReadOnlyList<CourseTaskDefinition> GetTasks(ResolvedStoryChapter chapter)
    {
        if (chapter is null) throw new ArgumentNullException(nameof(chapter));
        var tasks = new List<CourseTaskDefinition>(chapter.Definition.Tasks);
        if (Supplemental.TryGetValue(chapter.Definition.Id, out IReadOnlyList<CourseTaskDefinition>? extra))
            tasks.AddRange(extra);
        if (tasks.Select(task => task.Id).Distinct(StringComparer.OrdinalIgnoreCase).Count() != tasks.Count)
            throw new InvalidDataException($"Narrative Course chapter {chapter.Definition.Id} has duplicate task IDs.");
        foreach (CourseTaskDefinition task in tasks) task.Validate(chapter.Definition.Id);
        return tasks;
    }

    public static IReadOnlySet<CourseTaskKind> CoveredKinds(ResolvedStoryCatalog catalog) =>
        catalog.ChaptersById.Values
            .SelectMany(GetTasks)
            .Select(task => task.Kind)
            .ToHashSet();

    private static CourseTaskDefinition T(
        string id,
        CourseTaskKind kind,
        string prompt,
        string[] answers,
        params string[] grammar) =>
        new(id, kind, prompt, answers, grammar);

    private static IReadOnlyDictionary<string, IReadOnlyList<CourseTaskDefinition>> Build() =>
        new Dictionary<string, IReadOnlyList<CourseTaskDefinition>>(StringComparer.OrdinalIgnoreCase)
        {
            ["a1-morning-01"] = new[]
            {
                T("a1-morning-produce-01", CourseTaskKind.ActiveProduction,
                    "Переклади англійською: Її сім'я любить музику.",
                    new[] { "her family likes music" }, "grammar.present-simple.statement"),
                T("a1-morning-question-01", CourseTaskKind.Question,
                    "Склади англійське питання: Чи її сім'я любить музику?",
                    new[] { "does her family like music" }, "grammar.present-simple.question"),
                T("a1-morning-negative-01", CourseTaskKind.Negative,
                    "Скажи англійською в заперечній формі: Її сім'я не любить музику.",
                    new[] { "her family does not like music", "her family doesn't like music" }, "grammar.present-simple.negative"),
                T("a1-morning-paraphrase-01", CourseTaskKind.Paraphrase,
                    "Передай цей зміст простим англійським реченням: Анна йде до школи вранці.",
                    new[] { "anna goes to school in the morning" }, "grammar.present-simple.statement"),
                T("a1-morning-mixed-01", CourseTaskKind.MixedReview,
                    "З історії: що Анна робить після школи? Напиши повне англійське речення про музику.",
                    new[] { "after school anna plays music again" }, "grammar.present-simple.statement")
            },
            ["a2-journey-01"] = new[]
            {
                T("a2-journey-produce-01", CourseTaskKind.ActiveProduction,
                    "Переклади англійською: Марта читає повідомлення.",
                    new[] { "marta reads a message" }, "grammar.present-simple.statement"),
                T("a2-journey-question-01", CourseTaskKind.Question,
                    "Склади англійське питання: Чи дорога мокра?",
                    new[] { "is the road wet" }, "grammar.be-present.question"),
                T("a2-journey-negative-01", CourseTaskKind.Negative,
                    "Скажи англійською: Станція сьогодні не шумна.",
                    new[] { "the station is not noisy today", "the station isn't noisy today" }, "grammar.be-present.negative"),
                T("a2-journey-paraphrase-01", CourseTaskKind.Paraphrase,
                    "Передай англійською той самий зміст: Марта обережна під час подорожі.",
                    new[] { "marta is careful during the journey" }, "grammar.be-present.statement"),
                T("a2-journey-mixed-01", CourseTaskKind.MixedReview,
                    "Напиши англійською: Коли подорож закінчується, Марта надсилає повідомлення.",
                    new[] { "when the journey is over marta sends a message" }, "grammar.present-simple.statement")
            },
            ["b1-plan-01"] = new[]
            {
                T("b1-plan-produce-01", CourseTaskKind.ActiveProduction,
                    "Переклади англійською: Порада допомагає йому покращити план.",
                    new[] { "the advice helps him improve the plan" }, "grammar.present-simple.statement"),
                T("b1-plan-question-01", CourseTaskKind.Question,
                    "Склади англійське питання: Чому він змінив рішення?",
                    new[] { "why did he change the decision", "why did he change his decision" }, "grammar.past-simple.question"),
                T("b1-plan-negative-01", CourseTaskKind.Negative,
                    "Скажи англійською: Команда не проігнорувала пораду.",
                    new[] { "the team did not ignore the advice", "the team didn't ignore the advice" }, "grammar.past-simple.negative"),
                T("b1-plan-paraphrase-01", CourseTaskKind.Paraphrase,
                    "Передай англійською: Він бачить шанс покращити проєкт.",
                    new[] { "he sees an opportunity to improve the project" }, "grammar.present-simple.statement"),
                T("b1-plan-mixed-01", CourseTaskKind.MixedReview,
                    "Напиши англійською одне речення зі словами decision і opportunity.",
                    new[] { "the opportunity changes his decision", "his decision creates an opportunity" }, "grammar.present-simple.statement")
            },
            ["b2-project-01"] = new[]
            {
                T("b2-project-produce-01", CourseTaskKind.ActiveProduction,
                    "Переклади англійською: Команда має уточнити ризик до кінцевого терміну.",
                    new[] { "the team must clarify the risk before the deadline" }, "grammar.modal-obligation"),
                T("b2-project-question-01", CourseTaskKind.Question,
                    "Склади англійське питання: Чому різноманітна команда має уточнити ризик?",
                    new[] { "why must the diverse team clarify the risk" }, "grammar.modal-question"),
                T("b2-project-negative-01", CourseTaskKind.Negative,
                    "Скажи англійською: Кінцевий термін не був проігнорований.",
                    new[] { "the deadline was not ignored", "the deadline wasn't ignored" }, "grammar.passive-basic"),
                T("b2-project-paraphrase-01", CourseTaskKind.Paraphrase,
                    "Перефразуй англійською: Загалом команда прийняла сміливу пропозицію.",
                    new[] { "broadly the team accepted the bold proposal", "broadly speaking the team accepted the bold proposal" }, "grammar.past-simple.statement"),
                T("b2-project-mixed-01", CourseTaskKind.MixedReview,
                    "Напиши англійською одне речення зі словами diverse, clarify і deadline.",
                    new[] { "the diverse team must clarify the risk before the deadline" }, "grammar.modal-obligation")
            },
            ["c1-rehearsal-01"] = new[]
            {
                T("c1-rehearsal-produce-01", CourseTaskKind.ActiveProduction,
                    "Переклади англійською: Співаки наполегливо продовжують репетицію.",
                    new[] { "the singers persist with the rehearsal", "the singers persist through the rehearsal" }, "grammar.present-simple.statement"),
                T("c1-rehearsal-question-01", CourseTaskKind.Question,
                    "Склади англійське питання: Чому результат був вартий зусиль?",
                    new[] { "why was the result worthwhile" }, "grammar.be-past.question"),
                T("c1-rehearsal-negative-01", CourseTaskKind.Negative,
                    "Скажи англійською: Вони не втратили яскраве звучання назавжди.",
                    new[] { "they did not lose the vibrant sound forever", "they didn't lose the vibrant sound forever" }, "grammar.past-simple.negative"),
                T("c1-rehearsal-paraphrase-01", CourseTaskKind.Paraphrase,
                    "Передай англійською: Вони на мить побачили, яким може стати концерт.",
                    new[] { "they had a glimpse of what the concert could become", "they got a glimpse of what the concert could become" }, "grammar.modal-possibility"),
                T("c1-rehearsal-mixed-01", CourseTaskKind.MixedReview,
                    "Напиши англійською одне речення зі словами remarkable і worthwhile.",
                    new[] { "the remarkable result was worthwhile", "the remarkable result made the effort worthwhile" }, "grammar.past-simple.statement")
            }
        };
}
