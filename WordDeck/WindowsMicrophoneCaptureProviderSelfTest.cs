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
        var provider = new WindowsMicrophoneCaptureProvider(
            api,
            new WindowsMicrophoneCaptureOptions(TimeSpan.FromSeconds(1)),
            enforceWindowsPlatform: false);

        SpeechCaptureResult result = provider
            .CaptureAsync(MicrophoneRequest, CancellationToken.None)
            .GetAwaiter()
            .GetResult();

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
        var provider = new WindowsMicrophoneCaptureProvider(
            api,
            new WindowsMicrophoneCaptureOptions(TimeSpan.FromSeconds(1)),
            enforceWindowsPlatform: false);

        SpeechCaptureResult result = provider
            .CaptureAsync(MicrophoneRequest, CancellationToken.None)
            .GetAwaiter()
            .GetResult();

        Assert(!result.Success, "missing microphone result");
        Assert(result.ReasonCode == "MICROPHONE_UNAVAILABLE", "missing microphone reason");
        Assert(api.OpenCalls == 0, "must not open when no input device exists");
    }

    private static void BusyDeviceMapsToStableTechnicalReason()
    {
        var api = new FakeWaveInApi { OpenResult = 4 };
        var provider = new WindowsMicrophoneCaptureProvider(
            api,
            new WindowsMicrophoneCaptureOptions(TimeSpan.FromSeconds(1)),
            enforceWindowsPlatform: false);

        SpeechCaptureResult result = provider
            .CaptureAsync(MicrophoneRequest, CancellationToken.None)
            .GetAwaiter()
            .GetResult();

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
            SignalCallbackEvent();
            return 0;
        }

        public uint UnprepareHeader(nint handle, nint header, uint headerSize)
        {
            UnprepareCalls++;
            return 0;
        }

        public uint Close(nint handle)
        {
            CloseCalls++;
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
