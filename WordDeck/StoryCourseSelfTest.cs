using System.Text.Json;

namespace WordDeck;

internal static class StoryCourseSelfTest
{
    public static void Run()
    {
        ValidateProductionCatalogAndStableIds();
        ValidateSchedulerAndRouting();
        ValidateTaskEvaluation();
        ValidateRestartBackupAndFailClosedState();
        Console.WriteLine("Story/Narrative Course self-test PASS.");
    }

    private static void ValidateProductionCatalogAndStableIds()
    {
        DictionaryPackage dictionary = DictionaryLoader.LoadEmbeddedOxford();
        ResolvedStoryCatalog catalog = StoryCourseCatalog.Resolve(dictionary);
        Require(catalog.Units.Count >= 5, "Narrative Course must expose a real A1-C1 progression, not a single demo unit.");
        Require(catalog.Units.Select(unit => unit.Cefr).SequenceEqual(new[] { "A1", "A2", "B1", "B2", "C1" }, StringComparer.OrdinalIgnoreCase),
            "Built-in Narrative Course CEFR progression must be A1, A2, B1, B2, C1.");
        ResolvedStoryChapter[] chapters = catalog.ChaptersById.Values.ToArray();
        Require(chapters.Length >= 5, "Story Engine needs multiple production chapters.");
        Require(chapters.Sum(chapter => chapter.Targets.Count) >= 20, "Built-in Story curriculum should exercise dozens of lexical targets across its current chapters.");
        Require(chapters.All(chapter => chapter.Definition.Provenance.Origin == StoryContentOrigin.WordDeckAuthored),
            "Current built-in Story material must identify itself as WordDeck-authored, not sourced/generated.");
        Require(chapters.All(chapter => chapter.StableTargetEntryIds.Count == chapter.StableTargetEntryIds.Distinct(StringComparer.OrdinalIgnoreCase).Count()),
            "Resolved Story chapters must preserve distinct stable target IDs.");
        Require(chapters.SelectMany(chapter => chapter.StableTargetEntryIds).All(id => dictionary.Entries.Any(entry => entry.Id.Equals(id, StringComparison.OrdinalIgnoreCase))),
            "Every Story target stable ID must exist in the live dictionary.");
        foreach (ResolvedStoryChapter chapter in chapters)
        {
            chapter.Definition.Validate();
            Require(chapter.Definition.Tasks.Count > 0, $"Chapter {chapter.Definition.Id} has no usable Narrative Course task.");
            Require(chapter.Definition.GrammarSkillIds.Count > 0, $"Chapter {chapter.Definition.Id} has no Grammar integration reference.");
        }
    }

    private static void ValidateSchedulerAndRouting()
    {
        ResolvedStoryCatalog catalog = StoryCourseCatalog.Resolve(DictionaryLoader.LoadEmbeddedOxford());
        StoryCourseState state = StoryCourseStateStore.Normalize(new StoryCourseState());
        var neutral = new StorySchedulingContext(
            new Dictionary<string, double>(StringComparer.OrdinalIgnoreCase),
            new Dictionary<string, double>(StringComparer.OrdinalIgnoreCase));

        ResolvedStoryChapter first = NarrativeCourseScheduler.SelectNext(catalog, state, neutral);
        Require(first.Definition.Cefr.Equals("A1", StringComparison.OrdinalIgnoreCase),
            "Fresh deterministic course should begin at the lowest incomplete CEFR unit.");

        StoryCourseStateStore.RecordOpen(state, catalog, first, DateTimeOffset.UtcNow);
        StoryCourseStateStore.RecordCompletion(state, first, DateTimeOffset.UtcNow);
        ResolvedStoryChapter second = NarrativeCourseScheduler.SelectNext(catalog, state, neutral);
        Require(second.Definition.Cefr.Equals("A2", StringComparison.OrdinalIgnoreCase),
            "After completing the A1 wave, the course should advance to A2 before recycling later CEFR material.");

        StoryCourseStateStore.RecordCompletion(state, second, DateTimeOffset.UtcNow);
        ResolvedStoryChapter third = NarrativeCourseScheduler.SelectNext(catalog, state, neutral);
        Require(third.Definition.Cefr.Equals("B1", StringComparison.OrdinalIgnoreCase),
            "Structured course progression should continue A1 -> A2 -> B1.");

        // Weakness may rank eligible material, but it must never make a fresh
        // learner skip an earlier CEFR wave.
        ResolvedStoryChapter c1 = catalog.ChaptersById.Values.Single(chapter => chapter.Definition.Cefr.Equals("C1", StringComparison.OrdinalIgnoreCase));
        var forcedLaterWeakness = new StorySchedulingContext(
            c1.StableTargetEntryIds.ToDictionary(id => id, _ => 1.0, StringComparer.OrdinalIgnoreCase),
            c1.Definition.GrammarSkillIds.ToDictionary(id => id, _ => 1.0, StringComparer.OrdinalIgnoreCase));
        StoryCourseState fresh = StoryCourseStateStore.Normalize(new StoryCourseState());
        Require(NarrativeCourseScheduler.SelectNext(catalog, fresh, forcedLaterWeakness).Definition.Cefr.Equals("A1", StringComparison.OrdinalIgnoreCase),
            "Weak C1 evidence must not bypass the A1 course gate for a fresh learner.");

        IReadOnlyList<StoryPracticeRoute> routes = StoryCoursePracticeRouter.BuildPostStoryRoutes(catalog, first);
        Require(routes.Count == 4, "Story completion must produce Recall, Spelling, Sentence and Grammar routing contracts.");
        Require(routes.Select(route => route.Mode).Distinct().Count() == 4, "Story post-practice routes must cover four distinct modes.");
        Require(routes.All(route => route.TargetEntryIds.SequenceEqual(first.StableTargetEntryIds, StringComparer.OrdinalIgnoreCase)),
            "Post-story routes must preserve the chapter's stable target IDs exactly.");
        Require(routes.Single(route => route.Mode == StoryPracticeMode.Grammar).GrammarSkillIds.Count > 0,
            "Grammar route must preserve granular grammar-skill references.");
    }

