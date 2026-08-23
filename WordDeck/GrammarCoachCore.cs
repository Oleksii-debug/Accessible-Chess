using System.Text.RegularExpressions;

namespace WordDeck;

internal enum GrammarExerciseKind
{
    UkrainianToEnglish,
    Statement,
    Negative,
    Question,
    PersonChange,
    Contrast,
    ErrorCorrection,
    Paraphrase,
    MixedReview
}

internal enum GrammarErrorKind
{
    None,
    Blank,
    WordOrder,
    Auxiliary,
    TenseAspect,
    Agreement,
    Negation,
    QuestionForm,
    Article,
    Preposition,
    Modal,
    PassiveVoice,
    Conditional,
    Comparison,
    Lexical,
    Punctuation,
    Other
}

internal sealed record GrammarSkill(
    string SkillId,
    string FamilyId,
    string DisplayNameUk,
    string CefrLevel,
    IReadOnlyList<string> PrerequisiteSkillIds,
    IReadOnlyList<GrammarExerciseKind> ExerciseKinds)
{
    public void Validate()
    {
        RequireId(SkillId, "grammar skill id");
        RequireId(FamilyId, "grammar family id");
        if (string.IsNullOrWhiteSpace(DisplayNameUk)) throw new InvalidDataException("Grammar skill Ukrainian name is required.");
        if (CefrLevel is not ("A1" or "A2" or "B1" or "B2" or "C1")) throw new InvalidDataException("Grammar skill CEFR must be A1-C1.");
        if (ExerciseKinds.Count == 0) throw new InvalidDataException("Grammar skill requires at least one deterministic exercise kind.");
        if (PrerequisiteSkillIds.Any(id => string.Equals(id, SkillId, StringComparison.OrdinalIgnoreCase))) throw new InvalidDataException("Grammar skill cannot require itself.");
    }

    internal static void RequireId(string? id, string label)
    {
        if (string.IsNullOrWhiteSpace(id) || !Regex.IsMatch(id, "^[a-z0-9][a-z0-9._-]*$", RegexOptions.CultureInvariant))
            throw new InvalidDataException(label + " must be a stable lower-case identifier.");
    }
}

internal static class GrammarSkillCatalog
{
    public static IReadOnlyList<GrammarSkill> All { get; } = Build();
    public static IReadOnlyDictionary<string, GrammarSkill> ById { get; } = All.ToDictionary(x => x.SkillId, StringComparer.OrdinalIgnoreCase);

