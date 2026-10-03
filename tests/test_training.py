import hashlib
import json
import unittest
from collections.abc import Mapping

from acs.chesscore import Board
from acs.training import (
    ExerciseDefinition,
    ExerciseSession,
    ExerciseStatus,
    ExerciseStep,
)


class ExerciseSessionTests(unittest.TestCase):
    def make_definition(self):
        return ExerciseDefinition(
            "opening-001",
            Board.START,
            (
                ExerciseStep(
                    frozenset({"e4", "e2e4"}),
                    hint="Claim the centre.",
                    explanation="Good central move.",
                ),
                ExerciseStep(
                    frozenset({"e5", "e7e5"}),
                    hint="Answer in the centre.",
                    explanation="Balanced reply.",
                ),
            ),
            title="Two-step opening exercise",
            tags=("Opening", "Calculation"),
            source_id="local-pack-1",
            metadata={"difficulty": "starter", "locale": "en"},
        )

    def test_definition_normalizes_tags_and_preserves_source(self):
        definition = self.make_definition()
        self.assertEqual(definition.tags, ("opening", "calculation"))
        self.assertEqual(definition.source_id, "local-pack-1")

    def test_correct_move_advances_exactly_one_step(self):
        session = ExerciseSession(self.make_definition())
        result = session.submit("  e4  ")
        self.assertTrue(result.accepted)
        self.assertEqual(result.step_index, 1)
        self.assertEqual(result.status, ExerciseStatus.IN_PROGRESS)
        self.assertEqual(result.explanation, "Good central move.")
        self.assertEqual(result.move, "e4")
        self.assertNotEqual(session.current_fen, Board.START)

    def test_incorrect_move_does_not_advance_or_mutate_position(self):
        session = ExerciseSession(self.make_definition())
        before = session.current_fen
        result = session.submit("Nf3")
        self.assertFalse(result.accepted)
        self.assertEqual(result.step_index, 0)
        self.assertEqual(session.step_index, 0)
        self.assertEqual(session.attempts, 1)
        self.assertEqual(session.mistakes, 1)
        self.assertEqual(session.current_fen, before)

    def test_multiple_spellings_of_same_accepted_move_use_canonical_core(self):
        session = ExerciseSession(self.make_definition())
        first = session.submit("e2e4")
        second = session.submit("e7e5")
        self.assertEqual(first.move, "e4")
        self.assertEqual(second.move, "e5")
        self.assertTrue(second.accepted)
        self.assertTrue(second.completed)
        self.assertEqual(second.status, ExerciseStatus.COMPLETED)
        self.assertEqual(session.accepted_path, ("e4", "e5"))

    def test_completed_session_rejects_extra_submission(self):
        session = ExerciseSession(self.make_definition())
        session.submit("e4")
        session.submit("e5")
        with self.assertRaisesRegex(ValueError, "already completed"):
            session.submit("Nf3")

    def test_hint_does_not_advance_or_count_as_attempt(self):
        session = ExerciseSession(self.make_definition())
        before = session.current_fen
        hint = session.request_hint()
        self.assertTrue(hint.available)
        self.assertEqual(hint.hints_used, 1)
        self.assertEqual(session.step_index, 0)
        self.assertEqual(session.attempts, 0)
        self.assertEqual(session.current_fen, before)

    def test_reset_restores_clean_session_and_canonical_start_position(self):
        session = ExerciseSession(self.make_definition())
        session.request_hint()
        session.submit("Nf3")
        session.submit("e4")
        session.reset()
        self.assertEqual(session.status, ExerciseStatus.READY)
        self.assertEqual(session.step_index, 0)
        self.assertEqual(session.attempts, 0)
        self.assertEqual(session.mistakes, 0)
        self.assertEqual(session.hints_used, 0)
        self.assertEqual(session.current_fen, Board.START)
        self.assertEqual(session.accepted_path, ())

    def test_snapshot_roundtrip_restores_exact_progress_and_position(self):
        definition = self.make_definition()
        session = ExerciseSession(definition)
        session.request_hint()
        session.submit("Nf3")
        session.submit("e2e4")
        snapshot = session.snapshot()
        self.assertEqual(snapshot["schema_version"], 4)
        self.assertEqual(snapshot["accepted_path"], ["e4"])
        restored = ExerciseSession.restore(definition, snapshot)
        self.assertEqual(restored.step_index, 1)
        self.assertEqual(restored.attempts, 2)
        self.assertEqual(restored.mistakes, 1)
        self.assertEqual(restored.hints_used, 1)
        self.assertEqual(restored.status, ExerciseStatus.IN_PROGRESS)
        self.assertEqual(restored.accepted_path, ("e4",))
        self.assertEqual(restored.current_fen, session.current_fen)
        self.assertEqual(restored.snapshot(), snapshot)

    def test_v4_snapshot_rejects_full_definition_identity_drift(self):
        definition = self.make_definition()
        session = ExerciseSession(definition)
        session.submit("e4")
        snapshot = session.snapshot()

        first = definition.steps[0]
        second = definition.steps[1]
        mutations = {
            "title": ExerciseDefinition(
                definition.exercise_id,
                definition.start_fen,
                definition.steps,
                title=definition.title + " revised",
                tags=definition.tags,
                source_id=definition.source_id,
                metadata=definition.metadata,
            ),
            "tags": ExerciseDefinition(
                definition.exercise_id,
                definition.start_fen,
                definition.steps,
                title=definition.title,
                tags=(*definition.tags, "tactical"),
                source_id=definition.source_id,
                metadata=definition.metadata,
            ),
            "source_id": ExerciseDefinition(
                definition.exercise_id,
                definition.start_fen,
                definition.steps,
                title=definition.title,
                tags=definition.tags,
                source_id="local-pack-2",
                metadata=definition.metadata,
            ),
            "metadata": ExerciseDefinition(
                definition.exercise_id,
                definition.start_fen,
                definition.steps,
                title=definition.title,
                tags=definition.tags,
                source_id=definition.source_id,
                metadata={**definition.metadata, "difficulty": "advanced"},
            ),
            "hint": ExerciseDefinition(
                definition.exercise_id,
                definition.start_fen,
                (
                    ExerciseStep(
                        first.accepted_moves,
                        hint="A different hint.",
                        explanation=first.explanation,
                    ),
                    second,
                ),
                title=definition.title,
                tags=definition.tags,
                source_id=definition.source_id,
                metadata=definition.metadata,
            ),
            "explanation": ExerciseDefinition(
                definition.exercise_id,
                definition.start_fen,
                (
                    ExerciseStep(
                        first.accepted_moves,
                        hint=first.hint,
                        explanation="A different explanation.",
                    ),
                    second,
                ),
                title=definition.title,
                tags=definition.tags,
                source_id=definition.source_id,
                metadata=definition.metadata,
            ),
        }

        for field, changed in mutations.items():
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "different exercise revision"):
                    ExerciseSession.restore(changed, snapshot)

    def test_v4_definition_metadata_cannot_rebind_active_session_identity(self):
        source_metadata = {"difficulty": "starter", "locale": "en"}
        base = self.make_definition()
        definition = ExerciseDefinition(
            base.exercise_id,
            base.start_fen,
            base.steps,
            title=base.title,
            tags=base.tags,
            source_id=base.source_id,
            metadata=source_metadata,
        )
        session = ExerciseSession(definition)
        before = session.snapshot()

        # Construction snapshots the caller-owned mapping.
        source_metadata["difficulty"] = "mutated"
        self.assertEqual("starter", definition.metadata["difficulty"])

        # Retain plain-dict compatibility, but do not let later mutation rebind
        # an already-running session's persistence identity.
        definition.metadata["difficulty"] = "mutated"
        after = session.snapshot()
        self.assertEqual(before["definition_digest"], after["definition_digest"])

        pristine = ExerciseDefinition(
            base.exercise_id,
            base.start_fen,
            base.steps,
            title=base.title,
            tags=base.tags,
            source_id=base.source_id,
            metadata={"difficulty": "starter", "locale": "en"},
        )
        self.assertEqual(
            after,
            ExerciseSession.restore(pristine, after).snapshot(),
        )
        with self.assertRaisesRegex(ValueError, "different exercise revision"):
            ExerciseSession.restore(definition, after)

    def test_definition_metadata_is_snapshotted_once_before_validation(self):
        class OneGoodReadThenBad(Mapping):
            def __init__(self):
                self.reads = 0

            def __iter__(self):
                return iter(("difficulty",))

            def __len__(self):
                return 1

            def __getitem__(self, key):
                if key != "difficulty":
                    raise KeyError(key)
                self.reads += 1
                return "starter" if self.reads == 1 else 7

        source = OneGoodReadThenBad()
        base = self.make_definition()
        definition = ExerciseDefinition(
            base.exercise_id,
            base.start_fen,
            base.steps,
            title=base.title,
            tags=base.tags,
            source_id=base.source_id,
            metadata=source,
        )

        self.assertEqual({"difficulty": "starter"}, dict(definition.metadata))
        self.assertEqual(1, source.reads)
        snapshot = ExerciseSession(definition).snapshot()
        self.assertEqual(
            snapshot,
            ExerciseSession.restore(definition, snapshot).snapshot(),
        )

    def test_schema_v3_snapshot_remains_readable_and_upgrades_to_v4(self):
        definition = self.make_definition()
        session = ExerciseSession(definition)
        session.request_hint()
        session.submit("Nf3")
        session.submit("e4")
        snapshot = session.snapshot()

        legacy_payload = {
            "start_fen": definition.start_fen,
            "steps": [sorted(step.accepted_moves) for step in definition.steps],
        }
        legacy_digest = hashlib.sha256(
            json.dumps(
                legacy_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        snapshot["schema_version"] = 3
        snapshot["definition_digest"] = legacy_digest

        restored = ExerciseSession.restore(definition, snapshot)
        self.assertEqual(restored.step_index, 1)
        self.assertEqual(restored.accepted_path, ("e4",))
        upgraded = restored.snapshot()
        self.assertEqual(upgraded["schema_version"], 4)
        self.assertNotEqual(upgraded["definition_digest"], legacy_digest)

    def test_v4_definition_digest_is_deterministic_across_metadata_order(self):
        first = self.make_definition()
        second = ExerciseDefinition(
            first.exercise_id,
            first.start_fen,
            first.steps,
            title=first.title,
            tags=first.tags,
            source_id=first.source_id,
            metadata={"locale": "en", "difficulty": "starter"},
        )

        self.assertEqual(
            ExerciseSession(first).snapshot()["definition_digest"],
            ExerciseSession(second).snapshot()["definition_digest"],
        )

    def test_snapshot_from_other_exercise_is_rejected(self):
        definition = self.make_definition()
        snapshot = ExerciseSession(definition).snapshot()
        other = ExerciseDefinition("other", definition.start_fen, definition.steps)
        with self.assertRaisesRegex(ValueError, "different exercise"):
            ExerciseSession.restore(other, snapshot)

    def test_invalid_snapshot_cannot_claim_false_completion(self):
        definition = self.make_definition()
        snapshot = ExerciseSession(definition).snapshot()
        snapshot["status"] = "completed"
        with self.assertRaisesRegex(ValueError, "unfinished"):
            ExerciseSession.restore(definition, snapshot)

    def test_v4_identity_fields_reject_non_text_scalars_at_ingress(self):
        with self.assertRaisesRegex(TypeError, "hint"):
            ExerciseStep(frozenset({"e4"}), hint=7)  # type: ignore[arg-type]
        with self.assertRaisesRegex(TypeError, "explanation"):
            ExerciseStep(frozenset({"e4"}), explanation=7)  # type: ignore[arg-type]

        step = ExerciseStep(frozenset({"e4"}))
        with self.assertRaisesRegex(TypeError, "title"):
            ExerciseDefinition(  # type: ignore[arg-type]
                "bad-title",
                Board.START,
                (step,),
                title=7,
            )
        with self.assertRaisesRegex(TypeError, "tags"):
            ExerciseDefinition(
                "bad-tags",
                Board.START,
                (step,),
                tags="opening",  # type: ignore[arg-type]
            )
        with self.assertRaisesRegex(TypeError, "metadata"):
            ExerciseDefinition(  # type: ignore[arg-type]
                "bad-metadata-value",
                Board.START,
                (step,),
                metadata={"difficulty": 7},
            )
        with self.assertRaisesRegex(TypeError, "metadata"):
            ExerciseDefinition(  # type: ignore[arg-type]
                "bad-metadata-key",
                Board.START,
                (step,),
                metadata={7: "starter"},
            )

    def test_empty_move_empty_step_and_scalar_coercion_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            ExerciseStep(frozenset())
        session = ExerciseSession(self.make_definition())
        with self.assertRaisesRegex(ValueError, "move must not be empty"):
            session.submit("   ")
        with self.assertRaises(TypeError):
            session.submit(123)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
