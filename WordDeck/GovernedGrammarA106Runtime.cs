using System.Runtime.CompilerServices;

namespace WordDeck;

internal enum GovernedGrammarMasteryStage
{
    FamiliarityExposure = 1,
    ControlledMastery = 2,
    ProductiveMastery = 3
}

internal enum GovernedGrammarEvidenceChannel
{
    Typed,
    Spoken,
    Mixed,
    HumanReview
}

internal enum GovernedGrammarExposureClass
{
    Study,
    Transfer,
    FastTrackVerify,
    UnseenTransferProtected
}

internal sealed record GovernedGrammarAtomicCeiling(
    string AtomicSkillId,
    string LevelId,
    GovernedGrammarMasteryStage HighestStage);

internal sealed record GovernedGrammarItemContract(
    string ItemId,
    GovernedGrammarEvidenceChannel Channel,
    GovernedGrammarExposureClass ExposureClass,
    IReadOnlyList<string> AtomicSkillIds,
    bool ProtectedEvidence,
    bool RequiresNoHintReveal,
    string? ProtectedSiblingGroupId,
    string? ConflictWithItemId,
    bool ListeningEvidenceSupported,
    string? AudioAssetId);

internal sealed record GovernedGrammarAttemptDecision(
    string ItemId,
    bool Correct,
    bool ProtectedEvidenceEligible,
    bool MayContributeToAuthorizedMasteryDerivation,
    string ReasonCode,
    IReadOnlyList<GovernedGrammarAtomicCeiling> AtomicCeilings);

/// <summary>
/// Exact governed-content binding for Deep Grammar A1 / G-A1-06 Present Continuous.
///
/// This class deliberately reuses the existing LearnerCourseState sidecar,
/// SpeechPracticeRuntime, GrammarSkillCatalog and adaptive target model. It does
/// not create a second progress/mastery system. It records attributable facts;
/// approved assessment/mastery rules remain responsible for deriving mastery.
/// </summary>
internal sealed class GovernedGrammarA106Runtime
{
    public const string CourseId = "grammar-a1";
    public const string ModuleId = "G-A1-06";
    public const string CompatibilityAnchor = "present-continuous";
    public const string GrammarSkillId = "present.continuous";
    public const string PathId = "deep-grammar:grammar-a1:G-A1-06";

    public const string SourceDocumentId = "12ujFMeyM9nrgLhLo7Xv5xSNEl4aGX8LDPYrt_bZdSFE";
    public const string SourceRevision = "ANLCKQnm0_8JCGi5Rb3zod8B4MBO7hgtJWl4VUEr_ZHCVL55XS05J6syEYlMzuvO9_6Q12izcLbf1N_L4sBnpmsTyIdTu4H94LsF99n1Fw";
    public const string IndependentQaDocumentId = "1zQ8U0lnTc95x_tNK9O8UqSyRw6sN6L5G0mCrSXTN8LM";
    public const string IndependentQaRevision = "ANLCKQkRO431xxtUM_fUZPKjBx-2ATvvQgZqpv11Q5OUlhkB1BJNlyszqsQIUibywn9Fzd3LRIoJV87l6qXdmVlmy41sN_YRd1IQwiDcPQ";
    public const string IntegrationRecordId = "1PlzllAR0Nz42E9CtK1VdiO8AioLGOkqkOS_UzCqu_TU";
    public const string IntegrationRevision = "ANLCKQk4_iQMtooBeVyDJ-hkIb5P0EENo7g5bwbUpY93M2ukWS8g64HsLNc8oQeVq8k_UVPuCA7Uk3zHfwsB_aYLPdkH-vgYGypCROKwFA";

    private const string ProtectedSiblingGroup = "GA106-MULTIACTOR-CURRENT-01";
    private const string S0604TargetId = "spoken_repair/negative_architecture";

    private static readonly IReadOnlyDictionary<string, GovernedGrammarAtomicCeiling> AtomicCeilings =
        new Dictionary<string, GovernedGrammarAtomicCeiling>(StringComparer.OrdinalIgnoreCase)
        {
            ["present.continuous-form"] = new("present.continuous-form", "A1", GovernedGrammarMasteryStage.ProductiveMastery),
            ["present.continuous-use"] = new("present.continuous-use", "A1", GovernedGrammarMasteryStage.ControlledMastery),
            ["present.state-dynamic-basic"] = new("present.state-dynamic-basic", "A1", GovernedGrammarMasteryStage.FamiliarityExposure),
            ["present.simple-vs-continuous"] = new("present.simple-vs-continuous", "A1", GovernedGrammarMasteryStage.FamiliarityExposure)
        };

