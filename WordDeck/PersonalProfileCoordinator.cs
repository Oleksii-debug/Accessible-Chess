using System.Text.Json;

namespace WordDeck;

internal sealed class PersonalProfileCoordinator
{
    private sealed class Envelope
    {
        public int ProfileSchemaVersion { get; set; }
        public int StateSchemaVersion { get; set; }
        public string SourceAppVersion { get; set; } = string.Empty;
        public string CorpusIdentity { get; set; } = string.Empty;
        public DateTimeOffset ExportedAtUtc { get; set; }
        public AppState State { get; set; } = new();
        public SentenceCoachState? SentenceState { get; set; }
    }

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        PropertyNameCaseInsensitive = true
    };

    private readonly AppStateStore _appStore;
    private readonly SentenceCoachStateStore _sentenceStore;
    private readonly string _root;

    public PersonalProfileCoordinator(AppStateStore appStore)
        : this(appStore, Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WordDeck"))
    {
    }

    internal PersonalProfileCoordinator(AppStateStore appStore, string root)
    {
        _appStore = appStore ?? throw new ArgumentNullException(nameof(appStore));
        if (string.IsNullOrWhiteSpace(root))
            throw new ArgumentException("WordDeck personal-state root is required.", nameof(root));
        _root = Path.GetFullPath(root);
        _sentenceStore = new SentenceCoachStateStore(_root);
    }

    public void Export(AppState state, string destinationPath)
    {
        if (string.IsNullOrWhiteSpace(destinationPath))
            throw new ArgumentException("Profile destination path is required.", nameof(destinationPath));

        string fullDestination = Path.GetFullPath(destinationPath);
        string? directory = Path.GetDirectoryName(fullDestination);
        if (!string.IsNullOrWhiteSpace(directory)) Directory.CreateDirectory(directory);

        string baseTemp = fullDestination + ".base." + Guid.NewGuid().ToString("N") + ".tmp";
        string finalTemp = fullDestination + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            _appStore.ExportProfile(state, baseTemp);
            WordDeckProfile baseProfile = JsonSerializer.Deserialize<WordDeckProfile>(File.ReadAllText(baseTemp), JsonOptions)
                ?? throw new InvalidDataException("Could not materialize the base WordDeck profile for coordinated export.");

            var envelope = new Envelope
            {
                ProfileSchemaVersion = baseProfile.ProfileSchemaVersion,
                StateSchemaVersion = baseProfile.StateSchemaVersion,
                SourceAppVersion = baseProfile.SourceAppVersion,
                CorpusIdentity = baseProfile.CorpusIdentity,
                ExportedAtUtc = baseProfile.ExportedAtUtc,
                State = baseProfile.State,
                SentenceState = CloneSentence(_sentenceStore.Load())
            };

            File.WriteAllText(finalTemp, JsonSerializer.Serialize(envelope, JsonOptions));
            Envelope verify = ParseEnvelope(finalTemp);
            if (verify.SentenceState is null)
                throw new InvalidDataException("Coordinated WordDeck profile lost Sentence state during export verification.");
            File.Move(finalTemp, fullDestination, true);
        }
        finally
        {
            TryDelete(baseTemp);
            TryDelete(finalTemp);
        }
    }

    public ProfileImportResult Import(
        string sourcePath,
        AppState destination,
        IEnumerable<string> knownEntryIds,
        IEnumerable<string> knownDictionaryIds)
    {
        if (string.IsNullOrWhiteSpace(sourcePath))
            throw new ArgumentException("Profile source path is required.", nameof(sourcePath));
        string fullSource = Path.GetFullPath(sourcePath);
        if (!File.Exists(fullSource))
            throw new FileNotFoundException("WordDeck personal profile was not found.", fullSource);

        string[] knownEntries = knownEntryIds.Where(id => !string.IsNullOrWhiteSpace(id)).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        string[] knownDictionaries = knownDictionaryIds.Where(id => !string.IsNullOrWhiteSpace(id)).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        Envelope envelope = ParseEnvelope(fullSource);
        if (!string.Equals(envelope.CorpusIdentity, AppStateStore.CorpusIdentity, StringComparison.Ordinal))
            throw new InvalidDataException($"Profile corpus identity '{envelope.CorpusIdentity}' is incompatible with this WordDeck build. No personal state was changed.");

        SentenceCoachState? importedSentence = envelope.SentenceState is null
            ? null
            : ValidateSentenceState(envelope.SentenceState, knownEntries);

        if (importedSentence is not null && !string.IsNullOrWhiteSpace(importedSentence.ActivePackId))
        {
            InstalledSentencePack? installed = new SentencePackStore(_root).Find(importedSentence.ActivePackId);
            if (installed is null)
                throw new InvalidDataException($"Profile references SentencePack '{importedSentence.ActivePackId}', which is not installed and validated on this device. No personal state was changed.");
        }

        SentenceCoachState beforeSentence = CloneSentence(_sentenceStore.Load());
        ProfileImportResult result = _appStore.ImportProfile(fullSource, destination, knownEntries, knownDictionaries);
        if (importedSentence is null)
            return result; // Legacy V0.1 profile: preserve existing Sentence state.

        try
        {
            _sentenceStore.Save(importedSentence);
            return result;
        }
        catch
        {
            try { _sentenceStore.Save(beforeSentence); } catch { }
            try
            {
                _appStore.ImportProfile(result.BackupPath, destination, knownEntries, knownDictionaries);
            }
            catch { }
            throw;
        }
    }

    private static Envelope ParseEnvelope(string path)
    {
        Envelope? envelope;
        try
        {
            envelope = JsonSerializer.Deserialize<Envelope>(File.ReadAllText(path), JsonOptions);
        }
        catch (Exception ex) when (ex is JsonException or IOException or UnauthorizedAccessException)
        {
            throw new InvalidDataException("The selected file is not a readable WordDeck personal profile.", ex);
        }

        if (envelope is null || envelope.State is null)
            throw new InvalidDataException("The selected profile contains no WordDeck state.");
        if (envelope.ProfileSchemaVersion != AppStateStore.ProfileSchemaVersion)
            throw new InvalidDataException($"Unsupported WordDeck profile schema {envelope.ProfileSchemaVersion}; expected {AppStateStore.ProfileSchemaVersion}.");
        if (envelope.StateSchemaVersion > AppStateStore.CurrentSchemaVersion || envelope.State.SchemaVersion > AppStateStore.CurrentSchemaVersion)
            throw new InvalidDataException("The selected profile uses a newer incompatible WordDeck state schema. No data was changed.");
        if (string.IsNullOrWhiteSpace(envelope.CorpusIdentity))
            throw new InvalidDataException("The selected profile has no corpus identity and cannot be validated safely.");
        return envelope;
    }

    private static SentenceCoachState ValidateSentenceState(SentenceCoachState source, IEnumerable<string> knownEntryIds)
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

    private static SentenceCoachState CloneSentence(SentenceCoachState state) =>
        JsonSerializer.Deserialize<SentenceCoachState>(JsonSerializer.Serialize(state, JsonOptions), JsonOptions)
        ?? throw new InvalidDataException("Could not clone Sentence Coach personal state.");

    private static void TryDelete(string path)
    {
        try { if (File.Exists(path)) File.Delete(path); } catch { }
    }
}
