using System.Text.Json;

namespace WordDeck;

internal sealed class StoryChapterProgress
{
    public int Opens { get; set; }
    public int Completions { get; set; }
    public int TaskAttempts { get; set; }
    public int TaskFirstTrySuccesses { get; set; }
    public DateTimeOffset? LastOpenedUtc { get; set; }
    public DateTimeOffset? LastCompletedUtc { get; set; }
}

internal sealed class StoryTargetEvidence
{
    public int NarrativeEncounters { get; set; }
    public int CompletedNarrativeEncounters { get; set; }
    public DateTimeOffset? LastSeenUtc { get; set; }
}

internal sealed class StoryCourseState
{
    public int SchemaVersion { get; set; } = StoryCourseStateStore.CurrentSchemaVersion;
    public string? ActiveDictionaryId { get; set; }
    public string? ActiveUnitId { get; set; }
    public string? ActiveChapterId { get; set; }
    public string? ActiveTaskId { get; set; }
    public Dictionary<string, StoryChapterProgress> ChapterProgress { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public Dictionary<string, StoryTargetEvidence> TargetEvidenceByEntryId { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public List<StoryPracticeRoute> PendingPracticeRoutes { get; set; } = new();
}

internal sealed class StoryCourseStateStore
{
    public const int CurrentSchemaVersion = 1;
    private const int MaxPendingRoutes = 40;
    private readonly string _path;
    private readonly string _backupPath;
    private readonly string _recoveryDirectory;
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true, PropertyNameCaseInsensitive = true };

    public StoryCourseStateStore()
        : this(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WordDeck")) { }

    internal StoryCourseStateStore(string root)
    {
        if (string.IsNullOrWhiteSpace(root)) throw new ArgumentException("Story/Course state root is required.", nameof(root));
        string fullRoot = Path.GetFullPath(root);
        Directory.CreateDirectory(fullRoot);
        _path = Path.Combine(fullRoot, "story-course-state.json");
        _backupPath = Path.Combine(fullRoot, "story-course-state.backup.json");
        _recoveryDirectory = Path.Combine(fullRoot, "Backups");
    }

    public StoryCourseState Load()
    {
        if (!File.Exists(_path) && !File.Exists(_backupPath)) return Normalize(new StoryCourseState());
        Exception? primaryFailure = null;
        if (File.Exists(_path))
        {
            try { return Normalize(Parse(_path)); }
            catch (Exception ex) { primaryFailure = ex; }
        }
        if (File.Exists(_backupPath))
        {
            try { return Normalize(Parse(_backupPath)); }
            catch (Exception backupFailure)
            {
                throw new InvalidDataException(
                    "Story/Narrative Course progress could not be loaded safely from either the primary or backup state. Existing files were left untouched.",
                    new AggregateException(primaryFailure ?? new InvalidDataException("Primary Story/Course state is unavailable."), backupFailure));
            }
        }
        throw new InvalidDataException("Story/Narrative Course progress is unreadable. Existing progress was left untouched.", primaryFailure);
    }

    public void Save(StoryCourseState state)
    {
        StoryCourseState normalized = Normalize(Clone(state));
        string temp = _path + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(normalized, JsonOptions));
        _ = Normalize(Parse(temp));
        if (File.Exists(_path)) File.Copy(_path, _backupPath, true);
        File.Move(temp, _path, true);
        CopyInto(state, normalized);
    }

    public string CreateRecoveryBackup(StoryCourseState state, string reason)
    {
        Directory.CreateDirectory(_recoveryDirectory);
        string safe = string.Concat((reason ?? "manual").Select(ch => char.IsLetterOrDigit(ch) || ch is '-' or '_' ? ch : '-'));
        if (safe.Length == 0) safe = "manual";
        string path = Path.Combine(_recoveryDirectory, $"story-course-state-{DateTime.UtcNow:yyyyMMdd-HHmmssfff}-{safe}.json");
        StoryCourseState normalized = Normalize(Clone(state));
        File.WriteAllText(path, JsonSerializer.Serialize(normalized, JsonOptions));
        _ = Normalize(Parse(path));
        foreach (FileInfo stale in new DirectoryInfo(_recoveryDirectory)
                     .GetFiles("story-course-state-*.json")
                     .OrderByDescending(file => file.LastWriteTimeUtc)
                     .Skip(20))
        {
            try { stale.Delete(); } catch { }
        }
        return path;
    }

    public void QueuePracticeRoutes(StoryCourseState state, IEnumerable<StoryPracticeRoute> routes)
    {
        state.PendingPracticeRoutes ??= new();
        foreach (StoryPracticeRoute route in routes ?? Array.Empty<StoryPracticeRoute>())
        {
            ValidateRoute(route);
            state.PendingPracticeRoutes.RemoveAll(existing =>
                existing.Mode == route.Mode &&
                existing.ChapterId.Equals(route.ChapterId, StringComparison.OrdinalIgnoreCase) &&
                existing.DictionaryId.Equals(route.DictionaryId, StringComparison.OrdinalIgnoreCase));
            state.PendingPracticeRoutes.Add(route);
        }
        state.PendingPracticeRoutes = state.PendingPracticeRoutes
            .OrderBy(route => route.CreatedAtUtc)
            .TakeLast(MaxPendingRoutes)
            .ToList();
        Save(state);
    }

    public static StoryCourseState Normalize(StoryCourseState state)
    {
        if (state is null) throw new InvalidDataException("Story/Course state is missing.");
        if (state.SchemaVersion <= 0) state.SchemaVersion = CurrentSchemaVersion;
        if (state.SchemaVersion > CurrentSchemaVersion)
            throw new InvalidDataException($"Story/Course state schema {state.SchemaVersion} is newer than this WordDeck build. Existing progress was not changed.");
        state.SchemaVersion = CurrentSchemaVersion;
        state.ActiveDictionaryId = Clean(state.ActiveDictionaryId);
        state.ActiveUnitId = Clean(state.ActiveUnitId);
        state.ActiveChapterId = Clean(state.ActiveChapterId);
        state.ActiveTaskId = Clean(state.ActiveTaskId);

        state.ChapterProgress ??= new(StringComparer.OrdinalIgnoreCase);
        state.ChapterProgress = state.ChapterProgress
            .Where(pair => !string.IsNullOrWhiteSpace(pair.Key) && pair.Value is not null)
            .ToDictionary(pair => pair.Key.Trim(), pair => Normalize(pair.Value), StringComparer.OrdinalIgnoreCase);

        state.TargetEvidenceByEntryId ??= new(StringComparer.OrdinalIgnoreCase);
        state.TargetEvidenceByEntryId = state.TargetEvidenceByEntryId
            .Where(pair => !string.IsNullOrWhiteSpace(pair.Key) && pair.Value is not null)
            .ToDictionary(pair => pair.Key.Trim(), pair => Normalize(pair.Value), StringComparer.OrdinalIgnoreCase);

        state.PendingPracticeRoutes ??= new();
        foreach (StoryPracticeRoute route in state.PendingPracticeRoutes) ValidateRoute(route);
        state.PendingPracticeRoutes = state.PendingPracticeRoutes
            .GroupBy(route => $"{route.DictionaryId}\u001f{route.ChapterId}\u001f{route.Mode}", StringComparer.OrdinalIgnoreCase)
            .Select(group => group.OrderByDescending(route => route.CreatedAtUtc).First())
            .OrderBy(route => route.CreatedAtUtc)
            .TakeLast(MaxPendingRoutes)
            .ToList();
        return state;
    }

    public static void RecordOpen(StoryCourseState state, ResolvedStoryCatalog catalog, ResolvedStoryChapter chapter, DateTimeOffset now)
    {
        state.ActiveDictionaryId = catalog.Dictionary.Id;
        state.ActiveUnitId = chapter.Definition.UnitId;
        state.ActiveChapterId = chapter.Definition.Id;
        StoryChapterProgress progress = GetProgress(state, chapter.Definition.Id);
        progress.Opens++;
        progress.LastOpenedUtc = now;
        foreach (string entryId in chapter.StableTargetEntryIds)
        {
            StoryTargetEvidence evidence = GetTargetEvidence(state, entryId);
            evidence.NarrativeEncounters++;
            evidence.LastSeenUtc = now;
        }
    }

    public static void RecordCompletion(StoryCourseState state, ResolvedStoryChapter chapter, DateTimeOffset now)
    {
        StoryChapterProgress progress = GetProgress(state, chapter.Definition.Id);
        progress.Completions++;
        progress.LastCompletedUtc = now;
        foreach (string entryId in chapter.StableTargetEntryIds)
        {
            StoryTargetEvidence evidence = GetTargetEvidence(state, entryId);
            evidence.CompletedNarrativeEncounters++;
            evidence.LastSeenUtc = now;
        }
    }

    public static void RecordTaskAttempt(StoryCourseState state, ResolvedStoryChapter chapter, CourseTaskDefinition task, bool firstTrySuccess)
    {
        state.ActiveTaskId = task.Id;
        StoryChapterProgress progress = GetProgress(state, chapter.Definition.Id);
        progress.TaskAttempts++;
        if (firstTrySuccess) progress.TaskFirstTrySuccesses++;
    }

    private StoryCourseState Parse(string path)
    {
        try
        {
            StoryCourseState state = JsonSerializer.Deserialize<StoryCourseState>(File.ReadAllText(path), JsonOptions)
                ?? throw new InvalidDataException("Story/Course progress file is empty.");
            return state;
        }
        catch (InvalidDataException) { throw; }
        catch (Exception ex) { throw new InvalidDataException($"Story/Course progress file '{Path.GetFileName(path)}' is not readable.", ex); }
    }

    private static StoryChapterProgress GetProgress(StoryCourseState state, string chapterId)
    {
        state.ChapterProgress ??= new(StringComparer.OrdinalIgnoreCase);
        if (!state.ChapterProgress.TryGetValue(chapterId, out StoryChapterProgress? progress))
        {
            progress = new StoryChapterProgress();
            state.ChapterProgress[chapterId] = progress;
        }
        return progress;
    }

    private static StoryTargetEvidence GetTargetEvidence(StoryCourseState state, string entryId)
    {
        state.TargetEvidenceByEntryId ??= new(StringComparer.OrdinalIgnoreCase);
        if (!state.TargetEvidenceByEntryId.TryGetValue(entryId, out StoryTargetEvidence? evidence))
        {
            evidence = new StoryTargetEvidence();
            state.TargetEvidenceByEntryId[entryId] = evidence;
        }
        return evidence;
    }

    private static StoryChapterProgress Normalize(StoryChapterProgress value)
    {
        value.Opens = Math.Max(0, value.Opens);
        value.Completions = Math.Max(0, value.Completions);
        value.TaskAttempts = Math.Max(0, value.TaskAttempts);
        value.TaskFirstTrySuccesses = Math.Clamp(value.TaskFirstTrySuccesses, 0, value.TaskAttempts);
        return value;
    }

    private static StoryTargetEvidence Normalize(StoryTargetEvidence value)
    {
        value.NarrativeEncounters = Math.Max(0, value.NarrativeEncounters);
        value.CompletedNarrativeEncounters = Math.Clamp(value.CompletedNarrativeEncounters, 0, value.NarrativeEncounters);
        return value;
    }

    private static void ValidateRoute(StoryPracticeRoute route)
    {
        if (route is null || string.IsNullOrWhiteSpace(route.ChapterId) || string.IsNullOrWhiteSpace(route.DictionaryId))
            throw new InvalidDataException("Story post-practice route has incomplete identity.");
        if (route.TargetEntryIds is null || route.TargetEntryIds.Count == 0 || route.TargetEntryIds.Any(string.IsNullOrWhiteSpace))
            throw new InvalidDataException("Story post-practice route has no stable lexical targets.");
        if (route.GrammarSkillIds is null || route.GrammarSkillIds.Any(string.IsNullOrWhiteSpace))
            throw new InvalidDataException("Story post-practice route contains an invalid grammar skill.");
        if (string.IsNullOrWhiteSpace(route.Reason)) throw new InvalidDataException("Story post-practice route has no explanation.");
    }

    private static string? Clean(string? value) => string.IsNullOrWhiteSpace(value) ? null : value.Trim();

    private static StoryCourseState Clone(StoryCourseState state) =>
        JsonSerializer.Deserialize<StoryCourseState>(JsonSerializer.Serialize(state, JsonOptions), JsonOptions)
        ?? throw new InvalidDataException("Could not clone Story/Course progress state.");

    private static void CopyInto(StoryCourseState destination, StoryCourseState source)
    {
        destination.SchemaVersion = source.SchemaVersion;
        destination.ActiveDictionaryId = source.ActiveDictionaryId;
        destination.ActiveUnitId = source.ActiveUnitId;
        destination.ActiveChapterId = source.ActiveChapterId;
        destination.ActiveTaskId = source.ActiveTaskId;
        destination.ChapterProgress = source.ChapterProgress;
        destination.TargetEvidenceByEntryId = source.TargetEvidenceByEntryId;
        destination.PendingPracticeRoutes = source.PendingPracticeRoutes;
    }
}
