using System.Text.Json;

namespace WordDeck;

internal enum AssessmentMode
{
    Practice,
    Assessment
}

internal enum AssessmentMark
{
    Correct,
    Incorrect,
    Skipped,
    Unscored
}

internal sealed record AssessmentItemKey(
    string PoolId,
    int PoolVersion,
    string ItemId,
    int ItemVersion)
{
    public string ContentIdentity => $"{PoolId}\u001f{ItemId}\u001f{ItemVersion}";

    public void Validate()
    {
        AssessmentValidation.RequireStableId(PoolId, "assessment pool id");
        AssessmentValidation.RequireStableId(ItemId, "assessment item id");
        if (PoolVersion < 1) throw new InvalidDataException("Assessment pool version must be positive.");
        if (ItemVersion < 1) throw new InvalidDataException("Assessment item version must be positive.");
    }
}

internal sealed record AssessmentItem(
    AssessmentItemKey Key,
    string SkillId,
    int DifficultyTier)
{
    public void Validate()
    {
        ArgumentNullException.ThrowIfNull(Key);
        Key.Validate();
        AssessmentValidation.RequireStableId(SkillId, "assessment skill id");
        if (DifficultyTier is < 1 or > 3)
            throw new InvalidDataException("Assessment difficulty tier must be 1, 2 or 3. It is a routing tier, not a psychometric score.");
    }
}

internal sealed class AssessmentItemPool
{
    public string PoolId { get; set; } = string.Empty;
    public int Version { get; set; } = 1;
    public List<AssessmentItem> Items { get; set; } = new();

    public void Validate()
    {
        AssessmentValidation.RequireStableId(PoolId, "assessment pool id");
        if (Version < 1) throw new InvalidDataException("Assessment pool version must be positive.");
        if (Items.Count == 0) throw new InvalidDataException("Assessment item pool cannot be empty.");

        var itemIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (AssessmentItem item in Items)
        {
            if (item is null) throw new InvalidDataException("Assessment item pool contains a null item.");
            item.Validate();
            if (!string.Equals(item.Key.PoolId, PoolId, StringComparison.OrdinalIgnoreCase) || item.Key.PoolVersion != Version)
                throw new InvalidDataException($"Assessment item {item.Key.ItemId} does not belong to pool {PoolId} version {Version}.");
            if (!itemIds.Add(item.Key.ItemId))
                throw new InvalidDataException($"Assessment pool contains duplicate item id {item.Key.ItemId}.");
        }
    }

    public AssessmentItem Resolve(AssessmentItemKey key)
    {
        ArgumentNullException.ThrowIfNull(key);
        ValidateExactVersion(key);
        AssessmentItem? item = Items.FirstOrDefault(candidate =>
            string.Equals(candidate.Key.ItemId, key.ItemId, StringComparison.OrdinalIgnoreCase) &&
            candidate.Key.ItemVersion == key.ItemVersion);
        return item ?? throw new InvalidDataException($"Assessment item {key.ItemId} v{key.ItemVersion} is not present in pool {PoolId} v{Version}.");
    }

    public void ValidateExactVersion(AssessmentItemKey key)
    {
        if (!string.Equals(key.PoolId, PoolId, StringComparison.OrdinalIgnoreCase) || key.PoolVersion != Version)
            throw new InvalidDataException($"Assessment pool mismatch. Session requires {key.PoolId} v{key.PoolVersion}; supplied pool is {PoolId} v{Version}.");
    }
}

internal sealed class AssessmentAttempt
{
    public string AttemptId { get; set; } = string.Empty;
    public string SessionId { get; set; } = string.Empty;
    public AssessmentMode Mode { get; set; }
    public AssessmentItemKey ItemKey { get; set; } = new("invalid", 1, "invalid", 1);
    public string SkillId { get; set; } = string.Empty;
    public int DifficultyTier { get; set; } = 2;
    public AssessmentMark Mark { get; set; }
    public bool UsedHint { get; set; }
    public bool RevealedAnswer { get; set; }
    public DateTimeOffset RecordedAtUtc { get; set; }

