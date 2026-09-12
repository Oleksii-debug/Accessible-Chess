using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;

namespace WordDeck;

/// <summary>
/// Resolves only already-installed local sentence audio. The catalog never
/// synthesizes, downloads or uploads audio and never treats sentence text alone
/// as evidence that a production listening asset exists.
/// </summary>
internal interface ISentenceAudioCatalog
{
    bool TryResolve(string packId, string sentenceId, out string? audioPath);
}

internal sealed class InstalledSentenceAudioCatalog : ISentenceAudioCatalog
{
    public bool TryResolve(string packId, string sentenceId, out string? audioPath)
    {
        audioPath = SentenceAudioPackLayout.CandidatePaths(packId, sentenceId).FirstOrDefault(File.Exists);
        return audioPath is not null;
    }
}

internal static class SentenceAudioPackLayout
{
    internal static IReadOnlyList<string> CandidatePaths(string packId, string sentenceId)
    {
        string safePack = SafeName(packId);
        string fileName = SafeName(sentenceId) + ".mp3";
        string portableRoot = Path.Combine(AppContext.BaseDirectory, "SentenceAudioPacks");
        string localRoot = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "WordDeck",
            "SentenceAudioPacks");

        return new[]
        {
            Path.Combine(portableRoot, safePack, fileName),
            Path.Combine(localRoot, safePack, fileName)
        };
    }

    private static string SafeName(string value)
    {
        string trimmed = (value ?? string.Empty).Trim();
        if (trimmed.Length == 0) throw new InvalidDataException("Sentence audio pack/sentence ID must not be blank.");
        return Regex.Replace(trimmed, "[^A-Za-z0-9._-]+", "_");
    }
}

internal interface IListeningAudioFilePlayer : IDisposable
{
    bool TryPlay(string path, out string? error);
}

/// <summary>
/// Windows-local file playback used by future sentence/phrase Listening assets.
/// It has no network or synthesis capability.
/// </summary>
internal sealed class ListeningAudioFilePlayer : IListeningAudioFilePlayer
{
    private const string Alias = "worddeck_listening_sentence";
    private bool _opened;

    [DllImport("winmm.dll", CharSet = CharSet.Unicode)]
    private static extern int mciSendString(string command, StringBuilder? returnValue, int returnLength, IntPtr callback);