    private static readonly IReadOnlyDictionary<string, GovernedGrammarItemContract> Items =
        new Dictionary<string, GovernedGrammarItemContract>(StringComparer.OrdinalIgnoreCase)
        {
            ["FT06-05"] = new(
                "FT06-05",
                GovernedGrammarEvidenceChannel.Typed,
                GovernedGrammarExposureClass.FastTrackVerify,
                new[] { "present.continuous-use", "present.simple-vs-continuous" },
                ProtectedEvidence: true,
                RequiresNoHintReveal: true,
                ProtectedSiblingGroupId: null,
                ConflictWithItemId: null,
                ListeningEvidenceSupported: false,
                AudioAssetId: null),
            ["FT06-06"] = new(
                "FT06-06",
                GovernedGrammarEvidenceChannel.Typed,
                GovernedGrammarExposureClass.FastTrackVerify,
                new[] { "present.continuous-form" },
                ProtectedEvidence: true,
                RequiresNoHintReveal: true,
                ProtectedSiblingGroupId: ProtectedSiblingGroup,
                ConflictWithItemId: "UT06-03",
                ListeningEvidenceSupported: false,
                AudioAssetId: null),
            ["UT06-03"] = new(
                "UT06-03",
                GovernedGrammarEvidenceChannel.Typed,
                GovernedGrammarExposureClass.UnseenTransferProtected,
                new[] { "present.continuous-form" },
                ProtectedEvidence: true,
                RequiresNoHintReveal: true,
                ProtectedSiblingGroupId: ProtectedSiblingGroup,
                ConflictWithItemId: "FT06-06",
                ListeningEvidenceSupported: false,
                AudioAssetId: null),
            ["S06-04"] = new(
                "S06-04",
                GovernedGrammarEvidenceChannel.Spoken,
                GovernedGrammarExposureClass.Study,
                new[] { "present.continuous-form" },
                ProtectedEvidence: false,
                RequiresNoHintReveal: false,
                ProtectedSiblingGroupId: null,
                ConflictWithItemId: null,
                ListeningEvidenceSupported: false,
                AudioAssetId: null)
        };

    private readonly LearnerCourseStateStore _store;
    private readonly Func<string> _eventIdFactory;
    private readonly Func<DateTimeOffset> _clock;

    public GovernedGrammarA106Runtime(LearnerCourseStateStore store)
        : this(store, CreateEventId, () => DateTimeOffset.UtcNow)
    {
    }

    internal GovernedGrammarA106Runtime(
        LearnerCourseStateStore store,
        Func<string> eventIdFactory,
        Func<DateTimeOffset> clock)
    {
        _store = store ?? throw new ArgumentNullException(nameof(store));
        _eventIdFactory = eventIdFactory ?? throw new ArgumentNullException(nameof(eventIdFactory));
        _clock = clock ?? throw new ArgumentNullException(nameof(clock));
        RequireCanonicalRuntimeBinding();
    }

    public static GovernedGrammarItemContract GetItem(string itemId)
    {
        string id = RequireItemId(itemId);
        if (!Items.TryGetValue(id, out GovernedGrammarItemContract? item))
            throw new InvalidDataException($"G-A1-06 governed runtime does not own item '{id}'.");
        return item;
    }

    public static GovernedGrammarAtomicCeiling GetAtomicCeiling(string atomicSkillId)
    {
        if (string.IsNullOrWhiteSpace(atomicSkillId))
            throw new ArgumentException("Atomic grammar skill id is required.", nameof(atomicSkillId));
        string id = atomicSkillId.Trim();
        if (!AtomicCeilings.TryGetValue(id, out GovernedGrammarAtomicCeiling? ceiling))
            throw new InvalidDataException($"G-A1-06 does not own atomic grammar node '{id}'.");
        return ceiling;
    }

