from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from acs.child_coaching import compile_lesson_session, preset_templates
from acs.child_coaching_rotation import (
    RotationActivity,
    RotationPhase,
    RotationRound,
    RotationState,
    advance_rotation,
    bind_pair_play_batch,
    build_rotation_plan,
    start_rotation,
)
from acs.child_coaching_rotation_store import (
    ChildCoachingRotationStore,
    ChildCoachingRotationStoreConflictError,
    ChildCoachingRotationStoreError,
)
from acs.teaching_session import PositionSourceKind, TeachingPositionSource


class CompletedRotationRecoveryTests(unittest.TestCase):
    def _lesson(self):
        return compile_lesson_session(
            preset_templates()[1],
            session_id="completed-recovery-session",
            lesson_id="completed-recovery-lesson",
            source=TeachingPositionSource(PositionSourceKind.START),
            student_ids=("student-1", "student-2"),
            require_no_notation=True,
        )

    def _plan(self):
        return build_rotation_plan(
            self._lesson(),
            rotation_id="completed-recovery-rotation",
            rounds=(
                RotationRound(
                    "opening",
                    RotationActivity.DEMONSTRATION,
                    "Opening demonstration",
                    5,
                ),
                RotationRound(
                    "review",
                    RotationActivity.REVIEW,
                    "Review",
                    5,
                ),
            ),
        )

    def _pair_plan(self):
        return build_rotation_plan(
            self._lesson(),
            rotation_id="pair-recovery-rotation",
            rounds=(
                RotationRound(
                    "pair",
                    RotationActivity.PAIR_PLAY,
                    "Pair play",
                    5,
                ),
                RotationRound(
                    "review",
                    RotationActivity.REVIEW,
                    "Review",
                    5,
                ),
            ),
        )

    def _impossible_completed_state(self, plan):
        return RotationState(
            rotation_id=plan.rotation_id,
            plan_digest=plan.digest,
            phase=RotationPhase.COMPLETED,
            round_index=0,
            revision=1,
        )

    @staticmethod
    def _payload(plan, state):
        return {
            "schema_version": 1,
            "plan": plan.to_record(),
            "state": state.to_record(),
        }

    @staticmethod
    def _write_payload(path: Path, plan, state) -> None:
        path.write_text(
            json.dumps(
                CompletedRotationRecoveryTests._payload(plan, state),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )

    def test_save_rejects_completed_state_before_final_round(self) -> None:
        plan = self._plan()
        impossible = self._impossible_completed_state(plan)
        with tempfile.TemporaryDirectory() as temp:
            store = ChildCoachingRotationStore(Path(temp) / "rotation.json")
            with self.assertRaisesRegex(
                ChildCoachingRotationStoreError,
                "completed rotation must reference the final plan round",
            ):
                store.save(plan, impossible, expected_revision=None)

    def test_load_rejects_digest_valid_completed_state_before_final_round(self) -> None:
        plan = self._plan()
        impossible = self._impossible_completed_state(plan)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "rotation.json"
            self._write_payload(path, plan, impossible)
            store = ChildCoachingRotationStore(path)
            with self.assertRaisesRegex(
                ChildCoachingRotationStoreError,
                "completed rotation must reference the final plan round",
            ):
                store.load()

    def test_save_rejects_unreachable_active_revision(self) -> None:
        plan = self._plan()
        impossible = RotationState(
            rotation_id=plan.rotation_id,
            plan_digest=plan.digest,
            phase=RotationPhase.ACTIVE,
            round_index=0,
            revision=2,
        )
        with tempfile.TemporaryDirectory() as temp:
            store = ChildCoachingRotationStore(Path(temp) / "rotation.json")
            with self.assertRaisesRegex(
                ChildCoachingRotationStoreError,
                "rotation state revision is unreachable for the plan",
            ):
                store.save(plan, impossible, expected_revision=None)

    def test_load_rejects_digest_valid_completed_final_round_with_wrong_revision(self) -> None:
        plan = self._plan()
        # A two-round non-pair rotation is start(rev=1), advance(rev=2),
        # complete(rev=3). Final-round COMPLETED at revision 2 is digest-valid
        # but cannot be produced by the canonical transition API.
        impossible = RotationState(
            rotation_id=plan.rotation_id,
            plan_digest=plan.digest,
            phase=RotationPhase.COMPLETED,
            round_index=1,
            revision=2,
        )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "rotation.json"
            self._write_payload(path, plan, impossible)
            store = ChildCoachingRotationStore(path)
            with self.assertRaisesRegex(
                ChildCoachingRotationStoreError,
                "rotation state revision is unreachable for the plan",
            ):
                store.load()

    def test_load_rejects_pair_reference_without_its_bind_revision(self) -> None:
        plan = self._pair_plan()
        impossible = RotationState(
            rotation_id=plan.rotation_id,
            plan_digest=plan.digest,
            phase=RotationPhase.ACTIVE,
            round_index=0,
            pair_play_batch_ref="pair-batch-1",
            revision=1,
        )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "rotation.json"
            self._write_payload(path, plan, impossible)
            store = ChildCoachingRotationStore(path)
            with self.assertRaisesRegex(
                ChildCoachingRotationStoreError,
                "rotation state revision is unreachable for the plan",
            ):
                store.load()

    def test_load_rejects_escaped_surrogate_title_as_store_error(self) -> None:
        plan = self._plan()
        state = RotationState(
            rotation_id=plan.rotation_id,
            plan_digest=plan.digest,
        )
        payload = self._payload(plan, state)
        payload["plan"]["rounds"][0]["title"] = "\ud800"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "rotation.json"
            path.write_text(
                json.dumps(
                    payload,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            store = ChildCoachingRotationStore(path)
            with self.assertRaisesRegex(
                ChildCoachingRotationStoreError,
                "invalid rotation plan/state payload",
            ):
                store.load()

    def test_save_rechecks_existing_target_after_temp_fsync(self) -> None:
        plan = self._plan()
        planned = RotationState(
            rotation_id=plan.rotation_id,
            plan_digest=plan.digest,
        )
        active = start_rotation(plan)
        foreign = b'{"external":"newer"}'
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "rotation.json"
            store = ChildCoachingRotationStore(path)
            revision = store.save(plan, planned, expected_revision=None)
            real_fsync = os.fsync
            injected = False

            def fsync_then_replace_target(fd: int) -> None:
                nonlocal injected
                real_fsync(fd)
                if not injected:
                    injected = True
                    path.write_bytes(foreign)

            with mock.patch(
                "acs.child_coaching_rotation_store.os.fsync",
                side_effect=fsync_then_replace_target,
            ):
                with self.assertRaisesRegex(
                    ChildCoachingRotationStoreConflictError,
                    "changed since the caller last observed",
                ):
                    store.save(plan, active, expected_revision=revision)

            self.assertTrue(injected)
            self.assertEqual(path.read_bytes(), foreign)
            self.assertEqual(list(path.parent.glob(".rotation.json.*.tmp")), [])

    def test_save_rechecks_absent_target_after_temp_fsync(self) -> None:
        plan = self._plan()
        state = RotationState(
            rotation_id=plan.rotation_id,
            plan_digest=plan.digest,
        )
        foreign = b'{"external":"created"}'
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "rotation.json"
            store = ChildCoachingRotationStore(path)
            real_fsync = os.fsync
            injected = False

            def fsync_then_create_target(fd: int) -> None:
                nonlocal injected
                real_fsync(fd)
                if not injected:
                    injected = True
                    path.write_bytes(foreign)

            with mock.patch(
                "acs.child_coaching_rotation_store.os.fsync",
                side_effect=fsync_then_create_target,
            ):
                with self.assertRaisesRegex(
                    ChildCoachingRotationStoreConflictError,
                    "changed since the caller last observed",
                ):
                    store.save(plan, state, expected_revision=None)

            self.assertTrue(injected)
            self.assertEqual(path.read_bytes(), foreign)
            self.assertEqual(list(path.parent.glob(".rotation.json.*.tmp")), [])

    def test_real_pair_play_revisions_round_trip_through_completion(self) -> None:
        plan = self._pair_plan()
        state = start_rotation(plan)
        self.assertEqual(state.revision, 1)
        state = bind_pair_play_batch(
            plan,
            state,
            "pair-batch-1",
            expected_revision=state.revision,
        )
        self.assertEqual(state.revision, 2)

        with tempfile.TemporaryDirectory() as temp:
            store = ChildCoachingRotationStore(Path(temp) / "rotation.json")
            revision = store.save(plan, state, expected_revision=None)
            loaded = store.load()
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.state, state)

            state = advance_rotation(
                plan,
                state,
                expected_revision=state.revision,
            )
            self.assertEqual(state.round_index, 1)
            self.assertEqual(state.revision, 3)
            revision = store.save(plan, state, expected_revision=revision)

            state = advance_rotation(
                plan,
                state,
                expected_revision=state.revision,
            )
            self.assertEqual(state.phase, RotationPhase.COMPLETED)
            self.assertEqual(state.revision, 4)
            final_revision = store.save(plan, state, expected_revision=revision)
            final = store.load()
            self.assertIsNotNone(final)
            assert final is not None
            self.assertEqual(final.plan, plan)
            self.assertEqual(final.state, state)
            self.assertEqual(final.revision, final_revision)

    def test_real_completed_final_round_still_round_trips(self) -> None:
        plan = self._plan()
        state = start_rotation(plan)
        state = advance_rotation(plan, state, expected_revision=state.revision)
        state = advance_rotation(plan, state, expected_revision=state.revision)
        self.assertEqual(state.phase, RotationPhase.COMPLETED)
        self.assertEqual(state.round_index, len(plan.rounds) - 1)
        self.assertEqual(state.revision, 3)

        with tempfile.TemporaryDirectory() as temp:
            store = ChildCoachingRotationStore(Path(temp) / "rotation.json")
            revision = store.save(plan, state, expected_revision=None)
            loaded = store.load()
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.plan, plan)
            self.assertEqual(loaded.state, state)
            self.assertEqual(loaded.revision, revision)


if __name__ == "__main__":
    unittest.main()
