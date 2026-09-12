using System.Buffers.Binary;
using System.Runtime.InteropServices;
using System.Security.Cryptography;

namespace WordDeck;

/// <summary>
/// Bounded configuration for the production Windows microphone adapter.
/// The wire format is intentionally fixed to 16 kHz, mono, 16-bit PCM WAV so
/// downstream judges never have to infer the representation of captured bytes.
/// </summary>
internal sealed class WindowsMicrophoneCaptureOptions
{
    public static readonly TimeSpan DefaultMaxDuration = TimeSpan.FromSeconds(8);

    public WindowsMicrophoneCaptureOptions(TimeSpan? maxDuration = null)
    {
        MaxDuration = maxDuration ?? DefaultMaxDuration;
        if (MaxDuration < TimeSpan.FromSeconds(1) || MaxDuration > TimeSpan.FromSeconds(30))
            throw new ArgumentOutOfRangeException(nameof(maxDuration), "Capture duration must be between 1 and 30 seconds.");
    }

    public TimeSpan MaxDuration { get; }
}

[StructLayout(LayoutKind.Sequential)]
internal struct WindowsWaveFormat
{
    public ushort FormatTag;
    public ushort Channels;
    public uint SamplesPerSecond;
    public uint AverageBytesPerSecond;
    public ushort BlockAlign;
    public ushort BitsPerSample;
    public ushort ExtraSize;
}

[StructLayout(LayoutKind.Sequential)]
internal struct WindowsWaveHeader
{
    public nint Data;
    public uint BufferLength;
    public uint BytesRecorded;
    public nint User;
    public uint Flags;
    public uint Loops;
    public nint Next;
    public nint Reserved;
}

/// <summary>
/// Small seam around WinMM so CI can exercise lifecycle/error handling without
/// requiring a physical microphone on the GitHub runner.
/// </summary>
internal interface IWaveInApi
{
    uint GetDeviceCount();
    uint Open(out nint handle, ref WindowsWaveFormat format, nint callbackEventHandle);
    uint PrepareHeader(nint handle, nint header, uint headerSize);
    uint AddBuffer(nint handle, nint header, uint headerSize);
    uint Start(nint handle);
    uint Reset(nint handle);
    uint UnprepareHeader(nint handle, nint header, uint headerSize);
    uint Close(nint handle);
}

internal sealed class WinMmWaveInApi : IWaveInApi
{
    private const uint WaveMapper = 0xFFFFFFFF;
    private const uint CallbackEvent = 0x00050000;

    public uint GetDeviceCount() => waveInGetNumDevs();

    public uint Open(out nint handle, ref WindowsWaveFormat format, nint callbackEventHandle) =>
        waveInOpen(out handle, WaveMapper, ref format, callbackEventHandle, nint.Zero, CallbackEvent);

    public uint PrepareHeader(nint handle, nint header, uint headerSize) =>
        waveInPrepareHeader(handle, header, headerSize);

    public uint AddBuffer(nint handle, nint header, uint headerSize) =>
        waveInAddBuffer(handle, header, headerSize);

    public uint Start(nint handle) => waveInStart(handle);
    public uint Reset(nint handle) => waveInReset(handle);
    public uint UnprepareHeader(nint handle, nint header, uint headerSize) =>
        waveInUnprepareHeader(handle, header, headerSize);
    public uint Close(nint handle) => waveInClose(handle);

    [DllImport("winmm.dll", ExactSpelling = true)]
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    private static extern uint waveInGetNumDevs();

    [DllImport("winmm.dll", ExactSpelling = true)]
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    private static extern uint waveInOpen(
        out nint handle,
        uint deviceId,
        ref WindowsWaveFormat format,
        nint callback,
        nint instance,
        uint flags);

    [DllImport("winmm.dll", ExactSpelling = true)]
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    private static extern uint waveInPrepareHeader(nint handle, nint header, uint headerSize);

    [DllImport("winmm.dll", ExactSpelling = true)]
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    private static extern uint waveInAddBuffer(nint handle, nint header, uint headerSize);

    [DllImport("winmm.dll", ExactSpelling = true)]
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    private static extern uint waveInStart(nint handle);

    [DllImport("winmm.dll", ExactSpelling = true)]
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    private static extern uint waveInReset(nint handle);

    [DllImport("winmm.dll", ExactSpelling = true)]
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    private static extern uint waveInUnprepareHeader(nint handle, nint header, uint headerSize);

    [DllImport("winmm.dll", ExactSpelling = true)]
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    private static extern uint waveInClose(nint handle);
}

/// <summary>
/// Production default-microphone adapter for Windows desktop.
///
/// Raw learner audio never receives a path and is kept only in owned memory.
/// The adapter is deliberately NOT evidence-qualified: it enables a real
/// microphone practice path, but a separate provider qualification and judge
/// are still required before speech can become mastery-eligible.
/// </summary>
internal sealed class WindowsMicrophoneCaptureProvider : ISpeechCaptureProvider
{
    private const uint MmNoError = 0;
    private const uint MmBadDeviceId = 2;
    private const uint MmAllocated = 4;
    private const uint MmNoDriver = 6;
    private const uint MmNoMemory = 7;
    private const uint WaveBadFormat = 32;
    private const uint WaveStillPlaying = 33;
    private const uint WaveUnprepared = 34;

