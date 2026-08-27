using System.Text;

namespace WordDeck;

internal enum ListeningExerciseKind
{
    // Numeric identities are persisted in Listening history; do not renumber.
    Word = 1,
    Sentence = 2,
    Phrase = 3,
    Passage = 4
}

internal sealed record ListeningExercise(
    string ExerciseId,
    ListeningExerciseKind Kind,
    string TargetText,
    string Level,
    IReadOnlyList<string> StableEntryIds,
    string AudioKey,
    ListeningAudioContract? AudioContract = null);

internal interface IListeningExerciseSource : IDisposable
{
    IReadOnlyList<ListeningExercise> GetAvailable(string scopeId);
    bool TryPlay(ListeningExercise exercise, out string? error);
}

/// <summary>
/// Current production source: accepted offline word pronunciation keyed by the
/// canonical dictionary and stable Oxford entry IDs. Hidden user entries are
/// excluded from selection and playback. Phrase/sentence sources use separate
/// explicit approval boundaries.
/// </summary>
internal sealed class WordAudioListeningExerciseSource : IListeningExerciseSource
{
    private readonly DictionaryPackage _package;
    private readonly Dictionary<string, DictionaryEntry> _entries;
    private readonly IReadOnlySet<string> _hiddenEntryIds;
    private readonly PronunciationAudio _audio = new();

    public WordAudioListeningExerciseSource(DictionaryPackage package, IReadOnlySet<string>? hiddenEntryIds = null)
    {
        _package = package ?? throw new ArgumentNullException(nameof(package));
        _entries = package.Entries.ToDictionary(entry => entry.Id, StringComparer.OrdinalIgnoreCase);
        // The default source reads the same personal AppState used by Recall so
        // reversible hidden-word choices apply consistently to Listening too.
        _hiddenEntryIds = hiddenEntryIds ?? new AppStateStore().Load().HiddenEntryIds;
    }

    public IReadOnlyList<ListeningExercise> GetAvailable(string scopeId) =>
        EligibleEntries(_package.Entries, scopeId, _hiddenEntryIds,
                entry => PronunciationAudio.CandidatePaths(_package.Id, entry.Id).Any(File.Exists))
            .Select(entry => new ListeningExercise(
                ExerciseId: $"word:{entry.Id}",
                Kind: ListeningExerciseKind.Word,
                TargetText: entry.Source,
                Level: entry.Level,
                StableEntryIds: new[] { entry.Id },
                AudioKey: entry.Id,
                AudioContract: WordContract(entry)))
            .ToList();

    internal static IReadOnlyList<DictionaryEntry> EligibleEntries(
        IEnumerable<DictionaryEntry> entries,
        string scopeId,
        IReadOnlySet<string> hiddenEntryIds,
        Func<DictionaryEntry, bool> hasAudio) =>
        entries
            .Where(entry => StudyScopeIds.Includes(scopeId, entry))
            .Where(entry => !hiddenEntryIds.Contains(entry.Id))
            .Where(hasAudio)
            .ToList();

    public bool TryPlay(ListeningExercise exercise, out string? error)
    {
        if (exercise.Kind != ListeningExerciseKind.Word || exercise.StableEntryIds.Count != 1 ||
            !_entries.TryGetValue(exercise.StableEntryIds[0], out DictionaryEntry? entry))
        {
            error = "This listening item is not backed by an installed word-audio entry.";
            return false;
        }
        if (_hiddenEntryIds.Contains(entry.Id))
        {
            error = "This word is hidden from study and is not available in Listening.";
            return false;
        }
        if (!PronunciationAudio.CandidatePaths(_package.Id, entry.Id).Any(File.Exists))
        {
            error = "The installed offline audio for this listening word is missing.";
            return false;
        }
        return _audio.TryPlay(_package, entry, out error);
    }

    public void Dispose() => _audio.Dispose();

    private static ListeningAudioContract WordContract(DictionaryEntry entry) => new(
        AssetId: entry.Id,
        UnitKind: ListeningAudioUnitKind.Word,
        Locale: "en-GB",
        PackId: null,
        Provenance: "accepted-installed-word-audio",
        Speakers: Array.Empty<ListeningSpeakerMetadata>(),
        Transcript: new ListeningTranscriptContract(
            entry.Source,
            ListeningTranscriptAvailability.AfterReveal,
            Array.Empty<ListeningTranscriptTurn>()),
        ReplayPolicy: ListeningReplayPolicy.UnlimitedPractice,
        Prompts: new[]
        {
            new ListeningComprehensionPrompt(
                $"dictation:{entry.Id}",
                ListeningComprehensionKind.Dictation,
                "Transcribe the English word you hear.",
                new[] { entry.Source })
        },
        ApprovedForProduction: true);
}