    public static bool IsWithinAtomicCeiling(
        string atomicSkillId,
        string levelId,
        GovernedGrammarMasteryStage requestedStage)
    {
        if (!Enum.IsDefined(requestedStage) || string.IsNullOrWhiteSpace(levelId))
            return false;
        GovernedGrammarAtomicCeiling ceiling = GetAtomicCeiling(atomicSkillId);
        int requestedLevel = CefrRank(levelId.Trim());
        int ceilingLevel = CefrRank(ceiling.LevelId);
        return requestedLevel >= 0 && requestedLevel <= ceilingLevel && requestedStage <= ceiling.HighestStage;
    }

    public static AdaptivePracticeCandidate CreateAdaptiveCandidate(string dictionaryId)
    {
        if (string.IsNullOrWhiteSpace(dictionaryId) || !string.Equals(dictionaryId, dictionaryId.Trim(), StringComparison.Ordinal))
            throw new InvalidDataException("G-A1-06 adaptive dictionary identity must be canonical non-blank text.");
        RequireCanonicalRuntimeBinding();
        return new AdaptivePracticeCandidate(
            dictionaryId,
            GrammarSkillId,
            AdaptiveTargetKind.GrammarSkill,
            new HashSet<AdaptivePracticeMode> { AdaptivePracticeMode.Grammar });
    }

    /// <summary>
    /// Records learner-visible administration. Safe prompt administration does
    /// not by itself invalidate the same protected item, but it immediately
    /// retires a reciprocal protected sibling for this learner, as governed by
    /// G-A1-06 D2. Answer-bearing exposure is represented fail-closed by a reveal.
    /// </summary>
    public LearnerCourseState RecordExposure(
        string itemId,
        bool answerBearing = false,
        int hintUses = 0,
        int revealUses = 0)
    {
        GovernedGrammarItemContract item = GetItem(itemId);
        RequireCounters(hintUses, revealUses);
        LearnerCourseState state = _store.Load();
        int effectiveRevealUses = answerBearing ? checked(revealUses + 1) : revealUses;
        bool unseenAtAdministration = item.ProtectedEvidence &&
            !HasAnyActivityForItem(state, item.ItemId) &&
            !HasConflictingSiblingActivity(state, item);

        state.EvidenceHistory.Add(NewEvidence(
            item,
            LearnerActivityKind.Exposure,
            objectiveId: null,
            skillId: GrammarSkillId,
            completed: true,
            correct: null,
            unseenAtAdministration,
            productive: false,
            transfer: false,
            hintUses,
            effectiveRevealUses,
            attemptNumber: 1));
        _store.Save(state);
        return state;
    }

    /// <summary>
    /// Records a protected Fast Track / unseen-transfer attempt as evidence facts
    /// only. No MasteryClaim, SkillLevelEstimate or adaptive route is synthesized.
    /// Reuse, reveal/hint contamination and reciprocal sibling exposure all fail
    /// closed for qualifying evidence.
    /// </summary>
    public GovernedGrammarAttemptDecision RecordProtectedAttempt(
        string itemId,
        bool correct,
        int hintUses = 0,
        int revealUses = 0,
        bool isTransfer = true)
    {
        GovernedGrammarItemContract item = GetItem(itemId);
        if (!item.ProtectedEvidence)
            throw new InvalidDataException($"G-A1-06 item '{item.ItemId}' is not governed protected evidence.");
        RequireCounters(hintUses, revealUses);

        LearnerCourseState state = _store.Load();
        bool siblingClear = !HasConflictingSiblingActivity(state, item);
        bool priorSameItemClean = !HasPriorDisqualifyingSameItemActivity(state, item.ItemId);
        bool noCurrentContamination = hintUses == 0 && revealUses == 0;
        bool eligible = siblingClear && priorSameItemClean && noCurrentContamination;
        bool mayContribute = correct && eligible;

        string reason = !siblingClear ? "PROTECTED_SIBLING_RETIRED"
            : !priorSameItemClean ? "ITEM_REUSED_OR_PRIORLY_CONTAMINATED"
            : !noCurrentContamination ? "HINT_OR_REVEAL_CONTAMINATED"
            : !correct ? "INCORRECT_PRACTICE_ONLY"
            : "QUALIFYING_GOVERNED_EVIDENCE";

        foreach (string atomicSkillId in item.AtomicSkillIds)
        {
            _ = GetAtomicCeiling(atomicSkillId);
            state.EvidenceHistory.Add(NewEvidence(
                item,
                LearnerActivityKind.Assessment,
                atomicSkillId,
                GrammarSkillId,
                completed: true,
                correct,
                unseen: eligible,
                productive: true,
                transfer: isTransfer,
                hintUses,
                revealUses,
                attemptNumber: 1));
        }
        _store.Save(state);

        return new GovernedGrammarAttemptDecision(
            item.ItemId,
            correct,
            eligible,
            mayContribute,
            reason,
            item.AtomicSkillIds.Select(GetAtomicCeiling).ToArray());
    }