    private const ushort PcmFormat = 1;
    private const ushort Channels = 1;
    private const uint SamplesPerSecond = 16_000;
    private const ushort BitsPerSample = 16;
    private const ushort BlockAlign = Channels * (BitsPerSample / 8);
    private const uint AverageBytesPerSecond = SamplesPerSecond * BlockAlign;
    private const int WaveHeaderBytes = 44;

    private readonly IWaveInApi _api;
    private readonly WindowsMicrophoneCaptureOptions _options;
    private readonly bool _enforceWindowsPlatform;

    public WindowsMicrophoneCaptureProvider(WindowsMicrophoneCaptureOptions? options = null)
        : this(new WinMmWaveInApi(), options, enforceWindowsPlatform: true)
    {
    }

    internal WindowsMicrophoneCaptureProvider(
        IWaveInApi api,
        WindowsMicrophoneCaptureOptions? options,
        bool enforceWindowsPlatform)
    {
        _api = api ?? throw new ArgumentNullException(nameof(api));
        _options = options ?? new WindowsMicrophoneCaptureOptions();
        _enforceWindowsPlatform = enforceWindowsPlatform;
    }

    public SpeechProviderQualification Qualification { get; } = new(
        ProviderId: "windows-winmm-default-microphone",
        ProviderVersion: "1.0",
        IsQualified: false,
        QualificationId: string.Empty,
        QualificationRevision: string.Empty,
        Capabilities: SpeechProviderCapabilities.Capture,
        RawAudioPolicy: SpeechRawAudioPolicy.EphemeralMemoryOnly);

    public Task<SpeechCaptureResult> CaptureAsync(
        SpeechPracticeRequest request,
        CancellationToken cancellationToken)
    {
        if (cancellationToken.IsCancellationRequested)
            return Task.FromCanceled<SpeechCaptureResult>(cancellationToken);

        // Native waveform input is synchronous. Keep it off the UI thread while
        // the capture core itself observes cancellation and always performs native cleanup.
        return Task.Run(() => CaptureCore(request, cancellationToken), CancellationToken.None);
    }

    private SpeechCaptureResult CaptureCore(
        SpeechPracticeRequest request,
        CancellationToken cancellationToken)
    {
        if (request is null || request.SubmissionKind != SpeechSubmissionKind.Microphone)
            return SpeechCaptureResult.Fail("INVALID_CAPTURE_REQUEST");

        if (_enforceWindowsPlatform && !OperatingSystem.IsWindows())
            return SpeechCaptureResult.Fail("MICROPHONE_PLATFORM_UNSUPPORTED");

        cancellationToken.ThrowIfCancellationRequested();

        if (_api.GetDeviceCount() == 0)
            return SpeechCaptureResult.Fail("MICROPHONE_UNAVAILABLE");

        int rawBufferLength = checked((int)Math.Ceiling(
            AverageBytesPerSecond * _options.MaxDuration.TotalSeconds));
        rawBufferLength -= rawBufferLength % BlockAlign;
        if (rawBufferLength <= 0)
            return SpeechCaptureResult.Fail("MICROPHONE_CAPTURE_CONFIGURATION_INVALID");

        byte[] rawBuffer = GC.AllocateUninitializedArray<byte>(rawBufferLength);
        GCHandle pinnedBuffer = default;
        nint headerPointer = nint.Zero;
        nint waveHandle = nint.Zero;
        bool headerPrepared = false;
        uint headerSize = (uint)Marshal.SizeOf<WindowsWaveHeader>();

        using var captureEvent = new EventWaitHandle(false, EventResetMode.AutoReset);

        try
        {
            WindowsWaveFormat format = CreateWaveFormat();
            uint result = _api.Open(
                out waveHandle,
                ref format,
                captureEvent.SafeWaitHandle.DangerousGetHandle());
            if (result != MmNoError)
                return SpeechCaptureResult.Fail(MapNativeFailure("OPEN", result));

            pinnedBuffer = GCHandle.Alloc(rawBuffer, GCHandleType.Pinned);
            headerPointer = Marshal.AllocHGlobal((int)headerSize);
            WindowsWaveHeader header = new()
            {
                Data = pinnedBuffer.AddrOfPinnedObject(),
                BufferLength = (uint)rawBuffer.Length,
                BytesRecorded = 0,
                User = nint.Zero,
                Flags = 0,
                Loops = 0,
                Next = nint.Zero,
                Reserved = nint.Zero
            };
            Marshal.StructureToPtr(header, headerPointer, false);

            result = _api.PrepareHeader(waveHandle, headerPointer, headerSize);
            if (result != MmNoError)
                return SpeechCaptureResult.Fail(MapNativeFailure("PREPARE", result));
            headerPrepared = true;

            result = _api.AddBuffer(waveHandle, headerPointer, headerSize);
            if (result != MmNoError)
                return SpeechCaptureResult.Fail(MapNativeFailure("BUFFER", result));

            // An event callback may have been signalled for the device-open state.
            // Clear that state before starting the queued capture buffer.
            captureEvent.Reset();
            result = _api.Start(waveHandle);
            if (result != MmNoError)
                return SpeechCaptureResult.Fail(MapNativeFailure("START", result));

            int signal = WaitHandle.WaitAny(
                new WaitHandle[] { captureEvent, cancellationToken.WaitHandle },
                _options.MaxDuration);

            if (signal == 1)
                cancellationToken.ThrowIfCancellationRequested();

            if (signal == WaitHandle.WaitTimeout)
            {
                // Reset returns the partial pending buffer and updates BytesRecorded.
                _api.Reset(waveHandle);
                captureEvent.WaitOne(TimeSpan.FromSeconds(2));
            }

            WindowsWaveHeader completed = Marshal.PtrToStructure<WindowsWaveHeader>(headerPointer);
            int recordedLength = checked((int)Math.Min(completed.BytesRecorded, (uint)rawBuffer.Length));
            recordedLength -= recordedLength % BlockAlign;
            if (recordedLength <= 0)
                return SpeechCaptureResult.Fail("MICROPHONE_EMPTY_CAPTURE");

            byte[] wavePayload = BuildPcmWavePayload(rawBuffer.AsSpan(0, recordedLength));
            try
            {
                return SpeechCaptureResult.Ok(new SpeechCaptureSample(wavePayload));
            }
            finally
            {
                CryptographicOperations.ZeroMemory(wavePayload);
            }
        }
        finally
        {
            if (waveHandle != nint.Zero)
            {
                if (headerPrepared)
                {
                    _api.Reset(waveHandle);
                    captureEvent.WaitOne(TimeSpan.FromMilliseconds(250));
                    _api.UnprepareHeader(waveHandle, headerPointer, headerSize);
                }
                _api.Close(waveHandle);
            }

            if (headerPointer != nint.Zero)
                Marshal.FreeHGlobal(headerPointer);

            CryptographicOperations.ZeroMemory(rawBuffer);
            if (pinnedBuffer.IsAllocated)
                pinnedBuffer.Free();
        }
    }