    public void Validate()
    {
        AssessmentValidation.RequireStableId(AttemptId, "assessment attempt id");
        AssessmentValidation.RequireStableId(SessionId, "assessment session id");
        ItemKey.Validate();
        AssessmentValidation.RequireStableId(SkillId, "assessment skill id");
        if (DifficultyTier is < 1 or > 3) throw new InvalidDataException("Assessment attempt has invalid difficulty tier.");
        if (!Enum.IsDefined(Mode)) throw new InvalidDataException("Assessment attempt has invalid mode.");
        if (!Enum.IsDefined(Mark)) throw new InvalidDataException("Assessment attempt has invalid mark.");
        if (Mode == AssessmentMode.Assessment && (UsedHint || RevealedAnswer))
            throw new InvalidDataException("Formal assessment history cannot contain hint or revealed-answer attempts.");
    }
}

internal sealed class AssessmentSessionState
{
    public string SessionId { get; set; } = string.Empty;
    public string PoolId { get; set; } = string.Empty;
    public int PoolVersion { get; set; } = 1;
    public AssessmentMode Mode { get; set; }
    public bool AdaptiveDifficulty { get; set; }
    public int RetakeRecentWindow { get; set; } = 5;
    public int PlannedItemCount { get; set; }
    public List<AssessmentItemKey> ItemOrder { get; set; } = new();
    public int Cursor { get; set; }
    public DateTimeOffset StartedAtUtc { get; set; }
    public DateTimeOffset? CompletedAtUtc { get; set; }

    public bool IsComplete => Cursor >= ItemOrder.Count;

    public void Validate()
    {
        AssessmentValidation.RequireStableId(SessionId, "assessment session id");
        AssessmentValidation.RequireStableId(PoolId, "assessment pool id");
        if (PoolVersion < 1) throw new InvalidDataException("Assessment session pool version must be positive.");
        if (!Enum.IsDefined(Mode)) throw new InvalidDataException("Assessment session has invalid mode.");
        if (RetakeRecentWindow < 0) throw new InvalidDataException("Assessment retake recent window cannot be negative.");
        if (PlannedItemCount < 1 || PlannedItemCount != ItemOrder.Count)
            throw new InvalidDataException("Assessment session planned item count does not match its fixed item order.");
        if (Cursor < 0 || Cursor > ItemOrder.Count) throw new InvalidDataException("Assessment session cursor is outside its item order.");
        foreach (AssessmentItemKey key in ItemOrder)
        {
            key.Validate();
            if (!string.Equals(key.PoolId, PoolId, StringComparison.OrdinalIgnoreCase) || key.PoolVersion != PoolVersion)
                throw new InvalidDataException("Assessment session item order mixes pool identities or versions.");
        }
        if (ItemOrder.Select(key => key.ContentIdentity).Distinct(StringComparer.OrdinalIgnoreCase).Count() != ItemOrder.Count)
            throw new InvalidDataException("Assessment session item order contains duplicate content identities.");
        if (CompletedAtUtc.HasValue && !IsComplete)
            throw new InvalidDataException("Assessment session is marked complete before its cursor reached the end.");
    }
}

internal sealed class AssessmentRuntimeState
{
    public const int CurrentSchemaVersion = 1;

    public int SchemaVersion { get; set; } = CurrentSchemaVersion;
    public List<AssessmentAttempt> Attempts { get; set; } = new();
    public List<AssessmentSessionState> Sessions { get; set; } = new();

    public void Validate()
    {
        if (SchemaVersion != CurrentSchemaVersion)
            throw new InvalidDataException($"Unsupported assessment runtime schema {SchemaVersion}; expected {CurrentSchemaVersion}.");

        var sessionIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (AssessmentSessionState session in Sessions)
        {
            if (session is null) throw new InvalidDataException("Assessment runtime contains a null session.");
            session.Validate();
            if (!sessionIds.Add(session.SessionId)) throw new InvalidDataException($"Duplicate assessment session id {session.SessionId}.");
        }

        var attemptIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (AssessmentAttempt attempt in Attempts)
        {
            if (attempt is null) throw new InvalidDataException("Assessment runtime contains a null attempt.");
            attempt.Validate();
            if (!attemptIds.Add(attempt.AttemptId)) throw new InvalidDataException($"Duplicate assessment attempt id {attempt.AttemptId}.");
        }
    }
}

