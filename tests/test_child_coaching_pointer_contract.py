from __future__ import annotations

import unittest

from acs.child_coaching import (
    AgeBand,
    ChildCoachingError,
    LessonBlock,
    LessonBlockKind,
    LessonLevel,
    LessonTemplate,
    compile_lesson_session,
)
from acs.interaction_contracts import BoardPermissionState
from acs.teaching_session import (
    PositionSourceKind,
    TeachingActivity,
    TeachingInputKind,
    TeachingPositionSource,
)


class ChildCoachingPointerContractTests(unittest.TestCase):
    def test_pointer_task_rejects_move_policy(self) -> None:
        with self.assertRaisesRegex(
            ChildCoachingError,
            "pointer task must remain selection-only",
        ):
            LessonBlock(
                block_id="bad-pointer",
                kind=LessonBlockKind.POINTER_TASK,
                title="Find it",
                minutes=5,
                activity=TeachingActivity.MAKE_MOVE,
                prompt="Point only; do not move.",
            )

    def test_pointer_task_record_ingress_rejects_move_policy(self) -> None:
        with self.assertRaisesRegex(
            ChildCoachingError,
            "pointer task must remain selection-only",
        ):
            LessonBlock.from_record(
                {
                    "block_id": "bad-record",
                    "kind": "pointer_task",
                    "title": "Pointer",
                    "minutes": 5,
                    "activity": "make_move",
                    "prompt": "Point to a square.",
                    "notation_required": False,
                    "teacher_note": None,
                    "target_square": None,
                    "target_piece": None,
                    "solution_text": None,
                    "student_engine_visible": False,
                }
            )

    def test_pointer_task_rejects_noninteractive_policy(self) -> None:
        with self.assertRaisesRegex(
            ChildCoachingError,
            "pointer task must remain selection-only",
        ):
            LessonBlock(
                block_id="locked-pointer",
                kind=LessonBlockKind.POINTER_TASK,
                title="Pointer",
                minutes=5,
                activity=TeachingActivity.TEACHER_EXPLAINS,
                prompt="Find the named square.",
            )

    def test_pointer_task_compiles_through_canonical_selection_policy(self) -> None:
        block = LessonBlock(
            block_id="show-square",
            kind=LessonBlockKind.POINTER_TASK,
            title="Find e4",
            minutes=5,
            activity=TeachingActivity.SHOW_SQUARE,
            prompt="Find e4.",
            target_square="e4",
        )
        step = block.to_teaching_step()
        self.assertIs(step.policy.input_kind, TeachingInputKind.SELECTION)
        self.assertIs(step.policy.board_permission, BoardPermissionState.SELECT_ONLY)

        template = LessonTemplate(
            template_id="custom-pointer",
            title="Safe pointer task",
            age_band=AgeBand.YOUNG_BEGINNER_7_8,
            level=LessonLevel.BEGINNER,
            blocks=(block,),
            custom=True,
        )
        session = compile_lesson_session(
            template,
            session_id="session-pointer",
            lesson_id="lesson-pointer",
            source=TeachingPositionSource(PositionSourceKind.START),
            require_no_notation=True,
        )
        self.assertIs(session.steps[0].policy.input_kind, TeachingInputKind.SELECTION)
        self.assertIs(
            session.steps[0].policy.board_permission,
            BoardPermissionState.SELECT_ONLY,
        )


if __name__ == "__main__":
    unittest.main()