    private static IReadOnlyList<GrammarSkill> Build()
    {
        GrammarExerciseKind[] production = { GrammarExerciseKind.UkrainianToEnglish, GrammarExerciseKind.Statement, GrammarExerciseKind.Negative, GrammarExerciseKind.Question, GrammarExerciseKind.PersonChange, GrammarExerciseKind.ErrorCorrection, GrammarExerciseKind.MixedReview };
        GrammarExerciseKind[] contrast = production.Append(GrammarExerciseKind.Contrast).Append(GrammarExerciseKind.Paraphrase).Distinct().ToArray();
        var skills = new[]
        {
            S("verb.be.present","verbs.be","дієслово be у теперішньому","A1",Array.Empty<string>(),production),
            S("present.simple.core","tenses.present-simple","Present Simple: твердження","A1",new[]{"verb.be.present"},production),
            S("present.simple.third-person","tenses.present-simple","Present Simple: he/she/it","A1",new[]{"present.simple.core"},production),
            S("present.simple.questions-negatives","tenses.present-simple","Present Simple: питання і заперечення","A1",new[]{"present.simple.core"},production),
            S("past.simple.be","tenses.past-simple","Past Simple: was/were","A1",new[]{"verb.be.present"},production),
            S("past.simple.regular","tenses.past-simple","Past Simple: правильні дієслова","A2",new[]{"present.simple.core"},production),
            S("past.simple.irregular","tenses.past-simple","Past Simple: неправильні дієслова","A2",new[]{"past.simple.regular"},production),
            S("past.simple.questions-negatives","tenses.past-simple","Past Simple: питання і заперечення","A2",new[]{"past.simple.regular"},production),
            S("future.will","tenses.future","Future Simple with will","A2",new[]{"present.simple.core"},production),
            S("future.going-to","tenses.future","be going to: плани й наміри","A2",new[]{"verb.be.present"},production),
            S("present.continuous","tenses.continuous","Present Continuous","A1",new[]{"verb.be.present"},production),
            S("past.continuous","tenses.continuous","Past Continuous","A2",new[]{"present.continuous","past.simple.be"},production),
            S("present-perfect.core","tenses.perfect","Present Perfect","B1",new[]{"past.simple.irregular"},contrast),
            S("present-perfect.vs-past-simple","tenses.contrast","Present Perfect vs Past Simple","B1",new[]{"present-perfect.core","past.simple.irregular"},contrast),
            S("present-perfect-continuous","tenses.perfect-continuous","Present Perfect Continuous","B2",new[]{"present-perfect.core","present.continuous"},contrast),
            S("past-perfect","tenses.perfect","Past Perfect","B2",new[]{"present-perfect.core","past.simple.irregular"},contrast),
            S("continuous-vs-simple","tenses.contrast","Simple vs Continuous","B1",new[]{"present.simple.core","present.continuous"},contrast),
            S("articles.a-an-the","articles","a/an/the","A2",Array.Empty<string>(),contrast),
            S("countable-uncountable","nouns.countability","злічувані й незлічувані іменники","A2",Array.Empty<string>(),contrast),
            S("comparatives-superlatives","adjectives.comparison","ступені порівняння","A2",Array.Empty<string>(),contrast),
            S("modals.can-could","modals","can/could","A2",new[]{"present.simple.core"},contrast),
            S("modals.must-have-to","modals","must/have to","B1",new[]{"present.simple.core"},contrast),
            S("modals.should","modals","should: порада","A2",new[]{"present.simple.core"},contrast),
            S("passive.present-simple","voice.passive","Present Simple Passive","B1",new[]{"present.simple.core","verb.be.present"},contrast),
            S("passive.past-simple","voice.passive","Past Simple Passive","B1",new[]{"past.simple.irregular","passive.present-simple"},contrast),
            S("conditionals.zero","conditionals","Zero Conditional","B1",new[]{"present.simple.core"},contrast),
            S("conditionals.first","conditionals","First Conditional","B1",new[]{"future.will","present.simple.core"},contrast),
            S("conditionals.second","conditionals","Second Conditional","B1",new[]{"past.simple.irregular"},contrast),
            S("conditionals.third","conditionals","Third Conditional","B2",new[]{"past-perfect","conditionals.second"},contrast),
            S("reported-speech.statements","reported-speech","Reported Speech: твердження","B2",new[]{"past.simple.irregular","present-perfect.core"},contrast),
            S("relative-clauses.defining","relative-clauses","означальні підрядні речення","B1",new[]{"present.simple.core"},contrast),
            S("gerund-infinitive.core","verb-patterns","gerund vs infinitive","B1",new[]{"present.simple.core"},contrast)
        };
        foreach (GrammarSkill skill in skills) skill.Validate();
        var ids = new HashSet<string>(skills.Select(x => x.SkillId), StringComparer.OrdinalIgnoreCase);
        foreach (GrammarSkill skill in skills)
            foreach (string prerequisite in skill.PrerequisiteSkillIds)
                if (!ids.Contains(prerequisite)) throw new InvalidDataException($"Grammar prerequisite {prerequisite} is missing from the skill graph.");
        return skills;
    }

    private static GrammarSkill S(string id,string family,string uk,string cefr,IReadOnlyList<string> pre,IReadOnlyList<GrammarExerciseKind> kinds) => new(id,family,uk,cefr,pre,kinds);
}