internal sealed record AssessmentResumeSnapshot(
    string SessionId,
    AssessmentMode Mode,
    AssessmentItem? CurrentItem,
    int CompletedItems,
    int TotalItems,
    bool IsComplete);

internal sealed record AssessmentSkillResult(
    string SkillId,
    int Attempts,
    int Correct,
    int Incorrect,
    int Skipped,
    int Unscored,
    double? DescriptiveAccuracy)
{
    public bool PsychometricallyCalibrated => false;
}

internal sealed record AssessmentResultSummary(
    string SessionId,
    string PoolId,
    int PoolVersion,
    IReadOnlyList<AssessmentSkillResult> SkillResults)
{
    public bool PsychometricCalibrationApplied => false;
    public bool AiCanonicalAssessorUsed => false;
}

/// <summary>
/// Fixed, transparent routing heuristic. These thresholds are engineering defaults for
/// choosing a nearby item tier; they are not an ability estimate, CEFR placement score,
/// IRT parameter, norm-referenced score or other psychometric calibration.
/// </summary>
internal static class AssessmentDifficultyHeuristic
{
    public const int RecentScoredAttemptLimit = 6;

    public static int SuggestTier(IEnumerable<AssessmentAttempt> history, string skillId)
    {
        AssessmentValidation.RequireStableId(skillId, "assessment skill id");
        AssessmentAttempt[] scored = history
            .Where(attempt => attempt.Mode == AssessmentMode.Assessment &&
                              string.Equals(attempt.SkillId, skillId, StringComparison.OrdinalIgnoreCase) &&
                              attempt.Mark is AssessmentMark.Correct or AssessmentMark.Incorrect)
            .OrderByDescending(attempt => attempt.RecordedAtUtc)
            .ThenByDescending(attempt => attempt.AttemptId, StringComparer.Ordinal)
            .Take(RecentScoredAttemptLimit)
            .ToArray();

        if (scored.Length == 0) return 2;
        double accuracy = scored.Count(attempt => attempt.Mark == AssessmentMark.Correct) / (double)scored.Length;
        if (accuracy <= 0.50) return 1;
        if (accuracy >= 0.80) return 3;
        return 2;
    }
}

internal sealed class AssessmentRuntime
{
    private readonly AssessmentRuntimeState _state;

    public AssessmentRuntime(AssessmentRuntimeState? state = null)
    {
        _state = state ?? new AssessmentRuntimeState();
        _state.Validate();
    }

    public AssessmentRuntimeState State => _state;

    public AssessmentSessionState StartSession(
        AssessmentItemPool pool,
        AssessmentMode mode,
        int itemCount,
        bool adaptiveDifficulty,
        DateTimeOffset? nowUtc = null,
        int retakeRecentWindow = 5,
        string? sessionId = null)
    {
        ArgumentNullException.ThrowIfNull(pool);
        pool.Validate();
        if (!Enum.IsDefined(mode)) throw new ArgumentOutOfRangeException(nameof(mode));
        if (itemCount < 1 || itemCount > pool.Items.Count) throw new ArgumentOutOfRangeException(nameof(itemCount));
        if (retakeRecentWindow < 0) throw new ArgumentOutOfRangeException(nameof(retakeRecentWindow));

        string id = string.IsNullOrWhiteSpace(sessionId) ? $"assessment-session-{Guid.NewGuid():N}" : sessionId.Trim();
        AssessmentValidation.RequireStableId(id, "assessment session id");
        if (_state.Sessions.Any(session => string.Equals(session.SessionId, id, StringComparison.OrdinalIgnoreCase)))
            throw new InvalidOperationException($"Assessment session {id} already exists.");

        List<AssessmentItemKey> selected = SelectItems(pool, mode, itemCount, adaptiveDifficulty, retakeRecentWindow)
            .Select(item => item.Key)
            .ToList();

        var session = new AssessmentSessionState
        {
            SessionId = id,
            PoolId = pool.PoolId,
            PoolVersion = pool.Version,
            Mode = mode,
            AdaptiveDifficulty = adaptiveDifficulty,
            RetakeRecentWindow = retakeRecentWindow,
            PlannedItemCount = selected.Count,
            ItemOrder = selected,
            Cursor = 0,
            StartedAtUtc = nowUtc ?? DateTimeOffset.UtcNow
        };
        session.Validate();
        _state.Sessions.Add(session);
        return session;
    }

