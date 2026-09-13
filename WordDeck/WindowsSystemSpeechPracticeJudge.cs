using System.Buffers.Binary;
using System.Globalization;
using System.Security.Cryptography;
using System.Speech.Recognition;
using System.Text;

namespace WordDeck;

/// <summary>
/// Raw recognition observation produced by the Windows in-process recognizer seam.
/// This is transcription confidence only. It is not pronunciation, assessment,
/// or mastery evidence.
/// </summary>
internal sealed record SpeechRecognitionObservation(
    bool Success,
    string RecognizedText,
    double Confidence,
    string ReasonCode)
{
    public static SpeechRecognitionObservation Fail(string reasonCode) =>
        new(false, string.Empty, 0, NormalizeReason(reasonCode));

    private static string NormalizeReason(string value) =>
        string.IsNullOrWhiteSpace(value) ? "SPEECH_NOT_RECOGNIZED" : value.Trim();
}

internal interface ISpeechRecognitionAdapter
{
    Task<SpeechRecognitionObservation> RecognizeAsync(
        ReadOnlyMemory<byte> waveAudio,
        CancellationToken cancellationToken);
}

/// <summary>
/// Local Windows System.Speech adapter. Learner audio is copied into an owned
/// in-memory WAV buffer only for the duration of recognition and is explicitly
/// zeroed afterwards. No path, network request, telemetry payload, or durable
/// audio store is created here.
/// </summary>
internal sealed class WindowsSystemSpeechRecognitionAdapter : ISpeechRecognitionAdapter
{
    public async Task<SpeechRecognitionObservation> RecognizeAsync(
        ReadOnlyMemory<byte> waveAudio,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();

        if (!OperatingSystem.IsWindows())
            return SpeechRecognitionObservation.Fail("SPEECH_RECOGNIZER_PLATFORM_UNSUPPORTED");
        if (waveAudio.IsEmpty)
            return SpeechRecognitionObservation.Fail("SPEECH_AUDIO_EMPTY");

        byte[] ownedWave = waveAudio.ToArray();
        try
        {
            using var stream = new MemoryStream(ownedWave, writable: false);
            return await RecognizeCoreAsync(stream, cancellationToken).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch (PlatformNotSupportedException)
        {
            return SpeechRecognitionObservation.Fail("SPEECH_RECOGNIZER_PLATFORM_UNSUPPORTED");
        }
        catch (InvalidOperationException)
        {
            return SpeechRecognitionObservation.Fail("SPEECH_RECOGNIZER_FAILURE");
        }
        catch (ArgumentException)
        {
            return SpeechRecognitionObservation.Fail("SPEECH_RECOGNIZER_FAILURE");
        }
        finally
        {
            CryptographicOperations.ZeroMemory(ownedWave);
        }
    }

    private static async Task<SpeechRecognitionObservation> RecognizeCoreAsync(
        Stream waveStream,
        CancellationToken cancellationToken)
    {
        RecognizerInfo? recognizerInfo = SelectEnglishRecognizer();
        if (recognizerInfo is null)
            return SpeechRecognitionObservation.Fail("SPEECH_RECOGNIZER_UNAVAILABLE");

        using var recognizer = new SpeechRecognitionEngine(recognizerInfo);
        recognizer.LoadGrammar(new DictationGrammar());
        recognizer.SetInputToWaveStream(waveStream);

        var completion = new TaskCompletionSource<SpeechRecognitionObservation>(
            TaskCreationOptions.RunContinuationsAsynchronously);

        EventHandler<RecognizeCompletedEventArgs>? handler = null;
        handler = (_, args) =>
        {
            if (args.Cancelled)
            {
                if (cancellationToken.IsCancellationRequested)
                    completion.TrySetCanceled(cancellationToken);
                else
                    completion.TrySetResult(SpeechRecognitionObservation.Fail("SPEECH_RECOGNIZER_CANCELLED"));
                return;
            }

            if (args.Error is not null)
            {
                completion.TrySetResult(SpeechRecognitionObservation.Fail("SPEECH_RECOGNIZER_FAILURE"));
                return;
            }

            RecognitionResult? result = args.Result;
            if (result is null || string.IsNullOrWhiteSpace(result.Text))
            {
                completion.TrySetResult(SpeechRecognitionObservation.Fail("SPEECH_NOT_RECOGNIZED"));
                return;
            }

            double confidence = Math.Clamp((double)result.Confidence, 0, 1);
            completion.TrySetResult(new SpeechRecognitionObservation(
                true,
                result.Text.Trim(),
                confidence,
                "SPEECH_RECOGNIZED"));
        };

        recognizer.RecognizeCompleted += handler;
        try
        {
            cancellationToken.ThrowIfCancellationRequested();
            using CancellationTokenRegistration registration = cancellationToken.Register(
                static state =>
                {
                    try
                    {
                        ((SpeechRecognitionEngine)state!).RecognizeAsyncCancel();
                    }
                    catch (InvalidOperationException)
                    {
                        // A completion/start race is resolved by the post-start
                        // cancellation check below or by the completion event.
                    }
                },
                recognizer);

            recognizer.RecognizeAsync();
            if (cancellationToken.IsCancellationRequested)
            {
                try
                {
                    recognizer.RecognizeAsyncCancel();
                }
                catch (InvalidOperationException)
                {
                    cancellationToken.ThrowIfCancellationRequested();
                }
            }

            return await completion.Task.ConfigureAwait(false);
        }
        finally
        {
            recognizer.RecognizeCompleted -= handler;
        }
    }

    private static RecognizerInfo? SelectEnglishRecognizer() =>
        SpeechRecognitionEngine
            .InstalledRecognizers()
            .Where(info => string.Equals(
                info.Culture.TwoLetterISOLanguageName,
                "en",
                StringComparison.OrdinalIgnoreCase))
            .OrderBy(info => CultureRank(info.Culture))
            .ThenBy(info => info.Culture.Name, StringComparer.OrdinalIgnoreCase)
            .ThenBy(info => info.Id, StringComparer.Ordinal)
            .FirstOrDefault();

    private static int CultureRank(CultureInfo culture) =>
        culture.Name switch
        {
            "en-GB" => 0,
            "en-US" => 1,
            _ => 2
        };
}

/// <summary>
/// Production local Speaking-practice judge for Windows.
///
/// The provider is intentionally NOT qualified for mastery, protected
/// assessment, or pronunciation judgement. It performs only speech-to-text
/// comparison for low-stakes Speaking practice. SpeechPracticeRuntime's
/// qualification firewall therefore suppresses its internal score from
/// mastery/adaptive evidence until a separate real-speaker acoustic validation
/// and independent qualification gate exists.
/// </summary>
internal sealed class WindowsSystemSpeechPracticeJudge : ISpeechJudge
{
    private const int MaxExpectedUtteranceCharacters = 512;
    private readonly ISpeechRecognitionAdapter _recognizer;

