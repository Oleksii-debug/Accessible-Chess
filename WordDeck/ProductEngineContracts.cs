namespace WordDeck;

// Product/application contracts intentionally contain no WinForms controls, focus state,
// coordinates, HWNDs, or online-service assumptions. Current WinForms can remain an adapter;
// future semantic web/Blazor surfaces can consume the same learning semantics.
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
internal sealed record SpellingCheckResult(
    bool Accepted,
    bool EmptySubmission,
    string NormalizedTyped,
    string NormalizedExpected,
    string Feedback);

internal sealed record CoachHistoryDto(
    int CompletedReviews,
    int FirstTrySuccesses,
    int WrongAttempts,
    int HintUses,
    int ShowAnswerUses,
    int CurrentStreak,
    IReadOnlyList<bool> RecentOutcomes)
{
    public void Validate()
    {
        if (CompletedReviews < 0 || FirstTrySuccesses < 0 || WrongAttempts < 0 || HintUses < 0 || ShowAnswerUses < 0 || CurrentStreak < 0)
            throw new InvalidDataException("Coach history contains negative statistics.");
        if (FirstTrySuccesses > CompletedReviews)
            throw new InvalidDataException("Coach history first-try successes exceed completed reviews.");
        if (ShowAnswerUses > HintUses)
            throw new InvalidDataException("Coach history show-answer count exceeds total hint uses.");
        if (CurrentStreak > CompletedReviews)
            throw new InvalidDataException("Coach history streak exceeds completed reviews.");
        if (RecentOutcomes is null)
            throw new InvalidDataException("Coach recent outcomes are missing.");
        if (RecentOutcomes.Count > 10)
            throw new InvalidDataException("Coach recent history exceeds the bounded ten-review window.");
    }

    internal SpellingEntryStats ToInternalStats()
    {
        Validate();
        return new SpellingEntryStats
        {
            CompletedReviews = CompletedReviews,
            FirstTrySuccesses = FirstTrySuccesses,
            WrongAttempts = WrongAttempts,
            HintUses = HintUses,
            ShowAnswerUses = ShowAnswerUses,
            CurrentStreak = CurrentStreak,
            RecentOutcomes = RecentOutcomes.ToList()
        };
    }
}

internal sealed record CoachDecisionDto(string? TargetDeckId, string Explanation);
internal sealed record SentenceCheckRequest(string RequiredEnglish, string TypedEnglish);
internal sealed record SentenceCheckResultDto(
    bool Accepted,
    bool WordOrderIgnored,
    IReadOnlyList<string> Missing,
    IReadOnlyList<string> Extra,
    IReadOnlyList<string> PossibleMisspellings,
    string Feedback);

internal interface ISpellingLearningUseCases
{
    SpellingCheckResult Check(SpellingCheckRequest request);
    CoachDecisionDto EvaluateCoach(string currentDeckId, CoachHistoryDto history, bool firstTryCorrect, bool usedHint);
}

internal interface ISentenceLearningUseCases
{
    SentenceCheckResultDto Check(SentenceCheckRequest request);
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
        bool empty = typed.Length == 0;
        bool accepted = !empty && string.Equals(typed, expected, StringComparison.Ordinal);
        string feedback = empty
            ? "Type the English answer before checking. A blank Enter must not count as a wrong learning attempt."
            : accepted
                ? "Correct spelling."
                : "Incorrect spelling. Keep the same card and try again.";
        return new SpellingCheckResult(accepted, empty, typed, expected, feedback);
    }

    public CoachDecisionDto EvaluateCoach(string currentDeckId, CoachHistoryDto history, bool firstTryCorrect, bool usedHint)
    {
        if (string.IsNullOrWhiteSpace(currentDeckId))
            throw new ArgumentException("Current spelling deck id is required.", nameof(currentDeckId));
        ArgumentNullException.ThrowIfNull(history);
        SpellingScheduleDecision decision = _scheduler.Decide(currentDeckId, history.ToInternalStats(), firstTryCorrect, usedHint);
        return new CoachDecisionDto(decision.TargetDeckId, decision.Explanation);
    }
}

internal sealed class SentenceLearningApplicationService : ISentenceLearningUseCases
{
    public SentenceCheckResultDto Check(SentenceCheckRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);
        if (string.IsNullOrWhiteSpace(request.TypedEnglish))
        {
            return new SentenceCheckResultDto(
                false,
                false,
                Array.Empty<string>(),
                Array.Empty<string>(),
                Array.Empty<string>(),
                "Type the required English forms before checking. A blank Enter must not count as a wrong learning attempt.");
        }