    public AssessmentResumeSnapshot ResumeSession(string sessionId, AssessmentItemPool pool)
    {
        ArgumentNullException.ThrowIfNull(pool);
        pool.Validate();
        AssessmentSessionState session = FindSession(sessionId);
        ValidatePoolForSession(session, pool);
        AssessmentItem? current = session.IsComplete ? null : pool.Resolve(session.ItemOrder[session.Cursor]);
        return new(session.SessionId, session.Mode, current, session.Cursor, session.ItemOrder.Count, session.IsComplete);
    }

    public AssessmentAttempt RecordAttempt(
        string sessionId,
        AssessmentItemPool pool,
        AssessmentMark mark,
        bool usedHint = false,
        bool revealedAnswer = false,
        DateTimeOffset? nowUtc = null,
        string? attemptId = null)
    {
        ArgumentNullException.ThrowIfNull(pool);
        pool.Validate();
        if (!Enum.IsDefined(mark)) throw new ArgumentOutOfRangeException(nameof(mark));

        AssessmentSessionState session = FindSession(sessionId);
        ValidatePoolForSession(session, pool);
        if (session.IsComplete) throw new InvalidOperationException($"Assessment session {sessionId} is already complete.");
        if (session.Mode == AssessmentMode.Assessment && (usedHint || revealedAnswer))
            throw new InvalidOperationException("Hints and answer reveal are forbidden in formal assessment mode. Use Practice mode instead.");

        AssessmentItem current = pool.Resolve(session.ItemOrder[session.Cursor]);
        string id = string.IsNullOrWhiteSpace(attemptId) ? $"assessment-attempt-{Guid.NewGuid():N}" : attemptId.Trim();
        AssessmentValidation.RequireStableId(id, "assessment attempt id");
        if (_state.Attempts.Any(attempt => string.Equals(attempt.AttemptId, id, StringComparison.OrdinalIgnoreCase)))
            throw new InvalidOperationException($"Assessment attempt {id} already exists.");

        DateTimeOffset recorded = nowUtc ?? DateTimeOffset.UtcNow;
        var attempt = new AssessmentAttempt
        {
            AttemptId = id,
            SessionId = session.SessionId,
            Mode = session.Mode,
            ItemKey = current.Key,
            SkillId = current.SkillId,
            DifficultyTier = current.DifficultyTier,
            Mark = mark,
            UsedHint = usedHint,
            RevealedAnswer = revealedAnswer,
            RecordedAtUtc = recorded
        };
        attempt.Validate();
        _state.Attempts.Add(attempt);
        session.Cursor++;
        if (session.IsComplete) session.CompletedAtUtc = recorded;
        session.Validate();
        return attempt;
    }

    public bool IsUnseen(AssessmentItem item)
    {
        ArgumentNullException.ThrowIfNull(item);
        item.Validate();
        return !_state.Attempts.Any(attempt =>
            string.Equals(attempt.ItemKey.ContentIdentity, item.Key.ContentIdentity, StringComparison.OrdinalIgnoreCase));
    }

    public IReadOnlyList<AssessmentAttempt> GetAttemptHistory(
        AssessmentMode? mode = null,
        string? poolId = null,
        string? skillId = null)
    {
        IEnumerable<AssessmentAttempt> query = _state.Attempts;
        if (mode.HasValue) query = query.Where(attempt => attempt.Mode == mode.Value);
        if (!string.IsNullOrWhiteSpace(poolId)) query = query.Where(attempt => string.Equals(attempt.ItemKey.PoolId, poolId, StringComparison.OrdinalIgnoreCase));
        if (!string.IsNullOrWhiteSpace(skillId)) query = query.Where(attempt => string.Equals(attempt.SkillId, skillId, StringComparison.OrdinalIgnoreCase));
        return query.OrderBy(attempt => attempt.RecordedAtUtc).ThenBy(attempt => attempt.AttemptId, StringComparer.Ordinal).ToArray();
    }

