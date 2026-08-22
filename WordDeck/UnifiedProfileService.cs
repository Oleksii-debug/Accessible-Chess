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
        : this(appStore, Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WordDeck")) { }

    internal UnifiedProfileService(AppStateStore appStore, string root)
    {
        _appStore = appStore ?? throw new ArgumentNullException(nameof(appStore));
        if (string.IsNullOrWhiteSpace(root)) throw new ArgumentException("WordDeck personal-state root is required.", nameof(root));
        _root = Path.GetFullPath(root);
        Directory.CreateDirectory(_root);
        _spellingStore = new SpellingStateStore(_root);
        _sentenceStore = new SentenceCoachStateStore(_root);
    }

    public void Export(AppState appState, string destinationPath)
    {
        if (string.IsNullOrWhiteSpace(destinationPath)) throw new ArgumentException("Profile destination path is required.", nameof(destinationPath));
        SpellingState spelling = TrainingStateContinuityGuard.LoadSpelling(_root).State;
        SentenceCoachState sentence = TrainingStateContinuityGuard.LoadSentence(_root).State;
        AppStateStore.Normalize(appState);
        SpellingStateStore.Normalize(spelling);
        SentenceCoachStateStore.Normalize(sentence);

        var profile = new WordDeckUnifiedProfile
        {
            State = CloneApp(appState),
            SpellingState = SpellingStateStore.Clone(spelling),
            SentenceState = CloneSentence(sentence)
        };
        string fullPath = Path.GetFullPath(destinationPath);
        string? directory = Path.GetDirectoryName(fullPath);
        if (!string.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);
        string temp = fullPath + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(profile, JsonOptions));
        _ = ParseV3(temp);
        File.Move(temp, fullPath, true);
    }

    public UnifiedProfileImportResult Import(
        string sourcePath,
        AppState destinationApp,
        IEnumerable<string> knownEntryIds,
        IEnumerable<string> knownDictionaryIds)
    {
        if (!File.Exists(sourcePath)) throw new FileNotFoundException("WordDeck personal profile was not found.", sourcePath);
        int schema = ReadProfileSchema(sourcePath);
        SpellingState currentSpelling = TrainingStateContinuityGuard.LoadSpelling(_root).State;

        if (schema is AppStateStore.ProfileSchemaVersion or SpellingProfileService.CurrentProfileSchemaVersion)
        {
            CombinedProfileImportResult legacy = new SpellingProfileService(_appStore, _spellingStore).Import(
                sourcePath, destinationApp, currentSpelling, knownEntryIds, knownDictionaryIds);
            return new UnifiedProfileImportResult(
                legacy.RecallBackupPath, legacy.SpellingBackupPath, null, legacy.QuarantinedIds,
                legacy.SpellingImported, SentenceImported: false, SourceProfileSchemaVersion: schema);
        }
        if (schema != CurrentProfileSchemaVersion)
            throw new InvalidDataException($"Unsupported WordDeck profile schema {schema}; supported schemas are 1, 2 and {CurrentProfileSchemaVersion}.");

        WordDeckUnifiedProfile profile = ParseV3(sourcePath);
        ValidateV3Header(profile);
        string[] knownEntries = knownEntryIds.Where(id => !string.IsNullOrWhiteSpace(id)).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        string[] knownDictionaries = knownDictionaryIds.Where(id => !string.IsNullOrWhiteSpace(id)).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        SentenceCoachState importedSentence = ValidateSentence(profile.SentenceState, knownEntries);
        if (!string.IsNullOrWhiteSpace(importedSentence.ActivePackId) && new SentencePackStore(_root).Find(importedSentence.ActivePackId) is null)
            throw new InvalidDataException($"Profile references SentencePack '{importedSentence.ActivePackId}', which is not installed and validated on this device. No personal state was changed.");

        SentenceCoachState beforeSentence = TrainingStateContinuityGuard.LoadSentence(_root).State;
        AppState beforeApp = CloneApp(destinationApp);
        SpellingState beforeSpelling = SpellingStateStore.Clone(currentSpelling);
        string sentenceBackup = CreateSentenceRecoveryBackup(beforeSentence, "pre-import-v3");
        string tempV2 = Path.Combine(_root, $"profile-import-{Guid.NewGuid():N}.v2.tmp.json");
        string rollbackV2 = Path.Combine(_root, $"profile-rollback-{Guid.NewGuid():N}.v2.tmp.json");
        try
        {
            WriteV2(tempV2, profile.State, profile.SpellingState);
            CombinedProfileImportResult imported = new SpellingProfileService(_appStore, _spellingStore).Import(
                tempV2, destinationApp, currentSpelling, knownEntries, knownDictionaries);
            try
            {
                _sentenceStore.Save(importedSentence);
            }
            catch
            {
                try
                {
                    WriteV2(rollbackV2, beforeApp, beforeSpelling);
                    SpellingState rollbackSpelling = TrainingStateContinuityGuard.LoadSpelling(_root).State;
                    _ = new SpellingProfileService(_appStore, _spellingStore).Import(
                        rollbackV2, destinationApp, rollbackSpelling, knownEntries, knownDictionaries);
                    _sentenceStore.Save(beforeSentence);
                }
                catch { }
                throw;
            }
            return new UnifiedProfileImportResult(
                imported.RecallBackupPath,
                imported.SpellingBackupPath,
                sentenceBackup,
                imported.QuarantinedIds,
                SpellingImported: true,
                SentenceImported: true,
                SourceProfileSchemaVersion: schema);
        }
        finally
        {
            try { if (File.Exists(tempV2)) File.Delete(tempV2); } catch { }
            try { if (File.Exists(rollbackV2)) File.Delete(rollbackV2); } catch { }
        }
    }

    private static void ValidateV3Header(WordDeckUnifiedProfile profile)
    {
        if (!string.Equals(profile.CorpusIdentity, AppStateStore.CorpusIdentity, StringComparison.Ordinal))
            throw new InvalidDataException("The selected profile belongs to a different WordDeck corpus identity. No personal state was changed.");
        if (profile.StateSchemaVersion > AppStateStore.CurrentSchemaVersion || profile.State.SchemaVersion > AppStateStore.CurrentSchemaVersion)
            throw new InvalidDataException("The selected profile uses a newer incompatible Recall state schema. No personal state was changed.");
        if (profile.SpellingSchemaVersion > SpellingStateStore.CurrentSchemaVersion || profile.SpellingState.SchemaVersion > SpellingStateStore.CurrentSchemaVersion)
            throw new InvalidDataException("The selected profile uses a newer incompatible Spelling state schema. No personal state was changed.");
    }

    private static SentenceCoachState ValidateSentence(SentenceCoachState source, IReadOnlyCollection<string> knownEntryIds)
    {
        SentenceCoachState state = SentenceCoachStateStore.Normalize(CloneSentence(source));
        var known = new HashSet<string>(knownEntryIds, StringComparer.OrdinalIgnoreCase);
        if (state.CurrentTargetEntryIds.Any(id => !known.Contains(id)))
            throw new InvalidDataException("Sentence profile current exercise references a target stable ID absent from this WordDeck corpus.");
        foreach ((string dictionaryId, Dictionary<string, SentenceTargetStats> stats) in state.StatsByDictionary)
        {
            if (string.IsNullOrWhiteSpace(dictionaryId)) throw new InvalidDataException("Sentence profile contains a blank dictionary identity.");
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

    private void WriteV2(string path, AppState app, SpellingState spelling)
    {
        var v2 = new WordDeckCombinedProfile
        {
            ProfileSchemaVersion = SpellingProfileService.CurrentProfileSchemaVersion,
            StateSchemaVersion = AppStateStore.CurrentSchemaVersion,
            SpellingSchemaVersion = SpellingStateStore.CurrentSchemaVersion,
            SourceAppVersion = AppStateStore.SourceAppVersion,
            CorpusIdentity = AppStateStore.CorpusIdentity,
            ExportedAtUtc = DateTimeOffset.UtcNow,
            State = CloneApp(app),
            SpellingState = SpellingStateStore.Clone(spelling)
        };
        File.WriteAllText(path, JsonSerializer.Serialize(v2, JsonOptions));
    }

    private string CreateSentenceRecoveryBackup(SentenceCoachState state, string reason)
    {
        string backups = Path.Combine(_root, "Backups");
        Directory.CreateDirectory(backups);
        string safe = string.Concat(reason.Select(ch => char.IsLetterOrDigit(ch) || ch is '-' or '_' ? ch : '-'));
        string path = Path.Combine(backups, $"sentence-coach-state-{DateTime.UtcNow:yyyyMMdd-HHmmssfff}-{safe}.json");
        File.WriteAllText(path, JsonSerializer.Serialize(state, JsonOptions));
        foreach (FileInfo stale in new DirectoryInfo(backups).GetFiles("sentence-coach-state-*.json").OrderByDescending(x => x.LastWriteTimeUtc).Skip(20))
            try { stale.Delete(); } catch { }
        return path;
    }

    private static WordDeckUnifiedProfile ParseV3(string path)
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
        catch (Exception ex) { throw new InvalidDataException("The selected file is not a readable WordDeck personal profile.", ex); }
    }

    private static int ReadProfileSchema(string path)
    {
        try
        {
            using JsonDocument doc = JsonDocument.Parse(File.ReadAllText(path));
            if (!doc.RootElement.TryGetProperty(nameof(WordDeckUnifiedProfile.ProfileSchemaVersion), out JsonElement schema) ||
                schema.ValueKind != JsonValueKind.Number || !schema.TryGetInt32(out int value))
                throw new InvalidDataException("The selected file has no valid WordDeck profile schema version.");
            return value;
        }
        catch (InvalidDataException) { throw; }
        catch (Exception ex) { throw new InvalidDataException("The selected file is not a readable WordDeck personal profile.", ex); }
    }

    private static AppState CloneApp(AppState state) =>
        JsonSerializer.Deserialize<AppState>(JsonSerializer.Serialize(state, JsonOptions), JsonOptions)
        ?? throw new InvalidDataException("Could not clone WordDeck Recall state.");

    private static SentenceCoachState CloneSentence(SentenceCoachState state) =>
        JsonSerializer.Deserialize<SentenceCoachState>(JsonSerializer.Serialize(state, JsonOptions), JsonOptions)
        ?? throw new InvalidDataException("Could not clone WordDeck Sentence state.");
}
