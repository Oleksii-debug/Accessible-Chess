namespace WordDeck;

internal static class SpeechPracticeRuntimeSelfTest
{
    private static readonly SpeechPracticeBinding Binding = new(
        CourseId: "COMPLETE_ENGLISH",
        ModuleId: "CE-ST-RH03",
        ContentObjectId: "CE-ST-RH03-SPK0001",
        TargetId: "CE-ST-RH03-TL0001",
        SourceRevision: "source-revision",
        IntegrationRecordId: "integration-record",
        IntegrationRevision: "integration-revision");

    public static void Run()
    {
        TypedFallbackNeverCreatesMasteryOrCallsProviders();
        CaptureFailureIsTechnicalInvalid();
        JudgeFailureIsTechnicalInvalidAndAudioIsZeroed();
        UnqualifiedJudgeCannotCreateMasteryOrAdaptiveDeficits();
        QualifiedEvidenceCanBecomeMasteryEligible();
        QualifiedDeficitsRemainExactAndDeterministic();
        TargetMismatchFailsClosed();
        RawPersistencePolicyFailsBeforeCapture();
        ProtectedAssessmentRequiresExplicitQualification();
        CancellationIsSafeAndNonPenalizing();
        InvalidDeficitCodeFailsClosed();
    }

    private static void TypedFallbackNeverCreatesMasteryOrCallsProviders()
    {
        var capture = new FakeCaptureProvider(UnqualifiedCapture());
        var judge = new FakeJudge(UnqualifiedJudge(), GoodJudgement(mastery: true));
        SpeechPracticeOutcome outcome = Evaluate(
            capture,
            judge,
            Request(SpeechSubmissionKind.TypedFallback));

        Assert(outcome.Status == SpeechPracticeStatus.Completed, "typed fallback status");
        Assert(outcome.CountsAsPractice, "typed fallback should remain practice");
        Assert(!outcome.MasteryEligible, "typed fallback must not create mastery evidence");
        Assert(outcome.Score is null, "typed fallback must not expose a mastery score");
        Assert(outcome.DeficitCodes.Count == 0, "typed fallback must not route deficits");
        Assert(capture.Calls == 0 && judge.Calls == 0, "typed fallback must not call speech providers");
    }

    private static void CaptureFailureIsTechnicalInvalid()
    {
        var capture = new FakeCaptureProvider(QualifiedCapture(), failureCode: "MICROPHONE_UNAVAILABLE");
        var judge = new FakeJudge(QualifiedJudge(), GoodJudgement(mastery: true));
        SpeechPracticeOutcome outcome = Evaluate(capture, judge, Request());

        Assert(outcome.Status == SpeechPracticeStatus.TechnicalInvalid, "capture failure status");
        Assert(!outcome.CountsAsPractice && !outcome.MasteryEligible, "capture failure must be non-penalizing");
        Assert(judge.Calls == 0, "judge must not run after capture failure");
    }

    private static void JudgeFailureIsTechnicalInvalidAndAudioIsZeroed()
    {
        var capture = new FakeCaptureProvider(QualifiedCapture());
        var judge = new FakeJudge(QualifiedJudge(), SpeechJudgementResult.TechnicalFailure("JUDGE_OFFLINE"));
        SpeechPracticeOutcome outcome = Evaluate(capture, judge, Request());

        Assert(outcome.Status == SpeechPracticeStatus.TechnicalInvalid, "judge failure status");
        Assert(!outcome.CountsAsPractice && !outcome.MasteryEligible, "judge failure must be non-penalizing");
        Assert(capture.LastOwnedBuffer is not null, "test capture buffer should exist");
        Assert(capture.LastOwnedBuffer!.All(value => value == 0), "runtime must zero captured audio after judgement");
    }

    private static void UnqualifiedJudgeCannotCreateMasteryOrAdaptiveDeficits()
    {
        var capture = new FakeCaptureProvider(QualifiedCapture());
        var judge = new FakeJudge(
            UnqualifiedJudge(),
            GoodJudgement(mastery: true, score: 0.99, deficits: new[] { "PLACE-PREP" }));
        SpeechPracticeOutcome outcome = Evaluate(capture, judge, Request());

        Assert(outcome.Status == SpeechPracticeStatus.Completed, "unqualified practice status");
        Assert(outcome.CountsAsPractice, "successful unqualified speech may count only as practice");
        Assert(!outcome.MasteryEligible, "unqualified judge must not create mastery evidence");
        Assert(outcome.Score is null, "unqualified score must not be surfaced as qualified evidence");
        Assert(outcome.DeficitCodes.Count == 0, "unqualified judge must not drive Deep Practice");
        Assert(outcome.ReasonCode == "PRACTICE_ONLY_PROVIDER_UNQUALIFIED", "unqualified reason code");
    }