    /// <summary>
    /// The only typed fallback owned by this exact binding is S06-04. It remains
    /// practice and is never labeled as spoken/listening mastery.
    /// </summary>
    public LearnerCourseState RecordS0604TypedFallbackPractice(bool? correct, int attemptNumber = 1)
    {
        if (attemptNumber < 1)
            throw new ArgumentOutOfRangeException(nameof(attemptNumber), "Attempt number must be at least 1.");
        GovernedGrammarItemContract item = GetItem("S06-04");
        LearnerCourseState state = _store.Load();
        state.EvidenceHistory.Add(NewEvidence(
            item,
            LearnerActivityKind.Practice,
            item.AtomicSkillIds.Single(),
            skillId: "typed-fallback",
            completed: true,
            correct,
            unseen: false,
            productive: false,
            transfer: false,
            hintUses: 0,
            revealUses: 0,
            attemptNumber));
        _store.Save(state);
        return state;
    }

    public static SpeechPracticeRequest CreateS0604SpeechRequest(
        string expectedUtterance,
        SpeechSubmissionKind submissionKind)
    {
        if (string.IsNullOrWhiteSpace(expectedUtterance))
            throw new ArgumentException("S06-04 expected spoken repair must not be blank.", nameof(expectedUtterance));
        if (!Enum.IsDefined(submissionKind))
            throw new InvalidDataException("S06-04 speech submission kind is invalid.");

        return new SpeechPracticeRequest(
            new SpeechPracticeBinding(
                CourseId,
                ModuleId,
                "S06-04",
                S0604TargetId,
                SourceRevision,
                IntegrationRecordId,
                IntegrationRevision),
            SpeechPracticeMode.Speaking,
            submissionKind,
            expectedUtterance.Trim(),
            IsProtectedAssessment: false);
    }

    public bool IsProtectedItemAvailable(string itemId)
    {
        GovernedGrammarItemContract item = GetItem(itemId);
        if (!item.ProtectedEvidence) return false;
        LearnerCourseState state = _store.Load();
        return !HasConflictingSiblingActivity(state, item) &&
               !HasPriorDisqualifyingSameItemActivity(state, item.ItemId);
    }

    public static bool SupportsListeningEvidence(string itemId) => GetItem(itemId).ListeningEvidenceSupported;

    public static string? GetAudioAssetId(string itemId) => GetItem(itemId).AudioAssetId;

    private LearnerEvidenceEvent NewEvidence(
        GovernedGrammarItemContract item,
        LearnerActivityKind activityKind,
        string? objectiveId,
        string skillId,
        bool completed,
        bool? correct,
        bool unseen,
        bool productive,
        bool transfer,
        int hintUses,
        int revealUses,
        int attemptNumber)
    {
        string eventId = _eventIdFactory()?.Trim() ?? string.Empty;
        if (string.IsNullOrWhiteSpace(eventId))
            throw new InvalidDataException("G-A1-06 learner evidence requires a non-blank event id.");
        return new LearnerEvidenceEvent
        {
            EventId = eventId,
            ActivityKind = activityKind,
            PathId = PathId,
            CourseId = CourseId,
            ModuleId = ModuleId,
            ObjectiveId = objectiveId,
            SkillId = skillId,
            ItemId = item.ItemId,
            Completed = completed,
            Correct = correct,
            IsUnseenMaterial = unseen,
            IsProductivePerformance = productive,
            IsTransferPerformance = transfer,
            HintUses = hintUses,
            RevealUses = revealUses,
            AttemptNumber = attemptNumber,
            OccurredAtUtc = _clock()
        };
    }