    public WindowsSystemSpeechPracticeJudge()
        : this(new WindowsSystemSpeechRecognitionAdapter())
    {
    }

    internal WindowsSystemSpeechPracticeJudge(ISpeechRecognitionAdapter recognizer)
    {
        _recognizer = recognizer ?? throw new ArgumentNullException(nameof(recognizer));
    }

    public SpeechProviderQualification Qualification { get; } = new(
        ProviderId: "windows-system-speech-practice-judge",
        ProviderVersion: "1.0",
        IsQualified: false,
        QualificationId: string.Empty,
        QualificationRevision: string.Empty,
        Capabilities: SpeechProviderCapabilities.SpeakingJudgement,
        RawAudioPolicy: SpeechRawAudioPolicy.EphemeralMemoryOnly);

    public async Task<SpeechJudgementResult> JudgeAsync(
        SpeechPracticeRequest request,
        ReadOnlyMemory<byte> audio,
        CancellationToken cancellationToken)
    {
        if (request is null || request.Binding is null || !request.Binding.IsValid)
            return SpeechJudgementResult.TechnicalFailure("INVALID_SPEECH_JUDGE_REQUEST");
        if (request.Mode != SpeechPracticeMode.Speaking)
            return SpeechJudgementResult.TechnicalFailure("PRONUNCIATION_JUDGEMENT_UNSUPPORTED");
        if (request.IsProtectedAssessment)
            return SpeechJudgementResult.TechnicalFailure("PROTECTED_ASSESSMENT_PROVIDER_UNQUALIFIED");
        if (string.IsNullOrWhiteSpace(request.ExpectedUtterance) ||
            request.ExpectedUtterance.Length > MaxExpectedUtteranceCharacters)
        {
            return SpeechJudgementResult.TechnicalFailure("EXPECTED_UTTERANCE_INVALID");
        }
        if (!IsCanonicalCaptureWave(audio.Span))
            return SpeechJudgementResult.TechnicalFailure("SPEECH_AUDIO_FORMAT_INVALID");

        cancellationToken.ThrowIfCancellationRequested();

        SpeechRecognitionObservation observation;
        try
        {
            observation = await _recognizer
                .RecognizeAsync(audio, cancellationToken)
                .ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            throw;
        }
        catch
        {
            return SpeechJudgementResult.TechnicalFailure("SPEECH_RECOGNIZER_FAILURE");
        }

        if (!observation.Success)
            return SpeechJudgementResult.TechnicalFailure(observation.ReasonCode);
        if (string.IsNullOrWhiteSpace(observation.RecognizedText) ||
            !double.IsFinite(observation.Confidence) ||
            observation.Confidence is < 0 or > 1)
        {
            return SpeechJudgementResult.TechnicalFailure("SPEECH_RECOGNIZER_RESULT_INVALID");
        }

        double score = ComputePracticeSimilarity(
            request.ExpectedUtterance,
            observation.RecognizedText,
            observation.Confidence);

        return new SpeechJudgementResult(
            TechnicalSuccess: true,
            ContentObjectId: request.Binding.ContentObjectId,
            TargetId: request.Binding.TargetId,
            MasteryEvidenceRecommended: false,
            Score: score,
            DeficitCodes: Array.Empty<string>(),
            ReasonCode: "SPEAKING_PRACTICE_RECOGNIZED");
    }

