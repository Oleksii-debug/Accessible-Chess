using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;

namespace WordDeck;

/// <summary>
/// Optional offline pronunciation layer. Audio is resolved by stable dictionary
/// and entry IDs; missing files never block study or screen-reader access.
/// </summary>
internal sealed class PronunciationAudio : IDisposable
{
    private const string Alias = "worddeck_pronunciation";
    private bool _opened;

    [DllImport("winmm.dll", CharSet = CharSet.Unicode)]
    private static extern int mciSendString(string command, StringBuilder? returnValue, int returnLength, IntPtr callback);

    [DllImport("winmm.dll", CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool mciGetErrorString(int errorCode, StringBuilder errorText, int errorTextSize);

    public bool TryPlay(DictionaryPackage package, DictionaryEntry entry, out string? error)
    {
        string? path = CandidatePaths(package.Id, entry.Id).FirstOrDefault(File.Exists);
        if (path is null)
        {
            error = $"Generated pronunciation is not installed for {entry.Source}.";
            return false;
        }

        if (!OperatingSystem.IsWindows())
        {
            error = "Generated pronunciation playback is available on Windows only.";
            return false;
        }

        Stop();
        int result = mciSendString($"open \"{path}\" type mpegvideo alias {Alias}", null, 0, IntPtr.Zero);
        if (result != 0)
        {
            error = DescribeError("Could not open pronunciation audio", result);
            return false;
        }

        _opened = true;
        result = mciSendString($"play {Alias} from 0", null, 0, IntPtr.Zero);
        if (result != 0)
        {
            error = DescribeError("Could not play pronunciation audio", result);
            Stop();
            return false;
        }

        error = null;
        return true;
    }

    public void Stop()
    {
        if (!OperatingSystem.IsWindows() || !_opened)
            return;

        mciSendString($"stop {Alias}", null, 0, IntPtr.Zero);
        mciSendString($"close {Alias}", null, 0, IntPtr.Zero);
        _opened = false;
    }

    public void Dispose() => Stop();

    internal static IReadOnlyList<string> CandidatePaths(string dictionaryId, string entryId)
    {
        string dictionaryFolder = SafeName(dictionaryId);
        string fileName = SafeName(entryId) + ".mp3";
        string localRoot = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "WordDeck",
            "AudioPacks");
        string portableRoot = Path.Combine(AppContext.BaseDirectory, "AudioPacks");

        return new[]
        {
            Path.Combine(portableRoot, dictionaryFolder, fileName),
            Path.Combine(localRoot, dictionaryFolder, fileName)
        };
    }

    private static string SafeName(string value) =>
        Regex.Replace(value.Trim(), "[^A-Za-z0-9._-]+", "_");

    private static string DescribeError(string prefix, int code)
    {
        var message = new StringBuilder(256);
        return mciGetErrorString(code, message, message.Capacity)
            ? $"{prefix}: {message}."
            : $"{prefix} (Windows multimedia error {code}).";
    }
}
