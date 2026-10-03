import unittest
from collections.abc import Mapping

from acs.chesscore import Board
from acs.training import (
    ExerciseContentError,
    ExerciseDefinition,
    ExerciseSession,
    ExerciseStatus,
    ExerciseStep,
)


class _BombFrozenSet(frozenset):
    def __iter__(self):
        raise AssertionError("frozenset subclass iteration hook must not execute")

    def __len__(self):
        raise AssertionError("frozenset subclass length hook must not execute")


class _BombTuple(tuple):
    def __iter__(self):
        raise AssertionError("tuple subclass iteration hook must not execute")

    def __len__(self):
        raise AssertionError("tuple subclass length hook must not execute")


class _DefinitionSubclass(ExerciseDefinition):
    pass


class _BombDict(dict):
    def __iter__(self):
        raise AssertionError("dict subclass iteration hook must not execute")

    def __len__(self):
        raise AssertionError("dict subclass length hook must not execute")

    def __contains__(self, key):
        raise AssertionError("dict subclass containment hook must not execute")

    def __getitem__(self, key):
        raise AssertionError("dict subclass item hook must not execute")

    def items(self):
        raise AssertionError("dict subclass items hook must not execute")


class CanonicalTrainingEvaluationTests(unittest.TestCase):
    def test_coordinate_alias_and_san_are_the_same_canonical_answer(self):
        definition = ExerciseDefinition(
            "alias",
            Board.START,
            (ExerciseStep(frozenset({"e4"})),),
        )
        session = ExerciseSession(definition)
        result = session.submit("e2e4")
        self.assertTrue(result.accepted)
        self.assertEqual("e4", result.move)
        self.assertEqual(("e4",), session.accepted_path)
        self.assertTrue(session.completed)

    def test_illegal_user_move_is_a_mistake_but_never_mutates_position(self):
        definition = ExerciseDefinition(
            "illegal-user",
            Board.START,
            (ExerciseStep(frozenset({"e4"})),),
        )
        session = ExerciseSession(definition)
        before_fen = session.current_fen
        before_path = session.accepted_path
        result = session.submit("e5")
        self.assertFalse(result.accepted)
        self.assertEqual(1, session.attempts)
        self.assertEqual(1, session.mistakes)
        self.assertEqual(0, session.step_index)
        self.assertEqual(before_fen, session.current_fen)
        self.assertEqual(before_path, session.accepted_path)

    def test_legal_but_incorrect_move_is_a_mistake_without_hidden_board_mutation(self):
        definition = ExerciseDefinition(
            "wrong-legal",
            Board.START,
            (ExerciseStep(frozenset({"e4"})),),
        )
        session = ExerciseSession(definition)
        before = session.current_fen
        result = session.submit("Nf3")
        self.assertFalse(result.accepted)
        self.assertEqual("Nf3", result.move)
        self.assertEqual(before, session.current_fen)
        self.assertEqual((), session.accepted_path)

    def test_malformed_authored_current_step_fails_before_any_session_mutation(self):
        definition = ExerciseDefinition(
            "bad-content",
            Board.START,
            (ExerciseStep(frozenset({"Qa9"})),),
        )
        session = ExerciseSession(definition)
        before = session.snapshot()
        with self.assertRaises(ExerciseContentError):
            session.submit("e4")
        self.assertEqual(before, session.snapshot())

    def test_malformed_next_step_rolls_back_preceding_correct_answer_atomically(self):
        definition = ExerciseDefinition(
            "bad-next-content",
            Board.START,
            (
                ExerciseStep(frozenset({"e4"})),
                ExerciseStep(frozenset({"Qa9"})),
            ),
        )
        session = ExerciseSession(definition)
        before = session.snapshot()
        with self.assertRaises(ExerciseContentError):
            session.submit("e4")
        self.assertEqual(before, session.snapshot())
        self.assertEqual(Board.START, session.current_fen)
        self.assertEqual((), session.accepted_path)

    def test_distinct_correct_alternatives_record_the_exact_chosen_branch(self):
        definition = ExerciseDefinition(
            "branch",
            Board.START,
            (
                ExerciseStep(frozenset({"e4", "d4"})),
                ExerciseStep(frozenset({"e5", "c5"})),
            ),
        )
        e4 = ExerciseSession(definition)
        e4.submit("e4")
        e4.submit("e5")
        d4 = ExerciseSession(definition)
        d4.submit("d4")
        d4.submit("c5")
        self.assertEqual(("e4", "e5"), e4.accepted_path)
        self.assertEqual(("d4", "c5"), d4.accepted_path)
        self.assertNotEqual(e4.current_fen, d4.current_fen)
        self.assertEqual(e4.snapshot(), ExerciseSession.restore(definition, e4.snapshot()).snapshot())
        self.assertEqual(d4.snapshot(), ExerciseSession.restore(definition, d4.snapshot()).snapshot())


