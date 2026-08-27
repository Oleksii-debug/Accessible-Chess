namespace WordDeck;

/// <summary>
/// Presentation-neutral Listening task vocabulary. These contracts describe
/// learning content and policy only; WinForms/NVDA presentation is an adapter.
/// </summary>
internal enum ListeningComprehensionKind
{
    Dictation = 1,
    Gist = 2,
    Detail = 3
}

internal enum ListeningAudioUnitKind
{
    Word = 1,
    Phrase = 2,
    Sentence = 3,
    Passage = 4
}

internal enum ListeningTranscriptAvailability
{
    None = 0,
    AfterCheck = 1,
    AfterReveal = 2,
    Always = 3
}

internal sealed record ListeningReplayPolicy(
    int? MaximumReplays,
    bool AllowAfterCompletion,
    bool AllowAfterReveal)
{
    public static ListeningReplayPolicy UnlimitedPractice { get; } = new(null, true, true);
    public static ListeningReplayPolicy OneReplayAssessment { get; } = new(1, false, false);

    public bool Allows(int replaysAlreadyUsed, bool completed, bool revealed)
    {
        if (replaysAlreadyUsed < 0) return false;
        if (completed && !AllowAfterCompletion) return false;
        if (revealed && !AllowAfterReveal) return false;
        return MaximumReplays is null || replaysAlreadyUsed < MaximumReplays.Value;
    }

    public void Validate()
    {
        if (MaximumReplays is < 0)
            throw new InvalidDataException("Listening replay maximum cannot be negative.");
    }
}

internal sealed record ListeningSpeakerMetadata(
    string SpeakerId,
    string? DisplayName = null,
    string? Role = null)
{
    public void Validate()
    {
        if (string.IsNullOrWhiteSpace(SpeakerId))
            throw new InvalidDataException("Listening speaker ID is required.");
    }
}

internal sealed record ListeningTranscriptTurn(
    string SpeakerId,
    string Text,
    TimeSpan? Start = null,
    TimeSpan? End = null)
{
    public void Validate(IReadOnlySet<string> speakerIds)
    {
        if (string.IsNullOrWhiteSpace(SpeakerId) || !speakerIds.Contains(SpeakerId))
            throw new InvalidDataException("Listening transcript turn references an unknown speaker.");
        if (string.IsNullOrWhiteSpace(Text))
            throw new InvalidDataException("Listening transcript turn text is required.");
        if (Start is < TimeSpan.Zero || End is < TimeSpan.Zero || (Start is not null && End is not null && End < Start))
            throw new InvalidDataException("Listening transcript turn timing is invalid.");
    }
}

internal sealed record ListeningTranscriptContract(
    string? FullTranscript,
    ListeningTranscriptAvailability Availability,
    IReadOnlyList<ListeningTranscriptTurn> Turns)
{
    public void Validate(IReadOnlySet<string> speakerIds)
    {
        if (Availability != ListeningTranscriptAvailability.None &&
            string.IsNullOrWhiteSpace(FullTranscript) && (Turns?.Count ?? 0) == 0)
            throw new InvalidDataException("Listening transcript policy exposes no transcript content.");

        foreach (ListeningTranscriptTurn turn in Turns ?? Array.Empty<ListeningTranscriptTurn>())
            turn.Validate(speakerIds);
    }
}

internal sealed record ListeningComprehensionPrompt(
    string PromptId,
    ListeningComprehensionKind Kind,
    string PromptText,
    IReadOnlyList<string> AcceptedAnswers)
{
    public void Validate()
    {
        if (string.IsNullOrWhiteSpace(PromptId))
            throw new InvalidDataException("Listening prompt ID is required.");
        if (string.IsNullOrWhiteSpace(PromptText))
            throw new InvalidDataException("Listening prompt text is required.");
        if (AcceptedAnswers is null || AcceptedAnswers.Count == 0 || AcceptedAnswers.Any(string.IsNullOrWhiteSpace))
            throw new InvalidDataException("Listening prompt requires at least one non-blank accepted answer.");
    }
}

internal sealed record ListeningAudioContract(
    string AssetId,
    ListeningAudioUnitKind UnitKind,
    string Locale,
    string? PackId,
    string? Provenance,
    IReadOnlyList<ListeningSpeakerMetadata> Speakers,
    ListeningTranscriptContract? Transcript,
    ListeningReplayPolicy ReplayPolicy,
    IReadOnlyList<ListeningComprehensionPrompt> Prompts,
    bool ApprovedForProduction)
{
    public void Validate()
    {
        if (string.IsNullOrWhiteSpace(AssetId))
            throw new InvalidDataException("Listening audio asset ID is required.");
        if (string.IsNullOrWhiteSpace(Locale))
            throw new InvalidDataException("Listening audio locale is required.");
        if (UnitKind is ListeningAudioUnitKind.Phrase or ListeningAudioUnitKind.Sentence or ListeningAudioUnitKind.Passage)
        {
            if (string.IsNullOrWhiteSpace(PackId))
                throw new InvalidDataException("Phrase/sentence/passage Listening audio requires a pack ID.");
        }

        ReplayPolicy?.Validate();
        var speakerIds = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (ListeningSpeakerMetadata speaker in Speakers ?? Array.Empty<ListeningSpeakerMetadata>())
        {
            speaker.Validate();
            if (!speakerIds.Add(speaker.SpeakerId))
                throw new InvalidDataException("Listening speaker IDs must be unique within an audio asset.");
        }
        Transcript?.Validate(speakerIds);
        foreach (ListeningComprehensionPrompt prompt in Prompts ?? Array.Empty<ListeningComprehensionPrompt>())
            prompt.Validate();
    }
}

/// <summary>
/// Explicit approval token for production phrase/sentence/passage audio.
/// The default is always unapproved. A local file by itself is not approval.
/// </summary>
internal sealed record ListeningAudioPackApproval(
    string PackId,
    string ApprovalReference,
    bool ApprovedForProduction)
{
    public static ListeningAudioPackApproval Unapproved(string packId) =>
        new(packId ?? string.Empty, string.Empty, false);

    public bool MatchesApprovedPack(string packId) =>
        ApprovedForProduction &&
        !string.IsNullOrWhiteSpace(ApprovalReference) &&
        string.Equals(PackId, packId, StringComparison.OrdinalIgnoreCase);
}