    [DllImport("winmm.dll", CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool mciGetErrorString(int errorCode, StringBuilder errorText, int errorTextSize);

    public bool TryPlay(string path, out string? error)
    {
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
        {
            error = "The local sentence listening audio file is missing.";
            return false;
        }
        if (!OperatingSystem.IsWindows())
        {
            error = "Sentence listening playback is available on Windows only.";
            return false;
        }

        Stop();
        int result = mciSendString($"open \"{Path.GetFullPath(path)}\" type mpegvideo alias {Alias}", null, 0, IntPtr.Zero);
        if (result != 0)
        {
            error = DescribeError("Could not open sentence listening audio", result);
            return false;
        }

        _opened = true;
        result = mciSendString($"play {Alias} from 0", null, 0, IntPtr.Zero);
        if (result != 0)
        {
            error = DescribeError("Could not play sentence listening audio", result);
            Stop();
            return false;
        }
        error = null;
        return true;
    }

    private void Stop()
    {
        if (!OperatingSystem.IsWindows() || !_opened) return;
        mciSendString($"stop {Alias}", null, 0, IntPtr.Zero);
        mciSendString($"close {Alias}", null, 0, IntPtr.Zero);
        _opened = false;
    }

    public void Dispose() => Stop();

    private static string DescribeError(string prefix, int code)
    {
        var message = new StringBuilder(256);
        return mciGetErrorString(code, message, message.Capacity)
            ? $"{prefix}: {message}."
            : $"{prefix} (Windows multimedia error {code}).";
    }
}

/// <summary>
/// SentencePack-to-Listening adapter. Local audio is necessary but not sufficient:
/// an explicit production approval matching the exact PackId is also required.
/// Therefore an installed file, text corpus, fixture or historical database cannot
/// silently activate sentence dictation. Hidden target words remain excluded.
/// </summary>
internal sealed class SentencePackListeningExerciseSource : IListeningExerciseSource
{
    private readonly SentencePack _pack;
    private readonly ISentenceAudioCatalog _catalog;
    private readonly IListeningAudioFilePlayer _player;
    private readonly ListeningAudioPackApproval _approval;
    private readonly IReadOnlySet<string> _hiddenEntryIds;
    private readonly Dictionary<string, SentenceRecord> _sentencesByExerciseId;

    public SentencePackListeningExerciseSource(
        SentencePack pack,
        ISentenceAudioCatalog? catalog = null,
        IListeningAudioFilePlayer? player = null,
        ListeningAudioPackApproval? approval = null,
        IReadOnlySet<string>? hiddenEntryIds = null)
    {
        _pack = pack ?? throw new ArgumentNullException(nameof(pack));
        _pack.Validate();
        _catalog = catalog ?? new InstalledSentenceAudioCatalog();
        _player = player ?? new ListeningAudioFilePlayer();
        _approval = approval ?? ListeningAudioPackApproval.Unapproved(_pack.PackId);
        _hiddenEntryIds = hiddenEntryIds ?? new AppStateStore().Load().HiddenEntryIds;
        _sentencesByExerciseId = _pack.Sentences.ToDictionary(ExerciseId, StringComparer.OrdinalIgnoreCase);
    }

    public IReadOnlyList<ListeningExercise> GetAvailable(string scopeId)
    {
        if (!_approval.MatchesApprovedPack(_pack.PackId))
            return Array.Empty<ListeningExercise>();

        string canonicalScope = StudyScopeIds.Ordered.Contains(scopeId, StringComparer.OrdinalIgnoreCase)
            ? StudyScopeIds.Ordered.First(id => string.Equals(id, scopeId, StringComparison.OrdinalIgnoreCase))
            : StudyScopeIds.All;

        return _pack.Sentences
            .Where(sentence => string.Equals(canonicalScope, StudyScopeIds.All, StringComparison.OrdinalIgnoreCase) ||
                               string.Equals(sentence.DifficultyLevel, canonicalScope, StringComparison.OrdinalIgnoreCase))
            .Where(sentence => !sentence.TargetEntryIds.Any(_hiddenEntryIds.Contains))
            .Where(sentence => _catalog.TryResolve(_pack.PackId, sentence.Id, out _))
            .Select(sentence => new ListeningExercise(
                ExerciseId(sentence),
                ListeningExerciseKind.Sentence,
                sentence.English,
                sentence.DifficultyLevel,
                sentence.TargetEntryIds.ToArray(),
                $"sentence:{_pack.PackId}:{sentence.Id}",
                BuildContract(sentence)))
            .ToArray();
    }

    public bool TryPlay(ListeningExercise exercise, out string? error)
    {
        if (!_approval.MatchesApprovedPack(_pack.PackId))
        {
            error = "Sentence listening audio is not activated because this pack has no explicit production approval.";
            return false;
        }
        if (exercise.Kind != ListeningExerciseKind.Sentence ||
            !_sentencesByExerciseId.TryGetValue(exercise.ExerciseId, out SentenceRecord? sentence))
        {
            error = "This Listening item is not a sentence from the active SentencePack.";
            return false;
        }
        if (sentence.TargetEntryIds.Any(_hiddenEntryIds.Contains))
        {
            error = "This sentence contains a hidden study target and is not available in Listening.";
            return false;
        }
        if (!_catalog.TryResolve(_pack.PackId, sentence.Id, out string? path) || path is null)
        {
            error = "Approved local audio is not installed for this SentencePack sentence.";
            return false;
        }
        return _player.TryPlay(path, out error);
    }

    public void Dispose() => _player.Dispose();

    private ListeningAudioContract BuildContract(SentenceRecord sentence) => new(
        AssetId: $"sentence:{_pack.PackId}:{sentence.Id}",
        UnitKind: ListeningAudioUnitKind.Sentence,
        Locale: "en-GB",
        PackId: _pack.PackId,
        Provenance: _pack.Provenance,
        Speakers: Array.Empty<ListeningSpeakerMetadata>(),
        Transcript: new ListeningTranscriptContract(
            sentence.English,
            ListeningTranscriptAvailability.AfterReveal,
            Array.Empty<ListeningTranscriptTurn>()),
        ReplayPolicy: ListeningReplayPolicy.UnlimitedPractice,
        Prompts: new[]
        {
            new ListeningComprehensionPrompt(
                $"dictation:{_pack.PackId}:{sentence.Id}",
                ListeningComprehensionKind.Dictation,
                "Transcribe the English sentence you hear.",
                new[] { sentence.English })
        },
        ApprovedForProduction: true);

    private string ExerciseId(SentenceRecord sentence) => $"sentence:{_pack.PackId}:{sentence.Id}";
}