    public int SuggestDifficultyTier(string skillId) => AssessmentDifficultyHeuristic.SuggestTier(_state.Attempts, skillId);

    public AssessmentResultSummary BuildAssessmentResults(string sessionId)
    {
        AssessmentSessionState session = FindSession(sessionId);
        if (session.Mode != AssessmentMode.Assessment)
            throw new InvalidOperationException("Practice sessions do not produce formal assessment results.");

        AssessmentAttempt[] attempts = _state.Attempts
            .Where(attempt => attempt.Mode == AssessmentMode.Assessment && string.Equals(attempt.SessionId, session.SessionId, StringComparison.OrdinalIgnoreCase))
            .OrderBy(attempt => attempt.RecordedAtUtc)
            .ThenBy(attempt => attempt.AttemptId, StringComparer.Ordinal)
            .ToArray();

        AssessmentSkillResult[] results = attempts
            .GroupBy(attempt => attempt.SkillId, StringComparer.OrdinalIgnoreCase)
            .OrderBy(group => group.Key, StringComparer.Ordinal)
            .Select(group => BuildSkillResult(group.Key, group.ToArray()))
            .ToArray();

        return new(session.SessionId, session.PoolId, session.PoolVersion, results);
    }

    private List<AssessmentItem> SelectItems(
        AssessmentItemPool pool,
        AssessmentMode mode,
        int itemCount,
        bool adaptiveDifficulty,
        int retakeRecentWindow)
    {
        var latestFormalUse = _state.Attempts
            .Where(attempt => attempt.Mode == AssessmentMode.Assessment && string.Equals(attempt.ItemKey.PoolId, pool.PoolId, StringComparison.OrdinalIgnoreCase))
            .GroupBy(attempt => attempt.ItemKey.ContentIdentity, StringComparer.OrdinalIgnoreCase)
            .ToDictionary(
                group => group.Key,
                group => group.Max(attempt => attempt.RecordedAtUtc),
                StringComparer.OrdinalIgnoreCase);

        var recentlyAssessed = new HashSet<string>(
            _state.Attempts
                .Where(attempt => attempt.Mode == AssessmentMode.Assessment && string.Equals(attempt.ItemKey.PoolId, pool.PoolId, StringComparison.OrdinalIgnoreCase))
                .OrderByDescending(attempt => attempt.RecordedAtUtc)
                .ThenByDescending(attempt => attempt.AttemptId, StringComparer.Ordinal)
                .Select(attempt => attempt.ItemKey.ContentIdentity)
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .Take(retakeRecentWindow),
            StringComparer.OrdinalIgnoreCase);

        return pool.Items
            .Select(item => new
            {
                Item = item,
                Unseen = IsUnseen(item),
                RecentPenalty = mode == AssessmentMode.Assessment && recentlyAssessed.Contains(item.Key.ContentIdentity) ? 1 : 0,
                LastFormalUse = latestFormalUse.TryGetValue(item.Key.ContentIdentity, out DateTimeOffset when) ? when : DateTimeOffset.MinValue,
                DifficultyDistance = adaptiveDifficulty ? Math.Abs(item.DifficultyTier - SuggestDifficultyTier(item.SkillId)) : 0
            })
            .OrderBy(candidate => candidate.Unseen ? 0 : 1)
            .ThenBy(candidate => candidate.RecentPenalty)
            .ThenBy(candidate => candidate.LastFormalUse)
            .ThenBy(candidate => candidate.DifficultyDistance)
            .ThenBy(candidate => candidate.Item.SkillId, StringComparer.Ordinal)
            .ThenBy(candidate => candidate.Item.Key.ItemId, StringComparer.Ordinal)
            .ThenBy(candidate => candidate.Item.Key.ItemVersion)
            .Take(itemCount)
            .Select(candidate => candidate.Item)
            .ToList();
    }

    private AssessmentSessionState FindSession(string sessionId)
    {
        AssessmentValidation.RequireStableId(sessionId, "assessment session id");
        return _state.Sessions.FirstOrDefault(session => string.Equals(session.SessionId, sessionId, StringComparison.OrdinalIgnoreCase))
            ?? throw new KeyNotFoundException("Unknown assessment session: " + sessionId);
    }