    private static void ValidateTaskEvaluation()
    {
        CourseTaskDefinition task = StoryCourseCatalog.BuiltInUnits[0].Chapters[0].Tasks[0];
        Require(StoryTaskEvaluator.IsAccepted(task, "school"), "Bounded Story comprehension answer should be accepted.");
        Require(StoryTaskEvaluator.IsAccepted(task, "School."), "Story task checking should normalize harmless casing/punctuation.");
        Require(!StoryTaskEvaluator.IsAccepted(task, "home"), "Wrong Story comprehension answer must not be accepted.");
    }

    private static void ValidateRestartBackupAndFailClosedState()
    {
        string root = Path.Combine(Path.GetTempPath(), "WordDeck-StoryCourseSelfTest-" + Guid.NewGuid().ToString("N"));
        string newerRoot = Path.Combine(Path.GetTempPath(), "WordDeck-StoryCourseNewerSelfTest-" + Guid.NewGuid().ToString("N"));
        try
        {
            Directory.CreateDirectory(root);
            var store = new StoryCourseStateStore(root);
            StoryCourseState state = store.Load();
            ResolvedStoryCatalog catalog = StoryCourseCatalog.Resolve(DictionaryLoader.LoadEmbeddedOxford());
            ResolvedStoryChapter chapter = catalog.ChaptersById.Values.OrderBy(x => StoryCourseCatalog.CefrRank(x.Definition.Cefr)).First();
            StoryCourseStateStore.RecordOpen(state, catalog, chapter, DateTimeOffset.UtcNow);
            store.Save(state);

            StoryCourseStateStore.RecordCompletion(state, chapter, DateTimeOffset.UtcNow);
            IReadOnlyList<StoryPracticeRoute> routes = StoryCoursePracticeRouter.BuildPostStoryRoutes(catalog, chapter);
            store.QueuePracticeRoutes(state, routes);
            StoryCourseState restarted = store.Load();
            Require(restarted.ChapterProgress[chapter.Definition.Id].Completions == 1, "Story completion must survive restart.");
            Require(restarted.PendingPracticeRoutes.Count == 4, "Queued post-story routes must survive restart.");
            Require(restarted.TargetEvidenceByEntryId.Keys.All(id => chapter.StableTargetEntryIds.Contains(id, StringComparer.OrdinalIgnoreCase)),
                "Story evidence must remain keyed by stable dictionary IDs.");

            string recovery = store.CreateRecoveryBackup(restarted, "self-test");
            Require(File.Exists(recovery), "Story state recovery backup was not created.");

            // A later interrupted/corrupt primary file must recover from the last
            // parseable backup rather than resetting progress to zero.
            File.WriteAllText(Path.Combine(root, "story-course-state.json"), "{ broken json");
            StoryCourseState recovered = store.Load();
            Require(recovered.ChapterProgress.ContainsKey(chapter.Definition.Id), "Story state did not recover from backup after primary corruption.");

            Directory.CreateDirectory(newerRoot);
            File.WriteAllText(
                Path.Combine(newerRoot, "story-course-state.json"),
                JsonSerializer.Serialize(new StoryCourseState { SchemaVersion = StoryCourseStateStore.CurrentSchemaVersion + 100 }));
            bool rejected = false;
            try { _ = new StoryCourseStateStore(newerRoot).Load(); }
            catch (InvalidDataException) { rejected = true; }
            Require(rejected, "Newer Story/Course schema must fail closed instead of silently downgrading/resetting progress.");
        }
        finally
        {
            try { if (Directory.Exists(root)) Directory.Delete(root, true); } catch { }
            try { if (Directory.Exists(newerRoot)) Directory.Delete(newerRoot, true); } catch { }
        }
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidDataException("StoryCourseSelfTest: " + message);
    }
}