        SentenceAnswerResult result = SentenceAnswerEvaluator.Evaluate(request.RequiredEnglish, request.TypedEnglish);
        return new SentenceCheckResultDto(
            result.Accepted,
            result.WordOrderIgnored,
            result.Missing.ToArray(),
            result.Extra.ToArray(),
            result.PossibleMisspellings.ToArray(),
            result.Feedback);
    }
}

internal sealed record ProfileExportCommand(string DestinationPath);
internal sealed record ProfileImportCommand(string SourcePath);
internal sealed record ProfileTransferResultDto(
    int SourceSchemaVersion,
    bool RecallTransferred,
    bool SpellingTransferred,
    bool SentenceTransferred,
    IReadOnlyList<string> QuarantinedStableIds,
    string Status);

// Infrastructure owns actual LocalAppData/filesystem operations. This interface is the
// application boundary for current WinForms and any future presentation surface.
internal interface IProfileTransferPort
{
    ValueTask ExportAsync(ProfileExportCommand command, CancellationToken cancellationToken = default);
    ValueTask<ProfileTransferResultDto> ImportAsync(ProfileImportCommand command, CancellationToken cancellationToken = default);
}

internal sealed record SentencePackProductDescriptor(
    string PackId,
    string Provenance,
    string License,
    int SentenceCount,
    string SourceIdentity,
    string DerivativeIdentity,
    bool IsSynthetic)
{
    public void ValidateForRelease()
    {
        Require(PackId, nameof(PackId), 160);
        Require(Provenance, nameof(Provenance), 2048);
        Require(License, nameof(License), 160);
        RequireSha256Identity(SourceIdentity, nameof(SourceIdentity));
        RequireSha256Identity(DerivativeIdentity, nameof(DerivativeIdentity));
        if (SentenceCount <= 0)
            throw new InvalidDataException("SentencePack release descriptor must contain at least one sentence.");
        if (IsSynthetic)
            throw new InvalidDataException("Synthetic SentencePack data cannot be marked as a production release asset.");
    }

    private static void Require(string? value, string field, int maxLength)
    {
        if (string.IsNullOrWhiteSpace(value) || value.Length > maxLength)
            throw new InvalidDataException($"SentencePack release descriptor {field} is missing or too long.");
        if (!string.Equals(value, value.Trim(), StringComparison.Ordinal))
            throw new InvalidDataException($"SentencePack release descriptor {field} has outer whitespace.");
        SentenceTokenizer.ValidateUnicode(value, $"SentencePack release descriptor {field}");
    }

    private static void RequireSha256Identity(string? value, string field)
    {
        if (string.IsNullOrWhiteSpace(value) || !value.StartsWith("sha256:", StringComparison.Ordinal) || value.Length != 71)
            throw new InvalidDataException($"SentencePack release descriptor {field} must be a sha256 identity.");
        string hex = value[7..];
        if (hex.Any(ch => !Uri.IsHexDigit(ch)))
            throw new InvalidDataException($"SentencePack release descriptor {field} contains a malformed sha256 digest.");
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
        return string.Join(' ', normalized.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));
    }

    private static void Require(string? value, string field, int maxLength)
    {
        if (string.IsNullOrWhiteSpace(value))
            throw new InvalidDataException($"Image metadata {field} is required.");
        if (!string.Equals(value, value.Trim(), StringComparison.Ordinal))
            throw new InvalidDataException($"Image metadata {field} must not have outer whitespace.");
        if (value.Length > maxLength)
            throw new InvalidDataException($"Image metadata {field} is too long.");
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
        if (DurationMilliseconds is < 0)
            throw new InvalidDataException("Telemetry duration cannot be negative.");
        if (AggregateCount is < 0)
            throw new InvalidDataException("Telemetry aggregate count cannot be negative.");
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
    public ValueTask<AccountIdentity?> GetCurrentAsync(CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        return ValueTask.FromResult<AccountIdentity?>(null);
    }
}

internal sealed class NoOpTelemetryPort : ITelemetryPort
{
    public ValueTask TrackAsync(ProductTelemetryEvent telemetryEvent, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        ArgumentNullException.ThrowIfNull(telemetryEvent);
        telemetryEvent.Validate();
        return ValueTask.CompletedTask;
    }
}

internal sealed class OfflineReleaseMetadataPort : IReleaseMetadataPort
{
    public ValueTask<ReleaseMetadata?> GetLatestAsync(CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        return ValueTask.FromResult<ReleaseMetadata?>(null);
    }
}

internal sealed class OfflineWordImageProvider : IWordImageProvider
{
    public ValueTask<WordImageMetadata?> GetForEntryAsync(string dictionaryId, string entryId, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        if (string.IsNullOrWhiteSpace(dictionaryId))
            throw new ArgumentException("Dictionary id is required.", nameof(dictionaryId));
        if (string.IsNullOrWhiteSpace(entryId))
            throw new ArgumentException("Entry id is required.", nameof(entryId));
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
