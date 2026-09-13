using System.Buffers.Binary;

namespace WordDeck;

internal static class WindowsSystemSpeechPracticeJudgeSelfTest
{
    private static readonly SpeechPracticeBinding Binding = new(
        CourseId: "COMPLETE_ENGLISH",
        ModuleId: "CE-ST-M10",
        ContentObjectId: "CE-ST-M10-SPK0001",
        TargetId: "CE-ST-M10-TL0001",
        SourceRevision: "source-revision",
        IntegrationRecordId: "integration-record",
        IntegrationRevision: "integration-revision");

    public static void Run()
    {
        QualificationIsExplicitlyPracticeOnly();
        ExactSpeakingRecognitionReturnsBoundPracticeJudgement();
        TranscriptMismatchLowersOnlyInternalPracticeScore();
        PronunciationFailsClosedBeforeRecognizer();
        ProtectedAssessmentFailsClosedBeforeRecognizer();
        InvalidWaveFailsClosedBeforeRecognizer();
        RecognitionFailureRemainsTechnicalInvalid();
        RuntimeSuppressesUnqualifiedScoreAndAdaptiveEvidence();
        CancellationPropagatesAsCancellation();
        CanonicalWaveValidationRejectsHeaderDrift();
    }

    private static void QualificationIsExplicitlyPracticeOnly()
    {
        var judge = new WindowsSystemSpeechPracticeJudge(
            new FakeRecognizer(Success("Where is the station?", 0.91)));
        SpeechProviderQualification qualification = judge.Qualification;

        Assert(!qualification.IsQualified, "practice judge must remain unqualified");
        Assert(qualification.RawAudioPolicy == SpeechRawAudioPolicy.EphemeralMemoryOnly,
            "practice judge must be memory-only");
        Assert(qualification.Supports(SpeechProviderCapabilities.SpeakingJudgement),
            "practice judge should support Speaking judgement");
        Assert(!qualification.Supports(SpeechProviderCapabilities.PronunciationJudgement),
            "transcription must not be mislabeled as pronunciation judgement");
        Assert(!qualification.Supports(SpeechProviderCapabilities.ProtectedAssessment),
            "unqualified practice judge must not support protected assessment");
    }

    private static void ExactSpeakingRecognitionReturnsBoundPracticeJudgement()
    {
        var recognizer = new FakeRecognizer(Success("Where is the station?", 0.91));
        var judge = new WindowsSystemSpeechPracticeJudge(recognizer);
        SpeechJudgementResult result = Evaluate(judge, Request(), CanonicalWave());

        Assert(result.TechnicalSuccess, "exact recognition should be technically valid");
        Assert(result.ContentObjectId == Binding.ContentObjectId, "content binding must remain exact");
        Assert(result.TargetId == Binding.TargetId, "target binding must remain exact");
        Assert(!result.MasteryEvidenceRecommended, "practice transcription must never recommend mastery");
        Assert(result.Score == 0.91, "exact transcript should preserve recognition confidence as internal practice score");
        Assert(result.DeficitCodes.Count == 0, "practice transcription must not emit adaptive deficits");
        Assert(result.ReasonCode == "SPEAKING_PRACTICE_RECOGNIZED", "exact recognition reason code");
        Assert(recognizer.Calls == 1, "recognizer should run exactly once");
    }

    private static void TranscriptMismatchLowersOnlyInternalPracticeScore()
    {
        var recognizer = new FakeRecognizer(Success("Where station", 1.0));
        var judge = new WindowsSystemSpeechPracticeJudge(recognizer);
        SpeechJudgementResult result = Evaluate(judge, Request(), CanonicalWave());

        Assert(result.TechnicalSuccess, "different transcript can still be valid practice recognition");
        Assert(result.Score is > 0 and < 1, "transcript mismatch should lower internal practice similarity");
        Assert(!result.MasteryEvidenceRecommended, "mismatch must not create mastery evidence");
        Assert(result.DeficitCodes.Count == 0, "unqualified comparison must not route Deep Practice");
    }

    private static void PronunciationFailsClosedBeforeRecognizer()
    {
        var recognizer = new FakeRecognizer(Success("Where is the station?", 0.9));
        var judge = new WindowsSystemSpeechPracticeJudge(recognizer);
        SpeechJudgementResult result = Evaluate(
            judge,
            Request(mode: SpeechPracticeMode.Pronunciation),
            CanonicalWave());

        Assert(!result.TechnicalSuccess, "pronunciation must fail closed");
        Assert(result.ReasonCode == "PRONUNCIATION_JUDGEMENT_UNSUPPORTED", "pronunciation reason code");
        Assert(recognizer.Calls == 0, "unsupported pronunciation must not invoke transcription");
    }

