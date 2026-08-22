using System.Text.Json;

namespace WordDeck;

internal sealed class WordDeckUnifiedProfile
{
    public int ProfileSchemaVersion { get; set; } = UnifiedProfileService.CurrentProfileSchemaVersion;
    public int StateSchemaVersion { get; set; } = AppStateStore.CurrentSchemaVersion;
    public int SpellingSchemaVersion { get; set; } = SpellingStateStore.CurrentSchemaVersion;
    public string SourceAppVersion { get; set; } = AppStateStore.SourceAppVersion;
    public string CorpusIdentity { get; set; } = AppStateStore.CorpusIdentity;
    public DateTimeOffset ExportedAtUtc { get; set; } = DateTimeOffset.UtcNow;
    public AppState State { get; set; } = new();
    public SpellingState SpellingState { get; set; } = new();
    public SentenceCoachState SentenceState { get; set; } = new();
}

internal sealed record UnifiedProfileImportResult(
    string RecallBackupPath,
    string? SpellingBackupPath,
    string? SentenceBackupPath,
    IReadOnlyList<string> QuarantinedIds,
    bool SpellingImported,
    bool SentenceImported,
    int SourceProfileSchemaVersion);

internal sealed class UnifiedProfileService
{
    public const int CurrentProfileSchemaVersion = 3;

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        PropertyNameCaseInsensitive = true
    };

    private readonly AppStateStore _appStore;
    private readonly SpellingStateStore _spellingStore;
    private readonly SentenceCoachStateStore _sentenceStore;
    private readonly string _root;

    public UnifiedProfileService(AppStateStore appStore)
        : this(appStore, Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WordDeck"))
    {
    }

    internal UnifiedProfileService(AppStateStore appStore, string root)
    {
        _appStore = appStore ?? throw new ArgumentNullException(nameof(appStore));
        if (string.IsNullOrWhiteSpace(root))
            throw new ArgumentException("WordDeck personal-state root is required.", nameof(root));
        _root = Path.GetFullPath(root);
        Directory.CreateDirectory(_root);
        _spellingStore = new SpellingStateStore(_root);
        _sentenceStore = new SentenceCoachStateStore(_root);
    }

    public void Export(AppState appState, string destinationPath)
    {
        if (string.IsNullOrWhiteSpace(destinationPath))
            throw new ArgumentException("Profile destination path is required.", nameof(destinationPath));

        SpellingState spelling = TrainingStateContinuityGuard.LoadSpelling(_root).State;
        SentenceCoachState sentence = TrainingStateContinuityGuard.LoadSentence(_root).State;
        AppStateStore.Normalize(appState);
        SpellingStateStore.Normalize(spelling);
        SentenceCoachStateStore.Normalize(sentence);

        var profile = new WordDeckUnifiedProfile
        {
            ProfileSchemaVersion = CurrentProfileSchemaVersion,
            StateSchemaVersion = AppStateStore.CurrentSchemaVersion,
            SpellingSchemaVersion = SpellingStateStore.CurrentSchemaVersion,
            SourceAppVersion = AppStateStore.SourceAppVersion,
            CorpusIdentity = AppStateStore.CorpusIdentity,
            ExportedAtUtc = DateTimeOffset.UtcNow,
            State = CloneApp(appState),
            SpellingState = SpellingStateStore.Clone(spelling),
            SentenceState = CloneSentence(sentence)
        };

        string fullPath = Path.GetFullPath(destinationPath);
        string? directory = Path.GetDirectoryName(fullPath);
        if (!string.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);
        string temp = fullPath + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(profile, JsonOptions));
        WordDeckUnifiedProfile verify = ParseUnified(temp);
        if (verify.SpellingState is null || verify.SentenceState is null)
            throw new InvalidDataException("Unified WordDeck profile verification lost training state.");
        File.Move(temp, fullPath, true);
    }

    public UnifiedProfileImportResult Import(
        string sourcePath,
        AppState destinationApp,
        IEnumerable<string> knownEntryIds,
        IEnumerable<string> knownDictionaryIds)
    {
        if (!File.Exists(sourcePath))
            throw new FileNotFoundException("WordDeck personal profile was not found.", sourcePath);

        int schema = ReadProfileSchema(sourcePath);
        if (schema is AppStateStore.ProfileSchemaVersion or SpellingProfileService.CurrentProfileSchemaVersion)
        {
            SpellingState currentSpelling = TrainingStateContinuityGuard.LoadSpelling(_root).State;
            var legacyService = new SpellingProfileService(_appStore, _spellingStore);
            CombinedProfileImportResult legacy = legacyService.Import(
                sourcePath, destinationApp, currentSpelling, knownEntryIds, knownDictionaryIds);
            return new UnifiedProfileImportResult(
                legacy.RecallBackupPath,
                legacy.SpellingBackupPath,
                null,
                legacy.QuarantinedIds,
                legacy.SpellingImported,
                SentenceImported: false,
                SourceProfileSchemaVersion: schema);
        }
        if (schema != CurrentProfileSchemaVersion)
            throw new InvalidDataException($"Unsupported WordDeck profile schema {schema}; supported schemas are 1, 2 and {CurrentProfileSchemaVersion}.");

        WordDeckUnifiedProfile profile = ParseUnified(sourcePath);
        if (!string.Equals(profile.CorpusIdentity, AppStateStore.CorpusIdentity, StringComparison.Ordinal))
            throw new InvalidDataException("The selected profile belongs to a different WordDeck corpus identity. No personal state was changed.");
        if (profile.StateSchemaVersion > AppStateStore.CurrentSchemaVersion || profile.State.SchemaVersion > AppStateStore.CurrentSchemaVersion)
            throw new InvalidDataException("The selected profile uses a newer incompatible Recall state schema. No personal state was changed.");
        if (profile.SpellingSchemaVersion > SpellingStateStore.CurrentSchemaVersion || profile.SpellingState.SchemaVersion > SpellingStateStore.CurrentSchemaVersion)
            throw new InvalidDataException("The selected profile uses a newer incompatible Spelling state schema. No personal state was changed.");

        string[] knownEntriesArray = knownEntryIds.Where(id => !string.IsNullOrWhiteSpace(id)).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        string[] knownDictionariesArray = knownDictionaryIds.Where(id => !string.IsNullOrWhiteSpace(id)).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        AppState importedApp = AppStateStore.Normalize(CloneApp(profile.State));
        SpellingState importedSpelling = SpellingStateStore.Normalize(SpellingStateStore.Clone(profile.SpellingState));
        SentenceCoachState importedSentence = ValidateSentenceState(profile.SentenceState, knownEntriesArray);
        IReadOnlyList<string> quarantine = BuildQuarantine(importedApp, importedSpelling, knownEntriesArray, knownDictionariesArray);
        importedApp.QuarantinedProfileEntryIds = importedApp.QuarantinedProfileEntryIds
            .Concat(quarantine)
            .Where(id => !string.IsNullOrWhiteSpace(id))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(id => id, StringComparer.OrdinalIgnoreCase)
            .ToList();

        if (!string.IsNullOrWhiteSpace(importedSentence.ActivePackId) && new SentencePackStore(_root).Find(importedSentence.ActivePackId) is null)
            throw new InvalidDataException($"Profile references SentencePack '{importedSentence.ActivePackId}', which is not installed and validated on this device. No personal state was changed.");

        SpellingState currentSpelling = TrainingStateContinuityGuard.LoadSpelling(_root).State;
        SentenceCoachState currentSentence = TrainingStateContinuityGuard.LoadSentence(_root).State;
        AppState beforeApp = CloneApp(destinationApp);
        SpellingState beforeSpelling = SpellingStateStore.Clone(currentSpelling);
        SentenceCoachState beforeSentence = CloneSentence(currentSentence);

        _appStore.Save(destinationApp);
        _spellingStore.Save(currentSpelling);
        _sentenceStore.Save(currentSentence);
        string recallBackup = _appStore.CreateRecoveryProfile(destinationApp, "pre-import-v3");
        string spellingBackup = _spellingStore.CreateTimestampedBackup("pre-import-v3");
        string sentenceBackup = CreateSentenceRecoveryBackup(beforeSentence, "pre-import-v3");

        try
        {
            ReplaceApp(destinationApp, importedApp);
            SpellingStateStore.Replace(currentSpelling, importedSpelling);
            _appStore.Save(destinationApp);
            _spellingStore.Save(currentSpelling);
            _sentenceStore.Save(importedSentence);
            return new UnifiedProfileImportResult(
                recallBackup,
                spellingBackup,
                sentenceBackup,
                destinationApp.QuarantinedProfileEntryIds.ToArray(),
                SpellingImported: true,
                SentenceImported: true,
                SourceProfileSchemaVersion: schema);
        }
        catch
        {
            try
            {
                ReplaceApp(destinationApp, beforeApp);
                SpellingStateStore.Replace(currentSpelling, beforeSpelling);
                _appStore.Save(destinationApp);
                _spellingStore.Save(currentSpelling);
                _sentenceStore.Save(beforeSentence);
            }
            catch { }
            throw;
        }
    }

    private string CreateSentenceRecoveryBackup(SentenceCoachState state, string reason)
    {
        string backups = Path.Combine(_root, "Backups");
        Directory.CreateDirectory(backups);
        string safeReason = string.Concat(reason.Select(ch => char.IsLetterOrDigit(ch) || ch is '-' or '_' ? ch : '-'));
        string path = Path.Combine(backups, $"sentence-coach-state-{DateTime.UtcNow:yyyyMMdd-HHmmssfff}-{safeReason}.json");
        File.WriteAllText(path, JsonSerializer.Serialize(state, JsonOptions));
        foreach (FileInfo stale in new DirectoryInfo(backups).GetFiles("sentence-coach-state-*.json")
                     .OrderByDescending(file => file.LastWriteTimeUtc).Skip(20))
        {
            try { stale.Delete(); } catch { }
        }
        return path;
    }

    private static SentenceCoachState ValidateSentenceState(SentenceCoachState source, IReadOnlyCollection<string> knownEntryIds)
    {
        SentenceCoachState state = SentenceCoachStateStore.Normalize(CloneSentence(source));
        var known = new HashSet<string>(knownEntryIds, StringComparer.OrdinalIgnoreCase);
        if (state.CurrentTargetEntryIds.Any(id => !known.Contains(id)))
            throw new InvalidDataException("Sentence profile current exercise references a target stable ID absent from this WordDeck corpus.");
        foreach ((string dictionaryId, Dictionary<string, SentenceTargetStats> stats) in state.StatsByDictionary)
        {
            if (string.IsNullOrWhiteSpace(dictionaryId))
                throw new InvalidDataException("Sentence profile contains a blank dictionary identity.");
            if (stats.Keys.Any(id => !known.Contains(id)))
                throw new InvalidDataException("Sentence profile contains statistics for target stable IDs absent from this WordDeck corpus.");
            foreach (SentenceTargetStats value in stats.Values)
            {
                if (value.CompletedReviews < 0 || value.FirstTrySuccesses < 0 || value.WrongAttempts < 0 || value.ShowAnswerUses < 0)
                    throw new InvalidDataException("Sentence profile contains negative learning statistics.");
                if (value.FirstTrySuccesses > value.CompletedReviews)
                    throw new InvalidDataException("Sentence profile first-try successes exceed completed reviews.");
            }
        }
        if (state.CurrentTargetEntryIds.Count != 0 && state.CurrentTargetEntryIds.Count != state.TargetCount)
            throw new InvalidDataException("Sentence profile current exercise target count is inconsistent with its configured Sentence mode.");
        return state;
    }

    private static WordDeckUnifiedProfile ParseUnified(string path)
    {
        try
        {
            WordDeckUnifiedProfile profile = JsonSerializer.Deserialize<WordDeckUnifiedProfile>(File.ReadAllText(path), JsonOptions)
                ?? throw new InvalidDataException("The selected profile contains no WordDeck data.");
            if (profile.State is null || profile.SpellingState is null || profile.SentenceState is null)
                throw new InvalidDataException("The selected unified profile does not contain Recall, Spelling and Sentence state.");
            return profile;
        }
        catch (InvalidDataException) { throw; }
        catch (Exception ex)
        {
            throw new InvalidDataException("The selected file is not a readable WordDeck personal profile.", ex);
        }
    }

    private static int ReadProfileSchema(string sourcePath)
    {
        try
        {
            using JsonDocument doc = JsonDocument.Parse(File.ReadAllText(sourcePath));
            if (!doc.RootElement.TryGetProperty(nameof(WordDeckUnifiedProfile.ProfileSchemaVersion), out JsonElement schema) ||
                schema.ValueKind != JsonValueKind.Number || !schema.TryGetInt32(out int value))
                throw new InvalidDataException("The selected file has no valid WordDeck profile schema version.");
            return value;
        }
        catch (InvalidDataException) { throw; }
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
        var knownEntries = new HashSet<string>(knownEntryIds, StringComparer.OrdinalIgnoreCase);
        foreach (CustomEntryRecord record in appState.CustomEntriesByDictionary.Values.SelectMany(list => list)) knownEntries.Add(record.Id);
        var knownDictionaries = new HashSet<string>(knownDictionaryIds, StringComparer.OrdinalIgnoreCase);
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
        foreach (Dictionary<string, string> map in state.DeckIdsByDictionary.Values) foreach (string id in map.Keys) yield return id;
        foreach (List<CustomEntryRecord> records in state.CustomEntriesByDictionary.Values) foreach (CustomEntryRecord record in records) yield return record.Id;
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

    private static SentenceCoachState CloneSentence(SentenceCoachState state) =>
        JsonSerializer.Deserialize<SentenceCoachState>(JsonSerializer.Serialize(state, JsonOptions), JsonOptions)
        ?? throw new InvalidDataException("Could not clone WordDeck Sentence state.");

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
