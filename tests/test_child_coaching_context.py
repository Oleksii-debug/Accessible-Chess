from __future__ import annotations

import unittest

from acs.child_coaching_context import (
    ChildCoachingContextError,
    build_child_coaching_context,
    child_coaching_context_to_teacher_payload,
)
from acs.classroom_domain import ClassroomSnapshot, ConsentState, Student
from acs.full_product_ui_shell import UILanguage
from acs.student_progress import (
    ReviewKind,
    StudentProgressLedger,
    StudentReviewRecord,
)


class ChildCoachingContextTests(unittest.TestCase):
    @staticmethod
    def _classroom(
        *,
        consent: ConsentState = ConsentState.GRANTED,
        deleted: bool = False,
    ) -> ClassroomSnapshot:
        return ClassroomSnapshot(
            students=(
                Student(
                    "student-1",
                    "" if deleted else "Knight",
                    ConsentState.WITHDRAWN if deleted else consent,
                    deleted=deleted,
                ),
            ),
        )

    @staticmethod
    def _ledger() -> StudentProgressLedger:
        ledger = StudentProgressLedger()
        ledger.append(
            StudentReviewRecord(
                record_id="review-1",
                student_id="student-1",
                session_id="session-1",
                kind=ReviewKind.TRAINING,
                source_id="exercise-1",
                source_revision="rev-1",
                sequence=1,
                attempts=4,
                mistakes=1,
                hints_used=2,
                completed=True,
                engine_generation=7,
                engine_stale=True,
                engine_available=False,
            )
        )
        ledger.append(
            StudentReviewRecord(
                record_id="review-2",
                student_id="student-1",
                session_id="session-1",
                kind=ReviewKind.GAME,
                source_id="game-1",
                source_revision="rev-2",
                sequence=2,
                attempts=0,
                mistakes=0,
                hints_used=0,
                completed=True,
            )
        )
        return ledger

    def test_zero_history_is_neutral_and_does_not_infer_skill(self) -> None:
        context = build_child_coaching_context(
            self._classroom(),
            StudentProgressLedger(),
            student_id="student-1",
            session_id="session-1",
            language=UILanguage.EN,
        )
        payload = child_coaching_context_to_teacher_payload(context)
        self.assertEqual(0, payload["record_count"])
        self.assertIsNone(payload["accuracy_percent"])
        self.assertIn("No training or game review history", payload["accessible_text"])
        self.assertNotIn("beginner", repr(payload).lower())
        self.assertNotIn("level", payload)

    def test_summary_is_factual_bilingual_and_omits_internal_identity(self) -> None:
        context = build_child_coaching_context(
            self._classroom(),
            self._ledger(),
            student_id="student-1",
            session_id="session-1",
            language=UILanguage.UA,
        )
        payload = child_coaching_context_to_teacher_payload(context)
        self.assertEqual("Knight", payload["student_label"])
        self.assertEqual("granted", payload["consent"])
        self.assertEqual(2, payload["record_count"])
        self.assertEqual(1, payload["training_reviews"])
        self.assertEqual(1, payload["game_reviews"])
        self.assertEqual(4, payload["attempts"])
        self.assertEqual(1, payload["mistakes"])
        self.assertEqual(2, payload["hints_used"])
        self.assertEqual("75.0%", payload["accuracy_percent"])
        self.assertEqual(1, payload["engine_reviews"])
        self.assertEqual(1, payload["stale_engine_reviews"])
        self.assertNotIn("student_id", payload)
        self.assertNotIn("session_id", payload)
        self.assertNotIn("exercise-1", repr(payload))
        self.assertNotIn("game-1", repr(payload))

    def test_withdrawn_or_missing_consent_fails_closed(self) -> None:
        for consent in (ConsentState.NOT_COLLECTED, ConsentState.WITHDRAWN):
            with self.subTest(consent=consent):
                with self.assertRaisesRegex(
                    ChildCoachingContextError,
                    "without granted consent",
                ):
                    build_child_coaching_context(
                        self._classroom(consent=consent),
                        self._ledger(),
                        student_id="student-1",
                        session_id="session-1",
                    )

    def test_deleted_tombstone_never_projects_progress(self) -> None:
        with self.assertRaisesRegex(ChildCoachingContextError, "student is unavailable"):
            build_child_coaching_context(
                self._classroom(deleted=True),
                self._ledger(),
                student_id="student-1",
                session_id="session-1",
            )


if __name__ == "__main__":
    unittest.main()