class DeterministicResumeTests(unittest.TestCase):
    def make_unambiguous_definition(self):
        return ExerciseDefinition(
            "resume",
            Board.START,
            (
                ExerciseStep(frozenset({"e4", "e2e4"})),
                ExerciseStep(frozenset({"e5", "e7e5"})),
            ),
        )

    def test_schema_v3_persists_canonical_path_and_position(self):
        definition = self.make_unambiguous_definition()
        session = ExerciseSession(definition)
        session.submit("e2e4")
        snapshot = session.snapshot()
        self.assertEqual(3, snapshot["schema_version"])
        self.assertEqual(["e4"], snapshot["accepted_path"])
        self.assertEqual(session.current_fen, snapshot["position_fen"])
        restored = ExerciseSession.restore(definition, snapshot)
        self.assertEqual(("e4",), restored.accepted_path)
        self.assertEqual(session.current_fen, restored.current_fen)
        self.assertEqual(snapshot, restored.snapshot())

    def test_tampered_position_fen_is_rejected(self):
        definition = self.make_unambiguous_definition()
        session = ExerciseSession(definition)
        session.submit("e4")
        snapshot = session.snapshot()
        snapshot["position_fen"] = Board.START
        with self.assertRaisesRegex(ValueError, "position does not match"):
            ExerciseSession.restore(definition, snapshot)

    def test_tampered_path_is_rejected_even_when_move_is_legal(self):
        definition = self.make_unambiguous_definition()
        session = ExerciseSession(definition)
        session.submit("e4")
        snapshot = session.snapshot()
        snapshot["accepted_path"] = ["d4"]
        with self.assertRaisesRegex(ValueError, "not accepted"):
            ExerciseSession.restore(definition, snapshot)

    def test_unreachable_counter_equation_is_rejected(self):
        definition = self.make_unambiguous_definition()
        session = ExerciseSession(definition)
        session.submit("e4")
        snapshot = session.snapshot()
        snapshot["attempts"] = 99
        with self.assertRaisesRegex(ValueError, "counters"):
            ExerciseSession.restore(definition, snapshot)

    def test_v2_unambiguous_snapshot_migrates_by_replaying_canonical_core(self):
        definition = self.make_unambiguous_definition()
        session = ExerciseSession(definition)
        session.submit("e4")
        v3 = session.snapshot()
        legacy = {
            key: value
            for key, value in v3.items()
            if key not in {"accepted_path", "position_fen"}
        }
        legacy["schema_version"] = 2
        restored = ExerciseSession.restore(definition, legacy)
        self.assertEqual(("e4",), restored.accepted_path)
        self.assertEqual(session.current_fen, restored.current_fen)
        self.assertEqual(3, restored.snapshot()["schema_version"])

    def test_v2_distinct_alternative_snapshot_is_rejected_as_ambiguous(self):
        definition = ExerciseDefinition(
            "legacy-branch",
            Board.START,
            (
                ExerciseStep(frozenset({"e4", "d4"})),
                ExerciseStep(frozenset({"e5", "c5"})),
            ),
        )
        session = ExerciseSession(definition)
        session.submit("e4")
        v3 = session.snapshot()
        legacy = {
            key: value
            for key, value in v3.items()
            if key not in {"accepted_path", "position_fen"}
        }
        legacy["schema_version"] = 2
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            ExerciseSession.restore(definition, legacy)

    def test_future_or_unknown_snapshot_fields_fail_closed(self):
        definition = self.make_unambiguous_definition()
        snapshot = ExerciseSession(definition).snapshot()
        snapshot["future_hidden_state"] = "x"
        with self.assertRaisesRegex(ValueError, "unknown fields"):
            ExerciseSession.restore(definition, snapshot)

    def test_noncanonical_recorded_san_is_rejected(self):
        definition = self.make_unambiguous_definition()
        session = ExerciseSession(definition)
        session.submit("e4")
        snapshot = session.snapshot()
        snapshot["accepted_path"] = ["e2e4"]
        with self.assertRaisesRegex(ValueError, "canonical SAN"):
            ExerciseSession.restore(definition, snapshot)


