using System.Buffers.Binary;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace WordDeck;

internal static class WindowsMicrophoneCaptureProviderSelfTest
{
    private static readonly SpeechPracticeRequest MicrophoneRequest = new(
        new SpeechPracticeBinding(
            CourseId: "COMPLETE_ENGLISH",
            ModuleId: "CE-ST-RH03",
            ContentObjectId: "CE-ST-RH03-SPK0001",
            TargetId: "CE-ST-RH03-TL0001",
            SourceRevision: "source-revision",
            IntegrationRecordId: "integration-record",
            IntegrationRevision: "integration-revision"),
        SpeechPracticeMode.Speaking,
        SpeechSubmissionKind.Microphone,
        "Where is the station?",
        IsProtectedAssessment: false);

    public static void Run()
    {
        ProductionQualificationRemainsPracticeOnly();
        PcmWaveContractIsDeterministic();
        SuccessfulCaptureUsesNativeLifecycleAndReturnsOwnedWave();
        MissingDeviceFailsClosedWithoutOpening();
        BusyDeviceMapsToStableTechnicalReason();
        CancellationReturnsControlAndCleansNativeResources();
        CleanupRetriesStillPlayingUntilOwnershipReturns();
        PersistentQueuedOwnershipIsQuarantinedInsteadOfFreed();
        CloseStillPlayingFailsClosedAfterHeaderRelease();
        TimeoutResetFailureMapsToStableTechnicalFailure();
        CancellationCleanupFailureFailsClosedAndQuarantines();
        InvalidDurationFailsBeforeCapture();
    }

    private static void ProductionQualificationRemainsPracticeOnly()
    {
        var provider = new WindowsMicrophoneCaptureProvider(
            new FakeWaveInApi(),
            new WindowsMicrophoneCaptureOptions(TimeSpan.FromSeconds(1)),
            enforceWindowsPlatform: false);

        SpeechProviderQualification q = provider.Qualification;
        Assert(q.ProviderId == "windows-winmm-default-microphone", "provider identity");
        Assert(!q.IsQualified, "capture adapter must not self-qualify for mastery");
        Assert(!q.HasDocumentedQualification, "capture adapter must require later independent qualification");
        Assert(q.Supports(SpeechProviderCapabilities.Capture), "capture capability");
        Assert(!q.Supports(SpeechProviderCapabilities.SpeakingJudgement), "capture must not claim judgement");
        Assert(q.RawAudioPolicy == SpeechRawAudioPolicy.EphemeralMemoryOnly, "raw audio policy");
    }

    private static void PcmWaveContractIsDeterministic()
    {
        byte[] pcm = { 0x01, 0x02, 0x03, 0x04 };
        byte[] wave = WindowsMicrophoneCaptureProvider.BuildPcmWavePayloadForSelfTest(pcm);
        try
        {
            Assert(wave.Length == 48, "WAV size");
            Assert(System.Text.Encoding.ASCII.GetString(wave, 0, 4) == "RIFF", "RIFF marker");
            Assert(System.Text.Encoding.ASCII.GetString(wave, 8, 4) == "WAVE", "WAVE marker");
            Assert(System.Text.Encoding.ASCII.GetString(wave, 12, 4) == "fmt ", "fmt marker");
            Assert(System.Text.Encoding.ASCII.GetString(wave, 36, 4) == "data", "data marker");
            Assert(BinaryPrimitives.ReadUInt16LittleEndian(wave.AsSpan(20, 2)) == 1, "PCM format");
            Assert(BinaryPrimitives.ReadUInt16LittleEndian(wave.AsSpan(22, 2)) == 1, "mono channel count");
            Assert(BinaryPrimitives.ReadUInt32LittleEndian(wave.AsSpan(24, 4)) == 16_000, "sample rate");
            Assert(BinaryPrimitives.ReadUInt16LittleEndian(wave.AsSpan(34, 2)) == 16, "sample width");
            Assert(BinaryPrimitives.ReadUInt32LittleEndian(wave.AsSpan(40, 4)) == 4, "data length");
            Assert(wave.AsSpan(44).SequenceEqual(pcm), "PCM payload identity");
        }
        finally
        {
            Array.Clear(wave);
            Array.Clear(pcm);
        }
    }

