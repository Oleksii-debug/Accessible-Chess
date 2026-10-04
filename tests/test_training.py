import unittest
from unittest.mock import patch

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

    def test_raw_move_bound_precedes_chess_parsing_and_preserves_state(self):
        session = ExerciseSession(self.make_definition())
        before = session.snapshot()
        oversized = "e4" + (" " * 63)

        with patch(
            "acs.training.Board.parse_move",
            side_effect=AssertionError("oversized raw move must fail before chess parsing"),
        ) as parse_move:
            with self.assertRaisesRegex(ValueError, "move text is too long"):
                session.submit(oversized)

        parse_move.assert_not_called()
        self.assertEqual(before, session.snapshot())

    def test_durable_move_bound_precedes_board_replay(self):
        definition = self.make_definition()
        session = ExerciseSession(definition)
        session.submit("e4")
        snapshot = session.snapshot()
        snapshot["accepted_path"][0] = "e4" + (" " * 63)

        with patch(
            "acs.training.Board",
            side_effect=AssertionError("oversized durable move must fail before board replay"),
        ) as board_type:
            with self.assertRaisesRegex(ValueError, "move text is too long"):
                ExerciseSession.restore(definition, snapshot)

        board_type.assert_not_called()

    def test_definition_step_count_precedes_materialization(self):
        class OversizedSteps:
            def __len__(self):
                return 2049

            def __iter__(self):
                raise AssertionError("oversized steps must fail before iteration")

        with self.assertRaisesRegex(ValueError, "too many steps"):
            ExerciseDefinition(
                "oversized-steps",
                Board.START,
                OversizedSteps(),  # type: ignore[arg-type]
            )

    def test_unsized_definition_iterables_remain_supported_but_bounded(self):
        steps = (
            step
            for step in (
                ExerciseStep(frozenset({"e4"})),
                ExerciseStep(frozenset({"e5"})),
            )
        )
        tags = (tag for tag in ("Opening", "Calculation"))
        definition = ExerciseDefinition(
            "generator-definition",
            Board.START,
            steps,  # type: ignore[arg-type]
            tags=tags,  # type: ignore[arg-type]
        )
        self.assertEqual(2, len(definition.steps))
        self.assertEqual(("opening", "calculation"), definition.tags)

        yielded_steps = 0

        def endless_steps():
            nonlocal yielded_steps
            step = ExerciseStep(frozenset({"e4"}))
            while True:
                yielded_steps += 1
                yield step

        with self.assertRaisesRegex(ValueError, "too many steps"):
            ExerciseDefinition(
                "endless-steps",
                Board.START,
                endless_steps(),  # type: ignore[arg-type]
            )
        self.assertEqual(2049, yielded_steps)

        yielded_tags = 0

        def endless_tags():
            nonlocal yielded_tags
            while True:
                yielded_tags += 1
                yield "tag"

        with self.assertRaisesRegex(ValueError, "too many tags"):
            ExerciseDefinition(
                "endless-tags",
                Board.START,
                (ExerciseStep(frozenset({"e4"})),),
                tags=endless_tags(),  # type: ignore[arg-type]
            )
        self.assertEqual(257, yielded_tags)

    def test_source_id_type_contract_is_preserved(self):
        with self.assertRaisesRegex(TypeError, "source_id must be a string or None"):
            ExerciseDefinition(
                "bad-source-id",
                Board.START,
                (ExerciseStep(frozenset({"e4"})),),
                source_id=True,  # type: ignore[arg-type]
            )

    def test_definition_tag_count_precedes_tag_iteration(self):
        class OversizedTags:
            def __len__(self):
                return 257

            def __iter__(self):
                raise AssertionError("oversized tags must fail before iteration")

        with self.assertRaisesRegex(ValueError, "too many tags"):
            ExerciseDefinition(
                "oversized-tags",
                Board.START,
                (ExerciseStep(frozenset({"e4"})),),
                tags=OversizedTags(),  # type: ignore[arg-type]
            )

    def test_definition_metadata_count_precedes_item_iteration(self):
        class OversizedMetadata(dict):
            def __len__(self):
                return 257

            def items(self):
                raise AssertionError("oversized metadata must fail before items scan")

        with self.assertRaisesRegex(ValueError, "too many items"):
            ExerciseDefinition(
                "oversized-metadata",
                Board.START,
                (ExerciseStep(frozenset({"e4"})),),
                metadata=OversizedMetadata(),
            )

    def test_definition_raw_scalar_bounds_precede_normalization_and_board_parse(self):
        with patch(
            "acs.training.Board",
            side_effect=AssertionError("oversized definition scalar must fail before Board"),
        ) as board_type:
            with self.assertRaisesRegex(ValueError, "exercise_id is too long"):
                ExerciseDefinition(
                    "x" * 4097,
                    Board.START,
                    (ExerciseStep(frozenset({"e4"})),),
                )
        board_type.assert_not_called()

        with patch(
            "acs.training.Board",
            side_effect=AssertionError("oversized FEN must fail before Board"),
        ) as board_type:
            with self.assertRaisesRegex(ValueError, "start_fen is too long"):
                ExerciseDefinition(
                    "fen-bound",
                    "x" * 4097,
                    (ExerciseStep(frozenset({"e4"})),),
                )
        board_type.assert_not_called()

    def test_snapshot_field_count_precedes_mapping_iteration(self):
        class OversizedSnapshot(dict):
            def __len__(self):
                return 10

            def __contains__(self, _key):
                raise AssertionError("oversized snapshot must fail before key lookup")

            def __iter__(self):
                raise AssertionError("oversized snapshot must fail before field iteration")

        with self.assertRaisesRegex(ValueError, "field count"):
            ExerciseSession.restore(self.make_definition(), OversizedSnapshot())

    def test_snapshot_scalar_bounds_precede_identity_and_position_comparison(self):
        definition = self.make_definition()
        session = ExerciseSession(definition)
        snapshot = session.snapshot()
        snapshot["exercise_id"] = "x" * 4097
        with self.assertRaisesRegex(ValueError, "exercise_id is too long"):
            ExerciseSession.restore(definition, snapshot)

        snapshot = session.snapshot()
        snapshot["position_fen"] = "x" * 4097
        with self.assertRaisesRegex(ValueError, "position_fen is too long"):
            ExerciseSession.restore(definition, snapshot)

    def test_session_rejects_definition_subclass_before_attribute_hooks(self):
        class HostileDefinition(ExerciseDefinition):
            touched = False

            def __getattribute__(self, name):
                if name not in {"touched", "__class__"}:
                    type(self).touched = True
                    raise AssertionError("rejected definition subclass must stay passive")
                return super().__getattribute__(name)

        hostile = HostileDefinition.__new__(HostileDefinition)
        HostileDefinition.touched = False

        with self.assertRaisesRegex(TypeError, "definition must be an ExerciseDefinition"):
            ExerciseSession(hostile)
        self.assertFalse(HostileDefinition.touched)

    def test_session_rejects_noncanonical_definition_containers_before_hooks(self):
        class BombTuple(tuple):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("definition tuple hook must not execute")

            def __iter__(self):
                type(self).touched = True
                raise AssertionError("definition tuple hook must not execute")

        class BombDict(dict):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("definition metadata hook must not execute")

            def items(self):
                type(self).touched = True
                raise AssertionError("definition metadata hook must not execute")

        definition = self.make_definition()
        original_steps = definition.steps
        object.__setattr__(definition, "steps", BombTuple(original_steps))
        BombTuple.touched = False
        with self.assertRaisesRegex(ValueError, "steps must be canonical"):
            ExerciseSession(definition)
        self.assertFalse(BombTuple.touched)

        object.__setattr__(definition, "steps", original_steps)
        object.__setattr__(definition, "metadata", BombDict(dict(definition.metadata)))
        BombDict.touched = False
        with self.assertRaisesRegex(ValueError, "metadata must be canonical"):
            ExerciseSession(definition)
        self.assertFalse(BombDict.touched)
    def test_session_detaches_from_caller_owned_definition_state(self):
        definition = self.make_definition()
        session = ExerciseSession(definition)

        object.__setattr__(
            definition.steps[0],
            "accepted_moves",
            frozenset({"d4"}),
        )
        definition.metadata["mutated"] = "caller"

        current = session.current_step()
        self.assertIsNotNone(current)
        self.assertEqual(frozenset({"e4", "e2e4"}), current.accepted_moves)
        self.assertNotIn("mutated", session.definition.metadata)
        self.assertTrue(session.submit("e4").accepted)

    def test_session_rejects_public_definition_authority_replacement(self):
        session = ExerciseSession(self.make_definition())
        replacement = ExerciseDefinition(
            session.definition.exercise_id,
            session.definition.start_fen,
            session.definition.steps,
            title=session.definition.title,
            tags=session.definition.tags,
            source_id=session.definition.source_id,
            metadata=session.definition.metadata,
        )
        session.definition = replacement

        with self.assertRaisesRegex(ValueError, "authority was replaced"):
            session.current_step()
        with self.assertRaisesRegex(ValueError, "authority was replaced"):
            session.snapshot()

    def test_session_rejects_low_level_definition_drift(self):
        session = ExerciseSession(self.make_definition())
        object.__setattr__(session.definition, "exercise_id", "changed-id")

        with self.assertRaisesRegex(ValueError, "changed during session"):
            session.current_step()
        with self.assertRaisesRegex(ValueError, "changed during session"):
            session.submit("e4")

    def test_session_internal_container_subclasses_fail_before_hooks(self):
        class BombTuple(tuple):
            def __len__(self):
                raise AssertionError("session steps subclass length hook must not execute")

            def __iter__(self):
                raise AssertionError("session steps subclass iteration hook must not execute")

        class BombDict(dict):
            def __len__(self):
                raise AssertionError("session metadata subclass length hook must not execute")

            def items(self):
                raise AssertionError("session metadata subclass items hook must not execute")

        session = ExerciseSession(self.make_definition())
        original_steps = session.definition.steps
        object.__setattr__(
            session.definition,
            "steps",
            BombTuple(original_steps),
        )
        with self.assertRaisesRegex(ValueError, "steps changed during session"):
            session.current_step()

        object.__setattr__(session.definition, "steps", original_steps)
        object.__setattr__(
            session.definition,
            "metadata",
            BombDict(dict(session.definition.metadata)),
        )
        with self.assertRaisesRegex(ValueError, "metadata changed during session"):
            session.current_step()

    def test_current_step_returns_detached_authority_copy(self):
        session = ExerciseSession(self.make_definition())
        current = session.current_step()
        self.assertIsNotNone(current)
        object.__setattr__(current, "accepted_moves", frozenset({"d4"}))

        self.assertTrue(session.submit("e4").accepted)
        self.assertEqual(("e4",), session.accepted_path)

    def test_snapshot_key_iteration_is_bounded_without_len(self):
        definition = self.make_definition()
        canonical = ExerciseSession(definition).snapshot()

        class InfiniteKeyDict(dict):
            yielded = 0

            def __len__(self):
                raise AssertionError("snapshot Mapping.__len__ must not execute")

            def __iter__(self):
                type(self).yielded = 0
                while True:
                    type(self).yielded += 1
                    yield f"field_{type(self).yielded}"

        hostile = InfiniteKeyDict(canonical)
        with self.assertRaisesRegex(ValueError, "field count"):
            ExerciseSession.restore(definition, hostile)
        self.assertEqual(11, InfiniteKeyDict.yielded)

    def test_snapshot_field_names_are_exact_bounded_text_before_set_sort(self):
        definition = self.make_definition()

        non_text = ExerciseSession(definition).snapshot()
        del non_text["status"]
        non_text[7] = "ready"  # type: ignore[index]
        with self.assertRaisesRegex(TypeError, "field names must be strings"):
            ExerciseSession.restore(definition, non_text)

        overlong = ExerciseSession(definition).snapshot()
        del overlong["status"]
        overlong["x" * 129] = "ready"
        with self.assertRaisesRegex(ValueError, "field name is too long"):
            ExerciseSession.restore(definition, overlong)

    def test_snapshot_same_count_unknown_fields_keep_diagnostics(self):
        definition = self.make_definition()
        snapshot = ExerciseSession(definition).snapshot()
        del snapshot["status"]
        snapshot["future_status"] = "ready"

        with self.assertRaises(ValueError) as caught:
            ExerciseSession.restore(definition, snapshot)
        message = str(caught.exception)
        self.assertIn("missing fields: status", message)
        self.assertIn("unknown fields: future_status", message)

    def test_huge_snapshot_schema_version_has_bounded_error_message(self):
        definition = self.make_definition()
        snapshot = ExerciseSession(definition).snapshot()
        snapshot["schema_version"] = 10 ** 5000

        with self.assertRaises(ValueError) as caught:
            ExerciseSession.restore(definition, snapshot)
        self.assertEqual(
            "unsupported exercise snapshot schema_version",
            str(caught.exception),
        )

    def test_snapshot_counters_must_fit_javascript_safe_integer_domain(self):
        definition = self.make_definition()
        for field in ("attempts", "mistakes", "hints_used"):
            snapshot = ExerciseSession(definition).snapshot()
            snapshot[field] = 1 << 53
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "invalid exercise counters"):
                    ExerciseSession.restore(definition, snapshot)

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