internal sealed record GrammarExercise(
    string ExerciseId,
    string SkillId,
    GrammarExerciseKind Kind,
    string PromptUk,
    IReadOnlyList<string> AcceptedEnglishAnswers,
    IReadOnlyList<string> TargetStableEntryIds,
    string? ContrastTag = null,
    string? ExplanationUk = null)
{
    public void Validate()
    {
        GrammarSkill.RequireId(ExerciseId, "grammar exercise id");
        if (!GrammarSkillCatalog.ById.ContainsKey(SkillId)) throw new InvalidDataException("Grammar exercise references an unknown skill id.");
        if (string.IsNullOrWhiteSpace(PromptUk)) throw new InvalidDataException("Grammar exercise prompt is required.");
        if (AcceptedEnglishAnswers.Count == 0 || AcceptedEnglishAnswers.Any(string.IsNullOrWhiteSpace)) throw new InvalidDataException("Grammar exercise requires deterministic accepted English answers.");
        if (TargetStableEntryIds.Any(string.IsNullOrWhiteSpace)) throw new InvalidDataException("Grammar vocabulary targets contain a blank stable id.");
    }
}

internal sealed record GrammarEvaluation(
    bool Correct,
    GrammarErrorKind ErrorKind,
    string NormalizedAnswer,
    string ExpectedAnswer,
    string FeedbackUk);

internal static class GrammarAnswerEvaluator
{
    private static readonly Regex Spaces = new(@"\s+", RegexOptions.Compiled | RegexOptions.CultureInvariant);

    public static GrammarEvaluation Evaluate(GrammarExercise exercise, string? submitted)
    {
        ArgumentNullException.ThrowIfNull(exercise);
        exercise.Validate();
        string answer = Normalize(submitted ?? string.Empty);
        string[] accepted = exercise.AcceptedEnglishAnswers.Select(Normalize).Distinct(StringComparer.Ordinal).ToArray();
        string expected = accepted[0];
        if (answer.Length == 0) return new(false, GrammarErrorKind.Blank, answer, expected, "Відповідь порожня.");
        if (accepted.Contains(answer, StringComparer.Ordinal)) return new(true, GrammarErrorKind.None, answer, expected, "Правильно.");
        GrammarErrorKind error = Classify(exercise, answer, expected);
        return new(false, error, answer, expected, Feedback(error));
    }

    public static string Normalize(string value)
    {
        string v = value.Normalize(NormalizationForm.FormC).Trim().ToLowerInvariant();
        v = v.Replace('’','\'').Replace('‘','\'').Replace('`','\'');
        v = Regex.Replace(v, @"\s+([,.!?;:])", "$1");
        v = Spaces.Replace(v, " ");
        return v.TrimEnd('.', '!', '?');
    }

    private static GrammarErrorKind Classify(GrammarExercise exercise, string actual, string expected)
    {
        string[] a = actual.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        string[] e = expected.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        if (a.OrderBy(x=>x,StringComparer.Ordinal).SequenceEqual(e.OrderBy(x=>x,StringComparer.Ordinal), StringComparer.Ordinal)) return GrammarErrorKind.WordOrder;
        if (exercise.Kind == GrammarExerciseKind.Question && !ContainsAny(actual,"do ","does ","did ","is ","are ","was ","were ","have ","has ","will ","can ","could ","should ","must ")) return GrammarErrorKind.QuestionForm;
        if (expected.Contains(" not ", StringComparison.Ordinal) && !actual.Contains(" not ", StringComparison.Ordinal) && !actual.Contains("n't", StringComparison.Ordinal)) return GrammarErrorKind.Negation;
        if (ContainsAny(expected," do "," does "," did "," have "," has "," had "," will ") && !ContainsAny(actual," do "," does "," did "," have "," has "," had "," will ")) return GrammarErrorKind.Auxiliary;
        if (exercise.SkillId.StartsWith("conditionals.", StringComparison.Ordinal)) return GrammarErrorKind.Conditional;
        if (exercise.SkillId.StartsWith("passive.", StringComparison.Ordinal)) return GrammarErrorKind.PassiveVoice;
        if (exercise.SkillId.StartsWith("articles.", StringComparison.Ordinal)) return GrammarErrorKind.Article;
        if (exercise.SkillId.StartsWith("modals.", StringComparison.Ordinal)) return GrammarErrorKind.Modal;
        if (exercise.SkillId.Contains("comparative", StringComparison.Ordinal)) return GrammarErrorKind.Comparison;
        if (exercise.SkillId.StartsWith("tenses.", StringComparison.Ordinal) || exercise.SkillId.Contains("perfect", StringComparison.Ordinal) || exercise.SkillId.Contains("continuous", StringComparison.Ordinal)) return GrammarErrorKind.TenseAspect;
        return GrammarErrorKind.Other;
    }