    private static void SuccessfulCaptureUsesNativeLifecycleAndReturnsOwnedWave()
    {
        var api = new FakeWaveInApi
        {
            CaptureBytes = new byte[] { 11, 22, 33, 44, 55, 66, 77, 88 },
            CompleteOnStart = true
        };
        var provider = CreateProvider(api);

        SpeechCaptureResult result = Capture(provider);

        Assert(result.Success && result.Sample is not null, "successful capture result");
        Assert(api.OpenCalls == 1, "open lifecycle");
        Assert(api.PrepareCalls == 1, "prepare lifecycle");
        Assert(api.AddBufferCalls == 1, "buffer lifecycle");
        Assert(api.StartCalls == 1, "start lifecycle");
        Assert(api.ResetCalls >= 1, "reset lifecycle");
        Assert(api.UnprepareCalls == 1, "unprepare lifecycle");
        Assert(api.CloseCalls == 1, "close lifecycle");

        byte[] owned = result.Sample!.DangerousBufferForSelfTest();
        Assert(owned.Length == 52, "owned WAV length");
        Assert(System.Text.Encoding.ASCII.GetString(owned, 0, 4) == "RIFF", "owned WAV marker");
        Assert(owned.AsSpan(44).SequenceEqual(api.CaptureBytes), "owned PCM payload");

        result.Sample.Dispose();
        Assert(owned.All(value => value == 0), "owned speech sample must zero on dispose");
    }

    private static void MissingDeviceFailsClosedWithoutOpening()
    {
        var api = new FakeWaveInApi { DeviceCount = 0 };
        var provider = CreateProvider(api);

        SpeechCaptureResult result = Capture(provider);

        Assert(!result.Success, "missing microphone result");
        Assert(result.ReasonCode == "MICROPHONE_UNAVAILABLE", "missing microphone reason");
        Assert(api.OpenCalls == 0, "must not open when no input device exists");
    }

    private static void BusyDeviceMapsToStableTechnicalReason()
    {
        var api = new FakeWaveInApi { OpenResult = 4 };
        var provider = CreateProvider(api);

        SpeechCaptureResult result = Capture(provider);

        Assert(!result.Success, "busy microphone result");
        Assert(result.ReasonCode == "MICROPHONE_BUSY", "busy microphone reason");
        Assert(api.PrepareCalls == 0 && api.StartCalls == 0, "busy microphone stops before buffer lifecycle");
    }

    private static void CancellationReturnsControlAndCleansNativeResources()
    {
        var api = new FakeWaveInApi { CompleteOnStart = false };
        var provider = new WindowsMicrophoneCaptureProvider(
            api,
            new WindowsMicrophoneCaptureOptions(TimeSpan.FromSeconds(2)),
            enforceWindowsPlatform: false);
        using var cancellation = new CancellationTokenSource();
        cancellation.CancelAfter(TimeSpan.FromMilliseconds(50));

        bool cancelled = false;
        try
        {
            provider.CaptureAsync(MicrophoneRequest, cancellation.Token)
                .GetAwaiter()
                .GetResult();
        }
        catch (OperationCanceledException)
        {
            cancelled = true;
        }

        Assert(cancelled, "cancellation must propagate as cancellation");
        Assert(api.ResetCalls >= 1, "cancelled capture must reset native input");
        Assert(api.UnprepareCalls == 1, "cancelled capture must unprepare native buffer");
        Assert(api.CloseCalls == 1, "cancelled capture must close native input");
    }

    private static void CleanupRetriesStillPlayingUntilOwnershipReturns()
    {
        int quarantineBefore = WindowsMicrophoneCaptureProvider.QuarantinedLeaseCountForSelfTest;
        var api = new FakeWaveInApi
        {
            CompleteOnStart = true,
            UnprepareStillPlayingRemaining = 2
        };
        var provider = CreateProvider(api);

        SpeechCaptureResult result = Capture(provider);

        Assert(result.Success && result.Sample is not null, "recoverable STILLPLAYING capture result");
        Assert(api.ResetCalls == 3, "cleanup must reset before each unprepare retry");
        Assert(api.UnprepareCalls == 3, "cleanup must retry STILLPLAYING until header returns");
        Assert(api.CloseCalls == 1, "close only after header ownership returns");
        Assert(
            WindowsMicrophoneCaptureProvider.QuarantinedLeaseCountForSelfTest == quarantineBefore,
            "recoverable STILLPLAYING must not quarantine");
        result.Sample!.Dispose();
    }

