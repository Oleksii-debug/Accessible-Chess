using System.Text.Json;

namespace WordDeck;

internal sealed class WordDeckFullV1Profile
{
    public int ProfileSchemaVersion { get; set; } = FullV1ProfileService.CurrentProfileSchemaVersion;
    public int RecallSchemaVersion { get; set; } = AppStateStore.CurrentSchemaVersion;
    public int SpellingSchemaVersion { get; set; } = FullV1ProfileService.CurrentSpellingSchemaVersion;
    public int SentenceSchemaVersion { get; set; } = FullV1ProfileService.CurrentSentenceSchemaVersion;
    public string SourceAppVersion { get; set; } = AppStateStore.SourceAppVersion;
    public string CorpusIdentity { get; set; } = AppStateStore.CorpusIdentity;
    public DateTimeOffset ExportedAtUtc { get; set; } = DateTimeOffset.UtcNow;
    public AppState Recall { get; set; } = new();
    public SpellingState Spelling { get; set; } = new();
    public SentenceCoachState Sentence { get; set; } = new();
}

internal sealed class FullV1RecoveryBundle
{
    public int Version { get; set; } = 1;
    public string CorpusIdentity { get; set; } = AppStateStore.CorpusIdentity;
    public DateTimeOffset CreatedAtUtc { get; set; } = DateTimeOffset.UtcNow;
    public AppState Recall { get; set; } = new();
    public SpellingState Spelling { get; set; } = new();
    public SentenceCoachState Sentence { get; set; } = new();
}

internal sealed record FullV1ProfileImportResult(
    string RecoveryBundlePath,
    IReadOnlyList<string> QuarantinedIds,
    bool LegacyRecallOnlyProfile);

