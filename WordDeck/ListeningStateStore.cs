using System.Text.Json;

namespace WordDeck;

internal sealed class ListeningStateStore
{
    public const int CurrentSchemaVersion = 1;
    private const string FileName = "listening-state.json";
    private readonly string _root;
    private readonly string _path;
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        PropertyNameCaseInsensitive = true
    };

    public ListeningStateStore()
        : this(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WordDeck")) { }

    internal ListeningStateStore(string root)
    {
        if (string.IsNullOrWhiteSpace(root)) throw new ArgumentException("Listening state root is required.", nameof(root));
        _root = Path.GetFullPath(root);
        _path = Path.Combine(_root, FileName);
        Directory.CreateDirectory(_root);
    }

    public string StatePath => _path;

    public ListeningCoachState Load()
    {
        if (!File.Exists(_path)) return Normalize(new ListeningCoachState());
        ListeningCoachState state;
        try
        {
            state = JsonSerializer.Deserialize<ListeningCoachState>(File.ReadAllText(_path), JsonOptions)
                ?? throw new InvalidDataException("Listening progress file contains no state.");
        }
        catch (InvalidDataException) { throw; }
        catch (Exception ex)
        {
            throw new InvalidDataException("Listening progress could not be read. The existing file was left untouched.", ex);
        }

        if (state.SchemaVersion > CurrentSchemaVersion)
            throw new InvalidDataException($"Listening progress uses newer schema {state.SchemaVersion}; this build supports {CurrentSchemaVersion}. The file was left untouched.");
        if (state.SchemaVersion < CurrentSchemaVersion)
        {
            _ = CreateBackup("pre-migration");
            state.SchemaVersion = CurrentSchemaVersion;
            state = Normalize(state);
            Save(state);
            return state;
        }
        return Normalize(state);
    }

    public void Save(ListeningCoachState state)
    {
        state = Normalize(state);
        Directory.CreateDirectory(_root);
        string temp = _path + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(state, JsonOptions));
        _ = ParseAndValidate(temp);
        File.Move(temp, _path, true);
    }

    public string? CreateBackup(string reason)
    {
        if (!File.Exists(_path)) return null;
        string folder = Path.Combine(_root, "Backups");
        Directory.CreateDirectory(folder);
        string safe = string.Concat((reason ?? "backup").Select(ch => char.IsLetterOrDigit(ch) || ch is '-' or '_' ? ch : '-'));
        string destination = Path.Combine(folder, $"listening-state-{DateTime.UtcNow:yyyyMMdd-HHmmssfff}-{safe}.json");
        File.Copy(_path, destination, false);
        foreach (FileInfo stale in new DirectoryInfo(folder).GetFiles("listening-state-*.json").OrderByDescending(x => x.LastWriteTimeUtc).Skip(20))
            try { stale.Delete(); } catch { }
        return destination;
    }

    internal static ListeningCoachState Normalize(ListeningCoachState state)
    {
        state.SchemaVersion = CurrentSchemaVersion;
        if (!StudyScopeIds.Ordered.Contains(state.ActiveScopeId, StringComparer.OrdinalIgnoreCase))
            state.ActiveScopeId = StudyScopeIds.All;
        else
            state.ActiveScopeId = StudyScopeIds.Ordered.First(id => string.Equals(id, state.ActiveScopeId, StringComparison.OrdinalIgnoreCase));
        state.SelectionCounter = Math.Max(0, state.SelectionCounter);
        state.StatsByDictionary ??= new Dictionary<string, Dictionary<string, ListeningItemStats>>(StringComparer.OrdinalIgnoreCase);
        var normalized = new Dictionary<string, Dictionary<string, ListeningItemStats>>(StringComparer.OrdinalIgnoreCase);
        foreach ((string dictionaryId, Dictionary<string, ListeningItemStats>? source) in state.StatsByDictionary)
        {
            if (string.IsNullOrWhiteSpace(dictionaryId) || source is null) continue;
            var perDictionary = new Dictionary<string, ListeningItemStats>(StringComparer.OrdinalIgnoreCase);
            foreach ((string exerciseId, ListeningItemStats? stats) in source)
            {
                if (string.IsNullOrWhiteSpace(exerciseId) || stats is null) continue;
                ValidateNonNegative(stats);
                stats.CorrectReviews = Math.Min(stats.CorrectReviews, stats.CompletedReviews);
                perDictionary[exerciseId] = stats;
            }
            normalized[dictionaryId] = perDictionary;
        }
        state.StatsByDictionary = normalized;
        state.History ??= new List<ListeningHistoryRecord>();
        state.History = state.History
            .Where(item => item is not null && !string.IsNullOrWhiteSpace(item.DictionaryId) && !string.IsNullOrWhiteSpace(item.ExerciseId))
            .OrderBy(item => item.AtUtc)
            .TakeLast(2000)
            .ToList();
        return state;
    }

    private static void ValidateNonNegative(ListeningItemStats stats)
    {
        if (stats.CompletedReviews < 0 || stats.CorrectReviews < 0 || stats.WrongAttempts < 0 ||
            stats.ReplayCount < 0 || stats.ShowAnswerUses < 0 || stats.SkipCount < 0 || stats.ConsecutiveCorrect < 0)
            throw new InvalidDataException("Listening progress contains negative statistics.");
        if (stats.CorrectReviews > stats.CompletedReviews)
            throw new InvalidDataException("Listening correct-review count exceeds completed reviews.");
    }

    private static ListeningCoachState ParseAndValidate(string path)
    {
        try
        {
            ListeningCoachState value = JsonSerializer.Deserialize<ListeningCoachState>(File.ReadAllText(path), JsonOptions)
                ?? throw new InvalidDataException("Listening state validation produced no data.");
            if (value.SchemaVersion != CurrentSchemaVersion)
                throw new InvalidDataException("Listening state validation found an unexpected schema.");
            return Normalize(value);
        }
        catch (InvalidDataException) { throw; }
        catch (Exception ex) { throw new InvalidDataException("Listening state validation failed.", ex); }
    }
}