    private static bool ContainsAny(string value, params string[] needles) => needles.Any(n => value.Contains(n, StringComparison.Ordinal));

    private static string Feedback(GrammarErrorKind error) => error switch
    {
        GrammarErrorKind.WordOrder => "Перевір порядок слів.",
        GrammarErrorKind.Auxiliary => "Перевір допоміжне дієслово.",
        GrammarErrorKind.TenseAspect => "Перевір час або аспект дієслова.",
        GrammarErrorKind.Agreement => "Перевір узгодження підмета і дієслова.",
        GrammarErrorKind.Negation => "Перевір форму заперечення.",
        GrammarErrorKind.QuestionForm => "Перевір побудову питання.",
        GrammarErrorKind.Article => "Перевір артикль.",
        GrammarErrorKind.Modal => "Перевір модальне дієслово та форму після нього.",
        GrammarErrorKind.PassiveVoice => "Перевір passive: форма be + past participle.",
        GrammarErrorKind.Conditional => "Перевір обидві частини умовного речення.",
        GrammarErrorKind.Comparison => "Перевір форму порівняння.",
        _ => "Відповідь не збігається з детермінованою правильною формою."
    };
}

internal sealed record GrammarExerciseSeed(
    string PromptUk,
    string AnswerEn,
    GrammarExerciseKind Kind,
    IReadOnlyList<string>? TargetStableEntryIds = null,
    string? ContrastTag = null,
    string? ExplanationUk = null);

internal static class GrammarExerciseBank
{
    private static readonly IReadOnlyDictionary<string, GrammarExerciseSeed[]> Seeds = Build();

    public static IReadOnlyList<GrammarExercise> ForSkill(string skillId)
    {
        if (!GrammarSkillCatalog.ById.ContainsKey(skillId)) throw new KeyNotFoundException("Unknown grammar skill: " + skillId);
        if (!Seeds.TryGetValue(skillId, out GrammarExerciseSeed[]? seeds)) return Array.Empty<GrammarExercise>();
        return seeds.Select((seed,index) => new GrammarExercise(
            $"grammar.{skillId}.{index:D3}", skillId, seed.Kind, seed.PromptUk,
            new[]{seed.AnswerEn}, seed.TargetStableEntryIds ?? Array.Empty<string>(), seed.ContrastTag, seed.ExplanationUk)).ToArray();
    }

    public static IReadOnlyList<GrammarExercise> MixedReview(IEnumerable<string> skillIds, int maxItems)
    {
        if (maxItems is < 1 or > 200) throw new ArgumentOutOfRangeException(nameof(maxItems));
        return skillIds.SelectMany(ForSkill).OrderBy(x => x.SkillId, StringComparer.Ordinal).ThenBy(x => x.ExerciseId, StringComparer.Ordinal).Take(maxItems).ToArray();
    }