internal sealed class ListeningItemStats
{
    public int CompletedReviews { get; set; }
    public int CorrectReviews { get; set; }
    public int WrongAttempts { get; set; }
    public int ReplayCount { get; set; }
    public int ShowAnswerUses { get; set; }
    public int SkipCount { get; set; }
    public int ConsecutiveCorrect { get; set; }
    public DateTimeOffset? LastReviewedUtc { get; set; }

    public double Mastery => CompletedReviews <= 0
        ? 0d
        : Math.Clamp((double)CorrectReviews / CompletedReviews - Math.Min(0.35d, ShowAnswerUses * 0.03d), 0d, 1d);
}

internal sealed class ListeningHistoryRecord
{
    public DateTimeOffset AtUtc { get; set; }
    public string DictionaryId { get; set; } = string.Empty;
    public string ExerciseId { get; set; } = string.Empty;
    public ListeningExerciseKind Kind { get; set; }
    public bool Correct { get; set; }
    public bool ShowedAnswer { get; set; }
    public bool Skipped { get; set; }
    public int WrongAttempts { get; set; }
    public int Replays { get; set; }
}

internal sealed class ListeningCoachState
{
    public int SchemaVersion { get; set; } = ListeningStateStore.CurrentSchemaVersion;
    public string ActiveScopeId { get; set; } = StudyScopeIds.All;
    // Only an unfinished item is persisted here. Completion clears this field so
    // a reviewed item cannot be resurrected as pending after restart/import.
    public string? CurrentExerciseId { get; set; }
    public long SelectionCounter { get; set; }
    public Dictionary<string, Dictionary<string, ListeningItemStats>> StatsByDictionary { get; set; } = new(StringComparer.OrdinalIgnoreCase);
    public List<ListeningHistoryRecord> History { get; set; } = new();
}

internal sealed record ListeningCheckResult(bool IsCorrect, bool Completed, string Message);

internal sealed record ListeningStatistics(
    int AvailableItems,
    int ReviewedItems,
    int CompletedReviews,
    int CorrectReviews,
    int WrongAttempts,
    int ReplayCount,
    int ShowAnswerUses,
    int SkipCount,
    int HistoryEntries,
    double Accuracy,
    double AverageMastery);

internal static class ListeningCoachPresentation
{
    public static string BeforeCheck(ListeningExercise exercise) => exercise.Kind switch
    {
        ListeningExerciseKind.Word => "Audio played. Type the English word, then press Enter to check.",
        ListeningExerciseKind.Phrase => "Audio played. Type the English phrase, then press Enter to check.",
        ListeningExerciseKind.Sentence => "Audio played. Type the English sentence, then press Enter to check.",
        ListeningExerciseKind.Passage => "Audio played. Answer the listening task, then press Enter to check.",
        _ => "Audio played. Type what you heard, then press Enter to check."
    };

    public static string AfterShow(ListeningExercise exercise) => $"Answer: {exercise.TargetText}";
}

/// <summary>
/// Deterministic listening scheduler. It owns only ListeningCoachState. Recall,
/// Spelling and Sentence state are deliberately absent from this API.
/// </summary>
internal sealed class ListeningCoachEngine
{
    private const int MaxHistory = 2000;
    private readonly DictionaryPackage _package;
    private readonly IListeningExerciseSource _source;
    private readonly ListeningCoachState _state;
    private int _roundWrongAttempts;
    private int _roundReplays;
    private bool _roundCompleted;
    private bool _roundRevealed;

    public ListeningExercise? Current { get; private set; }
    public ListeningCoachState State => _state;

    public ListeningCoachEngine(DictionaryPackage package, ListeningCoachState state, IListeningExerciseSource source)
    {
        _package = package ?? throw new ArgumentNullException(nameof(package));
        _state = ListeningStateStore.Normalize(state ?? throw new ArgumentNullException(nameof(state)));
        _source = source ?? throw new ArgumentNullException(nameof(source));
    }

    public IReadOnlyList<ListeningExercise> Available() => _source.GetAvailable(_state.ActiveScopeId);

    public bool TryResumeCurrent(out ListeningExercise? exercise)
    {
        exercise = null;
        if (string.IsNullOrWhiteSpace(_state.CurrentExerciseId)) return false;

        exercise = Available().FirstOrDefault(item =>
            string.Equals(item.ExerciseId, _state.CurrentExerciseId, StringComparison.OrdinalIgnoreCase));
        if (exercise is null)
        {
            // The audio/scope/visibility may have changed since the previous run.
            // Do not fabricate a pending item that can no longer be practiced.
            _state.CurrentExerciseId = null;
            return false;
        }

        Current = exercise;
        ResetRound();
        return true;
    }