    private static void PersistentQueuedOwnershipIsQuarantinedInsteadOfFreed()
    {
        int quarantineBefore = WindowsMicrophoneCaptureProvider.QuarantinedLeaseCountForSelfTest;
        var api = new FakeWaveInApi
        {
            CompleteOnStart = true,
            ResetFailuresRemaining = 3,
            UnprepareStillPlayingRemaining = 3
        };
        var provider = CreateProvider(api);

        SpeechCaptureResult result = Capture(provider);

        Assert(!result.Success, "persistent queued ownership must fail capture closed");
        Assert(result.ReasonCode == "MICROPHONE_CLEANUP_FAILED", "persistent queued ownership reason");
        Assert(api.ResetCalls == 3, "persistent cleanup reset attempts are bounded");
        Assert(api.UnprepareCalls == 3, "persistent cleanup unprepare attempts are bounded");
        Assert(api.CloseCalls == 0, "must not close/free while header ownership is unproven");
        Assert(
            WindowsMicrophoneCaptureProvider.QuarantinedLeaseCountForSelfTest == quarantineBefore + 1,
            "driver-owned memory and callback lifetime must be quarantined");
    }

    private static void CloseStillPlayingFailsClosedAfterHeaderRelease()
    {
        int quarantineBefore = WindowsMicrophoneCaptureProvider.QuarantinedLeaseCountForSelfTest;
        var api = new FakeWaveInApi
        {
            CompleteOnStart = true,
            CloseStillPlayingRemaining = 3
        };
        var provider = CreateProvider(api);

        SpeechCaptureResult result = Capture(provider);

        Assert(!result.Success, "persistent close failure must fail capture closed");
        Assert(result.ReasonCode == "MICROPHONE_CLEANUP_FAILED", "persistent close failure reason");
        Assert(api.UnprepareCalls == 1, "header must be unprepared before close attempts");
        Assert(api.CloseCalls == 3, "close STILLPLAYING retries are bounded");
        Assert(
            WindowsMicrophoneCaptureProvider.QuarantinedLeaseCountForSelfTest == quarantineBefore + 1,
            "unclosed native handle and callback lifetime must be retained");
    }

    private static void TimeoutResetFailureMapsToStableTechnicalFailure()
    {
        var api = new FakeWaveInApi
        {
            CompleteOnStart = false,
            ResetFailuresRemaining = 1
        };
        var provider = CreateProvider(api);

        SpeechCaptureResult result = Capture(provider);

        Assert(!result.Success, "timeout reset failure must fail capture");
        Assert(result.ReasonCode == "MICROPHONE_RESET_FAILED", "timeout reset failure reason");
        Assert(api.ResetCalls >= 2, "cleanup retries ownership after timeout reset failure");
        Assert(api.UnprepareCalls == 1, "timeout reset failure still safely unprepares");
        Assert(api.CloseCalls == 1, "timeout reset failure still closes after safe return");
    }

    private static void CancellationCleanupFailureFailsClosedAndQuarantines()
    {
        int quarantineBefore = WindowsMicrophoneCaptureProvider.QuarantinedLeaseCountForSelfTest;
        var api = new FakeWaveInApi
        {
            CompleteOnStart = false,
            ResetFailuresRemaining = 3,
            UnprepareStillPlayingRemaining = 3
        };
        var provider = new WindowsMicrophoneCaptureProvider(
            api,
            new WindowsMicrophoneCaptureOptions(TimeSpan.FromSeconds(2)),
            enforceWindowsPlatform: false);
        using var cancellation = new CancellationTokenSource();
        cancellation.CancelAfter(TimeSpan.FromMilliseconds(50));

        SpeechCaptureResult result = provider.CaptureAsync(MicrophoneRequest, cancellation.Token)
            .GetAwaiter()
            .GetResult();

        Assert(!result.Success, "unsafe cancellation cleanup must override cancellation with technical failure");
        Assert(result.ReasonCode == "MICROPHONE_CLEANUP_FAILED", "cancellation cleanup failure reason");
        Assert(api.CloseCalls == 0, "unsafe cancellation cleanup must not close/free driver-owned buffer");
        Assert(
            WindowsMicrophoneCaptureProvider.QuarantinedLeaseCountForSelfTest == quarantineBefore + 1,
            "unsafe cancellation cleanup must retain driver-owned lifetime");
    }