    private static IReadOnlyDictionary<string, GrammarExerciseSeed[]> Build() => new Dictionary<string, GrammarExerciseSeed[]>(StringComparer.OrdinalIgnoreCase)
    {
        ["verb.be.present"] = A(("Я вдома.","I am at home.",GrammarExerciseKind.UkrainianToEnglish),("Вона не втомлена.","She is not tired.",GrammarExerciseKind.Negative),("Вони готові?","Are they ready?",GrammarExerciseKind.Question)),
        ["present.simple.core"] = A(("Я працюю щодня.","I work every day.",GrammarExerciseKind.UkrainianToEnglish),("Ми не живемо тут.","We do not live here.",GrammarExerciseKind.Negative),("Ти часто читаєш?","Do you often read?",GrammarExerciseKind.Question)),
        ["present.simple.third-person"] = A(("Вона працює щодня.","She works every day.",GrammarExerciseKind.PersonChange),("Він не грає тут.","He does not play here.",GrammarExerciseKind.Negative),("Вона знає його?","Does she know him?",GrammarExerciseKind.Question)),
        ["present.simple.questions-negatives"] = A(("Вони не розуміють.","They do not understand.",GrammarExerciseKind.Negative),("Твій брат працює тут?","Does your brother work here?",GrammarExerciseKind.Question)),
        ["past.simple.be"] = A(("Я був удома.","I was at home.",GrammarExerciseKind.UkrainianToEnglish),("Вони не були готові.","They were not ready.",GrammarExerciseKind.Negative),("Вона була там?","Was she there?",GrammarExerciseKind.Question)),
        ["past.simple.regular"] = A(("Ми відкрили вікно.","We opened the window.",GrammarExerciseKind.UkrainianToEnglish),("Вона працювала вчора.","She worked yesterday.",GrammarExerciseKind.Statement)),
        ["past.simple.irregular"] = A(("Він пішов додому.","He went home.",GrammarExerciseKind.UkrainianToEnglish),("Я побачив її вчора.","I saw her yesterday.",GrammarExerciseKind.Statement)),
        ["past.simple.questions-negatives"] = A(("Я не бачив його.","I did not see him.",GrammarExerciseKind.Negative),("Ти пішов туди?","Did you go there?",GrammarExerciseKind.Question)),
        ["future.will"] = A(("Я подзвоню тобі завтра.","I will call you tomorrow.",GrammarExerciseKind.UkrainianToEnglish),("Вона не прийде.","She will not come.",GrammarExerciseKind.Negative)),
        ["future.going-to"] = A(("Я збираюся вчитися сьогодні ввечері.","I am going to study this evening.",GrammarExerciseKind.UkrainianToEnglish),("Вони збираються переїхати.","They are going to move.",GrammarExerciseKind.Statement)),
        ["present.continuous"] = A(("Я зараз читаю.","I am reading now.",GrammarExerciseKind.UkrainianToEnglish),("Вона не спить.","She is not sleeping.",GrammarExerciseKind.Negative),("Вони чекають?","Are they waiting?",GrammarExerciseKind.Question)),
        ["past.continuous"] = A(("Я читав, коли ти подзвонив.","I was reading when you called.",GrammarExerciseKind.Contrast),("Вони не спали о десятій.","They were not sleeping at ten.",GrammarExerciseKind.Negative)),
        ["present-perfect.core"] = A(("Я вже закінчив.","I have already finished.",GrammarExerciseKind.UkrainianToEnglish),("Вона ще не приїхала.","She has not arrived yet.",GrammarExerciseKind.Negative)),
        ["present-perfect.vs-past-simple"] = A(("Я бачив цей фільм учора.","I saw this film yesterday.",GrammarExerciseKind.Contrast),("Я вже бачив цей фільм.","I have already seen this film.",GrammarExerciseKind.Contrast)),
        ["present-perfect-continuous"] = A(("Я вчуся вже дві години.","I have been studying for two hours.",GrammarExerciseKind.UkrainianToEnglish)),
        ["past-perfect"] = A(("Вона вже пішла до того, як я прийшов.","She had already left before I arrived.",GrammarExerciseKind.Contrast)),
        ["continuous-vs-simple"] = A(("Я зазвичай працюю вдома, але сьогодні працюю в офісі.","I usually work at home, but today I am working in the office.",GrammarExerciseKind.Contrast)),
        ["articles.a-an-the"] = A(("Я купив книгу. Книга цікава.","I bought a book. The book is interesting.",GrammarExerciseKind.Contrast)),
        ["countable-uncountable"] = A(("Мені потрібна інформація.","I need some information.",GrammarExerciseKind.UkrainianToEnglish)),
        ["comparatives-superlatives"] = A(("Ця книга краща за ту.","This book is better than that one.",GrammarExerciseKind.UkrainianToEnglish),("Це найважливіша частина.","This is the most important part.",GrammarExerciseKind.Statement)),
        ["modals.can-could"] = A(("Я можу допомогти.","I can help.",GrammarExerciseKind.UkrainianToEnglish),("Ти міг би повторити?","Could you repeat?",GrammarExerciseKind.Question)),
        ["modals.must-have-to"] = A(("Я мушу піти зараз.","I must go now.",GrammarExerciseKind.UkrainianToEnglish),("Мені доводиться працювати завтра.","I have to work tomorrow.",GrammarExerciseKind.Contrast)),
        ["modals.should"] = A(("Тобі слід відпочити.","You should rest.",GrammarExerciseKind.UkrainianToEnglish)),
        ["passive.present-simple"] = A(("Англійською говорять у багатьох країнах.","English is spoken in many countries.",GrammarExerciseKind.UkrainianToEnglish)),
        ["passive.past-simple"] = A(("Міст був побудований у 1990 році.","The bridge was built in 1990.",GrammarExerciseKind.UkrainianToEnglish)),
        ["conditionals.zero"] = A(("Якщо нагріти воду до 100 градусів, вона кипить.","If you heat water to 100 degrees, it boils.",GrammarExerciseKind.UkrainianToEnglish)),
        ["conditionals.first"] = A(("Якщо завтра буде дощ, я залишуся вдома.","If it rains tomorrow, I will stay at home.",GrammarExerciseKind.UkrainianToEnglish)),
        ["conditionals.second"] = A(("Якби я мав більше часу, я б більше читав.","If I had more time, I would read more.",GrammarExerciseKind.UkrainianToEnglish)),
        ["conditionals.third"] = A(("Якби я знав, я б тобі сказав.","If I had known, I would have told you.",GrammarExerciseKind.UkrainianToEnglish)),
        ["reported-speech.statements"] = A(("Вона сказала: «Я втомлена». Передай непрямою мовою.","She said that she was tired.",GrammarExerciseKind.Paraphrase)),
        ["relative-clauses.defining"] = A(("Це людина, яка мені допомогла.","This is the person who helped me.",GrammarExerciseKind.UkrainianToEnglish)),
        ["gerund-infinitive.core"] = A(("Я хочу вивчати англійську.","I want to learn English.",GrammarExerciseKind.UkrainianToEnglish),("Мені подобається читати.","I enjoy reading.",GrammarExerciseKind.Contrast))
    };

