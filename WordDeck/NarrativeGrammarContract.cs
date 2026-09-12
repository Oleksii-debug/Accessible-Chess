namespace WordDeck;

/// <summary>
/// Stable cross-lane contract observed from the live DEV04 Grammar skill graph.
/// Story/Course can compile independently before Grammar is integrated, but it
/// must emit only skill IDs that the Grammar lane actually owns. Historical
/// provisional Story labels are normalized here and unknown labels fail closed.
/// </summary>
internal static class NarrativeGrammarContract
{
    private static readonly IReadOnlyDictionary<string, string> LegacyAliases =
        new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["grammar.present-simple.statement"] = "present.simple.core",
            ["grammar.present-simple.question"] = "present.simple.questions-negatives",
            ["grammar.present-simple.negative"] = "present.simple.questions-negatives",
            ["grammar.past-simple.statement"] = "past.simple.regular",
            ["grammar.future-intention"] = "future.going-to",
            ["grammar.passive-basic"] = "passive.past-simple",
            ["grammar.aspect-contrast"] = "present-perfect.vs-past-simple",
            ["grammar.be-present.statement"] = "verb.be.present",
            ["grammar.be-present.question"] = "verb.be.present",
            ["grammar.be-present.negative"] = "verb.be.present",
            ["grammar.past-simple.question"] = "past.simple.questions-negatives",
            ["grammar.past-simple.negative"] = "past.simple.questions-negatives",
            ["grammar.modal-obligation"] = "modals.must-have-to",
            ["grammar.modal-question"] = "modals.must-have-to",
            ["grammar.be-past.question"] = "past.simple.be",
            ["grammar.modal-possibility"] = "modals.can-could"
        };

    // Subset/superset snapshot of the exact stable IDs currently exported by
    // DEV04 GrammarCoachCore. Keeping this explicit makes accidental invented
    // integration IDs fail in DEV06 CI before canonical integration.
    private static readonly HashSet<string> KnownSkillIds = new(StringComparer.OrdinalIgnoreCase)
    {
        "verb.be.present",
        "present.simple.core",
        "present.simple.third-person",
        "present.simple.questions-negatives",
        "past.simple.be",
        "past.simple.regular",
        "past.simple.irregular",
        "past.simple.questions-negatives",
        "future.will",
        "future.going-to",
        "present.continuous",
        "past.continuous",
        "present-perfect.core",
        "present-perfect.vs-past-simple",
        "present-perfect-continuous",
        "past-perfect",
        "continuous-vs-simple",
        "articles.a-an-the",
        "countable-uncountable",
        "comparatives-superlatives",
        "modals.can-could",
        "modals.must-have-to",
        "modals.should",
        "passive.present-simple",
        "passive.past-simple",
        "conditionals.zero",
        "conditionals.first",
        "conditionals.second",
        "conditionals.third",
        "reported-speech.statements",
        "relative-clauses.defining",
        "gerund-infinitive.core"
    };

    public static IReadOnlyList<string> SkillIdsFor(ResolvedStoryChapter chapter) =>
        NormalizeSkillIds(chapter.Definition.GrammarSkillIds);

    public static CourseTaskDefinition NormalizeTask(CourseTaskDefinition task) =>
        task with { GrammarSkillIds = NormalizeSkillIds(task.GrammarSkillIds) };

    public static IReadOnlyList<string> NormalizeSkillIds(IEnumerable<string> skillIds)
    {
        var normalized = new List<string>();
        foreach (string raw in skillIds ?? Array.Empty<string>())
        {
            if (string.IsNullOrWhiteSpace(raw))
                throw new InvalidDataException("Narrative Course contains a blank Grammar skill reference.");
            string id = LegacyAliases.TryGetValue(raw, out string? mapped) ? mapped : raw;
            if (!KnownSkillIds.Contains(id))
                throw new InvalidDataException($"Narrative Course references Grammar skill '{raw}', which is not present in the current DEV04 stable skill graph.");
            if (!normalized.Contains(id, StringComparer.OrdinalIgnoreCase)) normalized.Add(id);
        }
        return normalized;
    }

    public static bool IsKnownSkillId(string id) => KnownSkillIds.Contains(id);
}

internal static class NarrativeCoursePracticeRouter
{
    public static IReadOnlyList<StoryPracticeRoute> BuildPostStoryRoutes(
        ResolvedStoryCatalog catalog,
        ResolvedStoryChapter chapter)
    {
        string[] targets = chapter.StableTargetEntryIds.Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        string[] grammar = NarrativeGrammarContract.SkillIdsFor(chapter).ToArray();
        DateTimeOffset now = DateTimeOffset.UtcNow;
        return new[]
        {
            new StoryPracticeRoute(StoryPracticeMode.Recall, chapter.Definition.Id, catalog.Dictionary.Id, targets, grammar, "Recheck meaning after narrative exposure.", now),
            new StoryPracticeRoute(StoryPracticeMode.Spelling, chapter.Definition.Id, catalog.Dictionary.Id, targets, grammar, "Actively spell the same story targets.", now),
            new StoryPracticeRoute(StoryPracticeMode.Sentence, chapter.Definition.Id, catalog.Dictionary.Id, targets, grammar, "Reuse the same stable targets in real Sentence practice.", now),
            new StoryPracticeRoute(StoryPracticeMode.Grammar, chapter.Definition.Id, catalog.Dictionary.Id, targets, grammar, "Reuse story vocabulary with live DEV04 stable Grammar skill IDs.", now)
        };
    }
}