    public ListeningExercise StartNext(bool recordSkipForUnfinished = true)
    {
        if (Current is not null && !_roundCompleted && recordSkipForUnfinished)
            CompleteCurrent(correct: false, showedAnswer: false, skipped: true);

        IReadOnlyList<ListeningExercise> available = Available();
        if (available.Count == 0)
            throw new InvalidOperationException($"No installed offline listening audio is available for {StudyScopeIds.DisplayName(_state.ActiveScopeId)}.");

        var ranked = available
            .Select(item => (Item: item, Score: WeaknessScore(item)))
            .OrderByDescending(pair => pair.Score)
            .ThenBy(pair => pair.Item.ExerciseId, StringComparer.OrdinalIgnoreCase)
            .ToList();
        double top = ranked[0].Score;
        List<ListeningExercise> topBucket = ranked
            .Where(pair => Math.Abs(pair.Score - top) < 0.0001d)
            .Select(pair => pair.Item)
            .ToList();

        int start = (int)(Math.Abs(_state.SelectionCounter++) % topBucket.Count);
        ListeningExercise selected = topBucket[start];
        if (Current is not null && topBucket.Count > 1 &&
            string.Equals(selected.ExerciseId, Current.ExerciseId, StringComparison.OrdinalIgnoreCase))
            selected = topBucket[(start + 1) % topBucket.Count];

        Current = selected;
        _state.CurrentExerciseId = selected.ExerciseId;
        ResetRound();
        return selected;
    }

    public void CancelCurrent()
    {
        Current = null;
        _state.CurrentExerciseId = null;
        ResetRound();
    }

    public bool TryPlayCurrent(bool countAsReplay, out string? error)
    {
        if (Current is null)
        {
            error = "No listening item is active.";
            return false;
        }

        if (countAsReplay)
        {
            ListeningReplayPolicy policy = Current.AudioContract?.ReplayPolicy ?? ListeningReplayPolicy.UnlimitedPractice;
            if (!policy.Allows(_roundReplays, _roundCompleted, _roundRevealed))
            {
                error = "Replay is not allowed by the policy for this listening task.";
                return false;
            }
        }

        bool played = _source.TryPlay(Current, out error);
        if (played && countAsReplay)
        {
            _roundReplays++;
            GetStats(Current).ReplayCount++;
        }
        return played;
    }

    public ListeningCheckResult Check(string? answer)
    {
        if (Current is null)
            return new ListeningCheckResult(false, false, "No listening item is active.");
        if (_roundCompleted)
            return new ListeningCheckResult(false, true, "This listening item is already complete. Use Next for another item.");

        string normalizedAnswer = NormalizeAnswer(answer);
        if (normalizedAnswer.Length == 0)
            return new ListeningCheckResult(false, false, "Type what you heard before checking. Empty Enter does not change Listening progress.");

        bool correct = string.Equals(normalizedAnswer, NormalizeAnswer(Current.TargetText), StringComparison.Ordinal);
        if (!correct)
        {
            _roundWrongAttempts++;
            GetStats(Current).WrongAttempts++;
            return new ListeningCheckResult(false, false, "Not correct yet. Edit the answer and try again, replay the audio, or show the answer.");
        }

        CompleteCurrent(correct: true, showedAnswer: false, skipped: false);
        return new ListeningCheckResult(true, true, "Correct.");
    }

    public string ShowAnswer()
    {
        if (Current is null) throw new InvalidOperationException("No listening item is active.");
        if (!_roundCompleted)
        {
            _roundRevealed = true;
            GetStats(Current).ShowAnswerUses++;
            CompleteCurrent(correct: false, showedAnswer: true, skipped: false);
        }
        return Current.TargetText;
    }

