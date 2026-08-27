using System.Text.Json;

namespace WordDeck;

internal enum AssessmentMode { Practice, Assessment }
internal enum AssessmentMark { Correct, Incorrect, Skipped, Unscored }

internal sealed record AssessmentItemKey(string PoolId, int PoolVersion, string ItemId, int ItemVersion)
{
    // PoolVersion preserves exact form reproducibility. ContentIdentity intentionally omits
    // PoolVersion so a pure repack does not reset exposure; ItemVersion changes do.
    public string ContentIdentity => $"{PoolId}\u001f{ItemId}\u001f{ItemVersion}";

    public void Validate()
    {
        AssessmentValidation.RequireStableId(PoolId, "assessment pool id");
        AssessmentValidation.RequireStableId(ItemId, "assessment item id");
        if (PoolVersion < 1) throw new InvalidDataException("Assessment pool version must be positive.");
        if (ItemVersion < 1) throw new InvalidDataException("Assessment item version must be positive.");
    }
}

internal sealed record AssessmentItem(AssessmentItemKey Key, string SkillId, int DifficultyTier)
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
        var ids = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (AssessmentItem item in Items)
        {
            if (item is null) throw new InvalidDataException("Assessment item pool contains a null item.");
            item.Validate();
            if (!string.Equals(item.Key.PoolId, PoolId, StringComparison.OrdinalIgnoreCase) || item.Key.PoolVersion != Version)
                throw new InvalidDataException($"Assessment item {item.Key.ItemId} does not belong to pool {PoolId} version {Version}.");
            if (!ids.Add(item.Key.ItemId)) throw new InvalidDataException($"Assessment pool contains duplicate item id {item.Key.ItemId}.");
        }
    }

    public AssessmentItem Resolve(AssessmentItemKey key)
    {
        ArgumentNullException.ThrowIfNull(key);
        ValidateExactVersion(key);
        return Items.FirstOrDefault(x => string.Equals(x.Key.ItemId, key.ItemId, StringComparison.OrdinalIgnoreCase) && x.Key.ItemVersion == key.ItemVersion)
            ?? throw new InvalidDataException($"Assessment item {key.ItemId} v{key.ItemVersion} is not present in pool {PoolId} v{Version}.");
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
        if (!Enum.IsDefined(Mode) || !Enum.IsDefined(Mark)) throw new InvalidDataException("Assessment attempt has invalid enum value.");
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
        if (ItemOrder.Select(x => x.ContentIdentity).Distinct(StringComparer.OrdinalIgnoreCase).Count() != ItemOrder.Count)
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
        var sessions = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (AssessmentSessionState session in Sessions)
        {
            if (session is null) throw new InvalidDataException("Assessment runtime contains a null session.");
            session.Validate();
            if (!sessions.Add(session.SessionId)) throw new InvalidDataException($"Duplicate assessment session id {session.SessionId}.");
        }
        var attempts = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (AssessmentAttempt attempt in Attempts)
        {
            if (attempt is null) throw new InvalidDataException("Assessment runtime contains a null attempt.");
            attempt.Validate();
            if (!attempts.Add(attempt.AttemptId)) throw new InvalidDataException($"Duplicate assessment attempt id {attempt.AttemptId}.");
        }
    }
}

internal sealed record AssessmentResumeSnapshot(string SessionId, AssessmentMode Mode, AssessmentItem? CurrentItem, int CompletedItems, int TotalItems, bool IsComplete);
internal sealed record AssessmentSkillResult(string SkillId, int Attempts, int Correct, int Incorrect, int Skipped, int Unscored, double? DescriptiveAccuracy)
{
    public bool PsychometricallyCalibrated => false;
}
internal sealed record AssessmentResultSummary(string SessionId, string PoolId, int PoolVersion, IReadOnlyList<AssessmentSkillResult> SkillResults)
{
    public bool PsychometricCalibrationApplied => false;
    public bool AiCanonicalAssessorUsed => false;
}

