namespace WordDeck;

/// <summary>
/// Exact learner-runtime binding for the independently governed CE-A1-M10
/// formative Module Mission bank. This is a bounded A1 slice, not a claim that
/// the whole Complete English A1 course is complete.
/// </summary>
internal static class StoryCourseRuntimeBuiltInA1M10Catalog
{
    internal const string RuntimeCourseId = "ce-a1-m10-msn-runtime";
    internal const string RuntimeLevelId = "ce-a1-a1";
    internal const string RuntimeModuleId = "ce-a1-m10";

    internal const string SourceId = "1IyiVOYna2MeLgj0v1SCsOMJHcTEiOliISJH7ck77thw";
    internal const string SourceRevision = "ANLCKQkSIDip3t0EzWjeE1PgIlyHXZ-V7QM_ADzmBhjeTMlDfPMOPpkkgLj8Z43w9DRhZWmrBSrkTAjSYOyzKOYkSLVRIsDBL49YiZcVyg";
    internal const string QaId = "1hKjOMGkkdGINorf0481h1bU3sDlcaoc3BQhZc84B6ho";
    internal const string QaRevision = "ANLCKQnBKGoPyPV61Fo1Flt9N7xCdQKb_PWA0tak34xEA1RQ0TmwMPIYys3tzYtruvgBOa04JyJo0Re92UM9LxvoelR_OCd6GS05-M1ZGQ";
    internal const string IntegrationId = "1D1CfRaYRn7Li1x2p5Qr-mWlLx4C1Z5EI7A3TNecrDMM";
    internal const string IntegrationRevision = "ANLCKQl_2dlq-Cz-lJYzq_ZVHI0Za_KE1gcyXIfeH8QwyFVYKbVnlEAZQaTOOhK3KzqKOSkyqsR5LslHs9KQvoHl9xdbqrAB0rMnsz3kTg";

    private const string RightsHold =
        "HOLD_PENDING_CANONICAL_CONTENT_PROVENANCE_MANIFEST_AND_INDEPENDENT_RIGHTS_REVIEW";

    private sealed record MissionDefinition(
        string GovernedId,
        string RuntimeUnitId,
        string Title,
        string[] TargetIds,
        string[] EvidenceTargetIds,
        string[] DeepPracticeRoutes,
        string Stimulus,
        string LearnerInstructionUk,
        string R1,
        string R2,
        string R3,
        string ComprehensionPrompt,
        string[] ComprehensionAccepted,
        int? R2After = null,
        int? R3After = null);