    private static void ProtectedAssessmentFailsClosedBeforeRecognizer()
    {
        var recognizer = new FakeRecognizer(Success("Where is the station?", 0.9));
        var judge = new WindowsSystemSpeechPracticeJudge(recognizer);
        SpeechJudgementResult result = Evaluate(
            judge,
            Request(isProtectedAssessment: true),
            CanonicalWave());

        Assert(!result.TechnicalSuccess, "protected assessment must fail closed");
        Assert(result.ReasonCode == "PROTECTED_ASSESSMENT_PROVIDER_UNQUALIFIED", "protected assessment reason code");
        Assert(recognizer.Calls == 0, "protected assessment must not invoke unqualified transcription");
    }

    private static void InvalidWaveFailsClosedBeforeRecognizer()
    {
        var recognizer = new FakeRecognizer(Success("Where is the station?", 0.9));
        var judge = new WindowsSystemSpeechPracticeJudge(recognizer);
        SpeechJudgementResult result = Evaluate(judge, Request(), new byte[] { 1, 2, 3, 4 });

        Assert(!result.TechnicalSuccess, "invalid WAV must be technical invalid");
        Assert(result.ReasonCode == "SPEECH_AUDIO_FORMAT_INVALID", "invalid WAV reason code");
        Assert(recognizer.Calls == 0, "invalid audio must be rejected before recognizer");
    }

    private static void RecognitionFailureRemainsTechnicalInvalid()
    {
        var recognizer = new FakeRecognizer(
            SpeechRecognitionObservation.Fail("SPEECH_NOT_RECOGNIZED"));
        var judge = new WindowsSystemSpeechPracticeJudge(recognizer);
        SpeechJudgementResult result = Evaluate(judge, Request(), CanonicalWave());

        Assert(!result.TechnicalSuccess, "no recognition must not become a learner penalty");
        Assert(result.ReasonCode == "SPEECH_NOT_RECOGNIZED", "recognition failure reason code");
    }

    private static void RuntimeSuppressesUnqualifiedScoreAndAdaptiveEvidence()
    {
        byte[] wave = CanonicalWave();
        var capture = new FakeCapture(wave);
        var recognizer = new FakeRecognizer(Success("Where is the station?", 0.97));
        var judge = new WindowsSystemSpeechPracticeJudge(recognizer);
        var runtime = new SpeechPracticeRuntime(capture, judge);

        SpeechPracticeOutcome outcome = runtime
            .EvaluateAsync(Request())
            .GetAwaiter()
            .GetResult();

        Assert(outcome.Status == SpeechPracticeStatus.Completed, "recognized speech should complete practice");
        Assert(outcome.CountsAsPractice, "recognized speech should count as practice");
        Assert(!outcome.MasteryEligible, "unqualified practice judge must never create mastery");
        Assert(outcome.Score is null, "runtime must suppress unqualified internal practice score");
        Assert(outcome.DeficitCodes.Count == 0, "runtime must suppress unqualified adaptive evidence");
        Assert(outcome.ReasonCode == "PRACTICE_ONLY_PROVIDER_UNQUALIFIED", "runtime qualification firewall reason");
        Assert(capture.LastOwnedBuffer is not null && capture.LastOwnedBuffer.All(value => value == 0),
            "runtime must zero captured learner audio after judgement");
    }

    private static void CancellationPropagatesAsCancellation()
    {
        var recognizer = new FakeRecognizer(Success("Where is the station?", 0.9));
        var judge = new WindowsSystemSpeechPracticeJudge(recognizer);
        using var cancellation = new CancellationTokenSource();
        cancellation.Cancel();

        bool cancelled = false;
        try
        {
            judge.JudgeAsync(Request(), CanonicalWave(), cancellation.Token)
                .GetAwaiter()
                .GetResult();
        }
        catch (OperationCanceledException)
        {
            cancelled = true;
        }

        Assert(cancelled, "pre-cancelled judgement should propagate cancellation");
        Assert(recognizer.Calls == 0, "pre-cancelled judgement must not call recognizer");
    }