    private static void ValidatePoolForSession(AssessmentSessionState session, AssessmentItemPool pool)
    {
        if (!string.Equals(session.PoolId, pool.PoolId, StringComparison.OrdinalIgnoreCase) || session.PoolVersion != pool.Version)
            throw new InvalidDataException($"Cannot resume assessment session {session.SessionId}: it requires pool {session.PoolId} v{session.PoolVersion}, supplied {pool.PoolId} v{pool.Version}.");
    }

    private static AssessmentSkillResult BuildSkillResult(string skillId, IReadOnlyList<AssessmentAttempt> attempts)
    {
        int correct = attempts.Count(attempt => attempt.Mark == AssessmentMark.Correct);
        int incorrect = attempts.Count(attempt => attempt.Mark == AssessmentMark.Incorrect);
        int skipped = attempts.Count(attempt => attempt.Mark == AssessmentMark.Skipped);
        int unscored = attempts.Count(attempt => attempt.Mark == AssessmentMark.Unscored);
        int scored = correct + incorrect;
        double? descriptive = scored == 0 ? null : correct / (double)scored;
        return new(skillId, attempts.Count, correct, incorrect, skipped, unscored, descriptive);
    }
}

internal sealed class AssessmentRuntimeStateStore
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        PropertyNameCaseInsensitive = false
    };

    private readonly string _path;

    public AssessmentRuntimeStateStore(string path)
    {
        if (string.IsNullOrWhiteSpace(path)) throw new ArgumentException("Assessment runtime state path is required.", nameof(path));
        _path = Path.GetFullPath(path);
    }

    public string StatePath => _path;
    public string BackupPath => _path + ".bak";

    public static string DefaultStatePath()
    {
        string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        if (string.IsNullOrWhiteSpace(local)) throw new InvalidOperationException("LocalApplicationData is unavailable.");
        return Path.Combine(local, "WordDeck", "assessment-runtime.json");
    }

    public AssessmentRuntimeState Load()
    {
        if (!File.Exists(_path)) return new AssessmentRuntimeState();
        try
        {
            return DeserializeAndValidate(File.ReadAllText(_path));
        }
        catch (Exception primary) when (primary is JsonException or InvalidDataException or IOException)
        {
            if (!File.Exists(BackupPath))
                throw new InvalidDataException("Assessment runtime state is invalid and no backup is available.", primary);
            try
            {
                return DeserializeAndValidate(File.ReadAllText(BackupPath));
            }
            catch (Exception backup) when (backup is JsonException or InvalidDataException or IOException)
            {
                throw new InvalidDataException("Assessment runtime state and its backup are both invalid.", new AggregateException(primary, backup));
            }
        }
    }

    public void Save(AssessmentRuntimeState state)
    {
        ArgumentNullException.ThrowIfNull(state);
        state.Validate();
        string? directory = Path.GetDirectoryName(_path);
        if (!string.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);

        string temp = _path + ".tmp-" + Guid.NewGuid().ToString("N");
        try
        {
            string json = JsonSerializer.Serialize(state, JsonOptions);
            File.WriteAllText(temp, json, new System.Text.UTF8Encoding(false));
            if (File.Exists(_path)) File.Copy(_path, BackupPath, true);
            File.Move(temp, _path, true);
        }
        finally
        {
            if (File.Exists(temp)) File.Delete(temp);
        }
    }

    private static AssessmentRuntimeState DeserializeAndValidate(string json)
    {
        AssessmentRuntimeState? state = JsonSerializer.Deserialize<AssessmentRuntimeState>(json, JsonOptions);
        if (state is null) throw new InvalidDataException("Assessment runtime state is empty.");
        state.Validate();
        return state;
    }
}

internal static class AssessmentValidation
{
    public static void RequireStableId(string? value, string label)
    {
        if (string.IsNullOrWhiteSpace(value)) throw new InvalidDataException(label + " is required.");
        string trimmed = value.Trim();
        if (trimmed.Length > 200) throw new InvalidDataException(label + " is too long.");
        if (trimmed.Any(char.IsControl) || trimmed.Any(char.IsWhiteSpace))
            throw new InvalidDataException(label + " must not contain whitespace or control characters.");
    }
}