    private static readonly MissionDefinition[] Missions =
    {
        new(
            "CE-A1-M10-MSN0001", "ce-a1-m10-msn0001-runtime",
            "RIVERTON SATURDAY: TRAIN, MUSEUM, AND A CHANGED PLAN",
            Ids(1, 7, 12, 17, 22, 24, 25, 26),
            Ids(1, 12, 17, 22, 24, 25, 26),
            new[] { "GOING-TO", "TIME-DATE", "ARRANGEMENT", "CLARIFICATION", "CONNECTED-WRITING" },
            "Fictional plan. Saturday: train to Riverton 08:40; museum booking 10:00; lunch 12:30; meet Noor outside the station 15:00. Update: the 08:40 train is cancelled. The next train arrives at 10:20. The museum can move the booking to 11:00. A message says “Meet at platform fourteen,” but another note says “platform four.”",
            "Склади новий план після зміни. Не вигадуй нових розкладів або правил. Потім уточни суперечливий номер платформи.",
            "Write 2–4 simple English sentences stating the revised plan with at least one going-to plan and one exact time/date arrangement.",
            "Write one change request to the museum using the supplied 11:00 option.",
            "Write a clarification question that distinguishes platform four from platform fourteen, then write a confirmation sentence after the fictional reply “Platform four.”",
            "What time does the next train arrive after the cancellation?",
            new[] { "10:20", "10.20" }),
        new(
            "CE-A1-M10-MSN0002", "ce-a1-m10-msn0002-runtime",
            "DINNER AND FILM: TWO CHANGES, ONE AGREED ARRANGEMENT",
            Ids(8, 9, 12, 15, 17, 18, 19, 20, 21, 22, 23),
            Ids(9, 12, 17, 18, 20, 21, 22, 23),
            new[] { "ARRANGEMENT", "TIME-DATE", "INTEGRATION-LEXIS", "CONNECTED-WRITING" },
            "Fictional Saturday plan. Restaurant booking: 18:00 for two people. Film: 19:30. Update 1: the cinema moves the film to 20:15. Update 2: your friend cannot arrive before 18:30. The restaurant has one available alternative: 18:45.",
            "Узгодь новий час вечері та фільму, використовуючи тільки подані варіанти. Покажи, що стара домовленість змінилася.",
            "Write a short message rejecting 18:00 politely and proposing 18:45.",
            "Write the final revised arrangement with dinner at 18:45 and the film at 20:15.",
            "Write one sentence explaining whether this is now a fixed arrangement or only a general plan, using the simple M10 contrast rather than advanced grammar terminology.",
            "What restaurant alternative time is supplied?",
            new[] { "18:45", "18.45" }),
        new(
            "CE-A1-M10-MSN0003", "ce-a1-m10-msn0003-runtime",
            "STUDY DAY: WORK, LIBRARY, AND A MEETING-TIME REPAIR",
            Ids(1, 8, 9, 18, 19, 26, 28),
            Ids(1, 9, 18, 19, 26),
            new[] { "GOING-TO", "ARRANGEMENT", "TIME-DATE", "CLARIFICATION", "CONNECTED-WRITING" },
            "Fictional weekday. Work finishes at 16:30. A study group is booked for 17:15 at the library. The library closes at 19:00. Message from Maya: “Can we meet at 18:00 instead?” A second message says: “Sorry, I wrote the wrong time. I mean 17:30.”",
            "Відреагуй на зміну так, щоб фінальна домовленість була однозначною. Не використовуй свої реальні робочі чи навчальні дані.",
            "Write one sentence about what you are going to do after work.",
            "Write a clarification/confirmation message for Maya after the correction from 18:00 to 17:30.",
            "Write the final plan in chronological order and include the library closing time only as a constraint, not as something you control.",
            "What corrected meeting time did Maya supply?",
            new[] { "17:30", "17.30" }),
        new(
            "CE-A1-M10-MSN0004", "ce-a1-m10-msn0004-runtime",
            "VISITOR WEEKEND: ROOM, TRAIN, VISIT, AND BOOKING CORRECTION",
            Ids(7, 11, 12, 14, 15, 16, 24, 26, 28),
            Ids(11, 12, 14, 15, 16, 24, 26),
            new[] { "GOING-TO", "TIME-DATE", "INTEGRATION-LEXIS", "CLARIFICATION", "CONNECTED-WRITING" },
            "Fictional visit next month. Train: Friday 17:20. Room booking: Friday night. Gallery visit: Saturday 10:30. Booking message: “Your room is booked for Saturday night.” This conflicts with the original Friday-night plan. The host replies after clarification: “No, I mean Friday night. The first message was wrong.”",
            "Уточни бронювання, а потім склади короткий план поїздки. Не вигадуй правила готелю, оплату чи штрафи.",
            "Write a clarification message about Friday night versus Saturday night.",
            "After the supplied host correction, write a confirmation sentence and a 2–4 sentence plan using next month, the Friday train, and the Saturday gallery visit.",
            "Write one simple sentence with book or booking in the correct service sense.",
            "What night is the original room plan for?",
            new[] { "friday", "friday night" },
            R2After: 1),
        new(
            "CE-A1-M10-MSN0005", "ce-a1-m10-msn0005-runtime",
            "CLINIC APPOINTMENT: LOW-STAKES SCHEDULING, NOT MEDICAL ADVICE",
            Ids(12, 17, 18, 20, 21, 22, 23, 24, 25, 26),
            Ids(12, 17, 18, 20, 21, 22, 23, 24, 25, 26),
            new[] { "ARRANGEMENT", "TIME-DATE", "CLARIFICATION", "CONNECTED-WRITING" },
            "Fictional scheduling only. Appointment: Tuesday 14:00 at Green Street Clinic. Update: the clinic can offer Tuesday 16:00 or Wednesday 09:30 instead. A receptionist message says “Wednesday at nine thirty.” A copied note says “Tuesday at nine thirty.” No symptom, diagnosis, treatment, medicine, or medical recommendation is part of this mission.",
            "Зміни час вигаданого прийому та уточни суперечливий день. Це мовна задача на домовленість; не давай медичних порад і не повідомляй реальні дані про здоров’я.",
            "Reject the original Tuesday 14:00 time and propose one supplied alternative.",
            "Ask whether the 09:30 option is Tuesday or Wednesday.",
            "After the fictional reply “Wednesday at 09:30,” confirm the repaired appointment in one sentence.",
            "What is the original appointment time?",
            new[] { "14:00", "14.00", "tuesday 14:00", "tuesday at 14:00" },
            R3After: 2),
        new(
            "CE-A1-M10-MSN0006", "ce-a1-m10-msn0006-runtime",
            "SHOP, MEAL, AND EVENT: CHOOSE, ARRANGE, THEN REPAIR",
            Ids(1, 9, 12, 13, 17, 18, 19, 20, 21, 22, 24),
            Ids(1, 9, 12, 13, 17, 18, 19, 20, 21, 22, 24),
            new[] { "GOING-TO", "ARRANGEMENT", "TIME-DATE", "INTEGRATION-LEXIS", "CLARIFICATION", "CONNECTED-WRITING" },
            "Fictional Saturday. Shop pickup window: 11:00–12:00. Lunch table: 12:30. Community concert: 15:00. Update: the pickup will not be ready before 11:45. Friend message: “Let’s meet for lunch at 12:15.” Restaurant booking remains 12:30. No price, payment, food-choice, or concert vocabulary in this mission is automatically credited as upstream mastery.",
            "Зміни порядок дій так, щоб план був можливим, і виправ невідповідність 12:15/12:30.",
            "Write a simple going-to plan for pickup, lunch, and the concert using the supplied times.",
            "Write a message explaining that 12:15 does not match the booking and ask to keep or change the time.",
            "Write the final arrangement if the fictional friend replies “12:30 works for me.”",
            "What lunch booking time remains?",
            new[] { "12:30", "12.30" },
            R3After: 2),
        new(
            "CE-A1-M10-MSN0007", "ce-a1-m10-msn0007-runtime",
            "CANCELLED TRAIN: BUILD A NEW WEEKEND PLAN WITHOUT INVENTING FACTS",
            Ids(1, 2, 12, 13, 17, 23, 24, 25, 28),
            Ids(1, 2, 12, 13, 17, 23, 24, 25),
            new[] { "GOING-TO", "ARRANGEMENT", "TIME-DATE", "INTEGRATION-LEXIS", "CLARIFICATION", "CONNECTED-WRITING" },
            "Fictional weekend. Original plan: travel Friday 18:10, meet Lee at 20:00, visit North Hall Saturday morning. Update: the Friday 18:10 service is cancelled. Supplied alternatives: Friday 20:10 or Saturday 08:00. Lee writes, “Friday at ten works for me,” which could mean 10:00 or 22:00 in this context. The mission supplies no ticket rules, refunds, route details, or prices.",
            "Обери один із двох поданих варіантів, переплануй вихідні й уточни неоднозначне “ten”.",
            "Write one positive and one negative going-to sentence showing the changed plan.",
            "Write a clarification question asking whether Lee means 10:00 or 22:00.",
            "After the fictional reply “I mean 22:00 on Friday,” write the final plan and one change/cancel statement.",
            "What is the supplied Friday travel alternative time?",
            new[] { "20:10", "20.10", "friday 20:10" },
            R3After: 2),
        new(
            "CE-A1-M10-MSN0008", "ce-a1-m10-msn0008-runtime",
            "INTEGRATED SURVIVAL DAY: EXPOSED CAPSTONE PRACTICE, NOT LEVEL EXIT",
            Ids(1, 7, 9, 13, 15, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 28),
            Ids(1, 9, 13, 15, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26),
            new[] { "GOING-TO", "ARRANGEMENT", "TIME-DATE", "INTEGRATION-LEXIS", "CLARIFICATION", "CONNECTED-WRITING" },
            "Fictional practice day. 09:00 train arrival. 10:00 room-booking desk appointment. 12:00 lunch booking. 14:30 meet Sam at the library. 17:00 community event. Change 1: room desk moves the appointment to 10:45. Change 2: Sam writes “Meet at the library at 4,” but the event begins at 17:00 and another Sam message says “Sorry, I mean 14:00.” Change 3: lunch booking can stay at 12:00 or move to 12:30. No real travel, accommodation, purchase, health, work, or contact data is requested.",
            "Створи здійсненний оновлений план, постав одне уточнювальне питання, відреагуй на одну зміну часу та сформулюй щонайменше дві самостійні продуктивні відповіді. Це відкрита тренувальна місія, не захищений іспит.",
            "Write 3–5 simple English sentences with the revised day plan, including at least one going-to intention and one fixed arrangement/time statement.",
            "Write a clarification question for Sam that does not assume whether “4” means 14:00 or 16:00; then use the supplied correction “I mean 14:00” in a confirmation.",
            "Choose 12:00 or 12:30 for lunch and write an arrangement acceptance/change message. Both options are valid if the rest of the plan remains coherent.",
            "What new room-desk appointment time is supplied?",
            new[] { "10:45", "10.45" })
    };

