using System.Text.Json;

namespace WordDeck;

internal sealed class AppStateStore
{
    public const int CurrentSchemaVersion = 2;
    public const int ProfileSchemaVersion = 1;
    public const string SourceAppVersion = "0.1";
    public const string CorpusIdentity = "oxford-3000-en-uk:3308+2138";

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        PropertyNameCaseInsensitive = true
    };

    private readonly string _root;
    private readonly string _statePath;
    private readonly string _backupPath;
    private readonly string _backupsDirectory;
    public string DictionaryDirectory { get; }

    public AppStateStore()
        : this(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WordDeck"))
    {
    }

    internal AppStateStore(string root)
    {
        if (string.IsNullOrWhiteSpace(root))
            throw new ArgumentException("State root directory must not be blank.", nameof(root));

        _root = root;
        DictionaryDirectory = Path.Combine(_root, "Dictionaries");
        _backupsDirectory = Path.Combine(_root, "Backups");
        _statePath = Path.Combine(_root, "state.json");
        _backupPath = Path.Combine(_root, "state.backup.json");
        Directory.CreateDirectory(_root);
        Directory.CreateDirectory(DictionaryDirectory);
        Directory.CreateDirectory(_backupsDirectory);
    }

    public AppState Load()
    {
        AppState? primary = TryLoad(_statePath);
        if (primary is not null)
            return PrepareLoaded(primary, _statePath);

        AppState? backup = TryLoad(_backupPath);
        if (backup is not null)
            return PrepareLoaded(backup, _backupPath);

        if (File.Exists(_statePath) || File.Exists(_backupPath))
            throw new InvalidDataException("WordDeck personal state is unreadable and no verified backup can be loaded. The existing files were left untouched.");

        return Normalize(new AppState());
    }

    private AppState PrepareLoaded(AppState state, string sourcePath)
    {
        if (state.SchemaVersion > CurrentSchemaVersion)
            throw new InvalidDataException($"This WordDeck profile uses newer state schema {state.SchemaVersion}; this build supports up to {CurrentSchemaVersion}. No state was changed.");

        bool migrationNeeded = state.SchemaVersion < CurrentSchemaVersion;
        if (migrationNeeded)
        {
            CreateTimestampedFileBackup(sourcePath, "pre-migration");
            Normalize(state);
            Save(state);
        }
        else
        {
            Normalize(state);
        }
        return state;
    }

    public void Save(AppState state)
    {
        Normalize(state);
        state.SchemaVersion = CurrentSchemaVersion;
        string temp = _statePath + ".tmp";
        string json = JsonSerializer.Serialize(state, JsonOptions);
        File.WriteAllText(temp, json);

        // Keep the last parseable state as a recovery point. Never overwrite a
        // good backup with corrupted primary bytes.
        if (TryLoad(_statePath) is not null)
            File.Copy(_statePath, _backupPath, true);

        File.Move(temp, _statePath, true);
    }

    public string CreateTimestampedBackup(string reason)
    {
        string? source = TryLoad(_statePath) is not null ? _statePath : TryLoad(_backupPath) is not null ? _backupPath : null;
        if (source is null)
            throw new InvalidDataException("No parseable WordDeck state exists to back up.");
        return CreateTimestampedFileBackup(source, reason);
    }

    private string CreateTimestampedFileBackup(string sourcePath, string reason)
    {
        Directory.CreateDirectory(_backupsDirectory);
        string safeReason = string.Concat(reason.Select(ch => char.IsLetterOrDigit(ch) || ch is '-' or '_' ? ch : '-'));
        string destination = Path.Combine(_backupsDirectory, $"state-{DateTime.UtcNow:yyyyMMdd-HHmmssfff}-{safeReason}.json");
        File.Copy(sourcePath, destination, false);
        RotateBackups("state-*.json", 20);
        return destination;
    }

    public string CreateRecoveryProfile(AppState state, string reason)
    {
        Directory.CreateDirectory(_backupsDirectory);
        string safeReason = string.Concat(reason.Select(ch => char.IsLetterOrDigit(ch) || ch is '-' or '_' ? ch : '-'));
        string path = Path.Combine(_backupsDirectory, $"WordDeck-profile-{DateTime.UtcNow:yyyyMMdd-HHmmssfff}-{safeReason}.json");
        ExportProfile(state, path);
        RotateBackups("WordDeck-profile-*.json", 20);
        return path;
    }

    private void RotateBackups(string pattern, int keep)
    {
        foreach (FileInfo stale in new DirectoryInfo(_backupsDirectory).GetFiles(pattern)
                     .OrderByDescending(file => file.LastWriteTimeUtc).Skip(keep))
        {
            try { stale.Delete(); } catch { }
        }
    }

    public void ExportProfile(AppState state, string destinationPath)
    {
        if (string.IsNullOrWhiteSpace(destinationPath))
            throw new ArgumentException("Profile destination path is required.", nameof(destinationPath));

        Normalize(state);
        string fullPath = Path.GetFullPath(destinationPath);
        string? directory = Path.GetDirectoryName(fullPath);
        if (!string.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);

        var profile = new WordDeckProfile
        {
            ProfileSchemaVersion = ProfileSchemaVersion,
            StateSchemaVersion = CurrentSchemaVersion,
            SourceAppVersion = SourceAppVersion,
            CorpusIdentity = CorpusIdentity,
            ExportedAtUtc = DateTimeOffset.UtcNow,
            State = Clone(state)
        };
        string temp = fullPath + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(profile, JsonOptions));
        File.Move(temp, fullPath, true);
    }

    public ProfileImportResult ImportProfile(
        string sourcePath,
        AppState destination,
        IEnumerable<string> knownEntryIds,
        IEnumerable<string> knownDictionaryIds)
    {
        if (!File.Exists(sourcePath))
            throw new FileNotFoundException("WordDeck personal profile was not found.", sourcePath);

        WordDeckProfile? profile;
        try
        {
            profile = JsonSerializer.Deserialize<WordDeckProfile>(File.ReadAllText(sourcePath), JsonOptions);
        }
        catch (Exception ex)
        {
            throw new InvalidDataException("The selected file is not a readable WordDeck personal profile.", ex);
        }

        if (profile is null || profile.State is null)
            throw new InvalidDataException("The selected profile contains no WordDeck state.");
        if (profile.ProfileSchemaVersion != ProfileSchemaVersion)
            throw new InvalidDataException($"Unsupported WordDeck profile schema {profile.ProfileSchemaVersion}; expected {ProfileSchemaVersion}.");
        if (profile.StateSchemaVersion > CurrentSchemaVersion || profile.State.SchemaVersion > CurrentSchemaVersion)
            throw new InvalidDataException("The selected profile was created by a newer incompatible WordDeck state schema. No data was changed.");
        if (string.IsNullOrWhiteSpace(profile.CorpusIdentity))
            throw new InvalidDataException("The selected profile has no corpus identity and cannot be validated safely.");
        if (!string.Equals(profile.CorpusIdentity, CorpusIdentity, StringComparison.Ordinal))
            throw new InvalidDataException($"The selected profile belongs to incompatible corpus '{profile.CorpusIdentity}'. This build requires '{CorpusIdentity}'. No data was changed.");

        string backupPath = CreateRecoveryProfile(destination, "pre-import");
        AppState before = Clone(destination);
        try
        {
            AppState imported = Normalize(profile.State);
            var knownEntries = new HashSet<string>(knownEntryIds.Where(id => !string.IsNullOrWhiteSpace(id)), StringComparer.OrdinalIgnoreCase);
            foreach (CustomEntryRecord record in imported.CustomEntriesByDictionary.Values.SelectMany(list => list))
                knownEntries.Add(record.Id);
            var knownDictionaries = new HashSet<string>(knownDictionaryIds.Where(id => !string.IsNullOrWhiteSpace(id)), StringComparer.OrdinalIgnoreCase);

            var quarantined = CollectReferencedEntryIds(imported)
                .Where(id => !knownEntries.Contains(id))
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .OrderBy(id => id, StringComparer.OrdinalIgnoreCase)
                .ToList();
            foreach (string dictionaryId in CollectDictionaryIds(imported).Where(id => !knownDictionaries.Contains(id)))
                quarantined.Add($"dictionary:{dictionaryId}");
            imported.QuarantinedProfileEntryIds = imported.QuarantinedProfileEntryIds
                .Concat(quarantined)
                .Where(id => !string.IsNullOrWhiteSpace(id))
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .OrderBy(id => id, StringComparer.OrdinalIgnoreCase)
                .ToList();

            ReplaceState(destination, imported);
            Save(destination);
            return new ProfileImportResult(backupPath, destination.QuarantinedProfileEntryIds.ToArray());
        }
        catch
        {
            try
            {
                ReplaceState(destination, before);
                Save(destination);
            }
            catch { }
            throw;
        }
    }

    public string ImportDictionary(string sourcePath)
    {
        string fileName = Path.GetFileName(sourcePath);
        string destination = Path.Combine(DictionaryDirectory, fileName);
        File.Copy(sourcePath, destination, true);
        return destination;
    }

    public IEnumerable<string> EnumerateDictionaryFiles() =>
        Directory.EnumerateFiles(DictionaryDirectory, "*.tsv", SearchOption.TopDirectoryOnly);

    private static AppState? TryLoad(string path)
    {
        try
        {
            if (!File.Exists(path)) return null;
            return JsonSerializer.Deserialize<AppState>(File.ReadAllText(path), JsonOptions);
        }
        catch
        {
            return null;
        }
    }

    private static AppState Clone(AppState state) =>
        JsonSerializer.Deserialize<AppState>(JsonSerializer.Serialize(state, JsonOptions), JsonOptions)
        ?? throw new InvalidDataException("Could not clone WordDeck personal state.");

    private static IEnumerable<string> CollectReferencedEntryIds(AppState state)
    {
        foreach (string id in state.HiddenEntryIds) yield return id;
        foreach (string id in state.StudyHistoryByEntryId.Keys) yield return id;
        foreach (string id in state.CurrentEntryIdByDictionary.Values) yield return id;
        foreach (Dictionary<string, string> map in state.DeckIdsByDictionary.Values)
            foreach (string id in map.Keys) yield return id;
        foreach (List<CustomEntryRecord> records in state.CustomEntriesByDictionary.Values)
            foreach (CustomEntryRecord record in records) yield return record.Id;
        foreach (RecallStudyScopeDictionaryState dictionary in state.RecallStudyScopesByDictionary.Values)
        {
            foreach (RecallStudyScopeState scope in dictionary.Scopes.Values)
            {
                foreach (string id in scope.DeckIds.Keys) yield return id;
                if (!string.IsNullOrWhiteSpace(scope.CurrentEntryId)) yield return scope.CurrentEntryId;
                foreach (string id in scope.RemainingShuffleEntryIds) yield return id;
            }
        }
    }

    private static IEnumerable<string> CollectDictionaryIds(AppState state)
    {
        if (!string.IsNullOrWhiteSpace(state.ActiveDictionaryId)) yield return state.ActiveDictionaryId;
        foreach (string id in state.DeckIdsByDictionary.Keys) yield return id;
        foreach (string id in state.DecksByDictionary.Keys) yield return id;
        foreach (string id in state.CustomEntriesByDictionary.Keys) yield return id;
        foreach (string id in state.RecallStudyScopesByDictionary.Keys) yield return id;
    }

    private static void ReplaceState(AppState destination, AppState source)
    {
        destination.SchemaVersion = source.SchemaVersion;
        destination.ActiveDictionaryId = source.ActiveDictionaryId;
        destination.ActiveDeckId = source.ActiveDeckId;
        destination.Decks = source.Decks;
        destination.DeckIdsByDictionary = source.DeckIdsByDictionary;
        destination.CustomEntriesByDictionary = source.CustomEntriesByDictionary;
        destination.CurrentEntryIdByDictionary = source.CurrentEntryIdByDictionary;
        destination.RecallStudyScopesByDictionary = source.RecallStudyScopesByDictionary;
        destination.ActiveDeck = source.ActiveDeck;
        destination.DecksByDictionary = source.DecksByDictionary;
        destination.Shortcuts = source.Shortcuts;
        destination.AutoPlayPronunciationOnCardChange = source.AutoPlayPronunciationOnCardChange;
        destination.HiddenEntryIds = source.HiddenEntryIds;
        destination.StudyHistoryByEntryId = source.StudyHistoryByEntryId;
        destination.QuarantinedProfileEntryIds = source.QuarantinedProfileEntryIds;
        destination.ExtensionData = source.ExtensionData;
        Normalize(destination);
    }

    internal static AppState Normalize(AppState state)
    {
        if (state.SchemaVersion > CurrentSchemaVersion)
            throw new InvalidDataException($"State schema {state.SchemaVersion} is newer than supported schema {CurrentSchemaVersion}.");

        state.Shortcuts ??= new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        state.Shortcuts = new Dictionary<string, string>(state.Shortcuts, StringComparer.OrdinalIgnoreCase);
        state.Decks ??= new List<DeckDefinition>();
        state.DeckIdsByDictionary ??= new Dictionary<string, Dictionary<string, string>>(StringComparer.OrdinalIgnoreCase);
        state.DecksByDictionary ??= new Dictionary<string, Dictionary<string, int>>(StringComparer.OrdinalIgnoreCase);
        state.CustomEntriesByDictionary ??= new Dictionary<string, List<CustomEntryRecord>>(StringComparer.OrdinalIgnoreCase);
        state.CurrentEntryIdByDictionary ??= new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        state.RecallStudyScopesByDictionary ??= new Dictionary<string, RecallStudyScopeDictionaryState>(StringComparer.OrdinalIgnoreCase);
        state.HiddenEntryIds ??= new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        state.HiddenEntryIds = new HashSet<string>(state.HiddenEntryIds.Where(id => !string.IsNullOrWhiteSpace(id)), StringComparer.OrdinalIgnoreCase);
        state.StudyHistoryByEntryId ??= new Dictionary<string, WordStudyHistory>(StringComparer.OrdinalIgnoreCase);
        state.StudyHistoryByEntryId = state.StudyHistoryByEntryId
            .Where(pair => !string.IsNullOrWhiteSpace(pair.Key) && pair.Value is not null)
            .ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.OrdinalIgnoreCase);
        state.QuarantinedProfileEntryIds ??= new List<string>();
        state.QuarantinedProfileEntryIds = state.QuarantinedProfileEntryIds
            .Where(id => !string.IsNullOrWhiteSpace(id)).Distinct(StringComparer.OrdinalIgnoreCase).ToList();

        state.Decks = state.Decks
            .Where(deck => deck is not null && !string.IsNullOrWhiteSpace(deck.Id))
            .GroupBy(deck => deck.Id, StringComparer.OrdinalIgnoreCase)
            .Select(group => group.First())
            .ToList();

        for (int number = 1; number <= 5; number++)
        {
            string coreId = DeckIds.Core(number);
            DeckDefinition? core = state.Decks.FirstOrDefault(deck => string.Equals(deck.Id, coreId, StringComparison.OrdinalIgnoreCase));
            if (core is null)
            {
                core = new DeckDefinition { Id = coreId, Name = $"Deck {number}", IsCore = true, Order = number - 1 };
                state.Decks.Add(core);
            }
            else
            {
                core.IsCore = true;
                if (string.IsNullOrWhiteSpace(core.Name)) core.Name = $"Deck {number}";
            }
        }

        int nextOrder = state.Decks.Count == 0 ? 0 : state.Decks.Max(deck => deck.Order) + 1;
        foreach (DeckDefinition deck in state.Decks)
        {
            if (string.IsNullOrWhiteSpace(deck.Name)) deck.Name = deck.IsCore ? "Deck" : "Untitled deck";
            if (deck.Order < 0) deck.Order = nextOrder++;
        }

        List<DeckDefinition> ordered = state.Decks
            .OrderBy(deck => deck.Order)
            .ThenBy(deck => deck.IsCore ? 0 : 1)
            .ThenBy(deck => deck.Name, StringComparer.CurrentCultureIgnoreCase)
            .ToList();
        for (int i = 0; i < ordered.Count; i++) ordered[i].Order = i;
        state.Decks = ordered;

        state.DeckIdsByDictionary = state.DeckIdsByDictionary.ToDictionary(
            pair => pair.Key,
            pair => new Dictionary<string, string>(pair.Value ?? new Dictionary<string, string>(), StringComparer.OrdinalIgnoreCase),
            StringComparer.OrdinalIgnoreCase);
        state.DecksByDictionary = state.DecksByDictionary.ToDictionary(
            pair => pair.Key,
            pair => new Dictionary<string, int>(pair.Value ?? new Dictionary<string, int>(), StringComparer.OrdinalIgnoreCase),
            StringComparer.OrdinalIgnoreCase);
        state.CurrentEntryIdByDictionary = new Dictionary<string, string>(state.CurrentEntryIdByDictionary, StringComparer.OrdinalIgnoreCase);

        state.CustomEntriesByDictionary = state.CustomEntriesByDictionary.ToDictionary(
            pair => pair.Key,
            pair => (pair.Value ?? new List<CustomEntryRecord>())
                .Where(entry => entry is not null && !string.IsNullOrWhiteSpace(entry.Id) && !string.IsNullOrWhiteSpace(entry.Source) && !string.IsNullOrWhiteSpace(entry.Target))
                .GroupBy(entry => entry.Id, StringComparer.OrdinalIgnoreCase)
                .Select(group =>
                {
                    CustomEntryRecord entry = group.First();
                    return new CustomEntryRecord(entry.Id.Trim(), entry.Source.Trim(), entry.Target.Trim(),
                        string.IsNullOrWhiteSpace(entry.Level) ? "CUSTOM" : entry.Level.Trim());
                }).ToList(),
            StringComparer.OrdinalIgnoreCase);

        state.RecallStudyScopesByDictionary = state.RecallStudyScopesByDictionary
            .Where(pair => !string.IsNullOrWhiteSpace(pair.Key) && pair.Value is not null)
            .ToDictionary(pair => pair.Key, pair => NormalizeRecallScopeDictionary(pair.Value), StringComparer.OrdinalIgnoreCase);

        foreach ((string dictionaryId, Dictionary<string, int> legacyMap) in state.DecksByDictionary)
        {
            if (!state.DeckIdsByDictionary.TryGetValue(dictionaryId, out Dictionary<string, string>? newMap))
            {
                newMap = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                state.DeckIdsByDictionary[dictionaryId] = newMap;
            }
            foreach ((string entryId, int legacyDeck) in legacyMap)
                newMap.TryAdd(entryId, DeckIds.Core(Math.Clamp(legacyDeck, 1, 5)));
        }

        var validDeckIds = new HashSet<string>(state.Decks.Select(deck => deck.Id), StringComparer.OrdinalIgnoreCase);
        string fallbackDeckId = DeckIds.Core(1);
        foreach (Dictionary<string, string> map in state.DeckIdsByDictionary.Values)
        {
            foreach (string entryId in map.Keys.ToList())
            {
                string? deckId = map[entryId];
                if (string.IsNullOrWhiteSpace(deckId) || !validDeckIds.Contains(deckId)) map[entryId] = fallbackDeckId;
            }
        }

        foreach (RecallStudyScopeDictionaryState dictionaryState in state.RecallStudyScopesByDictionary.Values)
        {
            if (!StudyScopeIds.Ordered.Contains(dictionaryState.ActiveScopeId, StringComparer.OrdinalIgnoreCase))
                dictionaryState.ActiveScopeId = StudyScopeIds.All;
            foreach (RecallStudyScopeState scope in dictionaryState.Scopes.Values)
            {
                if (!validDeckIds.Contains(scope.ActiveDeckId)) scope.ActiveDeckId = fallbackDeckId;
                foreach (string entryId in scope.DeckIds.Keys.ToList())
                {
                    string? deckId = scope.DeckIds[entryId];
                    if (string.IsNullOrWhiteSpace(deckId) || !validDeckIds.Contains(deckId)) scope.DeckIds[entryId] = fallbackDeckId;
                }
                if (scope.CurrentEntryId is not null && !scope.DeckIds.ContainsKey(scope.CurrentEntryId)) scope.CurrentEntryId = null;
            }
        }

        for (int number = 1; number <= 5; number++)
        {
            string coreId = DeckIds.Core(number);
            CopyShortcutIfMissing(state.Shortcuts, ActionIds.LegacySwitchDeck(number), ActionIds.SwitchDeck(coreId));
            CopyShortcutIfMissing(state.Shortcuts, ActionIds.LegacyMoveToDeck(number), ActionIds.MoveToDeck(coreId));
        }

        if (string.IsNullOrWhiteSpace(state.ActiveDeckId) || !validDeckIds.Contains(state.ActiveDeckId))
            state.ActiveDeckId = DeckIds.Core(Math.Clamp(state.ActiveDeck, 1, 5));

        state.SchemaVersion = CurrentSchemaVersion;
        return state;
    }

    private static RecallStudyScopeDictionaryState NormalizeRecallScopeDictionary(RecallStudyScopeDictionaryState dictionaryState)
    {
        dictionaryState.ActiveScopeId = string.IsNullOrWhiteSpace(dictionaryState.ActiveScopeId) ? StudyScopeIds.All : dictionaryState.ActiveScopeId;
        dictionaryState.Scopes ??= new Dictionary<string, RecallStudyScopeState>(StringComparer.OrdinalIgnoreCase);
        dictionaryState.Scopes = dictionaryState.Scopes
            .Where(pair => !string.IsNullOrWhiteSpace(pair.Key) && pair.Value is not null)
            .ToDictionary(pair => pair.Key, pair =>
            {
                RecallStudyScopeState scope = pair.Value;
                scope.ActiveDeckId = string.IsNullOrWhiteSpace(scope.ActiveDeckId) ? DeckIds.Core(1) : scope.ActiveDeckId;
                scope.DeckIds ??= new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                scope.DeckIds = new Dictionary<string, string>(scope.DeckIds, StringComparer.OrdinalIgnoreCase);
                scope.RemainingShuffleEntryIds ??= new List<string>();
                scope.RemainingShuffleEntryIds = scope.RemainingShuffleEntryIds.Where(id => !string.IsNullOrWhiteSpace(id)).Distinct(StringComparer.OrdinalIgnoreCase).ToList();
                return scope;
            }, StringComparer.OrdinalIgnoreCase);
        return dictionaryState;
    }

    private static void CopyShortcutIfMissing(Dictionary<string, string> shortcuts, string legacyId, string durableId)
    {
        if (!shortcuts.ContainsKey(durableId) && shortcuts.TryGetValue(legacyId, out string? value) && !string.IsNullOrWhiteSpace(value))
            shortcuts[durableId] = value;
    }
}