    private static bool HasConflictingSiblingActivity(
        LearnerCourseState state,
        GovernedGrammarItemContract item) =>
        !string.IsNullOrWhiteSpace(item.ConflictWithItemId) &&
        HasAnyActivityForItem(state, item.ConflictWithItemId);

    private static bool HasAnyActivityForItem(LearnerCourseState state, string itemId) =>
        state.EvidenceHistory.Any(evidence =>
            evidence is not null &&
            string.Equals(evidence.CourseId, CourseId, StringComparison.OrdinalIgnoreCase) &&
            string.Equals(evidence.ModuleId, ModuleId, StringComparison.OrdinalIgnoreCase) &&
            string.Equals(evidence.ItemId, itemId, StringComparison.OrdinalIgnoreCase));

    private static bool HasPriorDisqualifyingSameItemActivity(LearnerCourseState state, string itemId) =>
        state.EvidenceHistory.Any(evidence =>
            evidence is not null &&
            string.Equals(evidence.CourseId, CourseId, StringComparison.OrdinalIgnoreCase) &&
            string.Equals(evidence.ModuleId, ModuleId, StringComparison.OrdinalIgnoreCase) &&
            string.Equals(evidence.ItemId, itemId, StringComparison.OrdinalIgnoreCase) &&
            (evidence.ActivityKind != LearnerActivityKind.Exposure || evidence.HintUses > 0 || evidence.RevealUses > 0));

    private static string RequireItemId(string itemId)
    {
        if (string.IsNullOrWhiteSpace(itemId))
            throw new ArgumentException("G-A1-06 item id is required.", nameof(itemId));
        return itemId.Trim();
    }

    private static void RequireCounters(int hintUses, int revealUses)
    {
        if (hintUses < 0 || revealUses < 0)
            throw new ArgumentOutOfRangeException(nameof(hintUses), "Hint and reveal counters cannot be negative.");
    }

    private static int CefrRank(string levelId) => levelId.Trim().ToUpperInvariant() switch
    {
        "PRE-A1" => 0,
        "A1" => 1,
        "A2" => 2,
        "B1" => 3,
        "B2" => 4,
        "C1" => 5,
        _ => -1
    };

