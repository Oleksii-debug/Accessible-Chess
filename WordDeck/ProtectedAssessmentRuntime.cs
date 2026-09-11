using System.Text.Json;

namespace WordDeck;

internal enum ProtectedAssessmentEvidenceRole
{
    General,
    Receptive,
    IndependentProductive
}

internal sealed record ProtectedAssessmentItemBinding(
    AssessmentItemKey Key,
    int AdministrationOrder,
    string ExposureGroupId,
    string EvidenceFamilyId,
    ProtectedAssessmentEvidenceRole EvidenceRole,
    bool RequiresUnexposedExposureGroup,
    bool IsReserve)
{
    public void Validate()
    {
        ArgumentNullException.ThrowIfNull(Key);
        Key.Validate();
        if (AdministrationOrder < 1)
            throw new InvalidDataException("Protected assessment administration order must be positive.");
        AssessmentValidation.RequireStableId(ExposureGroupId, "protected assessment exposure group id");
        AssessmentValidation.RequireStableId(EvidenceFamilyId, "protected assessment evidence family id");
        if (!Enum.IsDefined(EvidenceRole))
            throw new InvalidDataException("Protected assessment evidence role is invalid.");
        if (RequiresUnexposedExposureGroup && EvidenceRole != ProtectedAssessmentEvidenceRole.IndependentProductive)
            throw new InvalidDataException("Only independent productive evidence may require an unexposed exposure group.");
    }
}

internal sealed class ProtectedAssessmentFormContract
{
    public string PoolId { get; set; } = string.Empty;
    public int PoolVersion { get; set; } = 1;
    public string FormAssemblyVersion { get; set; } = string.Empty;
    public List<ProtectedAssessmentItemBinding> Bindings { get; set; } = new();

    public IReadOnlyList<ProtectedAssessmentItemBinding> PrimaryBindings => Bindings
        .Where(x => !x.IsReserve)
        .OrderBy(x => x.AdministrationOrder)
        .ThenBy(x => x.Key.ItemId, StringComparer.Ordinal)
        .ToArray();

    public void Validate(AssessmentItemPool pool)
    {
        ArgumentNullException.ThrowIfNull(pool);
        pool.Validate();
        AssessmentValidation.RequireStableId(PoolId, "protected assessment pool id");
        AssessmentValidation.RequireStableId(FormAssemblyVersion, "protected assessment form assembly version");
        if (PoolVersion < 1) throw new InvalidDataException("Protected assessment pool version must be positive.");
        if (!string.Equals(PoolId, pool.PoolId, StringComparison.OrdinalIgnoreCase) || PoolVersion != pool.Version)
            throw new InvalidDataException("Protected assessment form contract does not match the supplied pool identity/version.");
        if (Bindings.Count == 0) throw new InvalidDataException("Protected assessment form contract cannot be empty.");

        var bound = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var primaryOrders = new HashSet<int>();
        foreach (ProtectedAssessmentItemBinding binding in Bindings)
        {
            if (binding is null) throw new InvalidDataException("Protected assessment form contains a null binding.");
            binding.Validate();
            if (!string.Equals(binding.Key.PoolId, PoolId, StringComparison.OrdinalIgnoreCase) || binding.Key.PoolVersion != PoolVersion)
                throw new InvalidDataException("Protected assessment binding mixes pool identities or versions.");
            _ = pool.Resolve(binding.Key);
            if (!bound.Add(binding.Key.ContentIdentity))
                throw new InvalidDataException("Protected assessment form contains duplicate item content identities.");
            if (!binding.IsReserve && !primaryOrders.Add(binding.AdministrationOrder))
                throw new InvalidDataException("Protected assessment primary administration order contains duplicates.");
        }

        var poolIds = pool.Items.Select(x => x.Key.ContentIdentity).ToHashSet(StringComparer.OrdinalIgnoreCase);
        if (!bound.SetEquals(poolIds))
            throw new InvalidDataException("Protected assessment form contract must bind every item in the supplied pool exactly once.");
        if (PrimaryBindings.Count == 0)
            throw new InvalidDataException("Protected assessment form must contain at least one non-reserve item.");

        foreach (ProtectedAssessmentItemBinding primary in PrimaryBindings.Where(x => x.RequiresUnexposedExposureGroup))
        {
            bool hasFreshReserve = Bindings.Any(x =>
                x.IsReserve &&
                x.RequiresUnexposedExposureGroup &&
                x.EvidenceRole == ProtectedAssessmentEvidenceRole.IndependentProductive &&
                string.Equals(x.EvidenceFamilyId, primary.EvidenceFamilyId, StringComparison.OrdinalIgnoreCase) &&
                !string.Equals(x.ExposureGroupId, primary.ExposureGroupId, StringComparison.OrdinalIgnoreCase));
            if (!hasFreshReserve)
                throw new InvalidDataException($"Protected assessment evidence family {primary.EvidenceFamilyId} has no fresh reserve for independent evidence.");
        }
    }

