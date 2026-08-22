namespace WordDeck;

// Platform-neutral application contracts. WinForms is the current presentation
// adapter; these types deliberately contain no Control/Form/UIA dependencies.
internal sealed record LearningCardDto(
    string DictionaryId,
    string EntryId,
    string ScopeId,
    string DeckId,
    string English,
    string Ukrainian,
    bool AnswerRevealed,
    WordImageMetadata? Image = null,
    string? Status = null);

internal sealed record SpellingCheckRequest(string TypedEnglish, string ExpectedEnglish);
internal sealed record SpellingCheckResult(bool Accepted, string NormalizedTyped, string NormalizedExpected);
internal sealed record CoachDecisionDto(string? TargetDeckId, string Explanation);
internal sealed record SentenceCheckRequest(string RequiredEnglish, string TypedEnglish);
internal sealed record UnifiedProfileExportRequest(AppState AppState, string DestinationPath);
internal sealed record UnifiedProfileImportRequest(
    string SourcePath,
    AppState DestinationAppState,
    IReadOnlyCollection<string> KnownEntryIds,
    IReadOnlyCollection<string> KnownDictionaryIds);

internal interface ISpellingLearningUseCases
{
    SpellingCheckResult Check(SpellingCheckRequest request);
    CoachDecisionDto EvaluateCoach(string currentDeckId, SpellingEntryStats stats, bool firstTryCorrect, bool usedHint);
}

internal interface ISentenceLearningUseCases
{
    SentenceAnswerResult Check(SentenceCheckRequest request);
}

internal interface IUnifiedProfileUseCases
{
    void Export(UnifiedProfileExportRequest request);
    UnifiedProfileImportResult Import(UnifiedProfileImportRequest request);
}

internal sealed class SpellingLearningApplicationService : ISpellingLearningUseCases
{
    private readonly ISpellingScheduler _scheduler;

    public SpellingLearningApplicationService(ISpellingScheduler? scheduler = null)
    {
        _scheduler = scheduler ?? new ConservativeSpellingScheduler();
    }

    public SpellingCheckResult Check(SpellingCheckRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);
        string typed = SpellingAnswerComparer.NormalizeTechnical(request.TypedEnglish);
        string expected = SpellingAnswerComparer.NormalizeTechnical(request.ExpectedEnglish);
        return new SpellingCheckResult(string.Equals(typed, expected, StringComparison.Ordinal), typed, expected);
    }

    public CoachDecisionDto EvaluateCoach(string currentDeckId, SpellingEntryStats stats, bool firstTryCorrect, bool usedHint)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(currentDeckId);
        ArgumentNullException.ThrowIfNull(stats);
        SpellingScheduleDecision decision = _scheduler.Decide(currentDeckId, stats, firstTryCorrect, usedHint);
        return new CoachDecisionDto(decision.TargetDeckId, decision.Explanation);
    }
}

internal sealed class SentenceLearningApplicationService : ISentenceLearningUseCases
{
    public SentenceAnswerResult Check(SentenceCheckRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);
        return SentenceAnswerEvaluator.Evaluate(request.RequiredEnglish, request.TypedEnglish);
    }
}

internal sealed class UnifiedProfileApplicationService : IUnifiedProfileUseCases
{
    private readonly UnifiedProfileService _profiles;

    public UnifiedProfileApplicationService(UnifiedProfileService profiles)
    {
        _profiles = profiles ?? throw new ArgumentNullException(nameof(profiles));
    }

    public void Export(UnifiedProfileExportRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);
        _profiles.Export(request.AppState, request.DestinationPath);
    }

    public UnifiedProfileImportResult Import(UnifiedProfileImportRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);
        return _profiles.Import(
            request.SourcePath,
            request.DestinationAppState,
            request.KnownEntryIds,
            request.KnownDictionaryIds);
    }
}

internal enum ImageRevealPolicy
{
    NeverDuringQuestion = 0,
    HintOnly = 1,
    AfterAnswer = 2
}

internal sealed record WordImageMetadata(
    string AssetId,
    string Source,
    string License,
    string Provenance,
    string AltText,
    string HintText,
    ImageRevealPolicy RevealPolicy)
{
    public void ValidateForEntry(string englishAnswer)
    {
        Require(AssetId, nameof(AssetId), 160);
        Require(Source, nameof(Source), 2048);
        Require(License, nameof(License), 160);
        Require(Provenance, nameof(Provenance), 2048);
        Require(AltText, nameof(AltText), 1000);
        Require(HintText, nameof(HintText), 1000);

        string answer = NormalizeComparable(englishAnswer);
        if (answer.Length == 0)
            throw new InvalidDataException("Image metadata cannot be validated without a nonblank English answer.");

        if (RevealPolicy != ImageRevealPolicy.AfterAnswer &&
            (ContainsWholeAnswer(AltText, answer) || ContainsWholeAnswer(HintText, answer)))
        {
            throw new InvalidDataException("Image alt/hint text reveals the English answer before the answer phase.");
        }
    }

    private static bool ContainsWholeAnswer(string text, string normalizedAnswer)
    {
        string candidate = NormalizeComparable(text);
        if (candidate.Length == 0) return false;
        if (candidate == normalizedAnswer) return true;
        string padded = " " + candidate + " ";
        return padded.Contains(" " + normalizedAnswer + " ", StringComparison.Ordinal);
    }

    private static string NormalizeComparable(string value)
    {
        string normalized = SpellingAnswerComparer.NormalizeTechnical(value ?? string.Empty).ToLowerInvariant();
        return string.Join(" ", normalized.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));
    }

    private static void Require(string? value, string field, int maxLength)
    {
        if (string.IsNullOrWhiteSpace(value)) throw new InvalidDataException($"Image metadata {field} is required.");
        if (!string.Equals(value, value.Trim(), StringComparison.Ordinal)) throw new InvalidDataException($"Image metadata {field} must not have outer whitespace.");
        if (value.Length > maxLength) throw new InvalidDataException($"Image metadata {field} is too long.");
        SentenceTokenizer.ValidateUnicode(value, $"Image metadata {field}");
    }
}

