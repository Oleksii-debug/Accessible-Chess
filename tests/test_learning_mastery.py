from __future__ import annotations

import hashlib
import json
import unittest

from acs.learning_mastery import (
    LearningMode,
    MasteryError,
    MasteryState,
    TrainingOutcome,
    change_learning_mode,
    record_training_outcome,
)


def outcome(
    sequence: int,
    event_id: str,
    *,
    activity_id: str = "training.tactic.001",
    practice_date: str = "2026-09-26",
    completed: bool = True,
    correct_steps: int = 3,
    total_steps: int = 3,
    mistakes: int = 0,
    hints_used: int = 0,
    duration_seconds: int = 90,
) -> TrainingOutcome:
    return TrainingOutcome(
        sequence=sequence,
        event_id=event_id,
        activity_id=activity_id,
        practice_date=practice_date,
        completed=completed,
        correct_steps=correct_steps,
        total_steps=total_steps,
        mistakes=mistakes,
        hints_used=hints_used,
        duration_seconds=duration_seconds,
    )


class LearningMasteryTests(unittest.TestCase):
    def test_completed_clean_training_awards_transparent_mastery_and_first_achievement(self) -> None:
        update = record_training_outcome(MasteryState.empty(), outcome(1, "evt.1"))
        self.assertEqual(update.earned_points, 130)
        self.assertEqual(update.state.total_points, 130)
        self.assertEqual(update.state.completed_count, 1)
        self.assertEqual(update.state.perfect_completions, 1)
        self.assertEqual(update.new_achievements, ("first_completion",))
        self.assertEqual(update.state.level, 1)

    def test_mistakes_and_hints_never_subtract_points(self) -> None:
        state = MasteryState.empty()
        first = record_training_outcome(
            state,
            outcome(1, "evt.1", completed=False, correct_steps=1, mistakes=8, hints_used=8),
        )
        self.assertGreater(first.earned_points, 0)
        second = record_training_outcome(
            first.state,
            outcome(2, "evt.2", mistakes=20, hints_used=20),
        )
        self.assertGreaterEqual(second.state.total_points, first.state.total_points)
        self.assertEqual(second.state.perfect_completions, 0)

    def test_exact_latest_retry_is_idempotent_and_changed_reuse_fails_closed(self) -> None:
        event = outcome(1, "evt.1")
        update = record_training_outcome(MasteryState.empty(), event)
        retry = record_training_outcome(update.state, event)
        self.assertIs(retry.state, update.state)
        self.assertTrue(retry.duplicate_retry)
        self.assertEqual(retry.earned_points, 0)
        with self.assertRaises(MasteryError):
            record_training_outcome(
                update.state,
                outcome(1, "evt.1", duration_seconds=91),
            )

    def test_stale_or_gapped_sequence_cannot_farm_rewards(self) -> None:
        state = record_training_outcome(MasteryState.empty(), outcome(1, "evt.1")).state
        for candidate in (outcome(1, "different"), outcome(3, "evt.3")):
            with self.subTest(sequence=candidate.sequence):
                with self.assertRaises(MasteryError):
                    record_training_outcome(state, candidate)

    def test_streak_counts_practice_days_without_point_loss_after_gap(self) -> None:
        state = MasteryState.empty()
        state = record_training_outcome(state, outcome(1, "d1", practice_date="2026-09-24")).state
        state = record_training_outcome(state, outcome(2, "d2", practice_date="2026-09-25")).state
        before = state.total_points
        update = record_training_outcome(state, outcome(3, "d3", practice_date="2026-09-27"))
        self.assertEqual(update.state.current_streak, 1)
        self.assertEqual(update.state.best_streak, 2)
        self.assertGreater(update.state.total_points, before)

    def test_seven_day_streak_unlocks_achievement(self) -> None:
        state = MasteryState.empty()
        for index, day in enumerate(range(1, 8), start=1):
            state = record_training_outcome(
                state,
                outcome(index, f"evt.{index}", practice_date=f"2026-09-{day:02d}"),
            ).state
        self.assertIn("practice_streak_7", state.achievements)

    def test_out_of_order_calendar_event_fails_closed(self) -> None:
        state = record_training_outcome(
            MasteryState.empty(), outcome(1, "new", practice_date="2026-09-26")
        ).state
        with self.assertRaises(MasteryError):
            record_training_outcome(state, outcome(2, "old", practice_date="2026-09-25"))

    def test_child_daily_cap_blocks_compulsive_reward_farming_but_records_practice(self) -> None:
        state = MasteryState.empty(LearningMode.CHILD)
        capped = 0
        for sequence in range(1, 8):
            update = record_training_outcome(state, outcome(sequence, f"evt.{sequence}"))
            state = update.state
            capped += update.capped_points
        self.assertEqual(state.daily_points, 500)
        self.assertEqual(state.total_points, 500)
        self.assertGreater(capped, 0)
        self.assertEqual(state.revision, 7)
        self.assertEqual(state.completed_count, 7)

    def test_adult_daily_cap_is_bounded_too(self) -> None:
        state = MasteryState.empty(LearningMode.ADULT)
        for sequence in range(1, 25):
            state = record_training_outcome(state, outcome(sequence, f"evt.{sequence}")).state
        self.assertEqual(state.daily_points, 2000)
        self.assertEqual(state.total_points, 2000)

    def test_child_personal_best_does_not_reward_speed_pressure(self) -> None:
        state = MasteryState.empty(LearningMode.CHILD)
        state = record_training_outcome(
            state, outcome(1, "slow", duration_seconds=300)
        ).state
        update = record_training_outcome(
            state, outcome(2, "fast", duration_seconds=30)
        )
        self.assertFalse(update.personal_best_improved)
        self.assertEqual(update.state.bests[0].duration_seconds, 300)

    def test_adult_personal_best_uses_speed_only_after_mastery_tie(self) -> None:
        state = MasteryState.empty(LearningMode.ADULT)
        state = record_training_outcome(
            state, outcome(1, "slow", duration_seconds=300)
        ).state
        update = record_training_outcome(
            state, outcome(2, "fast", duration_seconds=30)
        )
        self.assertTrue(update.personal_best_improved)
        self.assertEqual(update.state.bests[0].duration_seconds, 30)

    def test_accuracy_and_support_usage_dominate_speed_for_personal_best(self) -> None:
        state = MasteryState.empty()
        state = record_training_outcome(
            state,
            outcome(1, "first", mistakes=0, hints_used=0, duration_seconds=400),
        ).state
        update = record_training_outcome(
            state,
            outcome(2, "second", mistakes=1, hints_used=0, duration_seconds=10),
        )
        self.assertFalse(update.personal_best_improved)
        self.assertEqual(update.state.bests[0].mistakes, 0)

    def test_mode_change_preserves_progress_and_daily_cap_accounting(self) -> None:
        state = record_training_outcome(MasteryState.empty(), outcome(1, "evt.1")).state
        changed = change_learning_mode(state, LearningMode.CHILD)
        self.assertEqual(changed.total_points, state.total_points)
        self.assertEqual(changed.completed_count, state.completed_count)
        self.assertEqual(changed.bests, state.bests)
        self.assertEqual(changed.daily_points, state.daily_points)
        self.assertEqual(changed.daily_points_date, state.daily_points_date)

    def test_mode_switch_cannot_reset_or_bypass_child_daily_cap(self) -> None:
        state = MasteryState.empty(LearningMode.CHILD)
        for sequence in range(1, 5):
            state = record_training_outcome(state, outcome(sequence, f"child.{sequence}")).state
        self.assertEqual(state.daily_points, 500)
        adult = change_learning_mode(state, LearningMode.ADULT)
        child_again = change_learning_mode(adult, LearningMode.CHILD)
        update = record_training_outcome(child_again, outcome(5, "child.5"))
        self.assertEqual(update.earned_points, 0)
        self.assertEqual(update.state.total_points, 500)
        self.assertGreater(update.capped_points, 0)

    def test_snapshot_roundtrip_is_deterministic_and_tamper_evident(self) -> None:
        state = record_training_outcome(MasteryState.empty(), outcome(1, "evt.1")).state
        text = state.to_json()
        restored = MasteryState.from_json(text)
        self.assertEqual(restored, state)
        self.assertEqual(restored.to_json(), text)
        raw = json.loads(text)
        raw["total_points"] += 1
        with self.assertRaises(MasteryError):
            MasteryState.from_json(json.dumps(raw))

    def test_snapshot_rejects_boolean_schema_version(self) -> None:
        raw = MasteryState.empty().to_record()
        raw["schema_version"] = True
        body = {key: raw[key] for key in raw if key != "digest"}
        encoded = json.dumps(
            body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        raw["digest"] = hashlib.sha256(encoded).hexdigest()
        with self.assertRaises(MasteryError):
            MasteryState.from_record(raw)

    def test_snapshot_rejects_unknown_and_duplicate_fields(self) -> None:
        state = MasteryState.empty()
        raw = state.to_record()
        raw["unknown"] = True
        with self.assertRaises(MasteryError):
            MasteryState.from_record(raw)
        text = state.to_json()
        duplicate = text[:-1] + ',"revision":0}'
        with self.assertRaises(MasteryError):
            MasteryState.from_json(duplicate)

    def test_completed_outcome_cannot_claim_partial_correctness(self) -> None:
        with self.assertRaises(MasteryError):
            outcome(1, "bad", completed=True, correct_steps=2, total_steps=3)

    def test_snapshot_contains_no_chess_content_or_external_identity_fields(self) -> None:
        keys = set(MasteryState.empty().to_record())
        forbidden = {
            "fen",
            "pgn",
            "moves",
            "book",
            "database",
            "chat",
            "audio",
            "video",
            "email",
            "username",
            "account",
            "participant",
            "display_name",
        }
        self.assertTrue(keys.isdisjoint(forbidden))


if __name__ == "__main__":
    unittest.main()