    internal static IReadOnlyList<string> GovernedMissionIds => Missions.Select(mission => mission.GovernedId).ToArray();

    internal static string GovernedMissionIdForUnit(string runtimeUnitId) =>
        Missions.Single(mission => mission.RuntimeUnitId.Equals(runtimeUnitId, StringComparison.OrdinalIgnoreCase)).GovernedId;

    internal static StoryCourseManifestContract BuildManifest()
    {
        StoryCourseUnitContract[] units = Missions.Select(BuildUnit).ToArray();
        StoryCourseObjectiveContract[] objectives = units
            .SelectMany(unit => unit.ObjectiveIds)
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .Select(id => BuildObjective(Missions.Single(mission => ObjectiveId(mission) == id)))
            .ToArray();

        StoryCourseModuleContract module = new(
            RuntimeModuleId,
            RuntimeLevelId,
            "Plans, Arrangements, and Integrated Everyday Survival",
            objectives,
            units);
        StoryCourseLevelContract level = new(
            RuntimeLevelId,
            "A1",
            "Complete English A1 — governed M10 mission practice",
            10,
            new[] { module });
        return new StoryCourseManifestContract(
            RuntimeCourseId,
            "Complete English A1 — M10 Module Mission Practice",
            StoryCourseCurriculumAuthority.ApprovedCurriculum,
            ClaimsCompleteEnglishCourse: false,
            new[] { level },
            BuildProvenance("CE-A1-M10-MODULE-MISSION-BANK"));
    }

