namespace WordDeck;

/// <summary>
/// Production course scheduler. CEFR progression is the primary curriculum
/// constraint; learner weakness influences recycling inside that progression
/// instead of allowing a fresh learner to jump to a later level merely because
/// that chapter happens to contain more target words.
/// </summary>
internal static class NarrativeCourseScheduler
{
    public static ResolvedStoryChapter SelectNext(
        ResolvedStoryCatalog catalog,
        StoryCourseState state,
        StorySchedulingContext context)
    {
        if (catalog is null) throw new ArgumentNullException(nameof(catalog));
        if (state is null) throw new ArgumentNullException(nameof(state));
        if (context is null) throw new ArgumentNullException(nameof(context));
        if (catalog.ChaptersById.Count == 0) throw new InvalidOperationException("Story catalog contains no chapters.");

        ResolvedStoryChapter[] chapters = catalog.ChaptersById.Values.ToArray();
        int minimumCompletions = chapters.Min(chapter => Progress(state, chapter).Completions);

        // Advance through the course in waves. A learner sees every chapter once
        // in CEFR order before a second full pass is eligible. This keeps the
        // curriculum structured while still allowing weakness to decide among
        // chapters at the same completion wave and CEFR level.
        ResolvedStoryChapter[] wave = chapters
            .Where(chapter => Progress(state, chapter).Completions == minimumCompletions)
            .ToArray();
        int lowestEligibleCefr = wave.Min(chapter => StoryCourseCatalog.CefrRank(chapter.Definition.Cefr));
        ResolvedStoryChapter[] level = wave
            .Where(chapter => StoryCourseCatalog.CefrRank(chapter.Definition.Cefr) == lowestEligibleCefr)
            .ToArray();

        return level
            .OrderByDescending(chapter => Weakness(chapter, context))
            .ThenBy(chapter => Progress(state, chapter).LastCompletedUtc ?? DateTimeOffset.MinValue)
            .ThenBy(chapter => chapter.Definition.Id, StringComparer.Ordinal)
            .First();
    }

    internal static double Weakness(ResolvedStoryChapter chapter, StorySchedulingContext context)
    {
        double lexical = chapter.StableTargetEntryIds.Count == 0
            ? 0
            : chapter.StableTargetEntryIds.Average(id =>
                Math.Clamp(context.LexicalWeaknessByEntryId.GetValueOrDefault(id, 0.5), 0, 1));
        IReadOnlyList<string> grammarSkills = NarrativeGrammarContract.SkillIdsFor(chapter);
        double grammar = grammarSkills.Count == 0
            ? 0
            : grammarSkills.Average(id =>
                Math.Clamp(context.GrammarWeaknessBySkillId.GetValueOrDefault(id, 0.5), 0, 1));
        return lexical * 0.7 + grammar * 0.3;
    }

    private static StoryChapterProgress Progress(StoryCourseState state, ResolvedStoryChapter chapter) =>
        state.ChapterProgress.GetValueOrDefault(chapter.Definition.Id) ?? new StoryChapterProgress();
}