    private static WindowsWaveFormat CreateWaveFormat() => new()
    {
        FormatTag = PcmFormat,
        Channels = Channels,
        SamplesPerSecond = SamplesPerSecond,
        AverageBytesPerSecond = AverageBytesPerSecond,
        BlockAlign = BlockAlign,
        BitsPerSample = BitsPerSample,
        ExtraSize = 0
    };

    private static string MapNativeFailure(string stage, uint result) => result switch
    {
        MmAllocated => "MICROPHONE_BUSY",
        MmBadDeviceId or MmNoDriver => "MICROPHONE_UNAVAILABLE",
        MmNoMemory => "MICROPHONE_RESOURCE_UNAVAILABLE",
        WaveBadFormat => "MICROPHONE_FORMAT_UNSUPPORTED",
        WaveStillPlaying => "MICROPHONE_BUFFER_BUSY",
        WaveUnprepared => "MICROPHONE_BUFFER_INVALID",
        _ => $"MICROPHONE_{stage}_FAILED"
    };

    private static byte[] BuildPcmWavePayload(ReadOnlySpan<byte> pcm)
    {
        int alignedLength = pcm.Length - (pcm.Length % BlockAlign);
        if (alignedLength <= 0)
            throw new ArgumentException("PCM payload must contain at least one complete sample frame.", nameof(pcm));

        byte[] wave = GC.AllocateUninitializedArray<byte>(checked(WaveHeaderBytes + alignedLength));
        Span<byte> header = wave.AsSpan(0, WaveHeaderBytes);
        "RIFF"u8.CopyTo(header);
        BinaryPrimitives.WriteUInt32LittleEndian(header[4..], checked((uint)(36 + alignedLength)));
        "WAVE"u8.CopyTo(header[8..]);
        "fmt "u8.CopyTo(header[12..]);
        BinaryPrimitives.WriteUInt32LittleEndian(header[16..], 16);
        BinaryPrimitives.WriteUInt16LittleEndian(header[20..], PcmFormat);
        BinaryPrimitives.WriteUInt16LittleEndian(header[22..], Channels);
        BinaryPrimitives.WriteUInt32LittleEndian(header[24..], SamplesPerSecond);
        BinaryPrimitives.WriteUInt32LittleEndian(header[28..], AverageBytesPerSecond);
        BinaryPrimitives.WriteUInt16LittleEndian(header[32..], BlockAlign);
        BinaryPrimitives.WriteUInt16LittleEndian(header[34..], BitsPerSample);
        "data"u8.CopyTo(header[36..]);
        BinaryPrimitives.WriteUInt32LittleEndian(header[40..], checked((uint)alignedLength));
        pcm[..alignedLength].CopyTo(wave.AsSpan(WaveHeaderBytes));
        return wave;
    }

    internal static byte[] BuildPcmWavePayloadForSelfTest(ReadOnlySpan<byte> pcm) =>
        BuildPcmWavePayload(pcm);
}