    private static void QualifiedEvidenceCanBecomeMasteryEligible()
    {
        var capture = new FakeCaptureProvider(QualifiedCapture());
        var judge = new FakeJudge(QualifiedJudge(), GoodJudgement(mastery: true, score: 0.91));
        SpeechPracticeOutcome outcome = Evaluate(capture, judge, Request());

        Assert(outcome.Status == SpeechPracticeStatus.Completed, "qualified status");
        Assert(outcome.CountsAsPractice, "qualified result also counts as completed practice");
        Assert(outcome.MasteryEligible, "qualified exact evidence may become mastery-eligible");
        Assert(outcome.Score == 0.91, "qualified score should survive");
        Assert(outcome.DeficitCodes.Count == 0, "clean qualified result should have no deficits");
    }

    private static void QualifiedDeficitsRemainExactAndDeterministic()
    {
        var capture = new FakeCaptureProvider(QualifiedCapture());
        var judge = new FakeJudge(
            QualifiedJudge(),
            GoodJudgement(
                mastery: false,
                score: 0.54,
                deficits: new[] { "place-prep", "ARTICLE", "PLACE-PREP" }));
        SpeechPracticeOutcome outcome = Evaluate(capture, judge, Request());

        Assert(!outcome.MasteryEligible, "deficit result should not imply mastery");
        Assert(outcome.DeficitCodes.SequenceEqual(new[] { "ARTICLE", "PLACE-PREP" }),
            "qualified deficits must be normalized, deduplicated and deterministic");
    }

    private static void TargetMismatchFailsClosed()
    {
        var capture = new FakeCaptureProvider(QualifiedCapture());
        var judge = new FakeJudge(
            QualifiedJudge(),
            new SpeechJudgementResult(
                true,
                "CE-ST-RH03-SPK9999",
                Binding.TargetId,
                true,
                0.95,
                Array.Empty<string>(),
                "OK"));
        SpeechPracticeOutcome outcome = Evaluate(capture, judge, Request());

        Assert(outcome.Status == SpeechPracticeStatus.TechnicalInvalid, "target mismatch status");
        Assert(!outcome.CountsAsPractice && !outcome.MasteryEligible, "target mismatch must fail closed");
    }

    private static void RawPersistencePolicyFailsBeforeCapture()
    {
        SpeechProviderQualification unsafeCapture = QualifiedCapture() with
        {
            RawAudioPolicy = SpeechRawAudioPolicy.ProviderMayPersist
        };
        var capture = new FakeCaptureProvider(unsafeCapture);
        var judge = new FakeJudge(QualifiedJudge(), GoodJudgement(mastery: true));
        SpeechPracticeOutcome outcome = Evaluate(capture, judge, Request());

        Assert(outcome.Status == SpeechPracticeStatus.TechnicalInvalid, "raw persistence policy status");
        Assert(outcome.ReasonCode == "RAW_AUDIO_RETENTION_NOT_AUTHORIZED", "raw persistence reason");
        Assert(capture.Calls == 0 && judge.Calls == 0, "unsafe capture must be rejected before learner audio is acquired");
    }

    private static void ProtectedAssessmentRequiresExplicitQualification()
    {
        var capture = new FakeCaptureProvider(QualifiedCapture());
        var judge = new FakeJudge(QualifiedJudge(), GoodJudgement(mastery: true));
        SpeechPracticeOutcome outcome = Evaluate(
            capture,
            judge,
            Request(isProtectedAssessment: true));

        Assert(outcome.Status == SpeechPracticeStatus.TechnicalInvalid, "protected assessment qualification status");
        Assert(outcome.ReasonCode == "PROTECTED_ASSESSMENT_PROVIDER_UNQUALIFIED", "protected assessment reason");
        Assert(capture.Calls == 0 && judge.Calls == 0, "protected assessment must not silently downgrade to practice");
    }

    private static void CancellationIsSafeAndNonPenalizing()
    {
        var capture = new FakeCaptureProvider(QualifiedCapture());
        var judge = new FakeJudge(QualifiedJudge(), GoodJudgement(mastery: true));
        using var cancellation = new CancellationTokenSource();
        cancellation.Cancel();
        SpeechPracticeOutcome outcome = new SpeechPracticeRuntime(capture, judge)
            .EvaluateAsync(Request(), cancellation.Token)
            .GetAwaiter()
            .GetResult();

        Assert(outcome.Status == SpeechPracticeStatus.Cancelled, "cancelled status");
        Assert(!outcome.CountsAsPractice && !outcome.MasteryEligible, "cancelled attempt must be non-penalizing");
        Assert(capture.Calls == 0 && judge.Calls == 0, "pre-cancelled request must not call providers");
    }

