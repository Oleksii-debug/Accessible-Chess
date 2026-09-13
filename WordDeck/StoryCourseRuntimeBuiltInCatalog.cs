namespace WordDeck;

/// <summary>
/// Small, release-bundled Story/Course catalog for content that has already passed
/// independent pedagogical QA and governed content integration. This is not a
/// replacement for the external package boundary: local approved packages are still
/// discovered separately. Built-in entries are deliberately explicit so a packaged
/// WordDeck executable cannot silently turn a Drive draft into learner-facing content.
/// </summary>
internal static class StoryCourseRuntimeBuiltInCatalog
{
    internal const string M07MissionRuntimeCourseId = "ce-st-m07-msn-runtime";
    internal const string M07MissionRuntimeUnitId = "ce-st-m07-msn-001-runtime";
    internal const string M07MissionGovernedObjectId = "CE-ST-M07-MSN-001";

    internal const string M07MissionSourceId = "1AYU_ccd9YV41w_PFEpDCTnQ_a--v4dN_ieIlCFIY-hs";
    internal const string M07MissionSourceRevision = "ANLCKQlU8Mwt95oINNVQ54Va2c94cQhhcHFyRb-cz2BLAXFBJREq-HnVW7TdbYeKx0fLFD7x_isdA1zW3vW8GUhVdnSx_8fYUBEnZpAt0A";
    internal const string M07MissionQaId = "1ZmwW-IbwlvBfTRGiXZEtTC5JKeIEurucQBnhSOFMTMo";
    internal const string M07MissionQaRevision = "ANLCKQlsYQDGqQpg6JDGaKsjcfbg0EXlNTRz0DNyAKoXTyDtIeU6AKbW5At6Rh-CO2_0dZNyjP2MBOMU-WGoB8e2mXbqI5kI4jUrWiJ6Ww";
    internal const string M07MissionIntegrationId = "1r6WT0yzrLEvglqBurOLLkUsnVhUH8F1PomJJqX6h3_I";
    internal const string M07MissionIntegrationRevision = "ANLCKQmp-Zxp_Po_3LyswLOFiPW04WO7vp-tclYXHx8dcS0ekgb_ZerGGEQE5EDb-S4oJ-MUxSTAKk1W2n1m-UbONGg_fX5b4x4HCJSaqg";

    private const string RightsHold =
        "HOLD_PENDING_CANONICAL_CONTENT_PROVENANCE_MANIFEST_AND_INDEPENDENT_RIGHTS_REVIEW";

    internal static IReadOnlyList<StoryCourseManifestContract> BuildApprovedManifests() =>
        new[] { BuildM07Mission(), StoryCourseRuntimeBuiltInA1M10Catalog.BuildManifest() };