    private static void CanonicalWaveValidationRejectsHeaderDrift()
    {
        byte[] wave = CanonicalWave();
        Assert(WindowsSystemSpeechPracticeJudge.IsCanonicalCaptureWave(wave),
            "canonical 16 kHz mono 16-bit PCM WAV should be accepted");

        BinaryPrimitives.WriteUInt32LittleEndian(wave.AsSpan(24, 4), 44_100);
        Assert(!WindowsSystemSpeechPracticeJudge.IsCanonicalCaptureWave(wave),
            "sample-rate drift must fail closed");
    }

    private static SpeechJudgementResult Evaluate(
        WindowsSystemSpeechPracticeJudge judge,
        SpeechPracticeRequest request,
        byte[] wave) =>
        judge.JudgeAsync(request, wave, CancellationToken.None)
            .GetAwaiter()
            .GetResult();

    private static SpeechPracticeRequest Request(
        SpeechPracticeMode mode = SpeechPracticeMode.Speaking,
        bool isProtectedAssessment = false) =>
        new(
            Binding,
            mode,
            SpeechSubmissionKind.Microphone,
            "Where is the station?",
            isProtectedAssessment);

    private static SpeechRecognitionObservation Success(string transcript, double confidence) =>
        new(true, transcript, confidence, "SPEECH_RECOGNIZED");

    private static byte[] CanonicalWave()
    {
        byte[] wave = new byte[48];
        "RIFF"u8.CopyTo(wave.AsSpan(0, 4));
        BinaryPrimitives.WriteUInt32LittleEndian(wave.AsSpan(4, 4), 40);
        "WAVE"u8.CopyTo(wave.AsSpan(8, 4));
        "fmt "u8.CopyTo(wave.AsSpan(12, 4));
        BinaryPrimitives.WriteUInt32LittleEndian(wave.AsSpan(16, 4), 16);
        BinaryPrimitives.WriteUInt16LittleEndian(wave.AsSpan(20, 2), 1);
        BinaryPrimitives.WriteUInt16LittleEndian(wave.AsSpan(22, 2), 1);
        BinaryPrimitives.WriteUInt32LittleEndian(wave.AsSpan(24, 4), 16_000);
        BinaryPrimitives.WriteUInt32LittleEndian(wave.AsSpan(28, 4), 32_000);
        BinaryPrimitives.WriteUInt16LittleEndian(wave.AsSpan(32, 2), 2);
        BinaryPrimitives.WriteUInt16LittleEndian(wave.AsSpan(34, 2), 16);
        "data"u8.CopyTo(wave.AsSpan(36, 4));
        BinaryPrimitives.WriteUInt32LittleEndian(wave.AsSpan(40, 4), 4);
        wave[44] = 1;
        wave[45] = 2;
        wave[46] = 3;
        wave[47] = 4;
        return wave;
    }

    private static void Assert(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException($"WindowsSystemSpeechPracticeJudgeSelfTest failed: {message}.");
    }

    private sealed class FakeRecognizer : ISpeechRecognitionAdapter
    {
        private readonly SpeechRecognitionObservation _observation;

        public FakeRecognizer(SpeechRecognitionObservation observation)
        {
            _observation = observation;
        }

        public int Calls { get; private set; }

        public Task<SpeechRecognitionObservation> RecognizeAsync(
            ReadOnlyMemory<byte> waveAudio,
            CancellationToken cancellationToken)
        {
            Calls++;
            cancellationToken.ThrowIfCancellationRequested();
            if (waveAudio.IsEmpty)
                throw new InvalidOperationException("Fake recognizer received empty audio.");
            return Task.FromResult(_observation);
        }
    }

    private sealed class FakeCapture : ISpeechCaptureProvider
    {
        private readonly byte[] _wave;

        public FakeCapture(byte[] wave)
        {
            _wave = wave.ToArray();
        }

        public SpeechProviderQualification Qualification { get; } = new(
            ProviderId: "test-unqualified-capture",
            ProviderVersion: "1.0",
            IsQualified: false,
            QualificationId: string.Empty,
            QualificationRevision: string.Empty,
            Capabilities: SpeechProviderCapabilities.Capture,
            RawAudioPolicy: SpeechRawAudioPolicy.EphemeralMemoryOnly);

        public byte[]? LastOwnedBuffer { get; private set; }

        public Task<SpeechCaptureResult> CaptureAsync(
            SpeechPracticeRequest request,
            CancellationToken cancellationToken)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var sample = new SpeechCaptureSample(_wave);
            LastOwnedBuffer = sample.DangerousBufferForSelfTest();
            return Task.FromResult(SpeechCaptureResult.Ok(sample));
        }
    }
}