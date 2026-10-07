from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from acs.teaching_session import (
    LessonSession,
    PositionSourceKind,
    TeachingActivity,
    TeachingPositionSource,
    TeachingStep,
    TeachingSessionState,
    default_policy,
    pause_session,
    start_session,
)
from acs.teaching_session_store import (
    TeachingSessionConflictError,
    TeachingSessionStore,
    TeachingSessionStoreError,
)


class TeachingSessionStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "teaching-session.json"
        self.store = TeachingSessionStore(self.path)

    @staticmethod
    def plan(session_id: str = "session-1") -> LessonSession:
        activity = TeachingActivity.TEACHER_EXPLAINS
        return LessonSession(
            session_id,
            "lesson-1",
            TeachingPositionSource(PositionSourceKind.START),
            (
                TeachingStep(
                    "step-1",
                    activity,
                    "Explain",
                    default_policy(activity),
                ),
            ),
            ("student-1",),
            "cohort-1",
        )

    def test_round_trip_update_and_clear_use_exact_cas(self) -> None:
        plan = self.plan()
        active = start_session(plan)
        revision = self.store.save(plan, active, expected_revision=None)

        loaded = self.store.load()
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(plan, loaded.plan)
        self.assertEqual(active, loaded.state)
        self.assertEqual(revision, loaded.revision)

        paused = pause_session(plan, active, 0)
        next_revision = self.store.save(
            plan,
            paused,
            expected_revision=revision,
        )
        self.assertNotEqual(revision, next_revision)
        self.assertEqual(paused, self.store.load().state)

        with self.assertRaises(TeachingSessionConflictError):
            self.store.save(plan, active, expected_revision=revision)

        self.store.clear(expected_revision=next_revision)
        self.assertIsNone(self.store.load())
        self.assertFalse(self.path.exists())

    def test_create_only_refuses_to_replace_existing_session(self) -> None:
        plan = self.plan()
        state = start_session(plan)
        self.store.save(plan, state, expected_revision=None)
        with self.assertRaises(TeachingSessionConflictError):
            self.store.save(plan, state, expected_revision=None)

    def test_plan_state_identity_mismatch_fails_before_publication(self) -> None:
        plan = self.plan()
        other = self.plan("session-2")
        state = start_session(other)
        with self.assertRaises(TeachingSessionStoreError):
            self.store.save(plan, state, expected_revision=None)
        self.assertFalse(self.path.exists())

    def test_corrupt_or_noncanonical_state_fails_closed(self) -> None:
        self.path.write_text('{"schema_version":1,"plan":{},"state":{}}', encoding="utf-8")
        with self.assertRaises(TeachingSessionStoreError):
            self.store.load()

        plan = self.plan()
        state = start_session(plan)
        self.path.unlink()
        revision = self.store.save(plan, state, expected_revision=None)
        loaded = self.store.load()
        assert loaded is not None
        forged = replace(loaded.state, plan_digest="0" * 64)
        with self.assertRaises(TeachingSessionStoreError):
            self.store.save(plan, forged, expected_revision=revision)


if __name__ == "__main__":
    unittest.main()
