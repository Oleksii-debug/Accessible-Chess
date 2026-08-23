namespace WordDeck;

internal sealed record SentenceCoachTargetOnlyPrompt(
    int TargetNumber,
    int TargetCount,
    string TargetEntryId,
    string TargetMeaningUkrainian,
    string UkrainianSentence,
    string EnglishCloze,
    string Instruction);

internal sealed record SentenceCoachTargetOnlyCheck(
    bool Accepted,
    bool SentenceComplete,
    string TargetEntryId,
    string Feedback,
    SentenceCoachTargetOnlyPrompt? NextPrompt);

/// <summary>
/// Product-facing Sentence Spelling state machine. One exact Oxford target form is
/// answered at a time even when a natural sentence carries two or three targets.
/// This keeps keyboard/NVDA interaction simple while preserving exact stable-ID
/// ownership and the fail-closed target-form rules from ContextTargetSpellingService.
/// </summary>
internal sealed class SentenceCoachTargetOnlySession
{
    private readonly IReadOnlyList<ContextTargetSpellingExercise> _exercises;
    private int _index;

    public int TargetCount => _exercises.Count;
    public int CurrentTargetNumber => _index + 1;
    public bool Complete => _index >= _exercises.Count;

    private SentenceCoachTargetOnlySession(IReadOnlyList<ContextTargetSpellingExercise> exercises)
    {
        if (exercises.Count is < 1 or > 3)
            throw new InvalidDataException("Sentence Spelling target-only session requires one, two, or three exact targets.");
        _exercises = exercises;
    }

    public static SentenceCoachTargetOnlySession Build(
        SentenceRecord sentence,
        IReadOnlyList<DictionaryEntry> targets,
        ContextTargetLexicon lexicon,
        DictionaryPackage dictionary,
        string sourceId,
        ContextCorpusKind sourceKind,
        string provenance,
        string license)
    {
        ArgumentNullException.ThrowIfNull(sentence);
        ArgumentNullException.ThrowIfNull(targets);
        ArgumentNullException.ThrowIfNull(lexicon);
        ArgumentNullException.ThrowIfNull(dictionary);
        sentence.Validate();

        string[] targetIds = targets
            .Select(target => ContextTargetIds.NormalizeSingle(target.Id))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
        if (targetIds.Length != targets.Count || targetIds.Length is < 1 or > 3)
            throw new InvalidDataException("Sentence Spelling target-only session requires one to three distinct stable target IDs.");

        ContextStableIdentityResolution.EnsureResolvedTargets(lexicon, targetIds);
        lexicon.EnsureDistinctLexicalTargets(targetIds);
        if (!targetIds.All(id => sentence.TargetEntryIds.Contains(id, StringComparer.OrdinalIgnoreCase)))
            throw new InvalidDataException("Sentence Spelling target-only session cannot attach a target ID that the selected sentence does not index.");

        var card = new ContextPracticeCard(
            sentence.Id,
            sentence.Ukrainian,
            sentence.English,
            targetIds,
            targetIds.Select(lexicon.LexicalKeyFor).ToArray(),
            new ContextDifficultyBreakdown(0, 0, 0, 0, 1, sentence.Length, 1, "Sentence Spelling UI target-only session"),
            sourceId,
            sourceKind,
            provenance,
            license,
            false,
            null,
            ContextGrammarMetadata.ExtractFromQualityFlags(sentence.QualityFlags),
            false);

        IReadOnlyList<ContextTargetSpellingExercise> exercises =
            ContextPracticeApplicationService.BuildTargetSpellingForAllTargets(card, lexicon, dictionary);
        return new SentenceCoachTargetOnlySession(exercises);
    }

    public SentenceCoachTargetOnlyPrompt CurrentPrompt()
    {
        if (Complete)
            throw new InvalidOperationException("Sentence Spelling target-only session is complete.");
        ContextTargetSpellingPrompt prompt = _exercises[_index].Prompt;
        return new SentenceCoachTargetOnlyPrompt(
            _index + 1,
            _exercises.Count,
            prompt.FocusTargetEntryId,
            prompt.TargetMeaningUkrainian,
            prompt.UkrainianSentence,
            prompt.EnglishCloze,
            prompt.Instruction);
    }

    public SentenceCoachTargetOnlyCheck Check(string typedTargetForm)
    {
        if (Complete)
            throw new InvalidOperationException("Sentence Spelling target-only session is complete.");

        ContextTargetSpellingExercise exercise = _exercises[_index];
        string targetId = exercise.Prompt.FocusTargetEntryId;
        ContextTargetSpellingResult result = exercise.Check(typedTargetForm ?? string.Empty);
        if (!result.Accepted)
            return new SentenceCoachTargetOnlyCheck(false, false, targetId, result.Feedback, CurrentPrompt());

        _index++;
        bool complete = Complete;
        return new SentenceCoachTargetOnlyCheck(
            true,
            complete,
            targetId,
            complete ? "Correct target form. Sentence exercise complete." : "Correct target form. Continue with the next target in this sentence.",
            complete ? null : CurrentPrompt());
    }

    public string RevealCurrentExpectedForm()
    {
        if (Complete)
            throw new InvalidOperationException("Sentence Spelling target-only session is complete.");
        return _exercises[_index].RevealExpectedForm();
    }
}