    private static void InvalidDeficitCodeFailsClosed()
    {
        var capture = new FakeCaptureProvider(QualifiedCapture());
        var judge = new FakeJudge(
            QualifiedJudge(),
            GoodJudgement(mastery: false, deficits: new[] { "valid-code", "bad code" }));
        SpeechPracticeOutcome outcome = Evaluate(capture, judge, Request());

        Assert(outcome.Status == SpeechPracticeStatus.TechnicalInvalid, "invalid deficit code status");
        Assert(outcome.DeficitCodes.Count == 0, "invalid deficit code must not route adaptive work");
    }

    private static SpeechPracticeOutcome Evaluate(
        FakeCaptureProvider capture,
        FakeJudge judge,
        SpeechPracticeRequest request) =>
        new SpeechPracticeRuntime(capture, judge)
            .EvaluateAsync(request)
            .GetAwaiter()
            .GetResult();

    private static SpeechPracticeRequest Request(
        SpeechSubmissionKind submissionKind = SpeechSubmissionKind.Microphone,
        bool isProtectedAssessment = false) =>
        new(
            Binding,
            SpeechPracticeMode.Speaking,
            submissionKind,
            "Where is the station?",
            isProtectedAssessment);

    private static SpeechJudgementResult GoodJudgement(
        bool mastery,
        double? score = 0.90,
        IReadOnlyList<string>? deficits = null) =>
        new(
            true,
            Binding.ContentObjectId,
            Binding.TargetId,
            mastery,
            score,
            deficits ?? Array.Empty<string>(),
            "OK");

    private static SpeechProviderQualification QualifiedCapture() =>
        new(
            "test-capture",
            "1.0",
            true,
            "CAPTURE-QUAL-001",
            "rev-1",
            SpeechProviderCapabilities.Capture,
            SpeechRawAudioPolicy.EphemeralMemoryOnly);

    private static SpeechProviderQualification UnqualifiedCapture() =>
        QualifiedCapture() with
        {
            IsQualified = false,
            QualificationId = string.Empty,
            QualificationRevision = string.Empty
        };

    private static SpeechProviderQualification QualifiedJudge() =>
        new(
            "test-judge",
            "1.0",
            true,
            "JUDGE-QUAL-001",
            "rev-1",
            SpeechProviderCapabilities.SpeakingJudgement | SpeechProviderCapabilities.PronunciationJudgement,
            SpeechRawAudioPolicy.EphemeralMemoryOnly);

    private static SpeechProviderQualification UnqualifiedJudge() =>
        QualifiedJudge() with
        {
            IsQualified = false,
            QualificationId = string.Empty,
            QualificationRevision = string.Empty
        };

    private static void Assert(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException($"SpeechPracticeRuntimeSelfTest failed: {message}.");
    }

    private sealed class FakeCaptureProvider : ISpeechCaptureProvider
    {
        private readonly string? _failureCode;

        public FakeCaptureProvider(
            SpeechProviderQualification qualification,
            string? failureCode = null)
        {
            Qualification = qualification;
            _failureCode = failureCode;
        }

        public SpeechProviderQualification Qualification { get; }
        public int Calls { get; private set; }
        public byte[]? LastOwnedBuffer { get; private set; }

        public Task<SpeechCaptureResult> CaptureAsync(
            SpeechPracticeRequest request,
            CancellationToken cancellationToken)
        {
            Calls++;
            cancellationToken.ThrowIfCancellationRequested();
            if (_failureCode is not null)
                return Task.FromResult(SpeechCaptureResult.Fail(_failureCode));

            var sample = new SpeechCaptureSample(new byte[] { 11, 22, 33, 44, 55, 66 });
            LastOwnedBuffer = sample.DangerousBufferForSelfTest();
            return Task.FromResult(SpeechCaptureResult.Ok(sample));
        }
    }

    private sealed class FakeJudge : ISpeechJudge
    {
        private readonly SpeechJudgementResult _result;

        public FakeJudge(
            SpeechProviderQualification qualification,
            SpeechJudgementResult result)
        {
            Qualification = qualification;
            _result = result;
        }

        public SpeechProviderQualification Qualification { get; }
        public int Calls { get; private set; }

        public Task<SpeechJudgementResult> JudgeAsync(
            SpeechPracticeRequest request,
            ReadOnlyMemory<byte> audio,
            CancellationToken cancellationToken)
        {
            Calls++;
            cancellationToken.ThrowIfCancellationRequested();
            if (audio.IsEmpty)
                throw new InvalidOperationException("Fake judge received empty audio.");
            return Task.FromResult(_result);
        }
    }
}