    private static void InvalidDurationFailsBeforeCapture()
    {
        bool rejected = false;
        try
        {
            _ = new WindowsMicrophoneCaptureOptions(TimeSpan.FromMilliseconds(999));
        }
        catch (ArgumentOutOfRangeException)
        {
            rejected = true;
        }
        Assert(rejected, "sub-second capture duration must be rejected");
    }

    private static WindowsMicrophoneCaptureProvider CreateProvider(FakeWaveInApi api) =>
        new(
            api,
            new WindowsMicrophoneCaptureOptions(TimeSpan.FromSeconds(1)),
            enforceWindowsPlatform: false);

    private static SpeechCaptureResult Capture(WindowsMicrophoneCaptureProvider provider) =>
        provider.CaptureAsync(MicrophoneRequest, CancellationToken.None)
            .GetAwaiter()
            .GetResult();

    private static void Assert(bool condition, string message)
    {
        if (!condition)
            throw new InvalidOperationException($"WindowsMicrophoneCaptureProviderSelfTest failed: {message}.");
    }

    private sealed class FakeWaveInApi : IWaveInApi
    {
        private nint _callbackEvent;
        private nint _header;

        public uint DeviceCount { get; init; } = 1;
        public uint OpenResult { get; init; }
        public bool CompleteOnStart { get; init; } = true;
        public byte[] CaptureBytes { get; init; } = new byte[] { 1, 2, 3, 4 };
        public int ResetFailuresRemaining { get; set; }
        public int UnprepareStillPlayingRemaining { get; set; }
        public int CloseStillPlayingRemaining { get; set; }

        public int OpenCalls { get; private set; }
        public int PrepareCalls { get; private set; }
        public int AddBufferCalls { get; private set; }
        public int StartCalls { get; private set; }
        public int ResetCalls { get; private set; }
        public int UnprepareCalls { get; private set; }
        public int CloseCalls { get; private set; }

        public uint GetDeviceCount() => DeviceCount;

        public uint Open(out nint handle, ref WindowsWaveFormat format, nint callbackEventHandle)
        {
            OpenCalls++;
            _callbackEvent = callbackEventHandle;
            handle = OpenResult == 0 ? (nint)0x1234 : nint.Zero;
            return OpenResult;
        }

        public uint PrepareHeader(nint handle, nint header, uint headerSize)
        {
            PrepareCalls++;
            _header = header;
            return 0;
        }

        public uint AddBuffer(nint handle, nint header, uint headerSize)
        {
            AddBufferCalls++;
            _header = header;
            return 0;
        }

        public uint Start(nint handle)
        {
            StartCalls++;
            if (CompleteOnStart)
                CompleteCapture();
            return 0;
        }

        public uint Reset(nint handle)
        {
            ResetCalls++;
            if (ResetFailuresRemaining > 0)
            {
                ResetFailuresRemaining--;
                return 1;
            }

            SignalCallbackEvent();
            return 0;
        }

        public uint UnprepareHeader(nint handle, nint header, uint headerSize)
        {
            UnprepareCalls++;
            if (UnprepareStillPlayingRemaining > 0)
            {
                UnprepareStillPlayingRemaining--;
                return 33;
            }
            return 0;
        }

        public uint Close(nint handle)
        {
            CloseCalls++;
            if (CloseStillPlayingRemaining > 0)
            {
                CloseStillPlayingRemaining--;
                return 33;
            }
            return 0;
        }

        private void CompleteCapture()
        {
            WindowsWaveHeader header = Marshal.PtrToStructure<WindowsWaveHeader>(_header);
            int bytes = Math.Min(CaptureBytes.Length, checked((int)header.BufferLength));
            Marshal.Copy(CaptureBytes, 0, header.Data, bytes);
            header.BytesRecorded = (uint)bytes;
            header.Flags |= 0x00000001; // WHDR_DONE
            Marshal.StructureToPtr(header, _header, false);
            SignalCallbackEvent();
        }

        private void SignalCallbackEvent()
        {
            if (_callbackEvent == nint.Zero)
                return;

            using var signal = new EventWaitHandle(false, EventResetMode.AutoReset);
            signal.SafeWaitHandle = new SafeWaitHandle(_callbackEvent, ownsHandle: false);
            signal.Set();
        }
    }
}
