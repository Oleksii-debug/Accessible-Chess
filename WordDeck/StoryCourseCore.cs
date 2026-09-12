using System.Text;

namespace WordDeck;

internal enum StoryContentOrigin
{
    WordDeckAuthored,
    Sourced,
    Generated
}

internal sealed record StoryProvenance(
    StoryContentOrigin Origin,
    string SourceLabel,
    string License,
    string Attribution)
{
    public void Validate(string ownerId)
    {
        if (string.IsNullOrWhiteSpace(SourceLabel)) throw new InvalidDataException($"{ownerId} has no story source label.");
        if (string.IsNullOrWhiteSpace(License)) throw new InvalidDataException($"{ownerId} has no story license/status label.");
        if (Origin == StoryContentOrigin.Sourced && string.IsNullOrWhiteSpace(Attribution))
            throw new InvalidDataException($"{ownerId} is sourced content but has no attribution.");
        if (Origin == StoryContentOrigin.Generated && SourceLabel.Contains("sourced", StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException($"{ownerId} generated content must not masquerade as sourced content.");
    }
}

internal sealed record StoryTargetReference(string Source, int MinimumRepetitions = 2)
{
    public void Validate(string chapterId)
    {
        if (string.IsNullOrWhiteSpace(Source)) throw new InvalidDataException($"Story {chapterId} contains a blank target lexical form.");
        if (MinimumRepetitions is < 1 or > 20) throw new InvalidDataException($"Story {chapterId} has an invalid target repetition requirement.");
    }
}

internal enum CourseTaskKind
{
    ContextComprehension,
    ActiveProduction,
    Question,
    Negative,
    Paraphrase,
    MixedReview
}

internal sealed record CourseTaskDefinition(
    string Id,
    CourseTaskKind Kind,
    string PromptUkrainian,
    IReadOnlyList<string> AcceptedAnswers,
    IReadOnlyList<string> GrammarSkillIds)
{
    public void Validate(string chapterId)
    {
        if (string.IsNullOrWhiteSpace(Id)) throw new InvalidDataException($"Story {chapterId} contains a task with no ID.");
        if (string.IsNullOrWhiteSpace(PromptUkrainian)) throw new InvalidDataException($"Course task {Id} has no Ukrainian prompt.");
        if (AcceptedAnswers is null || AcceptedAnswers.Count == 0 || AcceptedAnswers.Any(string.IsNullOrWhiteSpace))
            throw new InvalidDataException($"Course task {Id} needs at least one accepted bounded answer.");
        if (GrammarSkillIds is null || GrammarSkillIds.Any(string.IsNullOrWhiteSpace))
            throw new InvalidDataException($"Course task {Id} contains an invalid grammar-skill reference.");
    }
}

internal sealed record StoryChapterDefinition(
    string Id,
    string UnitId,
    string Title,
    string Cefr,
    string UkrainianExplanation,
    string EnglishStory,
    StoryProvenance Provenance,
    IReadOnlyList<StoryTargetReference> TargetVocabulary,
    IReadOnlyList<string> GrammarSkillIds,
    IReadOnlyList<CourseTaskDefinition> Tasks)
{
    public void Validate()
    {
        Require(Id, "story chapter ID");
        Require(UnitId, $"story {Id} unit ID");
        Require(Title, $"story {Id} title");
        Require(UkrainianExplanation, $"story {Id} Ukrainian explanation");
        Require(EnglishStory, $"story {Id} English text");
        if (!StoryCourseCatalog.IsSupportedCefr(Cefr)) throw new InvalidDataException($"Story {Id} has unsupported CEFR level {Cefr}.");
        Provenance.Validate(Id);
        if (TargetVocabulary is null || TargetVocabulary.Count == 0) throw new InvalidDataException($"Story {Id} has no target vocabulary.");
        foreach (StoryTargetReference target in TargetVocabulary) target.Validate(Id);
        if (TargetVocabulary.Select(x => x.Source).Distinct(StringComparer.OrdinalIgnoreCase).Count() != TargetVocabulary.Count)
            throw new InvalidDataException($"Story {Id} contains duplicate target lexical forms.");
        if (GrammarSkillIds is null || GrammarSkillIds.Any(string.IsNullOrWhiteSpace)) throw new InvalidDataException($"Story {Id} contains an invalid grammar-skill reference.");
        if (Tasks is null || Tasks.Count == 0) throw new InvalidDataException($"Story {Id} has no Narrative Course tasks.");
        if (Tasks.Select(x => x.Id).Distinct(StringComparer.OrdinalIgnoreCase).Count() != Tasks.Count)
            throw new InvalidDataException($"Story {Id} contains duplicate task IDs.");
        foreach (CourseTaskDefinition task in Tasks) task.Validate(Id);

        IReadOnlyList<string> tokens = SentenceTokenizer.Tokenize(EnglishStory);
        foreach (StoryTargetReference target in TargetVocabulary)
        {
            IReadOnlyList<string> targetTokens = SentenceTokenizer.Tokenize(target.Source);
            if (targetTokens.Count != 1)
                throw new InvalidDataException($"Built-in Story target '{target.Source}' in {Id} must currently resolve to one lexical token.");
            int count = tokens.Count(token => token.Equals(targetTokens[0], StringComparison.OrdinalIgnoreCase));
            if (count < target.MinimumRepetitions)
                throw new InvalidDataException($"Story {Id} uses target '{target.Source}' only {count} time(s); required {target.MinimumRepetitions}.");
        }
    }

    private static void Require(string? value, string label)
    {
        if (string.IsNullOrWhiteSpace(value)) throw new InvalidDataException($"Missing {label}.");
        try { _ = value.Normalize(NormalizationForm.FormKC); }
        catch (ArgumentException ex) { throw new InvalidDataException($"{label} contains malformed Unicode.", ex); }
    }
}

internal sealed record StoryUnitDefinition(
    string Id,
    string Title,
    string Cefr,
    string UkrainianOverview,
    IReadOnlyList<StoryChapterDefinition> Chapters)
{
    public void Validate()
    {
        if (string.IsNullOrWhiteSpace(Id) || string.IsNullOrWhiteSpace(Title) || string.IsNullOrWhiteSpace(UkrainianOverview))
            throw new InvalidDataException("Narrative Course unit metadata is incomplete.");
        if (!StoryCourseCatalog.IsSupportedCefr(Cefr)) throw new InvalidDataException($"Unit {Id} has unsupported CEFR level {Cefr}.");
        if (Chapters is null || Chapters.Count == 0) throw new InvalidDataException($"Unit {Id} has no chapters.");
        if (Chapters.Any(chapter => !chapter.UnitId.Equals(Id, StringComparison.OrdinalIgnoreCase)))
            throw new InvalidDataException($"Unit {Id} contains a chapter owned by another unit.");
        foreach (StoryChapterDefinition chapter in Chapters) chapter.Validate();
    }
}

internal sealed record ResolvedStoryTarget(DictionaryEntry Entry, int MinimumRepetitions);

internal sealed record ResolvedStoryChapter(
    StoryChapterDefinition Definition,
    IReadOnlyList<ResolvedStoryTarget> Targets)
{
    public IReadOnlyList<string> StableTargetEntryIds => Targets.Select(x => x.Entry.Id).ToArray();
}

internal sealed class ResolvedStoryCatalog
{
    public required DictionaryPackage Dictionary { get; init; }
    public required IReadOnlyList<StoryUnitDefinition> Units { get; init; }
    public required IReadOnlyDictionary<string, ResolvedStoryChapter> ChaptersById { get; init; }

    public ResolvedStoryChapter GetChapter(string chapterId) =>
        ChaptersById.TryGetValue(chapterId, out ResolvedStoryChapter? chapter)
            ? chapter
            : throw new KeyNotFoundException($"Unknown Story/Narrative Course chapter '{chapterId}'.");
}

internal static class StoryCourseCatalog
{
    public static IReadOnlyList<StoryUnitDefinition> BuiltInUnits { get; } = BuildBuiltInUnits();

    public static ResolvedStoryCatalog Resolve(DictionaryPackage dictionary)
    {
        if (dictionary is null) throw new ArgumentNullException(nameof(dictionary));
        foreach (StoryUnitDefinition unit in BuiltInUnits) unit.Validate();
        if (BuiltInUnits.Select(x => x.Id).Distinct(StringComparer.OrdinalIgnoreCase).Count() != BuiltInUnits.Count)
            throw new InvalidDataException("Narrative Course contains duplicate unit IDs.");
        StoryChapterDefinition[] definitions = BuiltInUnits.SelectMany(x => x.Chapters).ToArray();
        if (definitions.Select(x => x.Id).Distinct(StringComparer.OrdinalIgnoreCase).Count() != definitions.Length)
            throw new InvalidDataException("Narrative Course contains duplicate chapter IDs.");

        var bySource = dictionary.Entries
            .GroupBy(entry => NormalizeLexicalForm(entry.Source), StringComparer.OrdinalIgnoreCase)
            .ToDictionary(group => group.Key, group => group.ToArray(), StringComparer.OrdinalIgnoreCase);
        var resolved = new Dictionary<string, ResolvedStoryChapter>(StringComparer.OrdinalIgnoreCase);
        foreach (StoryChapterDefinition definition in definitions)
        {
            var targets = new List<ResolvedStoryTarget>();
            foreach (StoryTargetReference reference in definition.TargetVocabulary)
            {
                string form = NormalizeLexicalForm(reference.Source);
                if (!bySource.TryGetValue(form, out DictionaryEntry[]? matches) || matches.Length == 0)
                    throw new InvalidDataException($"Story {definition.Id} target '{reference.Source}' is absent from dictionary '{dictionary.Id}'.");

                // Physical lexical forms can legitimately map to multiple Oxford stable IDs
                // (for example noun/verb senses). Story content is not allowed to silently
                // collapse that ambiguity. A built-in target must therefore be unique by
                // lexical form inside the active dictionary; otherwise content must be revised
                // to carry an explicitly approved stable ID.
                if (matches.Length != 1)
                    throw new InvalidDataException($"Story {definition.Id} target '{reference.Source}' maps to {matches.Length} stable IDs. Ambiguous lexical forms must be explicitly disambiguated before production use.");

                DictionaryEntry entry = matches[0];
                if (CefrRank(entry.Level) > CefrRank(definition.Cefr))
                    throw new InvalidDataException($"Story {definition.Id} ({definition.Cefr}) targets '{entry.Source}' at higher level {entry.Level}.");
                targets.Add(new ResolvedStoryTarget(entry, reference.MinimumRepetitions));
            }
            resolved[definition.Id] = new ResolvedStoryChapter(definition, targets);
        }

        return new ResolvedStoryCatalog
        {
            Dictionary = dictionary,
            Units = BuiltInUnits,
            ChaptersById = resolved
        };
    }

    internal static bool IsSupportedCefr(string? cefr) => cefr?.ToUpperInvariant() is "A1" or "A2" or "B1" or "B2" or "C1";

    internal static int CefrRank(string? cefr) => cefr?.ToUpperInvariant() switch
    {
        "A1" => 1,
        "A2" => 2,
        "B1" => 3,
        "B2" => 4,
        "C1" => 5,
        _ => 99
    };

    private static string NormalizeLexicalForm(string value) =>
        string.Join(" ", SentenceTokenizer.Tokenize(value));

    private static StoryProvenance Authored() => new(
        StoryContentOrigin.WordDeckAuthored,
        "WordDeck built-in authored curriculum",
        "Project-authored content",
        "WordDeck project");

    private static CourseTaskDefinition Task(string id, CourseTaskKind kind, string prompt, string answer, params string[] grammar) =>
        new(id, kind, prompt, new[] { answer }, grammar);

    private static IReadOnlyList<StoryUnitDefinition> BuildBuiltInUnits() => new[]
    {
        new StoryUnitDefinition(
            "course-a1-start",
            "A1 — A New Morning",
            "A1",
            "Перший блок тренує прості речення про щоденне життя. Читай історію лінійно, звертай увагу на повторення базових слів, а потім виконай коротке завдання.",
            new[]
            {
                new StoryChapterDefinition(
                    "a1-morning-01", "course-a1-start", "A Quiet Morning", "A1",
                    "Тема: ранок, сім'я, музика і школа. Граматична опора — прості твердження Present Simple.",
                    "Every morning Anna gets up early. The morning is quiet, and her family is still at home. Her family likes music, so Anna plays soft music while she eats. Then she takes her bag and walks to school. At school she meets her friend near the door. After school she comes home, tells her family about the day, and plays music again.",
                    Authored(),
                    new[] { new StoryTargetReference("morning"), new StoryTargetReference("family"), new StoryTargetReference("music"), new StoryTargetReference("school") },
                    new[] { "grammar.present-simple.statement" },
                    new[] { Task("a1-morning-q1", CourseTaskKind.ContextComprehension, "Куди Анна йде зранку? Напиши англійською одним словом.", "school", "grammar.present-simple.statement") })
            }),
        new StoryUnitDefinition(
            "course-a2-journey",
            "A2 — The Journey",
            "A2",
            "Другий блок додає послідовність подій, прості причини та опис обставин.",
            new[]
            {
                new StoryChapterDefinition(
                    "a2-journey-01", "course-a2-journey", "The Careful Journey", "A2",
                    "Тема: поїздка і повідомлення. Після читання спробуй відтворити головний факт без підказки.",
                    "The journey starts before sunrise. Marta is careful because the road is wet. She checks her phone and reads a message from her brother. The message says that the station is quiet today. During the journey Marta stays careful at every crossing. When she arrives, the station is still quiet, so she sends another message to say that the journey is over.",
                    Authored(),
                    new[] { new StoryTargetReference("journey"), new StoryTargetReference("careful"), new StoryTargetReference("message"), new StoryTargetReference("quiet") },
                    new[] { "grammar.present-simple.statement", "grammar.past-simple.statement" },
                    new[] { Task("a2-journey-q1", CourseTaskKind.ContextComprehension, "Що Марта читає на телефоні? Напиши англійською.", "message") })
            }),
        new StoryUnitDefinition(
            "course-b1-change",
            "B1 — A Better Plan",
            "B1",
            "Третій блок тренує рішення, поради і поступове покращення. Він готує перехід від окремих речень до зв'язного контексту.",
            new[]
            {
                new StoryChapterDefinition(
                    "b1-plan-01", "course-b1-change", "A Better Plan", "B1",
                    "Тема: рішення після поради. Граматична опора — причинно-наслідкові твердження і майбутній намір.",
                    "Oleh asks for advice before he makes a decision. The advice is simple: improve one part of the plan at a time. He follows the advice and sees an opportunity to improve the project. That opportunity changes his decision about the next week. By Friday, the team understands why the decision was useful and why good advice can create a new opportunity.",
                    Authored(),
                    new[] { new StoryTargetReference("advice"), new StoryTargetReference("decision"), new StoryTargetReference("improve"), new StoryTargetReference("opportunity") },
                    new[] { "grammar.past-simple.statement", "grammar.future-intention" },
                    new[] { Task("b1-plan-q1", CourseTaskKind.ContextComprehension, "Що Олег просить перед рішенням? Напиши англійською.", "advice") })
            }),
        new StoryUnitDefinition(
            "course-b2-project",
            "B2 — The Community Project",
            "B2",
            "Четвертий блок свідомо повторює кілька активних B2-слів у довшому абзаці та підводить до змішаного повторення.",
            new[]
            {
                new StoryChapterDefinition(
                    "b2-project-01", "course-b2-project", "A Bold Deadline", "B2",
                    "Тема: командний проєкт. Звертай увагу, як одні й ті самі слова повертаються в різних реченнях.",
                    "The team makes a bold promise to finish before the deadline. Their members are diverse, so they do not always describe the problem in the same way. Iryna asks everyone to clarify one risk before the next meeting. Her bold proposal is accepted broadly across the group. As the deadline comes closer, the diverse team works calmly, and each person tries to clarify what remains. Broadly speaking, the project succeeds because the deadline is treated as a shared responsibility.",
                    Authored(),
                    new[] { new StoryTargetReference("bold"), new StoryTargetReference("deadline"), new StoryTargetReference("diverse"), new StoryTargetReference("clarify"), new StoryTargetReference("broadly") },
                    new[] { "grammar.present-simple.statement", "grammar.passive-basic" },
                    new[] { Task("b2-project-q1", CourseTaskKind.ContextComprehension, "Яке слово описує різноманітність команди? Напиши англійською.", "diverse") })
            }),
        new StoryUnitDefinition(
            "course-c1-rehearsal",
            "C1 — The Last Rehearsal",
            "C1",
            "П'ятий блок використовує складнішу лексику в емоційному контексті й готує довші chapter-based історії.",
            new[]
            {
                new StoryChapterDefinition(
                    "c1-rehearsal-01", "course-c1-rehearsal", "A Worthwhile Rehearsal", "C1",
                    "Тема: наполегливість перед виступом. Після історії WordDeck формує маршрути в інші режими з тими самими stable IDs.",
                    "At first, the rehearsal feels difficult, but the singers persist. A vibrant harmony appears for a moment, giving everyone a glimpse of what the concert may become. They persist through one more section, and the conductor calls the change remarkable. The vibrant sound returns, and another glimpse of confidence spreads through the room. The long evening now feels worthwhile. When they finish, everyone agrees that the remarkable result made the effort worthwhile.",
                    Authored(),
                    new[] { new StoryTargetReference("persist"), new StoryTargetReference("vibrant"), new StoryTargetReference("glimpse"), new StoryTargetReference("remarkable"), new StoryTargetReference("worthwhile") },
                    new[] { "grammar.present-simple.statement", "grammar.aspect-contrast" },
                    new[] { Task("c1-rehearsal-q1", CourseTaskKind.ContextComprehension, "Яке слово означає, що зусилля були варті того? Напиши англійською.", "worthwhile") })
            })
    };
}

internal sealed record StorySchedulingContext(
    IReadOnlyDictionary<string, double> LexicalWeaknessByEntryId,
    IReadOnlyDictionary<string, double> GrammarWeaknessBySkillId);

internal static class StoryCourseScheduler
{
    public static ResolvedStoryChapter SelectNext(ResolvedStoryCatalog catalog, StoryCourseState state, StorySchedulingContext context)
    {
        if (catalog.ChaptersById.Count == 0) throw new InvalidOperationException("Story catalog contains no chapters.");
        return catalog.ChaptersById.Values
            .OrderBy(chapter => Score(chapter, state, context))
            .ThenBy(chapter => StoryCourseCatalog.CefrRank(chapter.Definition.Cefr))
            .ThenBy(chapter => chapter.Definition.Id, StringComparer.Ordinal)
            .First();
    }

    internal static double Score(ResolvedStoryChapter chapter, StoryCourseState state, StorySchedulingContext context)
    {
        StoryChapterProgress progress = state.ChapterProgress.GetValueOrDefault(chapter.Definition.Id) ?? new StoryChapterProgress();
        double completedPenalty = progress.Completions * 1000.0;
        double lexicalWeakness = chapter.StableTargetEntryIds.Sum(id => Math.Clamp(context.LexicalWeaknessByEntryId.GetValueOrDefault(id, 0.5), 0, 1));
        double grammarWeakness = chapter.Definition.GrammarSkillIds.Sum(id => Math.Clamp(context.GrammarWeaknessBySkillId.GetValueOrDefault(id, 0.5), 0, 1));
        // Lower score is selected first. Weak targets therefore reduce the score,
        // while already-completed chapters move back unless recycling pressure is strong.
        return completedPenalty - lexicalWeakness * 100.0 - grammarWeakness * 40.0 + StoryCourseCatalog.CefrRank(chapter.Definition.Cefr);
    }
}

internal enum StoryPracticeMode
{
    Recall,
    Spelling,
    Sentence,
    Grammar
}

internal sealed record StoryPracticeRoute(
    StoryPracticeMode Mode,
    string ChapterId,
    string DictionaryId,
    IReadOnlyList<string> TargetEntryIds,
    IReadOnlyList<string> GrammarSkillIds,
    string Reason,
    DateTimeOffset CreatedAtUtc);

internal static class StoryCoursePracticeRouter
{
    public static IReadOnlyList<StoryPracticeRoute> BuildPostStoryRoutes(ResolvedStoryCatalog catalog, ResolvedStoryChapter chapter)
    {
        string[] targets = chapter.StableTargetEntryIds.Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        string[] grammar = chapter.Definition.GrammarSkillIds.Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        DateTimeOffset now = DateTimeOffset.UtcNow;
        return new[]
        {
            new StoryPracticeRoute(StoryPracticeMode.Recall, chapter.Definition.Id, catalog.Dictionary.Id, targets, grammar, "Recheck meaning after narrative exposure.", now),
            new StoryPracticeRoute(StoryPracticeMode.Spelling, chapter.Definition.Id, catalog.Dictionary.Id, targets, grammar, "Actively spell the same story targets.", now),
            new StoryPracticeRoute(StoryPracticeMode.Sentence, chapter.Definition.Id, catalog.Dictionary.Id, targets, grammar, "Reuse the same stable targets in real Sentence practice.", now),
            new StoryPracticeRoute(StoryPracticeMode.Grammar, chapter.Definition.Id, catalog.Dictionary.Id, targets, grammar, "Reuse story vocabulary with the chapter grammar-skill references.", now)
        };
    }
}

internal static class StoryTaskEvaluator
{
    public static bool IsAccepted(CourseTaskDefinition task, string answer)
    {
        string normalized = Normalize(answer);
        return task.AcceptedAnswers.Any(candidate => Normalize(candidate).Equals(normalized, StringComparison.Ordinal));
    }

    private static string Normalize(string value) =>
        string.Join(" ", SentenceTokenizer.Tokenize(value ?? string.Empty));
}