class MalformedAndResourceBoundaryTests(unittest.TestCase):
    def test_constructor_keeps_exact_move_set_and_canonicalizes_definition_containers(self):
        with self.assertRaisesRegex(TypeError, "exact frozenset"):
            ExerciseStep(_BombFrozenSet({"e4"}))

        step = ExerciseStep(frozenset({"e4"}))
        definition = ExerciseDefinition(
            "compatible-containers",
            Board.START,
            [step],  # type: ignore[arg-type]
            tags=(tag for tag in ("Opening", "Calculation")),  # type: ignore[arg-type]
            metadata={"kind": "test"},
        )
        self.assertIs(type(definition.steps), tuple)
        self.assertEqual((step,), definition.steps)
        self.assertIs(type(definition.tags), tuple)
        self.assertEqual(("opening", "calculation"), definition.tags)
        self.assertIs(type(definition.metadata), dict)
        self.assertEqual({"kind": "test"}, definition.metadata)

    def test_session_retains_exact_definition_authority(self):
        subclass = _DefinitionSubclass(
            "subclass",
            Board.START,
            (ExerciseStep(frozenset({"e4"})),),
        )
        with self.assertRaisesRegex(TypeError, "exact ExerciseDefinition"):
            ExerciseSession(subclass)

        definition = ExerciseDefinition(
            "authority",
            Board.START,
            (ExerciseStep(frozenset({"e4"})),),
        )
        session = ExerciseSession(definition)
        session.definition = subclass
        with self.assertRaisesRegex(TypeError, "exact ExerciseDefinition"):
            session.snapshot()
        with self.assertRaisesRegex(TypeError, "exact ExerciseDefinition"):
            session.submit("e4")
        with self.assertRaisesRegex(TypeError, "exact ExerciseDefinition"):
            session.reset()

    def test_session_rejects_postconstruction_container_substitution_before_hooks(self):
        definition = ExerciseDefinition(
            "container-authority",
            Board.START,
            (ExerciseStep(frozenset({"e4"})),),
            tags=("opening",),
            metadata={"kind": "test"},
        )
        session = ExerciseSession(definition)

        object.__setattr__(session.definition, "tags", _BombTuple(("changed",)))
        with self.assertRaisesRegex(TypeError, "tags must be an exact tuple"):
            session.snapshot()

        object.__setattr__(session.definition, "tags", ("opening",))
        object.__setattr__(session.definition, "metadata", _BombDict({"kind": "changed"}))
        with self.assertRaisesRegex(TypeError, "metadata must be an exact dict"):
            session.snapshot()

    def test_session_detaches_from_caller_definition_mutation(self):
        definition = ExerciseDefinition(
            "detached-authority",
            Board.START,
            (ExerciseStep(frozenset({"e4"})),),
        )
        session = ExerciseSession(definition)

        object.__setattr__(definition.steps[0], "accepted_moves", frozenset({"d4"}))

        current = session.current_step()
        self.assertIsNotNone(current)
        self.assertEqual(frozenset({"e4"}), current.accepted_moves)
        self.assertTrue(session.submit("e4").completed)

    def test_session_rejects_exact_definition_replacement_before_semantic_access(self):
        definition = ExerciseDefinition(
            "bound-authority",
            Board.START,
            (ExerciseStep(frozenset({"e4"})),),
        )
        session = ExerciseSession(definition)
        session.definition = ExerciseDefinition(
            "replacement",
            Board.START,
            (ExerciseStep(frozenset({"d4"})),),
        )

        with self.assertRaisesRegex(ValueError, "changed during session"):
            session.current_step()
        with self.assertRaisesRegex(ValueError, "changed during session"):
            session.snapshot()
        with self.assertRaisesRegex(ValueError, "changed during session"):
            session.submit("e4")

    def test_session_rejects_low_level_bound_definition_mutation(self):
        definition = ExerciseDefinition(
            "low-level-authority",
            Board.START,
            (ExerciseStep(frozenset({"e4"})),),
        )
        session = ExerciseSession(definition)
        object.__setattr__(session.definition, "exercise_id", "changed-id")

        with self.assertRaisesRegex(ValueError, "changed during session"):
            session.current_step()

    def test_session_rejects_noncanonical_step_mutation_before_move_parsing(self):
        definition = ExerciseDefinition(
            "noncanonical-step",
            Board.START,
            (ExerciseStep(frozenset({"e4"})),),
        )
        session = ExerciseSession(definition)
        object.__setattr__(
            session.definition.steps[0],
            "accepted_moves",
            frozenset({" e4 "}),
        )

        with self.assertRaisesRegex(ValueError, "not canonical"):
            session.submit("e4")

    def test_snapshot_field_scan_is_bounded_and_requires_string_keys(self):
        definition = ExerciseDefinition(
            "snapshot-field-bounds",
            Board.START,
            (ExerciseStep(frozenset({"e4"})),),
        )

        oversized = ExerciseSession(definition).snapshot()
        oversized.update({f"future_{index}": index for index in range(33)})
        with self.assertRaisesRegex(ValueError, "too many fields"):
            ExerciseSession.restore(definition, oversized)

        non_text_key = ExerciseSession(definition).snapshot()
        non_text_key[7] = "future"  # type: ignore[index]
        with self.assertRaisesRegex(TypeError, "field names must be strings"):
            ExerciseSession.restore(definition, non_text_key)

    def test_restore_state_preserves_session_identity_and_restores_progress(self):
        definition = ExerciseDefinition(
            "in-place-restore",
            Board.START,
            (
                ExerciseStep(frozenset({"e4"})),
                ExerciseStep(frozenset({"e5"})),
            ),
        )
        session = ExerciseSession(definition)
        retained_reference = session
        before = session.snapshot()

        session.submit("e4")
        self.assertEqual(1, session.step_index)
        session.restore_state(before)

        self.assertIs(retained_reference, session)
        self.assertEqual(before, session.snapshot())
        self.assertEqual(Board.START, session.current_fen)
        self.assertEqual((), session.accepted_path)

    def test_restore_state_validates_detached_candidate_before_live_mutation(self):
        definition = ExerciseDefinition(
            "atomic-in-place-restore",
            Board.START,
            (ExerciseStep(frozenset({"e4"})),),
        )
        session = ExerciseSession(definition)
        session.submit("e4")
        before = session.snapshot()
        invalid = dict(before)
        invalid["status"] = "ready"

        with self.assertRaises(ValueError):
            session.restore_state(invalid)

        self.assertEqual(before, session.snapshot())

    def test_constructor_raw_move_and_metadata_resources_are_bounded(self):
        with self.assertRaisesRegex(ValueError, "too long"):
            ExerciseStep(frozenset({"e4" + (" " * 63)}))

        with self.assertRaisesRegex(ValueError, "too many items"):
            ExerciseDefinition(
                "metadata-count",
                Board.START,
                (ExerciseStep(frozenset({"e4"})),),
                metadata={f"k{index}": "v" for index in range(257)},
            )

        with self.assertRaisesRegex(ValueError, "too many tags"):
            ExerciseDefinition(
                "tag-count",
                Board.START,
                (ExerciseStep(frozenset({"e4"})),),
                tags=tuple(f"tag-{index}" for index in range(257)),
            )

    def test_snapshot_dict_subclass_hooks_are_bypassed_during_restore(self):
        definition = ExerciseDefinition(
            "snapshot-container",
            Board.START,
            (ExerciseStep(frozenset({"e4"})),),
        )
        session = ExerciseSession(definition)
        session.submit("e4")
        snapshot = session.snapshot()
        restored = ExerciseSession.restore(definition, _BombDict(snapshot))
        self.assertEqual(snapshot, restored.snapshot())

    def test_generic_snapshot_mapping_is_detached_before_replay(self):
        definition = ExerciseDefinition(
            "snapshot-mapping",
            Board.START,
            (ExerciseStep(frozenset({"e4"})),),
        )
        session = ExerciseSession(definition)
        session.submit("e4")
        raw = session.snapshot()

        class ReadOnceMapping(Mapping):
            def __init__(self, data):
                self._data = data
                self.iter_calls = 0
                self.value_calls = 0

            def __len__(self):
                return len(self._data)

            def __iter__(self):
                self.iter_calls += 1
                if self.iter_calls > 1:
                    raise AssertionError("snapshot mapping must be iterated once")
                return iter(self._data)

            def __getitem__(self, key):
                self.value_calls += 1
                return self._data[key]

        wrapped = ReadOnceMapping(raw)
        restored = ExerciseSession.restore(definition, wrapped)

        self.assertEqual(raw, restored.snapshot())
        self.assertEqual(1, wrapped.iter_calls)
        self.assertEqual(len(raw), wrapped.value_calls)

    def test_snapshot_scalar_resources_are_bounded_before_replay(self):
        definition = ExerciseDefinition(
            "snapshot-bounds",
            Board.START,
            (ExerciseStep(frozenset({"e4"})),),
        )
        snapshot = ExerciseSession(definition).snapshot()
        snapshot["attempts"] = (1 << 53)
        snapshot["mistakes"] = (1 << 53)
        snapshot["status"] = "in_progress"
        with self.assertRaisesRegex(ValueError, "counters"):
            ExerciseSession.restore(definition, snapshot)

        snapshot = ExerciseSession(definition).snapshot()
        snapshot["position_fen"] = "x" * 4097
        with self.assertRaisesRegex(ValueError, "position_fen is too long"):
            ExerciseSession.restore(definition, snapshot)

    def test_invalid_start_position_uses_canonical_fen_validation(self):
        with self.assertRaises(ValueError):
            ExerciseDefinition(
                "bad-fen",
                "8/8/8/8/8/8/8/8 w - - 0 1",
                (ExerciseStep(frozenset({"e4"})),),
            )

    def test_scalar_moves_are_not_coerced_to_text(self):
        with self.assertRaises(TypeError):
            ExerciseStep(frozenset({123}))  # type: ignore[arg-type]
        definition = ExerciseDefinition(
            "scalar",
            Board.START,
            (ExerciseStep(frozenset({"e4"})),),
        )
        session = ExerciseSession(definition)
        before = session.snapshot()
        with self.assertRaises(TypeError):
            session.submit(True)  # type: ignore[arg-type]
        self.assertEqual(before, session.snapshot())

    def test_move_text_and_accepted_move_collection_are_bounded(self):
        with self.assertRaisesRegex(ValueError, "too many"):
            ExerciseStep(frozenset(f"a{i}" for i in range(65)))
        definition = ExerciseDefinition(
            "long-move",
            Board.START,
            (ExerciseStep(frozenset({"e4"})),),
        )
        session = ExerciseSession(definition)
        with self.assertRaisesRegex(ValueError, "too long"):
            session.submit("x" * 65)

    def test_reset_after_branch_restores_start_without_reusing_hidden_board_state(self):
        definition = ExerciseDefinition(
            "reset-branch",
            Board.START,
            (
                ExerciseStep(frozenset({"d4", "e4"})),
                ExerciseStep(frozenset({"c5", "e5"})),
            ),
        )
        session = ExerciseSession(definition)
        session.submit("d4")
        session.request_hint()
        session.reset()
        self.assertEqual(Board.START, session.current_fen)
        self.assertEqual((), session.accepted_path)
        self.assertEqual(ExerciseStatus.READY, session.status)
        self.assertEqual(0, session.attempts)
        self.assertEqual(0, session.mistakes)
        self.assertEqual(0, session.hints_used)


if __name__ == "__main__":
    unittest.main()