    private static StoryCourseManifestContract BuildM07Mission()
    {
        StoryCourseProvenanceContract provenance = BuildM07Provenance();

        StoryCourseObjectiveContract askDestination = new(
            "ce-st-m07-msn-001-s01-objective",
            "Ask where the fictional hotel is while preserving the requested destination.",
            new[] { "interaction", "spoken_production_required_for_canonical_mission" });
        StoryCourseObjectiveContract recoverRoute = new(
            "ce-st-m07-msn-001-s02-objective",
            "Recover the changed two-step route atomically: STRAIGHT, then RIGHT at the bus stop.",
            new[] { "semantic_route_comprehension", "route_mediation", "no_listening_evidence" });
        StoryCourseObjectiveContract giveRoute = new(
            "ce-st-m07-msn-001-s03-objective",
            "Give the recovered two-step route using learner-generated spoken production when that channel is available.",
            new[] { "productive_route_language", "route_mediation", "spoken_production_required_for_canonical_mission" });
        StoryCourseObjectiveContract writeArrival = new(
            "ce-st-m07-msn-001-s04-objective",
            "Preserve the NEAR relation and write an original short route message.",
            new[] { "relation_semantics", "writing", "reading_to_writing_mediation" });
        StoryCourseObjectiveContract repairCommunication = new(
            "ce-st-m07-msn-001-s05-objective",
            "Request clarification instead of guessing when one critical mission fact is deliberately unavailable.",
            new[] { "repair_strategy", "recovery_mediation", "interaction", "no_listening_evidence" });

        StoryCourseSkillTargetReferenceContract[] targets =
        {
            Target("CE-ST-M01-TL015"), Target("CE-ST-M01-TL016"),
            Target("CE-ST-M01-TL017"), Target("CE-ST-M01-TL018"),
            Target("CE-ST-M07-TL005"), Target("CE-ST-M07-TL006"),
            Target("CE-ST-M07-TL007"), Target("CE-ST-M07-TL011"),
            Target("CE-ST-M07-TL012"), Target("CE-ST-M07-TL015"),
            Target("CE-ST-M07-TL017"), Target("CE-ST-M07-TL019"),
            Target("CE-ST-M07-TL020"), Target("CE-ST-M07-TL022")
        };

        StoryCourseTargetsContract unitTargets = new(
            Array.Empty<string>(),
            Array.Empty<string>())
        {
            SkillTargets = targets
        };

        StoryCourseNarrativeContract missionCard = new(
            "ce-st-m07-msn-001-context",
            StoryCourseNarrativeKind.Story,
            "Help a fictional traveller reach a hotel. Start: pharmacy. Destination: hotel. " +
            "Step 1: GO STRAIGHT. Step 2: TURN RIGHT at the bus stop. " +
            "Arrival relation: the hotel is NEAR the bus stop. " +
            "These are exposed Study facts. No exact matching audio is bound, so this mission produces no Listening evidence. " +
            "No real address, map, location permission or personal travel data is required.",
            Array.Empty<string>(),
            provenance);

        StoryCourseComprehensionTaskContract[] comprehension =
        {
            Bounded(
                "ce-st-m07-msn-001-s02-step1",
                "Stage S02. What is Step 1? Enter the route action only.",
                recoverRoute.ObjectiveId,
                "straight", "go straight"),
            Bounded(
                "ce-st-m07-msn-001-s02-step2-direction",
                "Stage S02. What is the Step 2 direction? Enter the direction only.",
                recoverRoute.ObjectiveId,
                "right", "turn right"),
            Bounded(
                "ce-st-m07-msn-001-s02-step2-landmark",
                "Stage S02. At which landmark do you turn right?",
                recoverRoute.ObjectiveId,
                "bus stop", "the bus stop"),
            Bounded(
                "ce-st-m07-msn-001-s02-order",
                "Stage S02. Enter the two route actions in order using 'then'.",
                recoverRoute.ObjectiveId,
                "straight then right", "go straight then turn right"),
            Bounded(
                "ce-st-m07-msn-001-s04-relation",
                "Stage S04. Where is the hotel in relation to the bus stop? Enter the relation.",
                writeArrival.ObjectiveId,
                "near", "near the bus stop", "the hotel is near the bus stop")
        };

        StoryCourseProductiveTaskContract[] productive =
        {
            Productive(
                "ce-st-m07-msn-001-s01-speaking",
                StoryCourseProductiveChannel.Speaking,
                "Stage S01. Ask where the hotel is. Canonical mission completion requires learner-generated spoken production; a typed response is Study fallback only and must not count as Speaking.",
                askDestination.ObjectiveId,
                "policy.external.ce-st-m07-s01-spoken-required"),
            Productive(
                "ce-st-m07-msn-001-s03-speaking",
                StoryCourseProductiveChannel.Speaking,
                "Stage S03. Give the two-step route from the recovered facts: STRAIGHT, then RIGHT at the bus stop. Canonical mission completion requires the real spoken channel; typed fallback must never backfill Speaking or intelligibility evidence.",
                giveRoute.ObjectiveId,
                "policy.external.ce-st-m07-s03-spoken-required"),
            Productive(
                "ce-st-m07-msn-001-s04-writing",
                StoryCourseProductiveChannel.Writing,
                "Stage S04. Write your own short route message. Preserve the fictional destination hotel, STRAIGHT then RIGHT at the bus stop, and the fact that the hotel is NEAR the bus stop. Do not copy a completed model answer.",
                writeArrival.ObjectiveId,
                "policy.external.ce-st-m07-s04-writing-unjudged"),
            Productive(
                "ce-st-m07-msn-001-s05-speaking",
                StoryCourseProductiveChannel.Speaking,
                "Stage S05. If one critical fact is withheld, request clarification instead of guessing. Use one appropriate learned repair phrase, then continue only after the fact is supplied. This controlled Study branch is not Listening evidence; typed fallback is not Speaking.",
                repairCommunication.ObjectiveId,
                "policy.external.ce-st-m07-s05-repair-spoken-required")
        };

        StoryCourseUnitContract unit = new(
            M07MissionRuntimeUnitId,
            "ce-st-m07",
            "Help Me Get There — governed M07 mission",
            new[]
            {
                askDestination.ObjectiveId,
                recoverRoute.ObjectiveId,
                giveRoute.ObjectiveId,
                writeArrival.ObjectiveId,
                repairCommunication.ObjectiveId
            },
            unitTargets,
            new[] { missionCard },
            comprehension,
            productive,
            Checkpoint: null,
            provenance);

        StoryCourseModuleContract module = new(
            "ce-st-m07",
            "ce-st-starter",
            "Find and Reach a Place",
            new[] { askDestination, recoverRoute, giveRoute, writeArrival, repairCommunication },
            new[] { unit });

        StoryCourseLevelContract level = new(
            "ce-st-starter",
            "Pre-A1",
            "Complete English Starter / Pre-A1",
            7,
            new[] { module });

        return new StoryCourseManifestContract(
            M07MissionRuntimeCourseId,
            "Complete English Starter — M07 Mission — Help Me Get There",
            StoryCourseCurriculumAuthority.ApprovedCurriculum,
            ClaimsCompleteEnglishCourse: false,
            new[] { level },
            provenance);
    }

    private static StoryCourseProvenanceContract BuildM07Provenance() => new(
        StoryCourseContentOrigin.WordDeckAuthored,
        $"Drive:{M07MissionSourceId}@{M07MissionSourceRevision}",
        "1.1",
        RightsHold,
        $"Governed object {M07MissionGovernedObjectId}; independent QA Drive:{M07MissionQaId}@{M07MissionQaRevision}; " +
        $"content integration Drive:{M07MissionIntegrationId}@{M07MissionIntegrationRevision}. " +
        "Commercial/public redistribution remains HOLD until the project-wide provenance/release gate passes.");

    private static StoryCourseSkillTargetReferenceContract Target(string targetRef) =>
        new(StoryCourseSkillTargetReferenceContract.CourseTargetDomain, targetRef);

    private static StoryCourseComprehensionTaskContract Bounded(
        string taskId,
        string prompt,
        string objectiveId,
        params string[] accepted) =>
        new(
            taskId,
            StoryCourseComprehensionKind.BoundedResponse,
            prompt,
            new[] { objectiveId },
            accepted);

    private static StoryCourseProductiveTaskContract Productive(
        string taskId,
        StoryCourseProductiveChannel channel,
        string prompt,
        string objectiveId,
        string evaluationPolicyId) =>
        new(
            taskId,
            channel,
            prompt,
            new[] { objectiveId },
            evaluationPolicyId);
}
