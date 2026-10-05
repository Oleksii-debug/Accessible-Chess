from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from acs.child_coaching import compile_lesson_session, preset_templates
from acs.child_coaching_rotation import (
    ChildCoachingRotationError,
    RotationActivity,
    RotationPhase,
    RotationPlan,
    RotationRound,
    RotationState,
    RotationTarget,
    advance_rotation,
    bind_pair_play_batch,
    build_rotation_plan,
    current_round,
    default_group_rotation,
    start_rotation,
    validate_rotation_scope,
)
from acs.child_coaching_rotation_store import (
    ChildCoachingRotationStore,
    ChildCoachingRotationStoreBusyError,
    ChildCoachingRotationStoreConflictError,
    ChildCoachingRotationStoreError,
)
from acs.child_coaching_store import _exclusive_store_lock
from acs.teaching_session import PositionSourceKind, TeachingPositionSource


class ChildCoachingRotationTests(unittest.TestCase):
    def lesson(self):
        return compile_lesson_session(
            preset_templates()[1],
            session_id="lesson-session-1",
            lesson_id="lesson-1",
            source=TeachingPositionSource(PositionSourceKind.START),
            student_ids=("student-1", "student-2", "student-3"),
            require_no_notation=True,
        )

    def test_default_group_rotation_is_anchored_to_exact_canonical_lesson(self) -> None:
        lesson = self.lesson()
        plan = default_group_rotation(lesson, rotation_id="rotation-1")
        self.assertEqual(plan.lesson_session_id, lesson.session_id)
        self.assertEqual(plan.lesson_plan_digest, lesson.digest)
        self.assertEqual(
            tuple(item.activity for item in plan.rounds),
            (
                RotationActivity.DEMONSTRATION,
                RotationActivity.TASK_WORK,
                RotationActivity.PAIR_PLAY,
                RotationActivity.REVIEW,
            ),
        )
        self.assertEqual(plan.total_minutes, 50)
        validate_rotation_scope(plan, lesson)

    def test_selected_targets_must_belong_to_lesson_but_group_ids_remain_external(self) -> None:
        lesson = self.lesson()
        selected = build_rotation_plan(
            lesson,
            rotation_id="rotation-selected",
            rounds=(
                RotationRound(
                    "selected",
                    RotationActivity.TASK_WORK,
                    "Selected students",
                    10,
                    RotationTarget.SELECTED,
                    ("student-1", "student-3"),
                ),
            ),
        )
        validate_rotation_scope(selected, lesson)

        with self.assertRaises(ChildCoachingRotationError):
            build_rotation_plan(
                lesson,
                rotation_id="rotation-outsider",
                rounds=(
                    RotationRound(
                        "selected",
                        RotationActivity.TASK_WORK,
                        "Selected students",
                        10,
                        RotationTarget.SELECTED,
                        ("outsider",),
                    ),
                ),
            )

        group = build_rotation_plan(
            lesson,
            rotation_id="rotation-group",
            rounds=(
                RotationRound(
                    "group",
                    RotationActivity.DEMONSTRATION,
                    "Group A",
                    10,
                    RotationTarget.GROUP,
                    ("group-a",),
                ),
            ),
        )
        self.assertEqual(group.rounds[0].target_ids, ("group-a",))

    def test_pair_play_binding_is_opaque_and_cannot_own_pairing_or_chess_state(self) -> None:
        plan = default_group_rotation(self.lesson(), rotation_id="rotation-pair")
        state = start_rotation(plan)
        state = advance_rotation(plan, state, expected_revision=state.revision)
        state = advance_rotation(plan, state, expected_revision=state.revision)
        self.assertEqual(current_round(plan, state).activity, RotationActivity.PAIR_PLAY)

        with self.assertRaisesRegex(
            ChildCoachingRotationError,
            "cannot advance before external pair-play batch",
        ):
            advance_rotation(plan, state, expected_revision=state.revision)

        bound = bind_pair_play_batch(
            plan,
            state,
            "external-batch-17",
            expected_revision=state.revision,
        )
        self.assertEqual(bound.pair_play_batch_ref, "external-batch-17")
        record = bound.to_record()
        self.assertNotIn("pairs", record)
        self.assertNotIn("clock", record)
        self.assertNotIn("fen", record)
        self.assertNotIn("game_session_id", record)

        after = advance_rotation(
            plan,
            bound,
            expected_revision=bound.revision,
        )
        self.assertIsNone(after.pair_play_batch_ref)
        self.assertEqual(current_round(plan, after).activity, RotationActivity.REVIEW)

    def test_pair_play_bind_retry_is_idempotent_but_different_stale_bind_fails(self) -> None:
        plan = default_group_rotation(self.lesson(), rotation_id="rotation-pair-retry")
        state = start_rotation(plan)
        state = advance_rotation(plan, state, expected_revision=state.revision)
        state = advance_rotation(plan, state, expected_revision=state.revision)
        before_bind_revision = state.revision
        bound = bind_pair_play_batch(
            plan,
            state,
            "external-batch-17",
            expected_revision=before_bind_revision,
        )

        retried = bind_pair_play_batch(
            plan,
            bound,
            "external-batch-17",
            expected_revision=before_bind_revision,
        )
        self.assertEqual(retried, bound)
        with self.assertRaisesRegex(
            ChildCoachingRotationError,
            "stale rotation revision",
        ):
            bind_pair_play_batch(
                plan,
                bound,
                "different-batch",
                expected_revision=before_bind_revision,
            )

    def test_pair_play_batch_cannot_bind_during_non_pair_round(self) -> None:
        plan = default_group_rotation(self.lesson(), rotation_id="rotation-bind")
        state = start_rotation(plan)
        with self.assertRaisesRegex(
            ChildCoachingRotationError,
            "only bind during pair-play",
        ):
            bind_pair_play_batch(
                plan,
                state,
                "batch-1",
                expected_revision=state.revision,
            )

    def test_planned_rotation_cannot_advance_before_explicit_start(self) -> None:
        plan = build_rotation_plan(
            self.lesson(),
            rotation_id="rotation-planned",
            rounds=(
                RotationRound(
                    "only",
                    RotationActivity.REVIEW,
                    "Only round",
                    5,
                ),
            ),
        )
        planned = RotationState(
            rotation_id=plan.rotation_id,
            plan_digest=plan.digest,
        )
        with self.assertRaisesRegex(
            ChildCoachingRotationError,
            "rotation must be active",
        ):
            advance_rotation(
                plan,
                planned,
                expected_revision=planned.revision,
            )

    def test_rotation_completes_deterministically_and_stale_revision_fails(self) -> None:
        plan = build_rotation_plan(
            self.lesson(),
            rotation_id="rotation-simple",
            rounds=(
                RotationRound(
                    "demo",
                    RotationActivity.DEMONSTRATION,
                    "Demo",
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
        state = start_rotation(plan)
        with self.assertRaisesRegex(ChildCoachingRotationError, "stale rotation revision"):
            advance_rotation(plan, state, expected_revision=0)
        state = advance_rotation(plan, state, expected_revision=state.revision)
        self.assertEqual(state.round_index, 1)
        state = advance_rotation(plan, state, expected_revision=state.revision)
        self.assertEqual(state.phase, RotationPhase.COMPLETED)
        with self.assertRaisesRegex(ChildCoachingRotationError, "already completed"):
            current_round(plan, state)


    def test_rotation_state_rejects_impossible_phase_revision_shapes(self) -> None:
        plan = default_group_rotation(self.lesson(), rotation_id="rotation-shapes")
        with self.assertRaisesRegex(
            ChildCoachingRotationError,
            "pristine at round zero",
        ):
            RotationState(
                rotation_id=plan.rotation_id,
                plan_digest=plan.digest,
                phase=RotationPhase.PLANNED,
                round_index=1,
                revision=0,
            )
        with self.assertRaisesRegex(
            ChildCoachingRotationError,
            "positive revision",
        ):
            RotationState(
                rotation_id=plan.rotation_id,
                plan_digest=plan.digest,
                phase=RotationPhase.ACTIVE,
                round_index=0,
                revision=0,
            )
        with self.assertRaises(ChildCoachingRotationError):
            RotationState(
                rotation_id=plan.rotation_id,
                plan_digest=plan.digest,
                phase=RotationPhase.ACTIVE,
                round_index=64,
                revision=1,
            )


    def test_rotation_round_rejects_unpaired_surrogate_title(self) -> None:
        with self.assertRaisesRegex(
            ChildCoachingRotationError,
            "valid UTF-8 text",
        ):
            RotationRound(
                "surrogate-title",
                RotationActivity.REVIEW,
                "\ud800",
                5,
            )

    def test_plan_and_state_json_are_closed_world_and_tamper_evident(self) -> None:
        plan = default_group_rotation(self.lesson(), rotation_id="rotation-json")
        state = start_rotation(plan)
        self.assertEqual(RotationPlan.from_json(plan.to_json()), plan)
        self.assertEqual(RotationState.from_json(state.to_json()), state)

        plan_record = plan.to_record()
        plan_record["lesson_session_id"] = "other"
        with self.assertRaises(ChildCoachingRotationError):
            RotationPlan.from_record(plan_record)

        state_record = state.to_record()
        state_record["unexpected"] = True
        with self.assertRaises(ChildCoachingRotationError):
            RotationState.from_record(state_record)

        duplicate = plan.to_json()[:-1] + ',"version":1}'
        with self.assertRaises(ChildCoachingRotationError):
            RotationPlan.from_json(duplicate)

    def test_store_reopens_exact_plan_state_and_rejects_stale_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "rotation.json"
            store = ChildCoachingRotationStore(path)
            plan = default_group_rotation(self.lesson(), rotation_id="rotation-store")
            state = start_rotation(plan)
            first_revision = store.save(plan, state, expected_revision=None)

            loaded = store.load()
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.plan, plan)
            self.assertEqual(loaded.state, state)
            self.assertEqual(loaded.revision, first_revision)

            newer = advance_rotation(
                plan,
                state,
                expected_revision=state.revision,
            )
            newer_revision = store.save(
                plan,
                newer,
                expected_revision=loaded.revision,
            )
            self.assertNotEqual(newer_revision, first_revision)
            with self.assertRaises(ChildCoachingRotationStoreConflictError):
                store.save(
                    plan,
                    state,
                    expected_revision=first_revision,
                )

    def test_rotation_store_maps_shared_lock_contention_to_rotation_busy_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "rotation.json"
            store = ChildCoachingRotationStore(path)
            plan = default_group_rotation(self.lesson(), rotation_id="rotation-busy")
            state = start_rotation(plan)
            lock_path = path.with_name(f".{path.name}.lock")

            with _exclusive_store_lock(lock_path):
                with self.assertRaises(ChildCoachingRotationStoreBusyError):
                    store.save(plan, state, expected_revision=None)

            revision = store.save(plan, state, expected_revision=None)
            self.assertEqual(store.load().revision, revision)

    def test_store_fails_closed_on_corruption_future_schema_and_mismatched_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "rotation.json"
            store = ChildCoachingRotationStore(path)
            plan = default_group_rotation(self.lesson(), rotation_id="rotation-store-bad")
            state = start_rotation(plan)
            store.save(plan, state, expected_revision=None)

            path.write_text("{corrupt", encoding="utf-8")
            with self.assertRaises(ChildCoachingRotationStoreError):
                store.load()

            path.write_text(
                json.dumps(
                    {
                        "schema_version": 99,
                        "plan": plan.to_record(),
                        "state": state.to_record(),
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ChildCoachingRotationStoreError):
                store.load()

            other_plan = default_group_rotation(
                self.lesson(),
                rotation_id="rotation-other",
            )
            with self.assertRaises(ChildCoachingRotationStoreError):
                ChildCoachingRotationStore(path).save(
                    other_plan,
                    state,
                    expected_revision=None,
                )


if __name__ == "__main__":
    unittest.main()
