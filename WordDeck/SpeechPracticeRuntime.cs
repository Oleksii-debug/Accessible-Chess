using System.Security.Cryptography;
using System.Text.RegularExpressions;

namespace WordDeck;

[Flags]
internal enum SpeechProviderCapabilities
{
    None = 0,
    Capture = 1 << 0,
    SpeakingJudgement = 1 << 1,
    PronunciationJudgement = 1 << 2,
    ProtectedAssessment = 1 << 3
}

internal enum SpeechRawAudioPolicy
{
    EphemeralMemoryOnly,
    ProviderMayPersist
}

internal enum SpeechPracticeMode
{
    Speaking,
    Pronunciation
}

internal enum SpeechSubmissionKind
{
    Microphone,
    TypedFallback
}

internal enum SpeechPracticeStatus
{
    Completed,
    TechnicalInvalid,
    Cancelled
}

/// <summary>
/// Qualification evidence is deliberately explicit and fail-closed. A provider
/// cannot create mastery-eligible speech evidence merely by returning a score.
/// </summary>
internal sealed record SpeechProviderQualification(
    string ProviderId,
    string ProviderVersion,
    bool IsQualified,
    string QualificationId,
    string QualificationRevision,
    SpeechProviderCapabilities Capabilities,
    SpeechRawAudioPolicy RawAudioPolicy)
{
    public bool HasDocumentedQualification =>
        IsQualified &&
        !string.IsNullOrWhiteSpace(ProviderId) &&
        !string.IsNullOrWhiteSpace(ProviderVersion) &&
        !string.IsNullOrWhiteSpace(QualificationId) &&
        !string.IsNullOrWhiteSpace(QualificationRevision);

    public bool Supports(SpeechProviderCapabilities required) =>
        (Capabilities & required) == required;
}

/// <summary>
/// Exact governed-content binding. Runtime speech evidence is valid only for
/// the exact content object, target and authority revisions supplied here.
/// </summary>
internal sealed record SpeechPracticeBinding(
    string CourseId,
    string ModuleId,
    string ContentObjectId,
    string TargetId,
    string SourceRevision,
    string IntegrationRecordId,
    string IntegrationRevision)
{
    public bool IsValid =>
        !string.IsNullOrWhiteSpace(CourseId) &&
        !string.IsNullOrWhiteSpace(ModuleId) &&
        !string.IsNullOrWhiteSpace(ContentObjectId) &&
        !string.IsNullOrWhiteSpace(TargetId) &&
        !string.IsNullOrWhiteSpace(SourceRevision) &&
        !string.IsNullOrWhiteSpace(IntegrationRecordId) &&
        !string.IsNullOrWhiteSpace(IntegrationRevision);
}

internal sealed record SpeechPracticeRequest(
    SpeechPracticeBinding Binding,
    SpeechPracticeMode Mode,
    SpeechSubmissionKind SubmissionKind,
    string ExpectedUtterance,
    bool IsProtectedAssessment);

/// <summary>
/// In-memory audio only. The runtime has no path/file persistence surface and
/// zeroes the owned buffer when evaluation ends.
/// </summary>
internal sealed class SpeechCaptureSample : IDisposable
{
    private byte[]? _buffer;

    public SpeechCaptureSample(ReadOnlySpan<byte> audio)
    {
        if (audio.IsEmpty)
            throw new ArgumentException("Captured audio must not be empty.", nameof(audio));
        _buffer = audio.ToArray();
    }

    public ReadOnlyMemory<byte> Audio => _buffer ?? ReadOnlyMemory<byte>.Empty;

    internal byte[] DangerousBufferForSelfTest() =>
        _buffer ?? Array.Empty<byte>();

    public void Dispose()
    {
        byte[]? buffer = Interlocked.Exchange(ref _buffer, null);
        if (buffer is not null)
            CryptographicOperations.ZeroMemory(buffer);
    }
}

internal sealed record SpeechCaptureResult(
    bool Success,
    SpeechCaptureSample? Sample,
    string ReasonCode)
{
    public static SpeechCaptureResult Ok(SpeechCaptureSample sample) =>
        new(true, sample ?? throw new ArgumentNullException(nameof(sample)), "CAPTURE_OK");

    public static SpeechCaptureResult Fail(string reasonCode) =>
        new(false, null, NormalizeReason(reasonCode, "CAPTURE_FAILED"));

    private static string NormalizeReason(string value, string fallback) =>
        string.IsNullOrWhiteSpace(value) ? fallback : value.Trim();
}

