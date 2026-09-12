using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace WordDeck;

internal sealed record StoryCoursePackageDiscoveryResult(
    IReadOnlyList<StoryCourseManifestContract> Courses,
    IReadOnlyList<string> Errors);

/// <summary>
/// Production package boundary for Story/Course. Only exact local JSON files are read;
/// network content and pedagogical drafts never become learner-facing runtime authority.
/// Every accepted package is revalidated against the active canonical dictionary and
/// GrammarSkillReferenceResolver through StoryCourseContractValidator.
/// </summary>
internal static class StoryCoursePackageLoader
{
    internal const string SearchPattern = "*.story-course.json";

    private static readonly JsonSerializerOptions JsonOptions = CreateJsonOptions();

    public static StoryCoursePackageDiscoveryResult Discover(DictionaryPackage dictionary)
    {
        ArgumentNullException.ThrowIfNull(dictionary);
        string localRoot = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "WordDeck",
            "Courses");
        return Discover(dictionary, new[] { Path.Combine(AppContext.BaseDirectory, "Courses"), localRoot });
    }

    internal static StoryCoursePackageDiscoveryResult Discover(DictionaryPackage dictionary, IEnumerable<string> roots)
    {
        ArgumentNullException.ThrowIfNull(dictionary);
        ArgumentNullException.ThrowIfNull(roots);

        var courses = new List<StoryCourseManifestContract>();
        var errors = new List<string>();
        var seenFiles = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var seenCourseIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (string rawRoot in roots.Where(root => !string.IsNullOrWhiteSpace(root)))
        {
            string root;
            try { root = Path.GetFullPath(rawRoot); }
            catch (Exception ex)
            {
                errors.Add($"Course folder '{rawRoot}' is invalid: {ex.Message}");
                continue;
            }

            if (!Directory.Exists(root)) continue;

            IEnumerable<string> files;
            try { files = Directory.EnumerateFiles(root, SearchPattern, SearchOption.TopDirectoryOnly).Order(StringComparer.OrdinalIgnoreCase).ToArray(); }
            catch (Exception ex)
            {
                errors.Add($"Course folder '{root}' could not be read: {ex.Message}");
                continue;
            }

            foreach (string file in files)
            {
                string fullPath;
                try { fullPath = Path.GetFullPath(file); }
                catch (Exception ex)
                {
                    errors.Add($"Course package path '{file}' is invalid: {ex.Message}");
                    continue;
                }
                if (!seenFiles.Add(fullPath)) continue;

                try
                {
                    StoryCourseManifestContract manifest = Deserialize(File.ReadAllText(fullPath));
                    StoryCourseContractValidator.Validate(manifest, dictionary);
                    if (manifest.CurriculumAuthority != StoryCourseCurriculumAuthority.ApprovedCurriculum)
                        throw new InvalidDataException("Only independently approved curriculum is eligible for the learner-facing Story/Course runtime.");
                    if (!seenCourseIds.Add(manifest.CourseId))
                        throw new InvalidDataException($"Duplicate approved course id '{manifest.CourseId}' was found. WordDeck will not guess which package is authoritative.");
                    courses.Add(manifest);
                }
                catch (Exception ex)
                {
                    errors.Add($"{Path.GetFileName(fullPath)}: {ex.Message}");
                }
            }
        }

        return new StoryCoursePackageDiscoveryResult(courses, errors);
    }

    internal static string Serialize(StoryCourseManifestContract manifest)
    {
        ArgumentNullException.ThrowIfNull(manifest);
        return JsonSerializer.Serialize(manifest, JsonOptions);
    }

    internal static StoryCourseManifestContract Deserialize(string json)
    {
        if (string.IsNullOrWhiteSpace(json)) throw new InvalidDataException("Story/Course package is empty.");
        try
        {
            return JsonSerializer.Deserialize<StoryCourseManifestContract>(json, JsonOptions)
                ?? throw new InvalidDataException("Story/Course package did not contain a manifest.");
        }
        catch (JsonException ex)
        {
            throw new InvalidDataException("Story/Course package JSON is invalid.", ex);
        }
    }

    private static JsonSerializerOptions CreateJsonOptions()
    {
        var options = new JsonSerializerOptions(JsonSerializerDefaults.Web)
        {
            WriteIndented = true,
            PropertyNameCaseInsensitive = false
        };
        options.Converters.Add(new JsonStringEnumConverter(JsonNamingPolicy.CamelCase, allowIntegerValues: false));
        return options;
    }
}