    private static StoryCourseUnitContract BuildUnit(MissionDefinition mission)
    {
        StoryCourseObjectiveContract objective = BuildObjective(mission);
        StoryCourseTargetsContract targets = new(Array.Empty<string>(), Array.Empty<string>())
        {
            SkillTargets = mission.TargetIds.Select(Target).ToArray()
        };
        StoryCourseProvenanceContract provenance = BuildProvenance(mission.GovernedId);
        StoryCourseNarrativeContract context = new(
            mission.RuntimeUnitId + "-context",
            StoryCourseNarrativeKind.Story,
            $"{mission.GovernedId}. {mission.Stimulus}{Environment.NewLine}{Environment.NewLine}" +
            $"Інструкція: {mission.LearnerInstructionUk}{Environment.NewLine}{Environment.NewLine}" +
            "Статус: FORMATIVE_EXPOSED. Це відкрита тренувальна місія. Exposure, completion, MET, XP, streak, hint/reveal або введений текст не є mastery. " +
            "Цей банк не авторизує Fast Track, protected checkpoint, Listening evidence або Speaking evidence. Binary audio до цієї runtime-прив'язки не входить.",
            Array.Empty<string>(),
            provenance);
        StoryCourseComprehensionTaskContract comprehension = new(
            mission.RuntimeUnitId + "-fact-check",
            StoryCourseComprehensionKind.BoundedResponse,
            mission.ComprehensionPrompt + " Це лише перевірка факту зі stimulus; вона не є mastery target.",
            new[] { objective.ObjectiveId },
            mission.ComprehensionAccepted);

        StoryCourseProductiveTaskContract[] productive =
        {
            Productive(mission, 1, mission.R1, objective.ObjectiveId, mission.R1 is not null ? null : null),
            Productive(mission, 2, mission.R2, objective.ObjectiveId, mission.R2After),
            Productive(mission, 3, mission.R3, objective.ObjectiveId, mission.R3After)
        };

        return new StoryCourseUnitContract(
            mission.RuntimeUnitId,
            RuntimeModuleId,
            mission.Title,
            new[] { objective.ObjectiveId },
            targets,
            new[] { context },
            new[] { comprehension },
            productive,
            Checkpoint: null,
            provenance);
    }