    internal static bool IsCanonicalCaptureWave(ReadOnlySpan<byte> wave)
    {
        const int headerBytes = 44;
        const uint expectedSampleRate = 16_000;
        const uint expectedByteRate = 32_000;
        const ushort expectedBlockAlign = 2;

        if (wave.Length < headerBytes)
            return false;
        if (!wave[..4].SequenceEqual("RIFF"u8) ||
            !wave.Slice(8, 4).SequenceEqual("WAVE"u8) ||
            !wave.Slice(12, 4).SequenceEqual("fmt "u8) ||
            !wave.Slice(36, 4).SequenceEqual("data"u8))
        {
            return false;
        }

        uint riffSize = BinaryPrimitives.ReadUInt32LittleEndian(wave.Slice(4, 4));
        uint formatChunkSize = BinaryPrimitives.ReadUInt32LittleEndian(wave.Slice(16, 4));
        ushort formatTag = BinaryPrimitives.ReadUInt16LittleEndian(wave.Slice(20, 2));
        ushort channels = BinaryPrimitives.ReadUInt16LittleEndian(wave.Slice(22, 2));
        uint sampleRate = BinaryPrimitives.ReadUInt32LittleEndian(wave.Slice(24, 4));
        uint byteRate = BinaryPrimitives.ReadUInt32LittleEndian(wave.Slice(28, 4));
        ushort blockAlign = BinaryPrimitives.ReadUInt16LittleEndian(wave.Slice(32, 2));
        ushort bitsPerSample = BinaryPrimitives.ReadUInt16LittleEndian(wave.Slice(34, 2));
        uint dataLength = BinaryPrimitives.ReadUInt32LittleEndian(wave.Slice(40, 4));

        return formatChunkSize == 16 &&
               formatTag == 1 &&
               channels == 1 &&
               sampleRate == expectedSampleRate &&
               byteRate == expectedByteRate &&
               blockAlign == expectedBlockAlign &&
               bitsPerSample == 16 &&
               dataLength > 0 &&
               dataLength == wave.Length - headerBytes &&
               riffSize == wave.Length - 8 &&
               dataLength % blockAlign == 0;
    }

    internal static double ComputePracticeSimilarity(
        string expected,
        string recognized,
        double recognitionConfidence)
    {
        string[] expectedTokens = NormalizeTokens(expected);
        string[] recognizedTokens = NormalizeTokens(recognized);
        if (expectedTokens.Length == 0 || recognizedTokens.Length == 0)
            return 0;

        int distance = TokenEditDistance(expectedTokens, recognizedTokens);
        int denominator = Math.Max(expectedTokens.Length, recognizedTokens.Length);
        double transcriptSimilarity = Math.Clamp(1.0 - ((double)distance / denominator), 0, 1);
        return Math.Round(
            transcriptSimilarity * Math.Clamp(recognitionConfidence, 0, 1),
            4,
            MidpointRounding.AwayFromZero);
    }

    private static string[] NormalizeTokens(string text)
    {
        string normalized = text.Normalize(NormalizationForm.FormKC).ToLowerInvariant();
        var builder = new StringBuilder(normalized.Length);
        foreach (char value in normalized)
        {
            if (char.IsLetterOrDigit(value))
                builder.Append(value);
            else if (value is '\'' or '\u2019')
                continue;
            else
                builder.Append(' ');
        }

        return builder
            .ToString()
            .Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
    }

    private static int TokenEditDistance(string[] left, string[] right)
    {
        var previous = new int[right.Length + 1];
        var current = new int[right.Length + 1];
        for (int column = 0; column <= right.Length; column++)
            previous[column] = column;

        for (int row = 1; row <= left.Length; row++)
        {
            current[0] = row;
            for (int column = 1; column <= right.Length; column++)
            {
                int substitutionCost = string.Equals(
                    left[row - 1],
                    right[column - 1],
                    StringComparison.Ordinal) ? 0 : 1;
                current[column] = Math.Min(
                    Math.Min(previous[column] + 1, current[column - 1] + 1),
                    previous[column - 1] + substitutionCost);
            }

            (previous, current) = (current, previous);
        }

        return previous[right.Length];
    }
}