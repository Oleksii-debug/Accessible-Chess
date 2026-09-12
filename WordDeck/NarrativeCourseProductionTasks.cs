namespace WordDeck;

internal static class NarrativeCourseProductionTasks
{
    public static IReadOnlyList<CourseTaskDefinition> GetTasks(ResolvedStoryChapter chapter) =>
        NarrativeCourseTaskBank.GetTasks(chapter)
            .Select(NarrativeGrammarContract.NormalizeTask)
            .ToArray();

    public static IReadOnlySet<CourseTaskKind> CoveredKinds(ResolvedStoryCatalog catalog) =>
        catalog.ChaptersById.Values
            .SelectMany(GetTasks)
            .Select(task => task.Kind)
            .ToHashSet();
}