internal sealed class ListeningProfileEnvelope
{
    public int ProfileSchemaVersion { get; set; } = ListeningProfileService.CurrentProfileSchemaVersion;
    public int ListeningSchemaVersion { get; set; } = ListeningStateStore.CurrentSchemaVersion;
    public string CorpusIdentity { get; set; } = AppStateStore.CorpusIdentity;
    public string SourceAppVersion { get; set; } = AppStateStore.SourceAppVersion;
    public DateTimeOffset ExportedAtUtc { get; set; } = DateTimeOffset.UtcNow;
    public ListeningCoachState ListeningState { get; set; } = new();
}

internal sealed class ListeningProfileService
{
    public const int CurrentProfileSchemaVersion = 1;
    private readonly ListeningStateStore _store;
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        PropertyNameCaseInsensitive = true
    };

    public ListeningProfileService(ListeningStateStore store) => _store = store ?? throw new ArgumentNullException(nameof(store));

    public void Export(ListeningCoachState state, string destinationPath)
    {
        if (string.IsNullOrWhiteSpace(destinationPath)) throw new ArgumentException("Listening profile destination is required.", nameof(destinationPath));
        var envelope = new ListeningProfileEnvelope { ListeningState = Clone(ListeningStateStore.Normalize(state)) };
        string full = Path.GetFullPath(destinationPath);
        string? directory = Path.GetDirectoryName(full);
        if (!string.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);
        string temp = full + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(envelope, JsonOptions));
        _ = ReadValidated(temp);
        File.Move(temp, full, true);
    }

    public string? Import(string sourcePath)
    {
        ListeningProfileEnvelope envelope = ReadValidated(sourcePath);
        string? backup = _store.CreateBackup("pre-listening-profile-import");
        _store.Save(envelope.ListeningState);
        return backup;
    }

    private static ListeningProfileEnvelope ReadValidated(string path)
    {
        if (!File.Exists(path)) throw new FileNotFoundException("Listening profile was not found.", path);
        try
        {
            ListeningProfileEnvelope envelope = JsonSerializer.Deserialize<ListeningProfileEnvelope>(File.ReadAllText(path), JsonOptions)
                ?? throw new InvalidDataException("Listening profile contains no data.");
            if (envelope.ProfileSchemaVersion != CurrentProfileSchemaVersion)
                throw new InvalidDataException($"Unsupported Listening profile schema {envelope.ProfileSchemaVersion}.");
            if (envelope.ListeningSchemaVersion > ListeningStateStore.CurrentSchemaVersion ||
                envelope.ListeningState.SchemaVersion > ListeningStateStore.CurrentSchemaVersion)
                throw new InvalidDataException("Listening profile was created by a newer incompatible WordDeck version.");
            if (!string.Equals(envelope.CorpusIdentity, AppStateStore.CorpusIdentity, StringComparison.Ordinal))
                throw new InvalidDataException("Listening profile belongs to a different WordDeck corpus identity.");
            envelope.ListeningState = ListeningStateStore.Normalize(envelope.ListeningState);
            return envelope;
        }
        catch (InvalidDataException) { throw; }
        catch (Exception ex) { throw new InvalidDataException("Selected file is not a readable WordDeck Listening profile.", ex); }
    }

    private static ListeningCoachState Clone(ListeningCoachState state) =>
        JsonSerializer.Deserialize<ListeningCoachState>(JsonSerializer.Serialize(state, JsonOptions), JsonOptions)
        ?? throw new InvalidDataException("Could not clone Listening state.");
}