    private static GrammarExerciseSeed[] A(params (string uk,string en,GrammarExerciseKind kind)[] items) => items.Select(x => new GrammarExerciseSeed(x.uk,x.en,x.kind)).ToArray();
}

internal sealed record GrammarSkillMastery(string SkillId, int Attempts, int Correct, double Mastery, DateTimeOffset UpdatedUtc)
{
    public static GrammarSkillMastery Empty(string skillId) => new(skillId,0,0,0,DateTimeOffset.MinValue);
}

internal static class GrammarMasteryEngine
{
    public static GrammarSkillMastery Apply(GrammarSkillMastery current, GrammarEvaluation evaluation)
    {
        ArgumentNullException.ThrowIfNull(current);
        ArgumentNullException.ThrowIfNull(evaluation);
        int attempts = checked(current.Attempts + 1);
        int correct = checked(current.Correct + (evaluation.Correct ? 1 : 0));
        double evidence = evaluation.Correct ? 1.0 : 0.0;
        double next = Math.Clamp(current.Mastery * 0.82 + evidence * 0.18, 0, 1);
        if (!evaluation.Correct && evaluation.ErrorKind is GrammarErrorKind.TenseAspect or GrammarErrorKind.Auxiliary or GrammarErrorKind.QuestionForm)
            next = Math.Max(0, next - 0.04);
        return new GrammarSkillMastery(current.SkillId, attempts, correct, next, DateTimeOffset.UtcNow);
    }

    public static IReadOnlyList<string> AvailableSkills(IReadOnlyDictionary<string,GrammarSkillMastery> mastery, double prerequisiteThreshold = 0.65)
    {
        if (prerequisiteThreshold is < 0 or > 1) throw new ArgumentOutOfRangeException(nameof(prerequisiteThreshold));
        return GrammarSkillCatalog.All.Where(skill => skill.PrerequisiteSkillIds.All(pre => mastery.TryGetValue(pre,out GrammarSkillMastery? state) && state.Mastery >= prerequisiteThreshold))
            .Select(skill => skill.SkillId).ToArray();
    }
}
