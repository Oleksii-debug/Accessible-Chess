from __future__ import annotations

import unittest

from acs.lesson_plan import (
    AssignmentTarget,
    LessonItem,
    LessonItemKind,
    LessonPlan,
    LessonPosition,
    PairingMode,
    PairingService,
    PositionAssignment,
)


START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class LessonPlanTests(unittest.TestCase):
    def test_named_fen_positions_can_be_planned_and_assigned(self) -> None:
        position = LessonPosition("rook.demo", "Тура на відкритій лінії", START_FEN, prompt="Куди піде тура?")
        assignment = PositionAssignment(
            "assign.maria",
            position.position_id,
            AssignmentTarget.PARTICIPANTS,
            participant_ids=("maria",),
        )
        plan = LessonPlan(
            "lesson.rook.1",
            "Тура",
            "4-6",
            "beginner",
            (
                LessonItem("warmup", LessonItemKind.WARM_UP, "Розминка", 5),
                LessonItem("demo", LessonItemKind.POSITION, "Показ", 10, position.position_id),
                LessonItem("play", LessonItemKind.MINI_GAME, "Мінігра", 15),
            ),
            positions=(position,),
            assignments=(assignment,),
        )
        self.assertEqual(plan.planned_minutes, 30)
        self.assertEqual(plan.position_map()["rook.demo"].title, "Тура на відкритій лінії")

    def test_unknown_planned_position_reference_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            LessonPlan(
                "lesson.bad",
                "Bad",
                "8-10",
                "beginner",
                (LessonItem("demo", LessonItemKind.POSITION, "Demo", 10, "missing"),),
            )

    def test_preassignment_can_target_all_group_or_specific_participants(self) -> None:
        all_assignment = PositionAssignment("all", "p1")
        group_assignment = PositionAssignment("group", "p1", AssignmentTarget.GROUP, group_id="group-a")
        people_assignment = PositionAssignment(
            "people", "p1", AssignmentTarget.PARTICIPANTS, participant_ids=("s1", "s2")
        )
        self.assertEqual(all_assignment.target, AssignmentTarget.ALL)
        self.assertEqual(group_assignment.group_id, "group-a")
        self.assertEqual(people_assignment.participant_ids, ("s1", "s2"))


class PairingServiceTests(unittest.TestCase):
    def test_sequential_pairing_matches_requested_one_two_three_four_pattern(self) -> None:
        plan = PairingService().create(
            ["s1", "s2", "s3", "s4", "s5"],
            base_seconds=600,
            increment_seconds=5,
        )
        self.assertEqual(
            [(p.white_participant_id, p.black_participant_id) for p in plan.pairings],
            [("s1", "s2"), ("s3", "s4")],
        )
        self.assertEqual(plan.unpaired_participant_ids, ("s5",))
        self.assertEqual(plan.pairings[0].base_seconds, 600)
        self.assertEqual(plan.pairings[0].increment_seconds, 5)

    def test_random_pairing_is_reproducible_when_seeded(self) -> None:
        service = PairingService()
        first = service.create(["a", "b", "c", "d"], mode=PairingMode.RANDOM, random_seed=7)
        second = service.create(["a", "b", "c", "d"], mode=PairingMode.RANDOM, random_seed=7)
        self.assertEqual(first, second)

    def test_duplicate_participant_cannot_enter_pairing_twice(self) -> None:
        with self.assertRaises(ValueError):
            PairingService().create(["a", "a"])


if __name__ == "__main__":
    unittest.main()