internal sealed record ProductThemeTokens(
    double BaseSpacing,
    double CompactSpacing,
    double CornerRadius,
    double BodyTextScale,
    double HeadingTextScale,
    double FocusOutlineThickness,
    bool HighContrastCompatible,
    bool ReducedMotionSupported)
{
    public static ProductThemeTokens AccessibleDefault { get; } = new(
        BaseSpacing: 8,
        CompactSpacing: 4,
        CornerRadius: 6,
        BodyTextScale: 1.0,
        HeadingTextScale: 1.25,
        FocusOutlineThickness: 2,
        HighContrastCompatible: true,
        ReducedMotionSupported: true);

    public void Validate()
    {
        if (BaseSpacing <= 0 || CompactSpacing <= 0 || CompactSpacing > BaseSpacing)
            throw new InvalidDataException("Theme spacing tokens are invalid.");
        if (CornerRadius < 0 || BodyTextScale < 1.0 || HeadingTextScale < BodyTextScale || FocusOutlineThickness < 1)
            throw new InvalidDataException("Theme typography/focus tokens violate the accessibility baseline.");
        if (!HighContrastCompatible || !ReducedMotionSupported)
            throw new InvalidDataException("Theme contract must preserve high-contrast compatibility and reduced-motion support.");
    }
}

internal sealed record AccountIdentity(string PseudonymousAccountId, string? DisplayName = null);
internal sealed record ReleaseMetadata(string Version, string Channel, string? Notes = null);
internal sealed record ProductTelemetryEvent(
    string PseudonymousInstallationId,
    string SessionId,
    string AppVersion,
    string StudyMode,
    string EventName,
    long? DurationMilliseconds = null,
    int? AggregateCount = null)
{
    public void Validate()
    {
        RequireOpaque(PseudonymousInstallationId, nameof(PseudonymousInstallationId), 128);
        RequireOpaque(SessionId, nameof(SessionId), 128);
        RequireOpaque(AppVersion, nameof(AppVersion), 64);
        RequireOpaque(StudyMode, nameof(StudyMode), 64);
        RequireOpaque(EventName, nameof(EventName), 96);
        if (DurationMilliseconds is < 0) throw new InvalidDataException("Telemetry duration cannot be negative.");
        if (AggregateCount is < 0) throw new InvalidDataException("Telemetry aggregate count cannot be negative.");
    }

    private static void RequireOpaque(string? value, string field, int maxLength)
    {
        if (string.IsNullOrWhiteSpace(value) || value.Length > maxLength)
            throw new InvalidDataException($"Telemetry {field} is missing or too long.");
        if (value.IndexOfAny(new[] { '\r', '\n', '\t' }) >= 0)
            throw new InvalidDataException($"Telemetry {field} contains control separators.");
    }
}

internal interface IAccountIdentityPort
{
    ValueTask<AccountIdentity?> GetCurrentAsync(CancellationToken cancellationToken = default);
}

internal interface ITelemetryPort
{
    ValueTask TrackAsync(ProductTelemetryEvent telemetryEvent, CancellationToken cancellationToken = default);
}

internal interface IReleaseMetadataPort
{
    ValueTask<ReleaseMetadata?> GetLatestAsync(CancellationToken cancellationToken = default);
}

internal interface IWordImageProvider
{
    ValueTask<WordImageMetadata?> GetForEntryAsync(string dictionaryId, string entryId, CancellationToken cancellationToken = default);
}

internal sealed class OfflineAccountIdentityPort : IAccountIdentityPort
{
    public ValueTask<AccountIdentity?> GetCurrentAsync(CancellationToken cancellationToken = default) => ValueTask.FromResult<AccountIdentity?>(null);
}

internal sealed class NoOpTelemetryPort : ITelemetryPort
{
    public ValueTask TrackAsync(ProductTelemetryEvent telemetryEvent, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(telemetryEvent);
        telemetryEvent.Validate();
        return ValueTask.CompletedTask;
    }
}

internal sealed class OfflineReleaseMetadataPort : IReleaseMetadataPort
{
    public ValueTask<ReleaseMetadata?> GetLatestAsync(CancellationToken cancellationToken = default) => ValueTask.FromResult<ReleaseMetadata?>(null);
}

internal sealed class OfflineWordImageProvider : IWordImageProvider
{
    public ValueTask<WordImageMetadata?> GetForEntryAsync(string dictionaryId, string entryId, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(dictionaryId);
        ArgumentException.ThrowIfNullOrWhiteSpace(entryId);
        return ValueTask.FromResult<WordImageMetadata?>(null);
    }
}

internal sealed record ProductOptionalPorts(
    IAccountIdentityPort Accounts,
    ITelemetryPort Telemetry,
    IReleaseMetadataPort Releases,
    IWordImageProvider Images)
{
    public static ProductOptionalPorts Offline { get; } = new(
        new OfflineAccountIdentityPort(),
        new NoOpTelemetryPort(),
        new OfflineReleaseMetadataPort(),
        new OfflineWordImageProvider());
}