    private static void RequireCanonicalRuntimeBinding()
    {
        if (!GrammarSkillCatalog.ById.TryGetValue(GrammarSkillId, out GrammarSkill? skill))
            throw new InvalidDataException($"G-A1-06 canonical grammar skill '{GrammarSkillId}' is missing.");
        if (!string.Equals(skill.Cefr, "A1", StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException($"G-A1-06 canonical grammar skill '{GrammarSkillId}' no longer has the governed A1 level.");
    }

    private static string CreateEventId() => "ga106.event." + Guid.NewGuid().ToString("N");
}

internal static class GovernedGrammarA106RuntimeSelfTestBootstrap
{
    [ModuleInitializer]
    internal static void Initialize()
    {
        if (Environment.GetCommandLineArgs().Any(arg => arg.Equals("--self-test", StringComparison.OrdinalIgnoreCase)))
            GovernedGrammarA106RuntimeSelfTest.Run();
    }
}

internal static class GovernedGrammarA106RuntimeSelfTest
{
    public static void Run()
    {
        CanonicalAndAtomicCeilingsAreFailClosed();
        ProtectedSiblingRetirementSurvivesRestart();
        FastTrackRevealCannotBecomeMasteryEvidence();
        EvidenceFactsDoNotInventMasteryOrAdaptiveRoute();
        S0604TypedFallbackCannotBecomeSpeechOrListeningMastery();
    }

    private static void CanonicalAndAtomicCeilingsAreFailClosed()
    {
        AdaptivePracticeCandidate candidate = GovernedGrammarA106Runtime.CreateAdaptiveCandidate("oxford");
        Require(candidate.TargetId == GovernedGrammarA106Runtime.GrammarSkillId,
            "Governed module did not map to the existing canonical Grammar target.");
        Require(GovernedGrammarA106Runtime.IsWithinAtomicCeiling(
            "present.continuous-form", "A1", GovernedGrammarMasteryStage.ProductiveMastery),
            "A1 productive form evidence was incorrectly rejected.");
        Require(!GovernedGrammarA106Runtime.IsWithinAtomicCeiling(
            "present.continuous-use", "A2", GovernedGrammarMasteryStage.ProductiveMastery),
            "G-A1-06 must not promote continuous-use to its later A2 productive-mastery state.");
        Require(!GovernedGrammarA106Runtime.IsWithinAtomicCeiling(
            "present.state-dynamic-basic", "A1", GovernedGrammarMasteryStage.ControlledMastery),
            "G-A1-06 must cap state/dynamic evidence at A1 familiarity/exposure.");
        Require(!GovernedGrammarA106Runtime.IsWithinAtomicCeiling(
            "present.simple-vs-continuous", "B1", GovernedGrammarMasteryStage.ProductiveMastery),
            "G-A1-06 must not promote broad Simple-vs-Continuous evidence to B1 productive mastery.");
    }

    private static void ProtectedSiblingRetirementSurvivesRestart()
    {
        string root = NewTempRoot();
        try
        {
            int sequence = 0;
            var store = new LearnerCourseStateStore(root);
            var runtime = new GovernedGrammarA106Runtime(
                store,
                () => "ga106.test." + (++sequence).ToString("D4"),
                () => new DateTimeOffset(2026, 9, 13, 3, 30, sequence, TimeSpan.Zero));

            runtime.RecordExposure("FT06-06");
            Require(!runtime.IsProtectedItemAvailable("UT06-03"),
                "Administering FT06-06 must retire reciprocal UT06-03 protected evidence for this learner.");
            Require(runtime.IsProtectedItemAvailable("FT06-06"),
                "Safe prompt administration must not invalidate the same FT06-06 item before commitment.");

            var restarted = new GovernedGrammarA106Runtime(
                new LearnerCourseStateStore(root),
                () => "ga106.restart." + (++sequence).ToString("D4"),
                () => new DateTimeOffset(2026, 9, 13, 3, 31, sequence, TimeSpan.Zero));
            Require(!restarted.IsProtectedItemAvailable("UT06-03"),
                "Reciprocal protected-sibling retirement did not survive reopen.");

            GovernedGrammarAttemptDecision decision = restarted.RecordProtectedAttempt("FT06-06", correct: true);
            Require(decision.ProtectedEvidenceEligible && decision.MayContributeToAuthorizedMasteryDerivation,
                "Clean first FT06-06 commitment should remain eligible after safe prompt administration.");
            Require(!restarted.IsProtectedItemAvailable("FT06-06"),
                "A submitted protected item must not be reusable as fresh protected evidence.");
        }
        finally
        {
            TryDeleteDirectory(root);
        }
    }

    private static void FastTrackRevealCannotBecomeMasteryEvidence()
    {
        string root = NewTempRoot();
        try
        {
            int sequence = 0;
            var runtime = new GovernedGrammarA106Runtime(
                new LearnerCourseStateStore(root),
                () => "ga106.fasttrack." + (++sequence).ToString("D4"),
                () => new DateTimeOffset(2026, 9, 13, 3, 32, sequence, TimeSpan.Zero));
            runtime.RecordExposure("FT06-05", answerBearing: true);
            GovernedGrammarAttemptDecision contaminated = runtime.RecordProtectedAttempt("FT06-05", correct: true);
            Require(!contaminated.ProtectedEvidenceEligible && !contaminated.MayContributeToAuthorizedMasteryDerivation,
                "Answer-bearing FT06-05 exposure must fail closed even after a correct response.");
            Require(contaminated.ReasonCode == "ITEM_REUSED_OR_PRIORLY_CONTAMINATED",
                "FT06-05 contamination did not produce the expected fail-closed reason.");
        }
        finally
        {
            TryDeleteDirectory(root);
        }
    }

    private static void EvidenceFactsDoNotInventMasteryOrAdaptiveRoute()
    {
        string root = NewTempRoot();
        try
        {
            int sequence = 0;
            var store = new LearnerCourseStateStore(root);
            var runtime = new GovernedGrammarA106Runtime(
                store,
                () => "ga106.facts." + (++sequence).ToString("D4"),
                () => new DateTimeOffset(2026, 9, 13, 3, 33, sequence, TimeSpan.Zero));
            GovernedGrammarAttemptDecision clean = runtime.RecordProtectedAttempt("FT06-05", correct: true);
            Require(clean.MayContributeToAuthorizedMasteryDerivation,
                "Clean no-hint FT06-05 evidence should remain available to an authorized mastery rule.");
            LearnerCourseState persisted = store.Load();
            Require(persisted.MasteryByObjectiveId.Count == 0,
                "Governed activity facts must not synthesize mastery claims by themselves.");
            Require(persisted.SkillLevelsBySkillId.Count == 0,
                "Governed activity facts must not synthesize CEFR levels by themselves.");
            Require(persisted.AdaptiveRouteByPathId.Count == 0,
                "Governed activity facts must not synthesize a Fast Track/adaptive route by themselves.");
        }
        finally
        {
            TryDeleteDirectory(root);
        }
    }

    private static void S0604TypedFallbackCannotBecomeSpeechOrListeningMastery()
    {
        Require(!GovernedGrammarA106Runtime.SupportsListeningEvidence("S06-04"),
            "S06-04 must declare ListeningEvidence=NONE.");
        Require(GovernedGrammarA106Runtime.GetAudioAssetId("S06-04") is null,
            "S06-04 must declare AudioAssetId=NONE.");

        SpeechPracticeRequest request = GovernedGrammarA106Runtime.CreateS0604SpeechRequest(
            "Mina isn't writing a message; she's reading a message.",
            SpeechSubmissionKind.TypedFallback);
        var speech = new SpeechPracticeRuntime(new NeverCaptureProvider(), new NeverJudgeProvider());
        SpeechPracticeOutcome outcome = speech.EvaluateAsync(request).GetAwaiter().GetResult();
        Require(outcome.CountsAsPractice && !outcome.MasteryEligible &&
                outcome.ReasonCode == "TYPED_FALLBACK_PRACTICE_ONLY",
            "S06-04 typed fallback was incorrectly promoted to spoken mastery evidence.");

        string root = NewTempRoot();
        try
        {
            int sequence = 0;
            var store = new LearnerCourseStateStore(root);
            var runtime = new GovernedGrammarA106Runtime(
                store,
                () => "ga106.speech." + (++sequence).ToString("D4"),
                () => new DateTimeOffset(2026, 9, 13, 3, 34, sequence, TimeSpan.Zero));
            runtime.RecordS0604TypedFallbackPractice(correct: true);
            LearnerEvidenceEvent evidence = store.Load().EvidenceHistory.Single();
            Require(evidence.SkillId == "typed-fallback" && !evidence.IsProductivePerformance &&
                    evidence.ActivityKind == LearnerActivityKind.Practice,
                "S06-04 typed fallback persistence must remain explicit practice-only evidence.");
        }
        finally
        {
            TryDeleteDirectory(root);
        }
    }

    private static string NewTempRoot()
    {
        string root = Path.Combine(Path.GetTempPath(), "WordDeck G-A1-06 " + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        return root;
    }

    private static void TryDeleteDirectory(string root)
    {
        try { Directory.Delete(root, recursive: true); } catch { }
    }

    private static void Require(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException("GovernedGrammarA106RuntimeSelfTest: " + message);
    }

    private sealed class NeverCaptureProvider : ISpeechCaptureProvider
    {
        public SpeechProviderQualification Qualification { get; } = new(
            "ga106-selftest-capture",
            "1",
            IsQualified: false,
            QualificationId: "none",
            QualificationRevision: "none",
            SpeechProviderCapabilities.None,
            SpeechRawAudioPolicy.EphemeralMemoryOnly);

        public Task<SpeechCaptureResult> CaptureAsync(
            SpeechPracticeRequest request,
            CancellationToken cancellationToken) =>
            throw new InvalidOperationException("Typed fallback must not invoke microphone capture.");
    }

    private sealed class NeverJudgeProvider : ISpeechJudge
    {
        public SpeechProviderQualification Qualification { get; } = new(
            "ga106-selftest-judge",
            "1",
            IsQualified: false,
            QualificationId: "none",
            QualificationRevision: "none",
            SpeechProviderCapabilities.None,
            SpeechRawAudioPolicy.EphemeralMemoryOnly);

        public Task<SpeechJudgementResult> JudgeAsync(
            SpeechPracticeRequest request,
            ReadOnlyMemory<byte> audio,
            CancellationToken cancellationToken) =>
            throw new InvalidOperationException("Typed fallback must not invoke speech judgement.");
    }
}