    public ListeningStatistics Statistics()
    {
        IReadOnlyList<ListeningExercise> available = Available();
        var ids = new HashSet<string>(available.Select(item => item.ExerciseId), StringComparer.OrdinalIgnoreCase);
        var selected = new List<ListeningItemStats>();
        if (_state.StatsByDictionary.TryGetValue(_package.Id, out Dictionary<string, ListeningItemStats>? perDictionary))
        {
            foreach (string id in ids)
                if (perDictionary.TryGetValue(id, out ListeningItemStats? stats)) selected.Add(stats);
        }

        int completed = selected.Sum(stats => stats.CompletedReviews);
        int correct = selected.Sum(stats => stats.CorrectReviews);
        List<ListeningItemStats> reviewed = selected.Where(stats => stats.CompletedReviews > 0).ToList();
        double accuracy = completed == 0 ? 0d : (double)correct / completed;
        double mastery = reviewed.Count == 0 ? 0d : reviewed.Average(stats => stats.Mastery);
        int history = _state.History.Count(item =>
            string.Equals(item.DictionaryId, _package.Id, StringComparison.OrdinalIgnoreCase) && ids.Contains(item.ExerciseId));

        return new ListeningStatistics(
            AvailableItems: available.Count,
            ReviewedItems: reviewed.Count,
            CompletedReviews: completed,
            CorrectReviews: correct,
            WrongAttempts: selected.Sum(stats => stats.WrongAttempts),
            ReplayCount: selected.Sum(stats => stats.ReplayCount),
            ShowAnswerUses: selected.Sum(stats => stats.ShowAnswerUses),
            SkipCount: selected.Sum(stats => stats.SkipCount),
            HistoryEntries: history,
            Accuracy: accuracy,
            AverageMastery: mastery);
    }

    public double Mastery(string exerciseId)
    {
        if (!_state.StatsByDictionary.TryGetValue(_package.Id, out Dictionary<string, ListeningItemStats>? perDictionary) ||
            !perDictionary.TryGetValue(exerciseId, out ListeningItemStats? stats))
            return 0d;
        return stats.Mastery;
    }

    private double WeaknessScore(ListeningExercise item)
    {
        ListeningItemStats stats = GetStats(item);
        if (stats.CompletedReviews == 0) return 1000d;

        double failureRate = 1d - (double)stats.CorrectReviews / stats.CompletedReviews;
        double ageBonus = stats.LastReviewedUtc is null
            ? 120d
            : Math.Min(120d, Math.Max(0d, (DateTimeOffset.UtcNow - stats.LastReviewedUtc.Value).TotalDays));
        return failureRate * 500d
            + Math.Min(180d, stats.WrongAttempts * 8d)
            + Math.Min(100d, stats.ShowAnswerUses * 12d)
            + Math.Min(60d, stats.ReplayCount * 2d)
            + Math.Min(80d, stats.SkipCount * 10d)
            + ageBonus
            - Math.Min(80d, stats.ConsecutiveCorrect * 12d);
    }

    private ListeningItemStats GetStats(ListeningExercise exercise)
    {
        if (!_state.StatsByDictionary.TryGetValue(_package.Id, out Dictionary<string, ListeningItemStats>? perDictionary))
        {
            perDictionary = new Dictionary<string, ListeningItemStats>(StringComparer.OrdinalIgnoreCase);
            _state.StatsByDictionary[_package.Id] = perDictionary;
        }
        if (!perDictionary.TryGetValue(exercise.ExerciseId, out ListeningItemStats? stats))
        {
            stats = new ListeningItemStats();
            perDictionary[exercise.ExerciseId] = stats;
        }
        return stats;
    }

    private void CompleteCurrent(bool correct, bool showedAnswer, bool skipped)
    {
        if (Current is null || _roundCompleted) return;
        ListeningItemStats stats = GetStats(Current);
        stats.CompletedReviews++;
        if (correct)
        {
            stats.CorrectReviews++;
            stats.ConsecutiveCorrect++;
        }
        else
        {
            stats.ConsecutiveCorrect = 0;
            if (skipped) stats.SkipCount++;
        }
        stats.LastReviewedUtc = DateTimeOffset.UtcNow;

        _state.History.Add(new ListeningHistoryRecord
        {
            AtUtc = DateTimeOffset.UtcNow,
            DictionaryId = _package.Id,
            ExerciseId = Current.ExerciseId,
            Kind = Current.Kind,
            Correct = correct,
            ShowedAnswer = showedAnswer,
            Skipped = skipped,
            WrongAttempts = _roundWrongAttempts,
            Replays = _roundReplays
        });
        if (_state.History.Count > MaxHistory)
            _state.History.RemoveRange(0, _state.History.Count - MaxHistory);
        _roundCompleted = true;
        _state.CurrentExerciseId = null;
    }

    private void ResetRound()
    {
        _roundWrongAttempts = 0;
        _roundReplays = 0;
        _roundCompleted = false;
        _roundRevealed = false;
    }

    internal static string NormalizeAnswer(string? value)
    {
        string normalized = (value ?? string.Empty).Normalize(NormalizationForm.FormC).Trim().ToLowerInvariant();
        normalized = normalized.Replace('’', '\'').Replace('`', '\'');
        return string.Join(' ', normalized.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));
    }
}
