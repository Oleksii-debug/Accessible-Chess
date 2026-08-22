namespace WordDeck;

// Local infrastructure adapters for the platform-neutral Product Engine ports.
// Presentation code does not need to know LocalAppData paths or profile schema details.
internal sealed class LocalUnifiedProfileTransferPort : IProfileTransferPort
{
    private readonly UnifiedProfileService _profiles;
    private readonly AppState _appState;
    private readonly string[] _knownEntryIds;
    private readonly string[] _knownDictionaryIds;

    public LocalUnifiedProfileTransferPort(
        UnifiedProfileService profiles,
        AppState appState,
        IEnumerable<string> knownEntryIds,
        IEnumerable<string> knownDictionaryIds)
    {
        _profiles = profiles ?? throw new ArgumentNullException(nameof(profiles));
        _appState = appState ?? throw new ArgumentNullException(nameof(appState));
        _knownEntryIds = (knownEntryIds ?? throw new ArgumentNullException(nameof(knownEntryIds)))
            .Where(id => !string.IsNullOrWhiteSpace(id))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
        _knownDictionaryIds = (knownDictionaryIds ?? throw new ArgumentNullException(nameof(knownDictionaryIds)))
            .Where(id => !string.IsNullOrWhiteSpace(id))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
        if (_knownEntryIds.Length == 0)
            throw new ArgumentException("At least one known stable entry id is required.", nameof(knownEntryIds));
        if (_knownDictionaryIds.Length == 0)
            throw new ArgumentException("At least one known dictionary id is required.", nameof(knownDictionaryIds));
    }

    public ValueTask ExportAsync(ProfileExportCommand command, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(command);
        if (string.IsNullOrWhiteSpace(command.DestinationPath))
            throw new ArgumentException("Profile export destination is required.", nameof(command));
        _profiles.Export(_appState, command.DestinationPath);
        return ValueTask.CompletedTask;
    }

    public ValueTask<ProfileTransferResultDto> ImportAsync(ProfileImportCommand command, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(command);
        if (string.IsNullOrWhiteSpace(command.SourcePath))
            throw new ArgumentException("Profile import source is required.", nameof(command));

        UnifiedProfileImportResult result = _profiles.Import(
            command.SourcePath,
            _appState,
            _knownEntryIds,
            _knownDictionaryIds);
        string status = result.SourceProfileSchemaVersion == UnifiedProfileService.CurrentProfileSchemaVersion
            ? "Unified Recall, Spelling and Sentence profile imported."
            : result.SpellingImported
                ? "Legacy Recall and Spelling profile imported; current Sentence state was preserved."
                : "Legacy Recall profile imported; current Spelling and Sentence state were preserved.";

        return ValueTask.FromResult(new ProfileTransferResultDto(
            result.SourceProfileSchemaVersion,
            RecallTransferred: true,
            SpellingTransferred: result.SpellingImported,
            SentenceTransferred: result.SentenceImported,
            result.QuarantinedIds.ToArray(),
            status));
    }
}

internal static class SentencePackProductDescriptorFactory
{
    public static SentencePackProductDescriptor FromValidatedPortablePack(
        SentencePack pack,
        string? portablePath = null,
        string? sqlitePath = null,
        bool isSynthetic = false)
    {
        ArgumentNullException.ThrowIfNull(pack);
        SentencePackStructuralLimits.Validate(pack);
        SentencePackLicenseValidator.ValidateForInstallation(pack);

        string logicalIdentity = "sha256:" + SentencePackDerivativeIdentity.LogicalFingerprint(pack);
        string derivativeIdentity = logicalIdentity;
        if (!string.IsNullOrWhiteSpace(sqlitePath))
        {
            if (!File.Exists(sqlitePath))
                throw new FileNotFoundException("SentencePack SQLite derivative was not found.", sqlitePath);
            derivativeIdentity = "sha256:" + SentencePackDerivativeIdentity.FileHash(sqlitePath);
        }
        else if (!string.IsNullOrWhiteSpace(portablePath))
        {
            if (!File.Exists(portablePath))
                throw new FileNotFoundException("Portable SentencePack file was not found.", portablePath);
            derivativeIdentity = "sha256:" + SentencePackDerivativeIdentity.FileHash(portablePath);
        }

        var descriptor = new SentencePackProductDescriptor(
            pack.PackId,
            pack.Provenance,
            pack.License,
            pack.SentenceCount,
            logicalIdentity,
            derivativeIdentity,
            isSynthetic);
        descriptor.ValidateForRelease();
        return descriptor;
    }
}