    public ProtectedAssessmentItemBinding Resolve(AssessmentItemKey key)
    {
        ArgumentNullException.ThrowIfNull(key);
        return Bindings.FirstOrDefault(x => string.Equals(x.Key.ContentIdentity, key.ContentIdentity, StringComparison.OrdinalIgnoreCase))
            ?? throw new InvalidDataException($"Assessment item {key.ItemId} is not bound by protected form {FormAssemblyVersion}.");
    }

    public bool TryResolve(AssessmentItemKey key, out ProtectedAssessmentItemBinding? binding)
    {
        binding = Bindings.FirstOrDefault(x => string.Equals(x.Key.ContentIdentity, key.ContentIdentity, StringComparison.OrdinalIgnoreCase));
        return binding is not null;
    }
}

internal sealed class ProtectedAssessmentSessionBindingState
{
    public string SessionId { get; set; } = string.Empty;
    public string FormAssemblyVersion { get; set; } = string.Empty;
    public List<AssessmentItemKey> ItemOrder { get; set; } = new();

    public void Validate(AssessmentSessionState session)
    {
        AssessmentValidation.RequireStableId(SessionId, "protected assessment session id");
        AssessmentValidation.RequireStableId(FormAssemblyVersion, "protected assessment form assembly version");
        if (!string.Equals(SessionId, session.SessionId, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Protected assessment session binding references the wrong runtime session.");
        if (ItemOrder.Count != session.ItemOrder.Count ||
            !ItemOrder.Select(x => x.ContentIdentity).SequenceEqual(session.ItemOrder.Select(x => x.ContentIdentity), StringComparer.OrdinalIgnoreCase))
            throw new InvalidDataException("Protected assessment persisted form order does not match the runtime session order.");
    }
}

internal sealed class ProtectedAssessmentExposure
{
    public string ExposureId { get; set; } = string.Empty;
    public string SessionId { get; set; } = string.Empty;
    public AssessmentItemKey ItemKey { get; set; } = new("invalid", 1, "invalid", 1);
    public string ExposureGroupId { get; set; } = string.Empty;
    public DateTimeOffset PresentedAtUtc { get; set; }

    public void Validate()
    {
        AssessmentValidation.RequireStableId(ExposureId, "protected assessment exposure id");
        AssessmentValidation.RequireStableId(SessionId, "protected assessment exposure session id");
        ArgumentNullException.ThrowIfNull(ItemKey);
        ItemKey.Validate();
        AssessmentValidation.RequireStableId(ExposureGroupId, "protected assessment exposure group id");
    }
}

internal sealed class ProtectedAssessmentBindingState
{
    public const int CurrentSchemaVersion = 1;
    public int SchemaVersion { get; set; } = CurrentSchemaVersion;
    public List<ProtectedAssessmentSessionBindingState> Sessions { get; set; } = new();
    public List<ProtectedAssessmentExposure> Exposures { get; set; } = new();

    public void Validate(AssessmentRuntimeState runtimeState)
    {
        ArgumentNullException.ThrowIfNull(runtimeState);
        runtimeState.Validate();
        if (SchemaVersion != CurrentSchemaVersion)
            throw new InvalidDataException($"Unsupported protected assessment binding schema {SchemaVersion}; expected {CurrentSchemaVersion}.");

        var runtimeSessions = runtimeState.Sessions.ToDictionary(x => x.SessionId, StringComparer.OrdinalIgnoreCase);
        var sessionIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (ProtectedAssessmentSessionBindingState binding in Sessions)
        {
            if (binding is null) throw new InvalidDataException("Protected assessment binding state contains a null session.");
            if (!runtimeSessions.TryGetValue(binding.SessionId, out AssessmentSessionState? session))
                throw new InvalidDataException($"Protected assessment binding references unknown session {binding.SessionId}.");
            binding.Validate(session);
            if (!sessionIds.Add(binding.SessionId))
                throw new InvalidDataException($"Duplicate protected assessment session binding {binding.SessionId}.");
        }

        var exposureIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var exposedPerSessionItem = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (ProtectedAssessmentExposure exposure in Exposures)
        {
            if (exposure is null) throw new InvalidDataException("Protected assessment binding state contains a null exposure.");
            exposure.Validate();
            if (!exposureIds.Add(exposure.ExposureId))
                throw new InvalidDataException($"Duplicate protected assessment exposure id {exposure.ExposureId}.");
            if (!runtimeSessions.TryGetValue(exposure.SessionId, out AssessmentSessionState? session))
                throw new InvalidDataException($"Protected assessment exposure references unknown session {exposure.SessionId}.");
            if (!sessionIds.Contains(exposure.SessionId))
                throw new InvalidDataException($"Protected assessment exposure session {exposure.SessionId} is missing its form binding.");
            if (!string.Equals(exposure.ItemKey.PoolId, session.PoolId, StringComparison.OrdinalIgnoreCase) || exposure.ItemKey.PoolVersion != session.PoolVersion)
                throw new InvalidDataException("Protected assessment exposure does not match its session pool identity/version.");

            int visibleCount = session.IsComplete ? session.ItemOrder.Count : Math.Min(session.ItemOrder.Count, session.Cursor + 1);
            if (!session.ItemOrder.Take(visibleCount).Any(x => string.Equals(x.ContentIdentity, exposure.ItemKey.ContentIdentity, StringComparison.OrdinalIgnoreCase)))
                throw new InvalidDataException("Protected assessment exposure references an item beyond the consumed/current session boundary.");
            string sessionItem = exposure.SessionId + "\u001f" + exposure.ItemKey.ContentIdentity;
            if (!exposedPerSessionItem.Add(sessionItem))
                throw new InvalidDataException("Protected assessment state contains duplicate exposure for the same session item.");
        }
    }
}

internal sealed class ProtectedAssessmentRuntimeSnapshot
{
    public const int CurrentSchemaVersion = 1;
    public int SchemaVersion { get; set; } = CurrentSchemaVersion;
    public AssessmentRuntimeState RuntimeState { get; set; } = new();
    public ProtectedAssessmentBindingState BindingState { get; set; } = new();

    public void Validate()
    {
        if (SchemaVersion != CurrentSchemaVersion)
            throw new InvalidDataException($"Unsupported protected assessment snapshot schema {SchemaVersion}; expected {CurrentSchemaVersion}.");
        ArgumentNullException.ThrowIfNull(RuntimeState);
        ArgumentNullException.ThrowIfNull(BindingState);
        BindingState.Validate(RuntimeState);
    }
}

internal sealed class ProtectedAssessmentRuntime
{
    private readonly AssessmentItemPool _pool;
    private readonly ProtectedAssessmentFormContract _contract;
    private readonly AssessmentRuntime _runtime;
    private readonly ProtectedAssessmentBindingState _bindingState;

    public ProtectedAssessmentRuntime(
        AssessmentItemPool pool,
        ProtectedAssessmentFormContract contract,
        AssessmentRuntimeState? runtimeState = null,
        ProtectedAssessmentBindingState? bindingState = null)
    {
        _pool = pool ?? throw new ArgumentNullException(nameof(pool));
        _contract = contract ?? throw new ArgumentNullException(nameof(contract));
        _contract.Validate(_pool);
        _runtime = new AssessmentRuntime(runtimeState);
        _bindingState = bindingState ?? new ProtectedAssessmentBindingState();
        _bindingState.Validate(_runtime.State);
        ValidateBoundSessions();
    }

    public AssessmentRuntimeState RuntimeState => _runtime.State;
    public ProtectedAssessmentBindingState BindingState => _bindingState;

    public ProtectedAssessmentRuntimeSnapshot CreateSnapshot()
    {
        var snapshot = new ProtectedAssessmentRuntimeSnapshot
        {
            RuntimeState = _runtime.State,
            BindingState = _bindingState
        };
        snapshot.Validate();
        return snapshot;
    }

    public AssessmentSessionState StartSession(DateTimeOffset? nowUtc = null, string? sessionId = null)
    {
        IReadOnlyList<ProtectedAssessmentItemBinding> primary = _contract.PrimaryBindings;
        AssessmentSessionState session = _runtime.StartSession(
            _pool,
            AssessmentMode.Assessment,
            primary.Count,
            adaptiveDifficulty: false,
            nowUtc: nowUtc,
            retakeRecentWindow: 0,
            sessionId: sessionId);

        session.ItemOrder = primary.Select(x => x.Key).ToList();
        session.PlannedItemCount = session.ItemOrder.Count;
        session.Cursor = 0;
        session.CompletedAtUtc = null;
        session.Validate();
        _bindingState.Sessions.Add(new ProtectedAssessmentSessionBindingState
        {
            SessionId = session.SessionId,
            FormAssemblyVersion = _contract.FormAssemblyVersion,
            ItemOrder = session.ItemOrder.ToList()
        });
        _bindingState.Validate(_runtime.State);
        return session;
    }

    public AssessmentResumeSnapshot ResumeSession(string sessionId, DateTimeOffset? nowUtc = null)
    {
        AssessmentSessionState session = FindBoundSession(sessionId);
        if (!session.IsComplete)
        {
            AssessmentItem current = EnsureCurrentItemEligible(session);
            RegisterExposure(session, current, nowUtc ?? DateTimeOffset.UtcNow);
        }
        _bindingState.Validate(_runtime.State);
        return _runtime.ResumeSession(sessionId, _pool);
    }

    public AssessmentAttempt RecordAttempt(
        string sessionId,
        AssessmentMark mark,
        DateTimeOffset? nowUtc = null,
        string? attemptId = null)
    {
        AssessmentSessionState session = FindBoundSession(sessionId);
        if (session.IsComplete)
            throw new InvalidOperationException($"Assessment session {sessionId} is already complete.");
        DateTimeOffset recorded = nowUtc ?? DateTimeOffset.UtcNow;
        AssessmentItem current = EnsureCurrentItemEligible(session);
        RegisterExposure(session, current, recorded);
        AssessmentAttempt attempt = _runtime.RecordAttempt(
            sessionId,
            _pool,
            mark,
            usedHint: false,
            revealedAnswer: false,
            nowUtc: recorded,
            attemptId: attemptId);
        SyncSessionBinding(session);
        _bindingState.Validate(_runtime.State);
        return attempt;
    }

    public bool IsUnseen(AssessmentItem item)
    {
        ArgumentNullException.ThrowIfNull(item);
        item.Validate();
        if (_bindingState.Exposures.Any(x => string.Equals(x.ItemKey.ContentIdentity, item.Key.ContentIdentity, StringComparison.OrdinalIgnoreCase)))
            return false;
        return _runtime.IsUnseen(item);
    }

    private AssessmentItem EnsureCurrentItemEligible(AssessmentSessionState session)
    {
        AssessmentItemKey currentKey = session.ItemOrder[session.Cursor];
        ProtectedAssessmentItemBinding binding = _contract.Resolve(currentKey);
        if (!binding.RequiresUnexposedExposureGroup || !IsExposureGroupContaminated(binding, session.SessionId, currentKey))
            return _pool.Resolve(currentKey);

        var existingOrder = session.ItemOrder.Select(x => x.ContentIdentity).ToHashSet(StringComparer.OrdinalIgnoreCase);
        ProtectedAssessmentItemBinding? replacement = _contract.Bindings
            .Where(x =>
                x.IsReserve &&
                x.RequiresUnexposedExposureGroup &&
                x.EvidenceRole == ProtectedAssessmentEvidenceRole.IndependentProductive &&
                string.Equals(x.EvidenceFamilyId, binding.EvidenceFamilyId, StringComparison.OrdinalIgnoreCase) &&
                !existingOrder.Contains(x.Key.ContentIdentity) &&
                !IsExposureGroupContaminated(x, session.SessionId, x.Key))
            .OrderBy(x => x.AdministrationOrder)
            .ThenBy(x => x.Key.ItemId, StringComparer.Ordinal)
            .FirstOrDefault();

        if (replacement is null)
            throw new InvalidOperationException($"Protected assessment evidence family {binding.EvidenceFamilyId} has no fresh unexposed equivalent; independent evidence fails closed.");

        session.ItemOrder[session.Cursor] = replacement.Key;
        session.Validate();
        SyncSessionBinding(session);
        return _pool.Resolve(replacement.Key);
    }

    private bool IsExposureGroupContaminated(
        ProtectedAssessmentItemBinding binding,
        string currentSessionId,
        AssessmentItemKey currentKey)
    {
        bool exposed = _bindingState.Exposures.Any(x =>
            string.Equals(x.ExposureGroupId, binding.ExposureGroupId, StringComparison.OrdinalIgnoreCase) &&
            !(string.Equals(x.SessionId, currentSessionId, StringComparison.OrdinalIgnoreCase) &&
              string.Equals(x.ItemKey.ContentIdentity, currentKey.ContentIdentity, StringComparison.OrdinalIgnoreCase)));
        if (exposed) return true;

        foreach (AssessmentAttempt attempt in _runtime.State.Attempts)
        {
            if (!_contract.TryResolve(attempt.ItemKey, out ProtectedAssessmentItemBinding? attemptedBinding) || attemptedBinding is null)
                continue;
            if (!string.Equals(attemptedBinding.ExposureGroupId, binding.ExposureGroupId, StringComparison.OrdinalIgnoreCase))
                continue;
            if (string.Equals(attempt.SessionId, currentSessionId, StringComparison.OrdinalIgnoreCase) &&
                string.Equals(attempt.ItemKey.ContentIdentity, currentKey.ContentIdentity, StringComparison.OrdinalIgnoreCase))
                continue;
            return true;
        }
        return false;
    }

    private void RegisterExposure(AssessmentSessionState session, AssessmentItem item, DateTimeOffset presentedAtUtc)
    {
        if (_bindingState.Exposures.Any(x =>
            string.Equals(x.SessionId, session.SessionId, StringComparison.OrdinalIgnoreCase) &&
            string.Equals(x.ItemKey.ContentIdentity, item.Key.ContentIdentity, StringComparison.OrdinalIgnoreCase)))
            return;

        ProtectedAssessmentItemBinding binding = _contract.Resolve(item.Key);
        _bindingState.Exposures.Add(new ProtectedAssessmentExposure
        {
            ExposureId = $"protected-exposure-{Guid.NewGuid():N}",
            SessionId = session.SessionId,
            ItemKey = item.Key,
            ExposureGroupId = binding.ExposureGroupId,
            PresentedAtUtc = presentedAtUtc
        });
    }

    private AssessmentSessionState FindBoundSession(string sessionId)
    {
        AssessmentValidation.RequireStableId(sessionId, "protected assessment session id");
        AssessmentSessionState session = _runtime.State.Sessions.FirstOrDefault(x =>
            string.Equals(x.SessionId, sessionId, StringComparison.OrdinalIgnoreCase))
            ?? throw new KeyNotFoundException("Unknown protected assessment session: " + sessionId);
        ProtectedAssessmentSessionBindingState binding = _bindingState.Sessions.FirstOrDefault(x =>
            string.Equals(x.SessionId, sessionId, StringComparison.OrdinalIgnoreCase))
            ?? throw new InvalidDataException("Assessment session is missing protected form binding state.");
        if (!string.Equals(binding.FormAssemblyVersion, _contract.FormAssemblyVersion, StringComparison.Ordinal))
            throw new InvalidDataException("Protected assessment form assembly version changed; resume fails closed.");
        binding.Validate(session);
        ValidateSessionOrderAgainstContract(session);
        return session;
    }

    private void SyncSessionBinding(AssessmentSessionState session)
    {
        ProtectedAssessmentSessionBindingState binding = _bindingState.Sessions.First(x =>
            string.Equals(x.SessionId, session.SessionId, StringComparison.OrdinalIgnoreCase));
        binding.ItemOrder = session.ItemOrder.ToList();
    }

    private void ValidateBoundSessions()
    {
        foreach (ProtectedAssessmentSessionBindingState binding in _bindingState.Sessions)
        {
            if (!string.Equals(binding.FormAssemblyVersion, _contract.FormAssemblyVersion, StringComparison.Ordinal))
                throw new InvalidDataException("Persisted protected assessment form assembly version does not match the active contract.");
            AssessmentSessionState session = _runtime.State.Sessions.First(x =>
                string.Equals(x.SessionId, binding.SessionId, StringComparison.OrdinalIgnoreCase));
            ValidateSessionOrderAgainstContract(session);
        }
    }

    private void ValidateSessionOrderAgainstContract(AssessmentSessionState session)
    {
        IReadOnlyList<ProtectedAssessmentItemBinding> primary = _contract.PrimaryBindings;
        if (session.ItemOrder.Count != primary.Count)
            throw new InvalidDataException("Protected assessment session item count does not match the canonical form.");

        for (int i = 0; i < session.ItemOrder.Count; i++)
        {
            AssessmentItemKey actualKey = session.ItemOrder[i];
            ProtectedAssessmentItemBinding actual = _contract.Resolve(actualKey);
            ProtectedAssessmentItemBinding expected = primary[i];
            if (string.Equals(actual.Key.ContentIdentity, expected.Key.ContentIdentity, StringComparison.OrdinalIgnoreCase))
                continue;

            bool validReplacement = actual.IsReserve &&
                expected.RequiresUnexposedExposureGroup &&
                actual.RequiresUnexposedExposureGroup &&
                actual.EvidenceRole == ProtectedAssessmentEvidenceRole.IndependentProductive &&
                string.Equals(actual.EvidenceFamilyId, expected.EvidenceFamilyId, StringComparison.OrdinalIgnoreCase);
            if (!validReplacement)
                throw new InvalidDataException("Protected assessment persisted item order violates canonical administration order/fallback lineage.");
        }
    }
}

internal sealed class ProtectedAssessmentRuntimeStateStore
{
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true, PropertyNameCaseInsensitive = false };
    private readonly string _path;

    public ProtectedAssessmentRuntimeStateStore(string path)
    {
        if (string.IsNullOrWhiteSpace(path)) throw new ArgumentException("Protected assessment state path is required.", nameof(path));
        _path = Path.GetFullPath(path);
    }

    public string StatePath => _path;
    public string BackupPath => _path + ".bak";

    public ProtectedAssessmentRuntimeSnapshot Load()
    {
        if (!File.Exists(_path)) return new ProtectedAssessmentRuntimeSnapshot();
        try { return ReadValidated(_path); }
        catch (Exception primary) when (primary is JsonException or InvalidDataException or IOException)
        {
            if (!File.Exists(BackupPath))
                throw new InvalidDataException("Protected assessment state is invalid and no backup is available.", primary);
            try { return ReadValidated(BackupPath); }
            catch (Exception backup) when (backup is JsonException or InvalidDataException or IOException)
            {
                throw new InvalidDataException("Protected assessment state and its backup are both invalid.", new AggregateException(primary, backup));
            }
        }
    }

    public void Save(ProtectedAssessmentRuntimeSnapshot snapshot)
    {
        ArgumentNullException.ThrowIfNull(snapshot);
        snapshot.Validate();
        string? directory = Path.GetDirectoryName(_path);
        if (!string.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);
        string temp = _path + ".tmp-" + Guid.NewGuid().ToString("N");
        try
        {
            File.WriteAllText(temp, JsonSerializer.Serialize(snapshot, JsonOptions), new System.Text.UTF8Encoding(false));
            if (File.Exists(_path)) File.Copy(_path, BackupPath, true);
            File.Move(temp, _path, true);
        }
        finally
        {
            if (File.Exists(temp)) File.Delete(temp);
        }
    }

    private static ProtectedAssessmentRuntimeSnapshot ReadValidated(string path)
    {
        ProtectedAssessmentRuntimeSnapshot? snapshot = JsonSerializer.Deserialize<ProtectedAssessmentRuntimeSnapshot>(File.ReadAllText(path), JsonOptions);
        if (snapshot is null) throw new InvalidDataException("Protected assessment state is empty.");
        snapshot.Validate();
        return snapshot;
    }
}