/// <summary>
/// Transparent routing only. No ability score, IRT parameter, CEFR cut score or calibrated probability.
/// A tier cannot move until several formal scored attempts exist, so one lucky/unlucky item never shifts it.
/// </summary>
internal static class AssessmentDifficultyHeuristic
{
    public const int RecentScoredAttemptLimit = 6;
    public const int MinimumScoredAttemptsForAdjustment = 3;

    public static int SuggestTier(IEnumerable<AssessmentAttempt> history, string skillId)
    {
        AssessmentValidation.RequireStableId(skillId, "assessment skill id");
        AssessmentAttempt[] scored = history
            .Where(x => x.Mode == AssessmentMode.Assessment &&
                        string.Equals(x.SkillId, skillId, StringComparison.OrdinalIgnoreCase) &&
                        x.Mark is AssessmentMark.Correct or AssessmentMark.Incorrect)
            .OrderByDescending(x => x.RecordedAtUtc)
            .ThenByDescending(x => x.AttemptId, StringComparer.Ordinal)
            .Take(RecentScoredAttemptLimit)
            .ToArray();
        if (scored.Length < MinimumScoredAttemptsForAdjustment) return 2;
        double accuracy = scored.Count(x => x.Mark == AssessmentMark.Correct) / (double)scored.Length;
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

    public AssessmentSessionState StartSession(AssessmentItemPool pool, AssessmentMode mode, int itemCount, bool adaptiveDifficulty,
        DateTimeOffset? nowUtc = null, int retakeRecentWindow = 5, string? sessionId = null)
    {
        ArgumentNullException.ThrowIfNull(pool);
        pool.Validate();
        if (!Enum.IsDefined(mode)) throw new ArgumentOutOfRangeException(nameof(mode));
        if (itemCount < 1 || itemCount > pool.Items.Count) throw new ArgumentOutOfRangeException(nameof(itemCount));
        if (retakeRecentWindow < 0) throw new ArgumentOutOfRangeException(nameof(retakeRecentWindow));
        string id = string.IsNullOrWhiteSpace(sessionId) ? $"assessment-session-{Guid.NewGuid():N}" : sessionId.Trim();
        AssessmentValidation.RequireStableId(id, "assessment session id");
        if (_state.Sessions.Any(x => string.Equals(x.SessionId, id, StringComparison.OrdinalIgnoreCase)))
            throw new InvalidOperationException($"Assessment session {id} already exists.");

        List<AssessmentItemKey> order = SelectItems(pool, mode, itemCount, adaptiveDifficulty, retakeRecentWindow).Select(x => x.Key).ToList();
        var session = new AssessmentSessionState
        {
            SessionId = id, PoolId = pool.PoolId, PoolVersion = pool.Version, Mode = mode,
            AdaptiveDifficulty = adaptiveDifficulty, RetakeRecentWindow = retakeRecentWindow,
            PlannedItemCount = order.Count, ItemOrder = order, Cursor = 0, StartedAtUtc = nowUtc ?? DateTimeOffset.UtcNow
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

    public AssessmentAttempt RecordAttempt(string sessionId, AssessmentItemPool pool, AssessmentMark mark, bool usedHint = false,
        bool revealedAnswer = false, DateTimeOffset? nowUtc = null, string? attemptId = null)
    {
        ArgumentNullException.ThrowIfNull(pool);
        pool.Validate();
        if (!Enum.IsDefined(mark)) throw new ArgumentOutOfRangeException(nameof(mark));
        AssessmentSessionState session = FindSession(sessionId);
        ValidatePoolForSession(session, pool);
        if (session.IsComplete) throw new InvalidOperationException($"Assessment session {sessionId} is already complete.");
        if (session.Mode == AssessmentMode.Assessment && (usedHint || revealedAnswer))
            throw new InvalidOperationException("Hints and answer reveal are forbidden in formal assessment mode. Use Practice mode instead.");

        AssessmentItem item = pool.Resolve(session.ItemOrder[session.Cursor]);
        string id = string.IsNullOrWhiteSpace(attemptId) ? $"assessment-attempt-{Guid.NewGuid():N}" : attemptId.Trim();
        AssessmentValidation.RequireStableId(id, "assessment attempt id");
        if (_state.Attempts.Any(x => string.Equals(x.AttemptId, id, StringComparison.OrdinalIgnoreCase)))
            throw new InvalidOperationException($"Assessment attempt {id} already exists.");
        DateTimeOffset recorded = nowUtc ?? DateTimeOffset.UtcNow;
        var attempt = new AssessmentAttempt
        {
            AttemptId = id, SessionId = session.SessionId, Mode = session.Mode, ItemKey = item.Key, SkillId = item.SkillId,
            DifficultyTier = item.DifficultyTier, Mark = mark, UsedHint = usedHint, RevealedAnswer = revealedAnswer, RecordedAtUtc = recorded
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
        return !_state.Attempts.Any(x => string.Equals(x.ItemKey.ContentIdentity, item.Key.ContentIdentity, StringComparison.OrdinalIgnoreCase));
    }

    public IReadOnlyList<AssessmentAttempt> GetAttemptHistory(AssessmentMode? mode = null, string? poolId = null, string? skillId = null)
    {
        IEnumerable<AssessmentAttempt> query = _state.Attempts;
        if (mode.HasValue) query = query.Where(x => x.Mode == mode.Value);
        if (!string.IsNullOrWhiteSpace(poolId)) query = query.Where(x => string.Equals(x.ItemKey.PoolId, poolId, StringComparison.OrdinalIgnoreCase));
        if (!string.IsNullOrWhiteSpace(skillId)) query = query.Where(x => string.Equals(x.SkillId, skillId, StringComparison.OrdinalIgnoreCase));
        return query.OrderBy(x => x.RecordedAtUtc).ThenBy(x => x.AttemptId, StringComparer.Ordinal).ToArray();
    }

    public int SuggestDifficultyTier(string skillId) => AssessmentDifficultyHeuristic.SuggestTier(_state.Attempts, skillId);

    public AssessmentResultSummary BuildAssessmentResults(string sessionId)
    {
        AssessmentSessionState session = FindSession(sessionId);
        if (session.Mode != AssessmentMode.Assessment) throw new InvalidOperationException("Practice sessions do not produce formal assessment results.");
        AssessmentAttempt[] attempts = _state.Attempts
            .Where(x => x.Mode == AssessmentMode.Assessment && string.Equals(x.SessionId, session.SessionId, StringComparison.OrdinalIgnoreCase))
            .OrderBy(x => x.RecordedAtUtc).ThenBy(x => x.AttemptId, StringComparer.Ordinal).ToArray();
        AssessmentSkillResult[] skills = attempts
            .GroupBy(x => x.SkillId, StringComparer.OrdinalIgnoreCase)
            .OrderBy(x => x.Key, StringComparer.Ordinal)
            .Select(x => BuildSkillResult(x.Key, x.ToArray())).ToArray();
        return new(session.SessionId, session.PoolId, session.PoolVersion, skills);
    }

    private List<AssessmentItem> SelectItems(AssessmentItemPool pool, AssessmentMode mode, int count, bool adaptive, int recentWindow)
    {
        var lastFormal = _state.Attempts
            .Where(x => x.Mode == AssessmentMode.Assessment && string.Equals(x.ItemKey.PoolId, pool.PoolId, StringComparison.OrdinalIgnoreCase))
            .GroupBy(x => x.ItemKey.ContentIdentity, StringComparer.OrdinalIgnoreCase)
            .ToDictionary(x => x.Key, x => x.Max(y => y.RecordedAtUtc), StringComparer.OrdinalIgnoreCase);
        var recent = new HashSet<string>(_state.Attempts
            .Where(x => x.Mode == AssessmentMode.Assessment && string.Equals(x.ItemKey.PoolId, pool.PoolId, StringComparison.OrdinalIgnoreCase))
            .OrderByDescending(x => x.RecordedAtUtc).ThenByDescending(x => x.AttemptId, StringComparer.Ordinal)
            .Select(x => x.ItemKey.ContentIdentity).Distinct(StringComparer.OrdinalIgnoreCase).Take(recentWindow), StringComparer.OrdinalIgnoreCase);

        return pool.Items.Select(item => new
            {
                Item = item,
                Unseen = IsUnseen(item),
                RecentPenalty = mode == AssessmentMode.Assessment && recent.Contains(item.Key.ContentIdentity) ? 1 : 0,
                LastFormalUse = lastFormal.TryGetValue(item.Key.ContentIdentity, out DateTimeOffset when) ? when : DateTimeOffset.MinValue,
                DifficultyDistance = adaptive ? Math.Abs(item.DifficultyTier - SuggestDifficultyTier(item.SkillId)) : 0
            })
            .OrderBy(x => x.Unseen ? 0 : 1)
            .ThenBy(x => x.RecentPenalty)
            .ThenBy(x => x.LastFormalUse)
            .ThenBy(x => x.DifficultyDistance)
            .ThenBy(x => x.Item.SkillId, StringComparer.Ordinal)
            .ThenBy(x => x.Item.Key.ItemId, StringComparer.Ordinal)
            .ThenBy(x => x.Item.Key.ItemVersion)
            .Take(count).Select(x => x.Item).ToList();
    }

    private AssessmentSessionState FindSession(string sessionId)
    {
        AssessmentValidation.RequireStableId(sessionId, "assessment session id");
        return _state.Sessions.FirstOrDefault(x => string.Equals(x.SessionId, sessionId, StringComparison.OrdinalIgnoreCase))
            ?? throw new KeyNotFoundException("Unknown assessment session: " + sessionId);
    }

    private static void ValidatePoolForSession(AssessmentSessionState session, AssessmentItemPool pool)
    {
        if (!string.Equals(session.PoolId, pool.PoolId, StringComparison.OrdinalIgnoreCase) || session.PoolVersion != pool.Version)
            throw new InvalidDataException($"Cannot resume assessment session {session.SessionId}: it requires pool {session.PoolId} v{session.PoolVersion}, supplied {pool.PoolId} v{pool.Version}.");
    }

    private static AssessmentSkillResult BuildSkillResult(string skillId, IReadOnlyList<AssessmentAttempt> attempts)
    {
        int correct = attempts.Count(x => x.Mark == AssessmentMark.Correct);
        int incorrect = attempts.Count(x => x.Mark == AssessmentMark.Incorrect);
        int skipped = attempts.Count(x => x.Mark == AssessmentMark.Skipped);
        int unscored = attempts.Count(x => x.Mark == AssessmentMark.Unscored);
        int scored = correct + incorrect;
        return new(skillId, attempts.Count, correct, incorrect, skipped, unscored, scored == 0 ? null : correct / (double)scored);
    }
}

internal sealed class AssessmentRuntimeStateStore
{
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true, PropertyNameCaseInsensitive = false };
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
        try { return ReadValidated(_path); }
        catch (Exception primary) when (primary is JsonException or InvalidDataException or IOException)
        {
            if (!File.Exists(BackupPath)) throw new InvalidDataException("Assessment runtime state is invalid and no backup is available.", primary);
            try { return ReadValidated(BackupPath); }
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
            File.WriteAllText(temp, JsonSerializer.Serialize(state, JsonOptions), new System.Text.UTF8Encoding(false));
            if (File.Exists(_path)) File.Copy(_path, BackupPath, true);
            File.Move(temp, _path, true);
        }
        finally { if (File.Exists(temp)) File.Delete(temp); }
    }

    private static AssessmentRuntimeState ReadValidated(string path)
    {
        AssessmentRuntimeState? state = JsonSerializer.Deserialize<AssessmentRuntimeState>(File.ReadAllText(path), JsonOptions);
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