/// <summary>
/// Restart-safe progress persistence isolated from Recall/Spelling/Sentence state. The store
/// validates before and after every write, keeps a last-known-good backup, and refuses to
/// downgrade a newer schema. It never derives mastery from exposure or task completion.
/// </summary>
internal sealed class StoryCourseRuntimeStateStore
{
    public const int CurrentSchemaVersion = 1;
    private readonly string _path;
    private readonly string _backupPath;
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web) { WriteIndented = true };

    public StoryCourseRuntimeStateStore(string courseId)
        : this(
            courseId,
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WordDeck", "StoryCourseProgress"))
    {
    }

    internal StoryCourseRuntimeStateStore(string courseId, string root)
    {
        StoryCourseContractId.Require(courseId, "Story/Course state course id");
        if (string.IsNullOrWhiteSpace(root)) throw new ArgumentException("Story/Course state root is required.", nameof(root));
        string fullRoot = Path.GetFullPath(root);
        Directory.CreateDirectory(fullRoot);
        string safeCourseId = Regex.Replace(courseId, "[^a-z0-9._-]", "-", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
        _path = Path.Combine(fullRoot, safeCourseId + ".progress.json");
        _backupPath = Path.Combine(fullRoot, safeCourseId + ".progress.backup.json");
    }

    public StoryCourseProgressContract LoadOrCreate(StoryCourseManifestContract manifest)
    {
        ArgumentNullException.ThrowIfNull(manifest);
        if (!File.Exists(_path) && !File.Exists(_backupPath)) return CreateInitial(manifest);

        Exception? primaryFailure = null;
        if (File.Exists(_path))
        {
            try { return ReadValidated(_path, manifest.CourseId); }
            catch (StoryCourseNewerRuntimeStateException ex) { throw new InvalidDataException(ex.Message, ex); }
            catch (Exception ex) { primaryFailure = ex; }
        }

        if (File.Exists(_backupPath))
        {
            try { return ReadValidated(_backupPath, manifest.CourseId); }
            catch (StoryCourseNewerRuntimeStateException ex) { throw new InvalidDataException(ex.Message, ex); }
            catch (Exception backupFailure)
            {
                throw new InvalidDataException(
                    "Story/Course progress could not be loaded safely from either primary or backup state. Existing files were left untouched.",
                    new AggregateException(primaryFailure ?? new InvalidDataException("Primary Story/Course state is unavailable."), backupFailure));
            }
        }

        throw new InvalidDataException("Story/Course progress is unreadable. Existing progress was left untouched.", primaryFailure);
    }

    public void Save(StoryCourseProgressContract progress)
    {
        ValidateRuntimeProgress(progress);
        string temp = _path + ".tmp";
        try
        {
            File.WriteAllText(temp, JsonSerializer.Serialize(progress, JsonOptions));
            _ = ReadValidated(temp, progress.CourseId);
            if (File.Exists(_path)) File.Copy(_path, _backupPath, overwrite: true);
            File.Move(temp, _path, overwrite: true);
        }
        finally
        {
            try { if (File.Exists(temp)) File.Delete(temp); } catch { }
        }
    }

    internal static StoryCourseProgressContract CreateInitial(StoryCourseManifestContract manifest)
    {
        ArgumentNullException.ThrowIfNull(manifest);
        StoryCourseLevelContract firstLevel = manifest.Levels.First();
        StoryCourseModuleContract firstModule = firstLevel.Modules.First();
        StoryCourseUnitContract firstUnit = firstModule.Units.First();
        var progress = new StoryCourseProgressContract(
            CurrentSchemaVersion,
            manifest.CourseId,
            firstLevel.LevelId,
            firstModule.ModuleId,
            firstUnit.UnitId,
            Array.Empty<string>(),
            Array.Empty<string>(),
            new Dictionary<string, StoryCourseObjectiveProgressContract>(StringComparer.OrdinalIgnoreCase));
        ValidateRuntimeProgress(progress);
        return progress;
    }

    internal static StoryCourseProgressContract SelectUnit(
        StoryCourseProgressContract progress,
        StoryCourseLevelContract level,
        StoryCourseModuleContract module,
        StoryCourseUnitContract unit)
    {
        ArgumentNullException.ThrowIfNull(progress);
        return progress with
        {
            ActiveLevelId = level.LevelId,
            ActiveModuleId = module.ModuleId,
            ActiveUnitId = unit.UnitId
        };
    }

    internal static StoryCourseProgressContract RecordNarrativeCompletion(
        StoryCourseProgressContract progress,
        StoryCourseNarrativeContract narrative)
    {
        ArgumentNullException.ThrowIfNull(progress);
        ArgumentNullException.ThrowIfNull(narrative);
        var completed = new HashSet<string>(progress.CompletedContentIds, StringComparer.OrdinalIgnoreCase) { narrative.ContentId };
        StoryCourseProgressContract updated = progress with { CompletedContentIds = completed.Order(StringComparer.OrdinalIgnoreCase).ToArray() };
        ValidateRuntimeProgress(updated);
        return updated;
    }

    internal static StoryCourseProgressContract RecordBoundedComprehensionSuccess(
        StoryCourseProgressContract progress,
        StoryCourseComprehensionTaskContract task)
    {
        ArgumentNullException.ThrowIfNull(progress);
        ArgumentNullException.ThrowIfNull(task);
        if (task.Kind != StoryCourseComprehensionKind.BoundedResponse)
            throw new InvalidOperationException("Free-response comprehension cannot be silently converted into bounded evidence.");

        bool firstCompletion = !progress.CompletedTaskIds.Contains(task.TaskId, StringComparer.OrdinalIgnoreCase);
        var completed = new HashSet<string>(progress.CompletedTaskIds, StringComparer.OrdinalIgnoreCase) { task.TaskId };
        var objective = new Dictionary<string, StoryCourseObjectiveProgressContract>(progress.ObjectiveProgress, StringComparer.OrdinalIgnoreCase);

        if (firstCompletion)
        {
            foreach (string objectiveId in task.ObjectiveIds)
            {
                objective.TryGetValue(objectiveId, out StoryCourseObjectiveProgressContract? existing);
                existing ??= new StoryCourseObjectiveProgressContract(
                    objectiveId, 0, 0, 0, 0, StoryCourseMasteryDecision.Unknown, null);
                objective[objectiveId] = existing with
                {
                    ComprehensionEvidenceCount = existing.ComprehensionEvidenceCount + 1
                };
            }
        }

        StoryCourseProgressContract updated = progress with
        {
            CompletedTaskIds = completed.Order(StringComparer.OrdinalIgnoreCase).ToArray(),
            ObjectiveProgress = objective
        };
        ValidateRuntimeProgress(updated);
        return updated;
    }

    internal static bool IsAcceptedBoundedAnswer(StoryCourseComprehensionTaskContract task, string answer)
    {
        ArgumentNullException.ThrowIfNull(task);
        if (task.Kind != StoryCourseComprehensionKind.BoundedResponse || string.IsNullOrWhiteSpace(answer)) return false;
        string normalized = NormalizeAnswer(answer);
        return task.AcceptedBoundedResponses.Any(candidate =>
            NormalizeAnswer(candidate).Equals(normalized, StringComparison.OrdinalIgnoreCase));
    }

    private StoryCourseProgressContract ReadValidated(string path, string expectedCourseId)
    {
        StoryCourseProgressContract progress;
        try
        {
            progress = JsonSerializer.Deserialize<StoryCourseProgressContract>(File.ReadAllText(path), JsonOptions)
                ?? throw new InvalidDataException("Story/Course progress file is empty.");
        }
        catch (JsonException ex)
        {
            throw new InvalidDataException($"Story/Course progress file '{Path.GetFileName(path)}' is invalid JSON.", ex);
        }

        if (progress.SchemaVersion > CurrentSchemaVersion)
            throw new StoryCourseNewerRuntimeStateException(
                $"Story/Course progress schema {progress.SchemaVersion} is newer than this WordDeck build. WordDeck will not overwrite it or fall back to an older backup.");
        if (!progress.CourseId.Equals(expectedCourseId, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Story/Course progress belongs to a different course id.");
        ValidateRuntimeProgress(progress);
        return progress;
    }

    private static void ValidateRuntimeProgress(StoryCourseProgressContract progress)
    {
        progress.Validate();
        if (progress.SchemaVersion > CurrentSchemaVersion)
            throw new InvalidDataException($"Story/Course progress schema {progress.SchemaVersion} is newer than this WordDeck build.");
    }

    private static string NormalizeAnswer(string value) =>
        string.Join(" ", value.Trim().Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));

    private sealed class StoryCourseNewerRuntimeStateException : Exception
    {
        public StoryCourseNewerRuntimeStateException(string message) : base(message) { }
    }
}