internal sealed class FullV1ProfileService
{
    public const int CurrentProfileSchemaVersion = 3;
    public const int CurrentSpellingSchemaVersion = 1;
    public const int CurrentSentenceSchemaVersion = 1;

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        PropertyNameCaseInsensitive = true
    };

    private readonly string _root;
    private readonly string _backups;
    private readonly AppStateStore _appStore;
    private readonly SpellingStateStore _spellingStore;
    private readonly SentenceCoachStateStore _sentenceStore;
    private readonly Action<string>? _testCheckpoint;

    public FullV1ProfileService()
        : this(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WordDeck"))
    {
    }

    internal FullV1ProfileService(string root, Action<string>? testCheckpoint = null)
    {
        if (string.IsNullOrWhiteSpace(root))
            throw new ArgumentException("Profile root must not be blank.", nameof(root));
        _root = Path.GetFullPath(root);
        _backups = Path.Combine(_root, "Backups");
        Directory.CreateDirectory(_root);
        Directory.CreateDirectory(_backups);
        _appStore = new AppStateStore(_root);
        _spellingStore = new SpellingStateStore(_root);
        _sentenceStore = new SentenceCoachStateStore(_root);
        _testCheckpoint = testCheckpoint;
    }

    public void Export(AppState recall, SpellingState spelling, SentenceCoachState sentence, string destinationPath)
    {
        if (string.IsNullOrWhiteSpace(destinationPath))
            throw new ArgumentException("Profile destination path is required.", nameof(destinationPath));

        var profile = new WordDeckFullV1Profile
        {
            ProfileSchemaVersion = CurrentProfileSchemaVersion,
            RecallSchemaVersion = AppStateStore.CurrentSchemaVersion,
            SpellingSchemaVersion = CurrentSpellingSchemaVersion,
            SentenceSchemaVersion = CurrentSentenceSchemaVersion,
            SourceAppVersion = AppStateStore.SourceAppVersion,
            CorpusIdentity = AppStateStore.CorpusIdentity,
            ExportedAtUtc = DateTimeOffset.UtcNow,
            Recall = CloneRecall(AppStateStore.Normalize(CloneRecall(recall))),
            Spelling = CloneSpelling(SpellingStateStore.Normalize(CloneSpelling(spelling))),
            Sentence = CloneSentence(SentenceCoachStateStore.Normalize(CloneSentence(sentence)))
        };

        string fullPath = Path.GetFullPath(destinationPath);
        string? directory = Path.GetDirectoryName(fullPath);
        if (!string.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);
        string temp = fullPath + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(profile, JsonOptions));
        File.Move(temp, fullPath, true);
    }

    public FullV1ProfileImportResult Import(
        string sourcePath,
        AppState destinationRecall,
        SpellingState destinationSpelling,
        SentenceCoachState destinationSentence,
        IEnumerable<string> knownEntryIds,
        IEnumerable<string> knownDictionaryIds,
        IEnumerable<string>? knownSentencePackIds = null)
    {
        if (!File.Exists(sourcePath))
            throw new FileNotFoundException("WordDeck personal profile was not found.", sourcePath);

        int schema = ReadProfileSchema(sourcePath);
        if (schema == AppStateStore.ProfileSchemaVersion)
        {
            ValidateLegacyCorpus(sourcePath);
            ProfileImportResult legacy = _appStore.ImportProfile(sourcePath, destinationRecall, knownEntryIds, knownDictionaryIds);
            return new FullV1ProfileImportResult(legacy.BackupPath, legacy.QuarantinedIds, LegacyRecallOnlyProfile: true);
        }
        if (schema != CurrentProfileSchemaVersion)
            throw new InvalidDataException($"Unsupported WordDeck full profile schema {schema}; expected {CurrentProfileSchemaVersion} or legacy {AppStateStore.ProfileSchemaVersion}. No data was changed.");

        WordDeckFullV1Profile profile = ReadFullProfile(sourcePath);
        ValidateProfile(profile);

        AppState incomingRecall = AppStateStore.Normalize(CloneRecall(profile.Recall));
        SpellingState incomingSpelling = SpellingStateStore.Normalize(CloneSpelling(profile.Spelling));
        SentenceCoachState incomingSentence = SentenceCoachStateStore.Normalize(CloneSentence(profile.Sentence));
        IReadOnlyList<string> quarantine = BuildQuarantine(
            incomingRecall, incomingSpelling, incomingSentence,
            knownEntryIds, knownDictionaryIds, knownSentencePackIds ?? Array.Empty<string>());
        incomingRecall.QuarantinedProfileEntryIds = incomingRecall.QuarantinedProfileEntryIds
            .Concat(quarantine)
            .Where(id => !string.IsNullOrWhiteSpace(id))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(id => id, StringComparer.OrdinalIgnoreCase)
            .ToList();

        // No persistent writes occur before the full profile has parsed, passed
        // schema/corpus validation, and all three module states have normalized.
        _testCheckpoint?.Invoke("validated-before-backup");

        AppState beforeRecall = CloneRecall(destinationRecall);
        SpellingState beforeSpelling = CloneSpelling(destinationSpelling);
        SentenceCoachState beforeSentence = CloneSentence(destinationSentence);
        string recovery = CreateRecoveryBundle(beforeRecall, beforeSpelling, beforeSentence, "pre-import-v3");
        _testCheckpoint?.Invoke("recovery-bundle-written");

        try
        {
            ReplaceRecall(destinationRecall, incomingRecall);
            ReplaceSpelling(destinationSpelling, incomingSpelling);
            ReplaceSentence(destinationSentence, incomingSentence);

            _appStore.Save(destinationRecall);
            _testCheckpoint?.Invoke("recall-saved");
            _spellingStore.Save(destinationSpelling);
            _testCheckpoint?.Invoke("spelling-saved");
            _sentenceStore.Save(destinationSentence);
            _testCheckpoint?.Invoke("sentence-saved");

            return new FullV1ProfileImportResult(recovery, destinationRecall.QuarantinedProfileEntryIds.ToArray(), LegacyRecallOnlyProfile: false);
        }
        catch
        {
            try
            {
                ReplaceRecall(destinationRecall, beforeRecall);
                ReplaceSpelling(destinationSpelling, beforeSpelling);
                ReplaceSentence(destinationSentence, beforeSentence);
                _appStore.Save(destinationRecall);
                _spellingStore.Save(destinationSpelling);
                _sentenceStore.Save(destinationSentence);
            }
            catch
            {
                // The recovery bundle was committed before any imported state was
                // persisted and remains available if storage-level rollback fails.
            }
            throw;
        }
    }

    private string CreateRecoveryBundle(AppState recall, SpellingState spelling, SentenceCoachState sentence, string reason)
    {
        string safeReason = string.Concat(reason.Select(ch => char.IsLetterOrDigit(ch) || ch is '-' or '_' ? ch : '-'));
        string path = Path.Combine(_backups, $"WordDeck-full-profile-{DateTime.UtcNow:yyyyMMdd-HHmmssfff}-{safeReason}.json");
        var bundle = new FullV1RecoveryBundle
        {
            CorpusIdentity = AppStateStore.CorpusIdentity,
            CreatedAtUtc = DateTimeOffset.UtcNow,
            Recall = CloneRecall(recall),
            Spelling = CloneSpelling(spelling),
            Sentence = CloneSentence(sentence)
        };
        string temp = path + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(bundle, JsonOptions));
        File.Move(temp, path, false);
        RotateRecoveryBundles(20);
        return path;
    }

    private void RotateRecoveryBundles(int keep)
    {
        foreach (FileInfo stale in new DirectoryInfo(_backups).GetFiles("WordDeck-full-profile-*.json")
                     .OrderByDescending(file => file.LastWriteTimeUtc).Skip(keep))
        {
            try { stale.Delete(); } catch { }
        }
    }

    private static int ReadProfileSchema(string path)
    {
        try
        {
            using JsonDocument document = JsonDocument.Parse(File.ReadAllText(path));
            if (!document.RootElement.TryGetProperty(nameof(WordDeckProfile.ProfileSchemaVersion), out JsonElement value) ||
                value.ValueKind != JsonValueKind.Number || !value.TryGetInt32(out int schema))
                throw new InvalidDataException("The selected file has no valid WordDeck profile schema version.");
            return schema;
        }
        catch (InvalidDataException) { throw; }
        catch (Exception ex)
        {
            throw new InvalidDataException("The selected file is not a readable WordDeck personal profile.", ex);
        }
    }

    private static WordDeckFullV1Profile ReadFullProfile(string path)
    {
        try
        {
            return JsonSerializer.Deserialize<WordDeckFullV1Profile>(File.ReadAllText(path), JsonOptions)
                ?? throw new InvalidDataException("The selected full WordDeck profile contains no data.");
        }
        catch (InvalidDataException) { throw; }
        catch (Exception ex)
        {
            throw new InvalidDataException("The selected full WordDeck profile is unreadable.", ex);
        }
    }

    private static void ValidateProfile(WordDeckFullV1Profile profile)
    {
        if (profile.ProfileSchemaVersion != CurrentProfileSchemaVersion)
            throw new InvalidDataException("The selected full profile has an unsupported profile schema. No data was changed.");
        if (!string.Equals(profile.CorpusIdentity, AppStateStore.CorpusIdentity, StringComparison.Ordinal))
            throw new InvalidDataException("The selected full profile belongs to an incompatible WordDeck corpus. No data was changed.");
        if (profile.Recall is null || profile.Spelling is null || profile.Sentence is null)
            throw new InvalidDataException("The selected full profile is missing Recall, Spelling, or Sentence state. No data was changed.");
        if (profile.RecallSchemaVersion > AppStateStore.CurrentSchemaVersion || profile.Recall.SchemaVersion > AppStateStore.CurrentSchemaVersion)
            throw new InvalidDataException("The selected full profile uses a newer Recall state schema. No data was changed.");
        if (profile.SpellingSchemaVersion > CurrentSpellingSchemaVersion)
            throw new InvalidDataException("The selected full profile uses a newer Spelling state schema. No data was changed.");
        if (profile.SentenceSchemaVersion > CurrentSentenceSchemaVersion)
            throw new InvalidDataException("The selected full profile uses a newer Sentence state schema. No data was changed.");
    }

    private static void ValidateLegacyCorpus(string path)
    {
        try
        {
            WordDeckProfile profile = JsonSerializer.Deserialize<WordDeckProfile>(File.ReadAllText(path), JsonOptions)
                ?? throw new InvalidDataException("The selected legacy profile contains no state.");
            if (!string.Equals(profile.CorpusIdentity, AppStateStore.CorpusIdentity, StringComparison.Ordinal))
                throw new InvalidDataException("The selected legacy profile belongs to an incompatible WordDeck corpus. No data was changed.");
        }
        catch (InvalidDataException) { throw; }
        catch (Exception ex)
        {
            throw new InvalidDataException("The selected legacy profile is unreadable.", ex);
        }
    }

    private static IReadOnlyList<string> BuildQuarantine(
        AppState recall,
        SpellingState spelling,
        SentenceCoachState sentence,
        IEnumerable<string> knownEntryIds,
        IEnumerable<string> knownDictionaryIds,
        IEnumerable<string> knownSentencePackIds)
    {
        var knownEntries = new HashSet<string>(knownEntryIds.Where(id => !string.IsNullOrWhiteSpace(id)), StringComparer.OrdinalIgnoreCase);
        foreach (CustomEntryRecord custom in recall.CustomEntriesByDictionary.Values.SelectMany(items => items))
            knownEntries.Add(custom.Id);
        var knownDictionaries = new HashSet<string>(knownDictionaryIds.Where(id => !string.IsNullOrWhiteSpace(id)), StringComparer.OrdinalIgnoreCase);
        var knownPacks = new HashSet<string>(knownSentencePackIds.Where(id => !string.IsNullOrWhiteSpace(id)), StringComparer.OrdinalIgnoreCase);
        var quarantine = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (string id in CollectRecallEntryIds(recall).Concat(CollectSpellingEntryIds(spelling)).Concat(CollectSentenceEntryIds(sentence)))
            if (!knownEntries.Contains(id)) quarantine.Add(id);
        foreach (string id in CollectRecallDictionaryIds(recall).Concat(spelling.DeckIdsByDictionary.Keys).Concat(spelling.StatsByDictionary.Keys))
            if (!knownDictionaries.Contains(id)) quarantine.Add("dictionary:" + id);
        if (!string.IsNullOrWhiteSpace(sentence.ActivePackId) && knownPacks.Count > 0 && !knownPacks.Contains(sentence.ActivePackId))
            quarantine.Add("sentence-pack:" + sentence.ActivePackId);

        return quarantine.OrderBy(id => id, StringComparer.OrdinalIgnoreCase).ToArray();
    }

    private static IEnumerable<string> CollectRecallEntryIds(AppState state)
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
        foreach (Dictionary<string, string> map in state.DeckIdsByDictionary.Values)
            foreach (string id in map.Keys) yield return id;
        foreach (string id in state.CurrentEntryIdByDictionary.Values)
            if (!string.IsNullOrWhiteSpace(id)) yield return id;
        foreach (Dictionary<string, SpellingEntryStats> stats in state.StatsByDictionary.Values)
            foreach (string id in stats.Keys) yield return id;
        if (state.LastCoachMove is not null) yield return state.LastCoachMove.EntryId;
    }

    private static IEnumerable<string> CollectSentenceEntryIds(SentenceCoachState state)
    {
        foreach (string id in state.CurrentTargetEntryIds) if (!string.IsNullOrWhiteSpace(id)) yield return id;
        if (!string.IsNullOrWhiteSpace(state.CurrentTargetEntryId)) yield return state.CurrentTargetEntryId;
        foreach (Dictionary<string, SentenceTargetStats> stats in state.StatsByDictionary.Values)
            foreach (string id in stats.Keys) yield return id;
    }

    private static IEnumerable<string> CollectRecallDictionaryIds(AppState state)
    {
        if (!string.IsNullOrWhiteSpace(state.ActiveDictionaryId)) yield return state.ActiveDictionaryId;
        foreach (string id in state.DeckIdsByDictionary.Keys) yield return id;
        foreach (string id in state.DecksByDictionary.Keys) yield return id;
        foreach (string id in state.CustomEntriesByDictionary.Keys) yield return id;
        foreach (string id in state.RecallStudyScopesByDictionary.Keys) yield return id;
    }

    private static AppState CloneRecall(AppState value) => Clone<AppState>(value, "Recall");
    private static SpellingState CloneSpelling(SpellingState value) => Clone<SpellingState>(value, "Spelling");
    private static SentenceCoachState CloneSentence(SentenceCoachState value) => Clone<SentenceCoachState>(value, "Sentence");

    private static T Clone<T>(T value, string label) where T : class =>
        JsonSerializer.Deserialize<T>(JsonSerializer.Serialize(value, JsonOptions), JsonOptions)
        ?? throw new InvalidDataException($"Could not clone {label} profile state.");

    private static void ReplaceRecall(AppState destination, AppState source)
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

    private static void ReplaceSpelling(SpellingState destination, SpellingState source)
    {
        destination.ActiveDeckId = source.ActiveDeckId;
        destination.Decks = source.Decks;
        destination.DeckIdsByDictionary = source.DeckIdsByDictionary;
        destination.CurrentEntryIdByDictionary = source.CurrentEntryIdByDictionary;
        destination.StatsByDictionary = source.StatsByDictionary;
        destination.CoachEnabled = source.CoachEnabled;
        destination.LastCoachMove = source.LastCoachMove;
        SpellingStateStore.Normalize(destination);
    }

    private static void ReplaceSentence(SentenceCoachState destination, SentenceCoachState source)
    {
        destination.ActivePackId = source.ActivePackId;
        destination.ActiveSpellingDeckId = source.ActiveSpellingDeckId;
        destination.TargetCount = source.TargetCount;
        destination.CurrentSentenceId = source.CurrentSentenceId;
        destination.CurrentTargetEntryId = source.CurrentTargetEntryId;
        destination.CurrentTargetEntryIds = source.CurrentTargetEntryIds;
        destination.RecentSentenceIds = source.RecentSentenceIds;
        destination.StatsByDictionary = source.StatsByDictionary;
        SentenceCoachStateStore.Normalize(destination);
    }
}
