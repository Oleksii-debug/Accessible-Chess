using System.Text.Json;

namespace WordDeck;

internal sealed class WordDeckCombinedProfile
{
    public int ProfileSchemaVersion { get; set; } = SpellingProfileService.CurrentProfileSchemaVersion;
    public int StateSchemaVersion { get; set; } = AppStateStore.CurrentSchemaVersion;
    public int SpellingSchemaVersion { get; set; } = SpellingStateStore.CurrentSchemaVersion;
    public string SourceAppVersion { get; set; } = AppStateStore.SourceAppVersion;
    public string CorpusIdentity { get; set; } = AppStateStore.CorpusIdentity;
    public DateTimeOffset ExportedAtUtc { get; set; } = DateTimeOffset.UtcNow;
    public AppState State { get; set; } = new();
    public SpellingState SpellingState { get; set; } = new();
}

internal sealed record CombinedProfileImportResult(
    string RecallBackupPath,
    string? SpellingBackupPath,
    IReadOnlyList<string> QuarantinedIds,
    bool SpellingImported,
    bool LegacyProfile);

internal sealed class SpellingProfileService
{
    public const int CurrentProfileSchemaVersion = 2;

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        PropertyNameCaseInsensitive = true
    };

    private readonly AppStateStore _appStore;
    private readonly SpellingStateStore _spellingStore;

    public SpellingProfileService(AppStateStore appStore, SpellingStateStore spellingStore)
    {
        _appStore = appStore;
        _spellingStore = spellingStore;
    }

    public void Export(AppState appState, SpellingState spellingState, string destinationPath)
    {
        if (string.IsNullOrWhiteSpace(destinationPath))
            throw new ArgumentException("Profile destination path is required.", nameof(destinationPath));

        AppStateStore.Normalize(appState);
        SpellingStateStore.Normalize(spellingState);
        string fullPath = Path.GetFullPath(destinationPath);
        string? directory = Path.GetDirectoryName(fullPath);
        if (!string.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);

        var profile = new WordDeckCombinedProfile
        {
            ProfileSchemaVersion = CurrentProfileSchemaVersion,
            StateSchemaVersion = AppStateStore.CurrentSchemaVersion,
            SpellingSchemaVersion = SpellingStateStore.CurrentSchemaVersion,
            SourceAppVersion = AppStateStore.SourceAppVersion,
            CorpusIdentity = AppStateStore.CorpusIdentity,
            ExportedAtUtc = DateTimeOffset.UtcNow,
            State = CloneApp(appState),
            SpellingState = SpellingStateStore.Clone(spellingState)
        };

        string temp = fullPath + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(profile, JsonOptions));
        File.Move(temp, fullPath, true);
    }

    public CombinedProfileImportResult Import(
        string sourcePath,
        AppState destinationApp,
        SpellingState destinationSpelling,
        IEnumerable<string> knownEntryIds,
        IEnumerable<string> knownDictionaryIds)
    {
        if (!File.Exists(sourcePath))
            throw new FileNotFoundException("WordDeck personal profile was not found.", sourcePath);

        int profileSchema = ReadProfileSchema(sourcePath);
        if (profileSchema == AppStateStore.ProfileSchemaVersion)
        {
            // V0.1 profiles predate Spelling-in-profile. Import Recall through the
            // proven V0.1 path and deliberately preserve the user's current
            // Spelling state rather than resetting it to defaults.
            ProfileImportResult legacy = _appStore.ImportProfile(sourcePath, destinationApp, knownEntryIds, knownDictionaryIds);
            return new CombinedProfileImportResult(legacy.BackupPath, null, legacy.QuarantinedIds, SpellingImported: false, LegacyProfile: true);
        }
        if (profileSchema != CurrentProfileSchemaVersion)
            throw new InvalidDataException($"Unsupported WordDeck profile schema {profileSchema}; this build supports legacy schema {AppStateStore.ProfileSchemaVersion} and schema {CurrentProfileSchemaVersion}.");

        WordDeckCombinedProfile profile;
        try
        {
            profile = JsonSerializer.Deserialize<WordDeckCombinedProfile>(File.ReadAllText(sourcePath), JsonOptions)
                ?? throw new InvalidDataException("The selected profile contains no WordDeck data.");
        }
        catch (InvalidDataException)
        {
            throw;
        }
        catch (Exception ex)
        {
            throw new InvalidDataException("The selected file is not a readable WordDeck personal profile.", ex);
        }

        if (profile.State is null || profile.SpellingState is null)
            throw new InvalidDataException("The selected profile does not contain both Recall and Spelling state.");
        if (profile.StateSchemaVersion > AppStateStore.CurrentSchemaVersion || profile.State.SchemaVersion > AppStateStore.CurrentSchemaVersion)
            throw new InvalidDataException("The selected profile uses a newer incompatible Recall state schema. No data was changed.");
        if (profile.SpellingSchemaVersion > SpellingStateStore.CurrentSchemaVersion || profile.SpellingState.SchemaVersion > SpellingStateStore.CurrentSchemaVersion)
            throw new InvalidDataException("The selected profile uses a newer incompatible Spelling state schema. No data was changed.");
        if (!string.Equals(profile.CorpusIdentity, AppStateStore.CorpusIdentity, StringComparison.Ordinal))
            throw new InvalidDataException("The selected profile belongs to a different WordDeck corpus identity. No data was changed.");

        AppState beforeApp = CloneApp(destinationApp);
        SpellingState beforeSpelling = SpellingStateStore.Clone(destinationSpelling);

        // Ensure both parseable files exist before making import backups.
        _appStore.Save(destinationApp);
        _spellingStore.Save(destinationSpelling);
        string recallBackup = _appStore.CreateRecoveryProfile(destinationApp, "pre-import-v2");
        string spellingBackup = _spellingStore.CreateTimestampedBackup("pre-import-v2");

        try
        {
            AppState importedApp = AppStateStore.Normalize(CloneApp(profile.State));
            SpellingState importedSpelling = SpellingStateStore.Normalize(SpellingStateStore.Clone(profile.SpellingState));
            IReadOnlyList<string> quarantine = BuildQuarantine(importedApp, importedSpelling, knownEntryIds, knownDictionaryIds);
            importedApp.QuarantinedProfileEntryIds = importedApp.QuarantinedProfileEntryIds
                .Concat(quarantine)
                .Where(id => !string.IsNullOrWhiteSpace(id))
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .OrderBy(id => id, StringComparer.OrdinalIgnoreCase)
                .ToList();

            ReplaceApp(destinationApp, importedApp);
            SpellingStateStore.Replace(destinationSpelling, importedSpelling);
            _appStore.Save(destinationApp);
            _spellingStore.Save(destinationSpelling);
            return new CombinedProfileImportResult(recallBackup, spellingBackup, destinationApp.QuarantinedProfileEntryIds.ToArray(), SpellingImported: true, LegacyProfile: false);
        }
        catch
        {
            try
            {
                ReplaceApp(destinationApp, beforeApp);
                SpellingStateStore.Replace(destinationSpelling, beforeSpelling);
                _appStore.Save(destinationApp);
                _spellingStore.Save(destinationSpelling);
            }
            catch
            {
                // The timestamped recovery files remain available even if a
                // storage-level rollback itself cannot be completed.
            }
            throw;
        }
    }

    private static int ReadProfileSchema(string sourcePath)
    {
        try
        {
            using JsonDocument doc = JsonDocument.Parse(File.ReadAllText(sourcePath));
            if (!doc.RootElement.TryGetProperty(nameof(WordDeckProfile.ProfileSchemaVersion), out JsonElement schema) ||
                schema.ValueKind != JsonValueKind.Number || !schema.TryGetInt32(out int value))
                throw new InvalidDataException("The selected file has no valid WordDeck profile schema version.");
            return value;
        }
        catch (InvalidDataException)
        {
            throw;
        }
        catch (Exception ex)
        {
            throw new InvalidDataException("The selected file is not a readable WordDeck personal profile.", ex);
        }
    }

    private static IReadOnlyList<string> BuildQuarantine(
        AppState appState,
        SpellingState spellingState,
        IEnumerable<string> knownEntryIds,
        IEnumerable<string> knownDictionaryIds)
    {
        var knownEntries = new HashSet<string>(knownEntryIds.Where(id => !string.IsNullOrWhiteSpace(id)), StringComparer.OrdinalIgnoreCase);
        foreach (CustomEntryRecord record in appState.CustomEntriesByDictionary.Values.SelectMany(list => list))
            knownEntries.Add(record.Id);
        var knownDictionaries = new HashSet<string>(knownDictionaryIds.Where(id => !string.IsNullOrWhiteSpace(id)), StringComparer.OrdinalIgnoreCase);
        var quarantine = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (string id in CollectAppEntryIds(appState).Concat(CollectSpellingEntryIds(spellingState)))
            if (!knownEntries.Contains(id)) quarantine.Add(id);
        foreach (string dictionaryId in CollectAppDictionaryIds(appState).Concat(CollectSpellingDictionaryIds(spellingState)))
            if (!knownDictionaries.Contains(dictionaryId)) quarantine.Add($"dictionary:{dictionaryId}");
        return quarantine.OrderBy(id => id, StringComparer.OrdinalIgnoreCase).ToArray();
    }

    private static IEnumerable<string> CollectAppEntryIds(AppState state)
    {
        foreach (string id in state.HiddenEntryIds) yield return id;
        foreach (string id in state.StudyHistoryByEntryId.Keys) yield return id;
        foreach (string id in state.CurrentEntryIdByDictionary.Values) if (!string.IsNullOrWhiteSpace(id)) yield return id;
        foreach (Dictionary<string, string> map in state.DeckIdsByDictionary.Values)
            foreach (string id in map.Keys) yield return id;
        foreach (List<CustomEntryRecord> records in state.CustomEntriesByDictionary.Values)
            foreach (CustomEntryRecord record in records) yield return record.Id;
        foreach (RecallStudyScopeDictionaryState dictionary in state.RecallStudyScopesByDictionary.Values)
            foreach (RecallStudyScopeState scope in dictionary.Scopes.Values)
            {
                foreach (string id in scope.DeckIds.Keys) yield return id;
                if (!string.IsNullOrWhiteSpace(scope.CurrentEntryId)) yield return scope.CurrentEntryId;
                foreach (string id in scope.RemainingShuffleEntryIds) yield return id;
            }
    }

    private static IEnumerable<string> CollectSpellingEntryIds(SpellingState state)
    {
        foreach (Dictionary<string, Dictionary<string, string>> scopes in state.DeckIdsByDictionaryScope.Values)
            foreach (Dictionary<string, string> map in scopes.Values)
                foreach (string id in map.Keys) yield return id;
        foreach (Dictionary<string, string> scopes in state.CurrentEntryIdsByDictionaryScope.Values)
            foreach (string id in scopes.Values) if (!string.IsNullOrWhiteSpace(id)) yield return id;
        foreach (Dictionary<string, SpellingEntryStats> stats in state.StatsByDictionary.Values)
            foreach (string id in stats.Keys) yield return id;
        if (state.LastCoachMove is not null) yield return state.LastCoachMove.EntryId;
    }

    private static IEnumerable<string> CollectAppDictionaryIds(AppState state)
    {
        if (!string.IsNullOrWhiteSpace(state.ActiveDictionaryId)) yield return state.ActiveDictionaryId;
        foreach (string id in state.DeckIdsByDictionary.Keys) yield return id;
        foreach (string id in state.DecksByDictionary.Keys) yield return id;
        foreach (string id in state.CustomEntriesByDictionary.Keys) yield return id;
        foreach (string id in state.RecallStudyScopesByDictionary.Keys) yield return id;
    }

    private static IEnumerable<string> CollectSpellingDictionaryIds(SpellingState state)
    {
        foreach (string id in state.DeckIdsByDictionaryScope.Keys) yield return id;
        foreach (string id in state.ActiveScopeIdByDictionary.Keys) yield return id;
        foreach (string id in state.CurrentEntryIdsByDictionaryScope.Keys) yield return id;
        foreach (string id in state.StatsByDictionary.Keys) yield return id;
        if (state.LastCoachMove is not null) yield return state.LastCoachMove.DictionaryId;
    }

    private static AppState CloneApp(AppState state) =>
        JsonSerializer.Deserialize<AppState>(JsonSerializer.Serialize(state, JsonOptions), JsonOptions)
        ?? throw new InvalidDataException("Could not clone WordDeck Recall state.");

    private static void ReplaceApp(AppState destination, AppState source)
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
        AppStateStore.Normalize(destination);
    }
}
