import hashlib
import json
import unittest

from acs.chesscore import Board
from acs.training import ExerciseDefinition, ExerciseSession, ExerciseStep


def _definition(
    *,
    title: str = "Fork tactic",
    tags: tuple[str, ...] = ("tactic", "fork"),
    source_id: str | None = "starter-001",
    metadata: dict[str, str] | None = None,
    hint: str | None = "Attack both pieces.",
    explanation: str | None = "The knight forks king and rook.",
) -> ExerciseDefinition:
    return ExerciseDefinition(
        "definition-identity",
        Board.START,
        (ExerciseStep(frozenset({"e4"}), hint=hint, explanation=explanation),),
        title=title,
        tags=tags,
        source_id=source_id,
        metadata={"difficulty": "1", "theme": "fork"} if metadata is None else metadata,
    )


def _legacy_digest(definition: ExerciseDefinition) -> str:
    payload = {
        "start_fen": definition.start_fen,
        "steps": [sorted(step.accepted_moves) for step in definition.steps],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class TrainingSnapshotDefinitionIdentityV4Tests(unittest.TestCase):
    def test_new_snapshot_is_schema_v4_and_round_trips(self) -> None:
        definition = _definition()
        session = ExerciseSession(definition)
        snapshot = session.snapshot()

        self.assertEqual(4, snapshot["schema_version"])
        restored = ExerciseSession.restore(definition, snapshot)
        self.assertEqual(snapshot, restored.snapshot())

    def test_v4_rejects_every_non_chess_definition_identity_drift(self) -> None:
        definition = _definition()
        snapshot = ExerciseSession(definition).snapshot()
        variants = {
            "title": _definition(title="Changed title"),
            "tags": _definition(tags=("tactic", "double-attack")),
            "source_id": _definition(source_id="starter-002"),
            "metadata": _definition(metadata={"difficulty": "2", "theme": "fork"}),
            "hint": _definition(hint="Changed hint"),
            "explanation": _definition(explanation="Changed explanation"),
        }

        for name, changed in variants.items():
            with self.subTest(field=name):
                with self.assertRaisesRegex(ValueError, "different exercise revision"):
                    ExerciseSession.restore(changed, snapshot)

    def test_v4_digest_is_deterministic_across_metadata_insertion_order(self) -> None:
        first = _definition(metadata={"difficulty": "1", "theme": "fork"})
        second = _definition(metadata={"theme": "fork", "difficulty": "1"})

        self.assertEqual(
            ExerciseSession(first).snapshot()["definition_digest"],
            ExerciseSession(second).snapshot()["definition_digest"],
        )

    def test_legacy_v3_remains_readable_and_upgrades_to_v4(self) -> None:
        old_definition = _definition(title="Old title", metadata={"edition": "old"})
        session = ExerciseSession(old_definition)
        session.submit("e4")
        legacy = session.snapshot()
        legacy["schema_version"] = 3
        legacy["definition_digest"] = _legacy_digest(old_definition)

        # v3 historically authenticated only start_fen + accepted moves, so a
        # non-chess presentation revision must remain readable for compatibility.
        revised = _definition(title="New title", metadata={"edition": "new"})
        restored = ExerciseSession.restore(revised, legacy)
        upgraded = restored.snapshot()

        self.assertEqual(("e4",), restored.accepted_path)
        self.assertEqual(4, upgraded["schema_version"])
        self.assertNotEqual(legacy["definition_digest"], upgraded["definition_digest"])
        with self.assertRaisesRegex(ValueError, "different exercise revision"):
            ExerciseSession.restore(old_definition, upgraded)

    def test_restore_state_definition_mismatch_is_atomic(self) -> None:
        source = ExerciseSession(_definition())
        source_snapshot = source.snapshot()
        target = ExerciseSession(_definition(title="Different title"))
        before = target.snapshot()

        with self.assertRaisesRegex(ValueError, "different exercise revision"):
            target.restore_state(source_snapshot)

        self.assertEqual(before, target.snapshot())


if __name__ == "__main__":
    unittest.main()