    private static StoryCourseObjectiveContract BuildObjective(MissionDefinition mission)
    {
        var evidence = new List<string>
        {
            "writing",
            "formative-exposed",
            "eligibility-is-not-mastery"
        };
        evidence.AddRange(mission.EvidenceTargetIds.Select(id => "eligible-course-target=" + id));
        evidence.AddRange(mission.DeepPracticeRoutes.Select(route => "deep-practice-route=" + route));
        return new StoryCourseObjectiveContract(
            ObjectiveId(mission),
            $"Complete governed formative mission {mission.GovernedId} using only supplied fictional facts; preserve independent Writing and the target/evidence firewall.",
            evidence);
    }

    private static StoryCourseProductiveTaskContract Productive(
        MissionDefinition mission,
        int slot,
        string prompt,
        string objectiveId,
        int? revealAfterSlot)
    {
        string taskId = TaskId(mission, slot);
        string policyId = $"policy.external.ce-a1-m10-{mission.GovernedId[^7..].ToLowerInvariant()}-r{slot}-writing-unjudged";
        if (revealAfterSlot is int priorSlot)
            policyId += StoryCourseProductiveRevealPolicy.AfterToken + TaskId(mission, priorSlot);
        return new StoryCourseProductiveTaskContract(
            taskId,
            StoryCourseProductiveChannel.Writing,
            $"Response slot R{slot}. {prompt}",
            new[] { objectiveId },
            policyId);
    }

    private static string ObjectiveId(MissionDefinition mission) => mission.RuntimeUnitId + "-objective";
    private static string TaskId(MissionDefinition mission, int slot) => mission.RuntimeUnitId.Replace("-runtime", string.Empty, StringComparison.Ordinal) + $"-r{slot}-writing";

    private static StoryCourseSkillTargetReferenceContract Target(string targetRef) =>
        new(StoryCourseSkillTargetReferenceContract.CourseTargetDomain, targetRef);

    private static StoryCourseProvenanceContract BuildProvenance(string governedObjectId) => new(
        StoryCourseContentOrigin.WordDeckAuthored,
        $"Drive:{SourceId}@{SourceRevision}",
        "1.3",
        RightsHold,
        $"Governed object {governedObjectId}; independent QA Drive:{QaId}@{QaRevision}; " +
        $"content integration Drive:{IntegrationId}@{IntegrationRevision}. " +
        "Commercial/public redistribution remains HOLD until the project-wide provenance/release gate passes.");

    private static string[] Ids(params int[] numbers) =>
        numbers.Select(number => $"CE-A1-M10-TL{number:0000}").ToArray();
}