internal sealed record SpeechJudgementResult(
    bool TechnicalSuccess,
    string ContentObjectId,
    string TargetId,
    bool MasteryEvidenceRecommended,
    double? Score,
    IReadOnlyList<string> DeficitCodes,
    string ReasonCode)
{
    public static SpeechJudgementResult TechnicalFailure(string reasonCode) =>
        new(false, string.Empty, string.Empty, false, null, Array.Empty<string>(),
            string.IsNullOrWhiteSpace(reasonCode) ? "JUDGE_FAILED" : reasonCode.Trim());
}

internal interface ISpeechCaptureProvider
{
    SpeechProviderQualification Qualification { get; }
    Task<SpeechCaptureResult> CaptureAsync(
        SpeechPracticeRequest request,
        CancellationToken cancellationToken);
}

internal interface ISpeechJudge
{
    SpeechProviderQualification Qualification { get; }
    Task<SpeechJudgementResult> JudgeAsync(
        SpeechPracticeRequest request,
        ReadOnlyMemory<byte> audio,
        CancellationToken cancellationToken);
}

internal sealed record SpeechPracticeOutcome(
    SpeechPracticeStatus Status,
    bool CountsAsPractice,
    bool MasteryEligible,
    double? Score,
    IReadOnlyList<string> DeficitCodes,
    string ReasonCode)
{
    public static SpeechPracticeOutcome TechnicalInvalid(string reasonCode) =>
        new(SpeechPracticeStatus.TechnicalInvalid, false, false, null,
            Array.Empty<string>(), reasonCode);

    public static SpeechPracticeOutcome Cancelled() =>
        new(SpeechPracticeStatus.Cancelled, false, false, null,
            Array.Empty<string>(), "CANCELLED");

    public static SpeechPracticeOutcome Completed(
        bool masteryEligible,
        double? score,
        IReadOnlyList<string> deficitCodes,
        string reasonCode) =>
        new(SpeechPracticeStatus.Completed, true, masteryEligible, score,
            deficitCodes, reasonCode);
}

/// <summary>
/// Orchestrates microphone speech practice without confusing exposure with
/// mastery. Technical failures never penalize the learner. Typed fallback and
/// unqualified providers remain practice-only. Protected assessment never
/// silently downgrades to an unqualified provider.
/// </summary>
internal sealed class SpeechPracticeRuntime
{
    private static readonly Regex DeficitCodePattern = new(
        "^[A-Z0-9][A-Z0-9._-]{0,63}$",
        RegexOptions.CultureInvariant | RegexOptions.Compiled);

    private readonly ISpeechCaptureProvider _capture;
    private readonly ISpeechJudge _judge;

    public SpeechPracticeRuntime(ISpeechCaptureProvider capture, ISpeechJudge judge)
    {
        _capture = capture ?? throw new ArgumentNullException(nameof(capture));
        _judge = judge ?? throw new ArgumentNullException(nameof(judge));
    }

    public async Task<SpeechPracticeOutcome> EvaluateAsync(
        SpeechPracticeRequest request,
        CancellationToken cancellationToken = default)
    {
        if (!IsValidRequest(request))
            return SpeechPracticeOutcome.TechnicalInvalid("INVALID_REQUEST_BINDING");

        if (cancellationToken.IsCancellationRequested)
            return SpeechPracticeOutcome.Cancelled();

        if (request.SubmissionKind == SpeechSubmissionKind.TypedFallback)
        {
            return SpeechPracticeOutcome.Completed(
                masteryEligible: false,
                score: null,
                deficitCodes: Array.Empty<string>(),
                reasonCode: "TYPED_FALLBACK_PRACTICE_ONLY");
        }

        SpeechProviderQualification captureQualification = _capture.Qualification;
        SpeechProviderQualification judgeQualification = _judge.Qualification;

        if (captureQualification.RawAudioPolicy != SpeechRawAudioPolicy.EphemeralMemoryOnly)
            return SpeechPracticeOutcome.TechnicalInvalid("RAW_AUDIO_RETENTION_NOT_AUTHORIZED");

        bool providersQualifiedForEvidence =
            captureQualification.HasDocumentedQualification &&
            captureQualification.Supports(SpeechProviderCapabilities.Capture) &&
            judgeQualification.HasDocumentedQualification &&
            judgeQualification.Supports(RequiredJudgementCapability(request.Mode));

        if (request.IsProtectedAssessment &&
            (!providersQualifiedForEvidence ||
             !captureQualification.Supports(SpeechProviderCapabilities.ProtectedAssessment) ||
             !judgeQualification.Supports(SpeechProviderCapabilities.ProtectedAssessment)))
        {
            return SpeechPracticeOutcome.TechnicalInvalid("PROTECTED_ASSESSMENT_PROVIDER_UNQUALIFIED");
        }

        SpeechCaptureResult captureResult;
        try
        {
            captureResult = await _capture.CaptureAsync(request, cancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            return SpeechPracticeOutcome.Cancelled();
        }
        catch
        {
            return SpeechPracticeOutcome.TechnicalInvalid("CAPTURE_EXCEPTION");
        }

        if (!captureResult.Success || captureResult.Sample is null)
        {
            captureResult.Sample?.Dispose();
            return SpeechPracticeOutcome.TechnicalInvalid(
                string.IsNullOrWhiteSpace(captureResult.ReasonCode)
                    ? "CAPTURE_FAILED"
                    : captureResult.ReasonCode);
        }

        using SpeechCaptureSample sample = captureResult.Sample;
        if (sample.Audio.IsEmpty)
            return SpeechPracticeOutcome.TechnicalInvalid("CAPTURE_EMPTY");

        SpeechJudgementResult judgement;
        try
        {
            judgement = await _judge
                .JudgeAsync(request, sample.Audio, cancellationToken)
                .ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            return SpeechPracticeOutcome.Cancelled();
        }
        catch
        {
            return SpeechPracticeOutcome.TechnicalInvalid("JUDGE_EXCEPTION");
        }

        if (!judgement.TechnicalSuccess)
        {
            return SpeechPracticeOutcome.TechnicalInvalid(
                string.IsNullOrWhiteSpace(judgement.ReasonCode)
                    ? "JUDGE_FAILED"
                    : judgement.ReasonCode);
        }

        if (!string.Equals(judgement.ContentObjectId, request.Binding.ContentObjectId, StringComparison.Ordinal) ||
            !string.Equals(judgement.TargetId, request.Binding.TargetId, StringComparison.Ordinal))
        {
            return SpeechPracticeOutcome.TechnicalInvalid("JUDGE_TARGET_MISMATCH");
        }

        if (judgement.Score is < 0 or > 1 || double.IsNaN(judgement.Score ?? 0))
            return SpeechPracticeOutcome.TechnicalInvalid("JUDGE_SCORE_INVALID");

        if (!TryNormalizeDeficitCodes(judgement.DeficitCodes, out IReadOnlyList<string> deficits))
            return SpeechPracticeOutcome.TechnicalInvalid("JUDGE_DEFICIT_CODE_INVALID");

        if (!providersQualifiedForEvidence)
        {
            return SpeechPracticeOutcome.Completed(
                masteryEligible: false,
                score: null,
                deficitCodes: Array.Empty<string>(),
                reasonCode: "PRACTICE_ONLY_PROVIDER_UNQUALIFIED");
        }

        return SpeechPracticeOutcome.Completed(
            masteryEligible: judgement.MasteryEvidenceRecommended,
            score: judgement.Score,
            deficitCodes: deficits,
            reasonCode: judgement.MasteryEvidenceRecommended
                ? "QUALIFIED_EVIDENCE_MASTERY_ELIGIBLE"
                : "QUALIFIED_EVIDENCE_PRACTICE_ONLY");
    }

    private static bool IsValidRequest(SpeechPracticeRequest? request) =>
        request is not null &&
        request.Binding is not null &&
        request.Binding.IsValid &&
        !string.IsNullOrWhiteSpace(request.ExpectedUtterance);

    private static SpeechProviderCapabilities RequiredJudgementCapability(SpeechPracticeMode mode) =>
        mode switch
        {
            SpeechPracticeMode.Speaking => SpeechProviderCapabilities.SpeakingJudgement,
            SpeechPracticeMode.Pronunciation => SpeechProviderCapabilities.PronunciationJudgement,
            _ => SpeechProviderCapabilities.None
        };

    private static bool TryNormalizeDeficitCodes(
        IReadOnlyList<string>? raw,
        out IReadOnlyList<string> normalized)
    {
        var values = new SortedSet<string>(StringComparer.Ordinal);
        foreach (string value in raw ?? Array.Empty<string>())
        {
            string code = (value ?? string.Empty).Trim().ToUpperInvariant();
            if (!DeficitCodePattern.IsMatch(code))
            {
                normalized = Array.Empty<string>();
                return false;
            }
            values.Add(code);
        }

        normalized = values.ToArray();
        return true;
    }
}
