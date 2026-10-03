import copy
import json
import unittest
from unittest.mock import patch

from acs.book_training import (
    BOOK_TRAINING_SCHEMA_VERSION,
    BookTrainingError,
    BookTrainingErrorCode,
    build_book_training_material,
    build_current_book_training_material,
    resolve_book_training_origin,
    restore_book_training_material,
    return_reader_to_book_training_origin,
)
from acs.bookdocument import BookDocument, Exercise, Heading, Paragraph
from acs.bookreader import BookReader
from acs.training import ExerciseSession


START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
KING_FEN = "8/8/8/8/8/8/4K3/7k w - - 0 1"


def make_book(*, source_name="training-source.docx", blocks=None):
    return BookDocument(
        "Training book",
        language="uk",
        author="Author",
        source_name=source_name,
        blocks=list(blocks or []),
    )


class BookTrainingCanonicalConversionTests(unittest.TestCase):
    def test_answer_text_becomes_one_canonical_move_without_mutating_book(self):
        exercise = Exercise(
            fen=KING_FEN,
            prompt="Move the king.",
            answer_text="Kf3",
            block_id="ex-king",
            difficulty="beginner",
        )
        book = make_book(blocks=[exercise])
        before = book.as_dict()

        material = build_book_training_material(book, "block:ex-king")

        self.assertEqual(before, book.as_dict())
        self.assertEqual(material.definition.start_fen, KING_FEN)
        self.assertEqual(material.definition.steps[0].accepted_moves, frozenset({"Kf3"}))
        self.assertEqual(material.definition.title, "Move the king.")
        self.assertEqual(material.definition.metadata["difficulty"], "beginner")
        session = ExerciseSession(material.definition)
        result = session.submit("e2f3")
        self.assertTrue(result.completed)
        self.assertEqual(session.accepted_path, ("Kf3",))

    def test_solution_pgn_mainline_uses_gametree_structure_and_canonical_board(self):
        exercise = Exercise(
            fen=START_FEN,
            prompt="Play the opening line.",
            solution_pgn="1. e4 e5 2. Nf3 *",
            source_anchor="exercise-12",
        )
        book = make_book(blocks=[exercise])
        material = build_book_training_material(book, "source:exercise-12")

        self.assertEqual(
            tuple(next(iter(step.accepted_moves)) for step in material.definition.steps),
            ("e4", "e5", "Nf3"),
        )
        session = ExerciseSession(material.definition)
        self.assertTrue(session.submit("e2e4").accepted)
        self.assertTrue(session.submit("e7e5").accepted)
        self.assertTrue(session.submit("g1f3").completed)
        self.assertEqual(session.accepted_path, ("e4", "e5", "Nf3"))

    def test_illegal_book_answer_fails_through_canonical_core(self):
        book = make_book(
            blocks=[
                Exercise(
                    fen=KING_FEN,
                    prompt="Impossible pawn move.",
                    answer_text="e4",
                    block_id="bad",
                )
            ]
        )
        before = book.as_dict()
        with self.assertRaises(BookTrainingError) as caught:
            build_book_training_material(book, "block:bad")
        self.assertEqual(caught.exception.code, BookTrainingErrorCode.ILLEGAL_SOLUTION)
        self.assertEqual(before, book.as_dict())

    def test_mismatched_pgn_fen_fails_instead_of_switching_position(self):
        book = make_book(
            blocks=[
                Exercise(
                    fen=START_FEN,
                    prompt="No hidden position switch.",
                    solution_pgn=(
                        '[SetUp "1"]\n'
                        '[FEN "8/8/8/8/8/8/4K3/7k w - - 0 1"]\n\n'
                        "1. Kf3 *"
                    ),
                    block_id="mismatch",
                )
            ]
        )
        with self.assertRaises(BookTrainingError) as caught:
            build_book_training_material(book, "block:mismatch")
        self.assertEqual(
            caught.exception.code,
            BookTrainingErrorCode.UNSUPPORTED_SOLUTION_STRUCTURE,
        )

    def test_variations_annotations_and_dual_solution_sources_fail_closed(self):
        for solution in (
            "1. e4 (1. d4) *",
            "1. e4 $1 *",
            "1. e4 {comment} *",
        ):
            with self.subTest(solution=solution):
                book = make_book(
                    blocks=[
                        Exercise(
                            fen=START_FEN,
                            prompt="No silent flattening.",
                            solution_pgn=solution,
                            block_id="structured",
                        )
                    ]
                )
                with self.assertRaises(BookTrainingError) as caught:
                    build_book_training_material(book, "block:structured")
                self.assertEqual(
                    caught.exception.code,
                    BookTrainingErrorCode.UNSUPPORTED_SOLUTION_STRUCTURE,
                )

        dual = make_book(
            blocks=[
                Exercise(
                    fen=START_FEN,
                    prompt="Ambiguous authoring policy.",
                    solution_pgn="1. e4 *",
                    answer_text="e4",
                    block_id="dual",
                )
            ]
        )
        with self.assertRaises(BookTrainingError) as caught:
            build_book_training_material(dual, "block:dual")
        self.assertEqual(caught.exception.code, BookTrainingErrorCode.UNSUPPORTED_SOLUTION)

    def test_non_exercise_and_ambiguous_semantic_targets_never_guess(self):
        non_exercise = make_book(blocks=[Paragraph(text="Text", block_id="p")])
        with self.assertRaises(BookTrainingError) as caught:
            build_book_training_material(non_exercise, "block:p")
        self.assertEqual(caught.exception.code, BookTrainingErrorCode.INVALID_TARGET)

        duplicate = make_book(
            blocks=[
                Exercise(fen=KING_FEN, prompt="One", answer_text="Kf3", block_id="same"),
                Exercise(fen=KING_FEN, prompt="Two", answer_text="Kd3", block_id="same"),
            ]
        )
        with self.assertRaises(BookTrainingError) as caught:
            build_book_training_material(duplicate, "block:same")
        self.assertEqual(caught.exception.code, BookTrainingErrorCode.INVALID_TARGET)


class BookTrainingOriginTests(unittest.TestCase):
    def test_semantic_origin_survives_surrounding_reorder_and_returns_reader(self):
        exercise = Exercise(
            fen=KING_FEN,
            prompt="Return here.",
            answer_text="Kf3",
            block_id="exercise-stable",
            source_anchor="paragraph-20",
        )
        original = make_book(
            blocks=[Heading(text="Chapter", level=1, block_id="h"), exercise]
        )
        material = build_book_training_material(original, "block:exercise-stable")
        self.assertEqual(material.origin.index_at_export, 1)

        reordered = make_book(
            blocks=[
                Paragraph(text="Inserted before the chapter."),
                Heading(text="Chapter", level=1, block_id="h"),
                Exercise(**{k: v for k, v in exercise.as_dict().items() if k != "kind"}),
            ]
        )
        location = resolve_book_training_origin(reordered, material.origin)
        self.assertEqual(location.index, 2)
        self.assertEqual(location.block_id, "exercise-stable")

        reader = BookReader(reordered)
        reader.go_to(0)
        returned = return_reader_to_book_training_origin(reader, material.origin)
        self.assertEqual(returned.index, 2)
        self.assertEqual(reader.index, 2)

    def test_index_fallback_is_snapshot_bound_and_fails_after_reorder(self):
        exercise = Exercise(fen=KING_FEN, prompt="Fallback", answer_text="Kf3")
        original = make_book(blocks=[exercise])
        material = build_book_training_material(original, 0)
        self.assertEqual(material.origin.target_key, "index:0")

        changed = make_book(
            blocks=[
                Paragraph(text="Inserted"),
                Exercise(**{k: v for k, v in exercise.as_dict().items() if k != "kind"}),
            ]
        )
        with self.assertRaises(BookTrainingError) as caught:
            resolve_book_training_origin(changed, material.origin)
        self.assertEqual(caught.exception.code, BookTrainingErrorCode.STALE_ORIGIN)

    def test_same_target_with_revised_exercise_content_fails_stale(self):
        original = make_book(
            blocks=[
                Exercise(
                    fen=KING_FEN,
                    prompt="Original prompt",
                    answer_text="Kf3",
                    block_id="stable",
                )
            ]
        )
        material = build_book_training_material(original, "block:stable")
        revised = make_book(
            blocks=[
                Exercise(
                    fen=KING_FEN,
                    prompt="Changed prompt",
                    answer_text="Kf3",
                    block_id="stable",
                )
            ]
        )
        with self.assertRaises(BookTrainingError) as caught:
            resolve_book_training_origin(revised, material.origin)
        self.assertEqual(caught.exception.code, BookTrainingErrorCode.STALE_ORIGIN)

    def test_current_reader_conversion_requires_current_exercise(self):
        book = make_book(
            blocks=[
                Paragraph(text="Intro"),
                Exercise(fen=KING_FEN, prompt="Exercise", answer_text="Kf3", block_id="ex"),
            ]
        )
        reader = BookReader(book)
        with self.assertRaises(BookTrainingError):
            build_current_book_training_material(reader)
        reader.go_to(1)
        material = build_current_book_training_material(reader)
        self.assertEqual(material.origin.target_key, "block:ex")


class BookTrainingWireContractTests(unittest.TestCase):
    def setUp(self):
        self.private_source = r"C:\Users\BlindTeacher\Documents\private-book.docx"
        self.book = make_book(
            source_name=self.private_source,
            blocks=[
                Exercise(
                    fen=START_FEN,
                    prompt="Opening",
                    solution_pgn="1. e4 e5 *",
                    block_id="opening-1",
                    difficulty="easy",
                )
            ],
        )
        self.material = build_book_training_material(self.book, "block:opening-1")
        self.payload = self.material.as_dict()

    def test_export_is_versioned_deterministic_and_does_not_expose_source_path(self):
        self.assertEqual(self.payload["schema_version"], BOOK_TRAINING_SCHEMA_VERSION)
        self.assertEqual(self.payload, self.material.as_dict())
        encoded = json.dumps(self.payload, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(self.private_source, encoded)
        self.assertNotIn("BlindTeacher", encoded)
        self.assertTrue(self.material.definition.source_id.startswith("book:"))
        self.assertNotIn("opening-1", self.material.definition.source_id)

    def test_export_restore_revalidates_source_and_canonical_definition(self):
        restored = restore_book_training_material(self.book, self.payload)
        self.assertEqual(restored.as_dict(), self.payload)
        session = ExerciseSession(restored.definition)
        session.submit("e4")
        self.assertTrue(session.submit("e5").completed)

    def test_future_unknown_and_coercive_wire_fields_fail_closed(self):
        future = copy.deepcopy(self.payload)
        future["schema_version"] = BOOK_TRAINING_SCHEMA_VERSION + 1
        with self.assertRaises(BookTrainingError) as caught:
            restore_book_training_material(self.book, future)
        self.assertEqual(caught.exception.code, BookTrainingErrorCode.UNSUPPORTED_SCHEMA)

        unknown = copy.deepcopy(self.payload)
        unknown["extra"] = True
        with self.assertRaises(BookTrainingError) as caught:
            restore_book_training_material(self.book, unknown)
        self.assertEqual(caught.exception.code, BookTrainingErrorCode.UNKNOWN_FIELD)

        coercive = copy.deepcopy(self.payload)
        coercive["origin"]["index_at_export"] = True
        with self.assertRaises(BookTrainingError) as caught:
            restore_book_training_material(self.book, coercive)
        self.assertEqual(caught.exception.code, BookTrainingErrorCode.INVALID_FIELD)

    def test_wire_field_discovery_is_bounded_before_set_hashing(self):
        oversized = copy.deepcopy(self.payload)
        oversized.update({f"extra_{index}": None for index in range(1_000)})

        with patch(
            "acs.book_training.set",
            side_effect=AssertionError("oversized fields must fail before set()"),
            create=True,
        ):
            with self.assertRaises(BookTrainingError) as caught:
                restore_book_training_material(self.book, oversized)

        self.assertEqual(caught.exception.code, BookTrainingErrorCode.UNKNOWN_FIELD)

        long_name = copy.deepcopy(self.payload)
        del long_name["schema_version"]
        long_name["x" * 129] = BOOK_TRAINING_SCHEMA_VERSION
        with patch(
            "acs.book_training.set",
            side_effect=AssertionError("oversized field name must fail before set()"),
            create=True,
        ):
            with self.assertRaises(BookTrainingError) as caught:
                restore_book_training_material(self.book, long_name)

        self.assertEqual(caught.exception.code, BookTrainingErrorCode.UNKNOWN_FIELD)

    def test_huge_schema_version_uses_bounded_error_message(self):
        future = copy.deepcopy(self.payload)
        future["schema_version"] = 10 ** 5_000

        with self.assertRaises(BookTrainingError) as caught:
            restore_book_training_material(self.book, future)

        self.assertEqual(
            caught.exception.code,
            BookTrainingErrorCode.UNSUPPORTED_SCHEMA,
        )
        self.assertEqual(
            str(caught.exception),
            "unsupported book training schema_version",
        )

    def test_wire_dict_subclasses_are_rejected_before_hooks(self):
        class HostileDict(dict):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("wire dict subclass len must never execute")

            def __iter__(self):
                type(self).touched = True
                raise AssertionError("wire dict subclass iteration must never execute")

            def items(self):
                type(self).touched = True
                raise AssertionError("wire dict subclass items must never execute")

        payloads = []

        payloads.append(HostileDict(self.payload))

        nested_origin = copy.deepcopy(self.payload)
        nested_origin["origin"] = HostileDict(nested_origin["origin"])
        payloads.append(nested_origin)

        nested_definition = copy.deepcopy(self.payload)
        nested_definition["definition"] = HostileDict(nested_definition["definition"])
        payloads.append(nested_definition)

        nested_step = copy.deepcopy(self.payload)
        nested_step["definition"]["steps"][0] = HostileDict(
            nested_step["definition"]["steps"][0]
        )
        payloads.append(nested_step)

        nested_metadata = copy.deepcopy(self.payload)
        nested_metadata["definition"]["metadata"] = HostileDict(
            nested_metadata["definition"]["metadata"]
        )
        payloads.append(nested_metadata)

        for payload in payloads:
            with self.subTest(level=type(payload).__name__):
                HostileDict.touched = False
                with self.assertRaises(BookTrainingError) as caught:
                    restore_book_training_material(self.book, payload)
                self.assertEqual(
                    caught.exception.code,
                    BookTrainingErrorCode.INVALID_FIELD,
                )
                self.assertFalse(HostileDict.touched)

    def test_wire_hostile_key_is_rejected_before_rehash_or_equality(self):
        class HostileKey(str):
            armed = False

            def __hash__(self):
                if type(self).armed:
                    raise AssertionError("wire key must not be rehashed before type guard")
                return str.__hash__(self)

            def __eq__(self, other):
                if type(self).armed:
                    raise AssertionError("wire key must not be compared before type guard")
                return str.__eq__(self, other)

        payload = {}
        for key, value in self.payload.items():
            payload[
                HostileKey(key) if key == "schema_version" else key
            ] = copy.deepcopy(value)
        HostileKey.armed = True
        try:
            with self.assertRaises(BookTrainingError) as caught:
                restore_book_training_material(self.book, payload)
        finally:
            HostileKey.armed = False

        self.assertEqual(caught.exception.code, BookTrainingErrorCode.INVALID_FIELD)

    def test_wire_step_count_is_rejected_before_step_materialization(self):
        oversized = copy.deepcopy(self.payload)
        raw_step = copy.deepcopy(oversized["definition"]["steps"][0])
        oversized["definition"]["steps"] = [raw_step] * 2049

        with patch(
            "acs.book_training.ExerciseStep",
            side_effect=AssertionError("oversized step list must fail before ExerciseStep"),
        ) as step_type:
            with self.assertRaises(BookTrainingError) as caught:
                restore_book_training_material(self.book, oversized)

        step_type.assert_not_called()
        self.assertEqual(caught.exception.code, BookTrainingErrorCode.INVALID_FIELD)

    def test_wire_accepted_move_count_is_rejected_before_frozenset_and_step(self):
        oversized = copy.deepcopy(self.payload)
        oversized["definition"]["steps"][0]["accepted_moves"] = ["e4"] * 65

        with patch(
            "acs.book_training.ExerciseStep",
            side_effect=AssertionError("oversized accepted_moves must fail before ExerciseStep"),
        ) as step_type:
            with self.assertRaises(BookTrainingError) as caught:
                restore_book_training_material(self.book, oversized)

        step_type.assert_not_called()
        self.assertEqual(caught.exception.code, BookTrainingErrorCode.INVALID_FIELD)

    def test_wire_move_scalar_bound_precedes_domain_normalization(self):
        oversized = copy.deepcopy(self.payload)
        oversized["definition"]["steps"][0]["accepted_moves"] = ["e4" + (" " * 63)]

        with patch(
            "acs.book_training.ExerciseStep",
            side_effect=AssertionError("raw oversized move must fail before normalization"),
        ) as step_type:
            with self.assertRaises(BookTrainingError) as caught:
                restore_book_training_material(self.book, oversized)

        step_type.assert_not_called()
        self.assertEqual(caught.exception.code, BookTrainingErrorCode.INVALID_FIELD)

    def test_wire_tags_and_metadata_counts_are_bounded_before_definition_build(self):
        oversized_tags = copy.deepcopy(self.payload)
        oversized_tags["definition"]["tags"] = ["tag"] * 257
        with patch(
            "acs.book_training.ExerciseDefinition",
            side_effect=AssertionError("oversized tags must fail before definition build"),
        ) as definition_type:
            with self.assertRaises(BookTrainingError) as caught:
                restore_book_training_material(self.book, oversized_tags)
        definition_type.assert_not_called()
        self.assertEqual(caught.exception.code, BookTrainingErrorCode.INVALID_FIELD)

        oversized_metadata = copy.deepcopy(self.payload)
        oversized_metadata["definition"]["metadata"] = {
            f"k{index}": "v" for index in range(257)
        }
        with patch(
            "acs.book_training.ExerciseDefinition",
            side_effect=AssertionError("oversized metadata must fail before definition build"),
        ) as definition_type:
            with self.assertRaises(BookTrainingError) as caught:
                restore_book_training_material(self.book, oversized_metadata)
        definition_type.assert_not_called()
        self.assertEqual(caught.exception.code, BookTrainingErrorCode.INVALID_FIELD)

    def test_wire_origin_heading_path_count_is_bounded(self):
        oversized = copy.deepcopy(self.payload)
        oversized["origin"]["heading_path"] = ["Heading"] * 257

        with self.assertRaises(BookTrainingError) as caught:
            restore_book_training_material(self.book, oversized)

        self.assertEqual(caught.exception.code, BookTrainingErrorCode.INVALID_FIELD)

    def test_tampered_move_and_origin_digest_fail_closed(self):
        tampered_move = copy.deepcopy(self.payload)
        tampered_move["definition"]["steps"][0]["accepted_moves"] = ["d4"]
        with self.assertRaises(BookTrainingError) as caught:
            restore_book_training_material(self.book, tampered_move)
        self.assertEqual(caught.exception.code, BookTrainingErrorCode.STALE_ORIGIN)

        tampered_origin = copy.deepcopy(self.payload)
        tampered_origin["origin"]["block_digest"] = "0" * 64
        with self.assertRaises(BookTrainingError) as caught:
            restore_book_training_material(self.book, tampered_origin)
        self.assertEqual(caught.exception.code, BookTrainingErrorCode.STALE_ORIGIN)

    def test_mutated_origin_is_revalidated_before_export_materialization(self):
        origin = self.material.origin
        original_heading_path = origin.heading_path
        original_target_key = origin.target_key

        class HostileTuple(tuple):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("hostile origin tuple length must not execute")

            def __iter__(self):
                type(self).touched = True
                raise AssertionError("hostile origin tuple iteration must not execute")

        try:
            object.__setattr__(origin, "heading_path", HostileTuple(("Heading",)))
            with self.assertRaises(BookTrainingError) as caught:
                self.material.as_dict()
            self.assertEqual(caught.exception.code, BookTrainingErrorCode.INVALID_FIELD)
            self.assertFalse(HostileTuple.touched)

            object.__setattr__(origin, "heading_path", original_heading_path)
            object.__setattr__(origin, "target_key", "x" * 4_097)
            with self.assertRaises(BookTrainingError) as caught:
                self.material.as_dict()
            self.assertEqual(caught.exception.code, BookTrainingErrorCode.INVALID_FIELD)
        finally:
            object.__setattr__(origin, "heading_path", original_heading_path)
            object.__setattr__(origin, "target_key", original_target_key)

    def test_mutated_definition_collections_fail_before_export_materialization(self):
        definition = self.material.definition
        original_steps = definition.steps
        original_tags = definition.tags
        original_metadata = definition.metadata
        step = original_steps[0]
        original_hint = step.hint

        try:
            object.__setattr__(definition, "steps", (step,) * 2_049)
            with self.assertRaises(BookTrainingError) as caught:
                self.material.as_dict()
            self.assertEqual(caught.exception.code, BookTrainingErrorCode.INVALID_FIELD)

            object.__setattr__(definition, "steps", original_steps)
            object.__setattr__(definition, "tags", ("tag",) * 257)
            with self.assertRaises(BookTrainingError) as caught:
                self.material.as_dict()
            self.assertEqual(caught.exception.code, BookTrainingErrorCode.INVALID_FIELD)

            object.__setattr__(definition, "tags", original_tags)
            oversized_metadata = {
                f"k{index}": "v" for index in range(257)
            }
            object.__setattr__(definition, "metadata", oversized_metadata)
            with self.assertRaises(BookTrainingError) as caught:
                self.material.as_dict()
            self.assertEqual(caught.exception.code, BookTrainingErrorCode.INVALID_FIELD)

            object.__setattr__(definition, "metadata", original_metadata)
            object.__setattr__(step, "hint", "x" * 4_097)
            with self.assertRaises(BookTrainingError) as caught:
                self.material.as_dict()
            self.assertEqual(caught.exception.code, BookTrainingErrorCode.INVALID_FIELD)
        finally:
            object.__setattr__(step, "hint", original_hint)
            object.__setattr__(definition, "steps", original_steps)
            object.__setattr__(definition, "tags", original_tags)
            object.__setattr__(definition, "metadata", original_metadata)

    def test_mutated_metadata_hostile_key_fails_before_sort(self):
        class HostileKey(str):
            armed = False

            def __lt__(self, other):
                if type(self).armed:
                    raise AssertionError("hostile metadata key must not be sorted")
                return str.__lt__(self, other)

        metadata = dict(self.material.definition.metadata)
        hostile = HostileKey("hostile")
        metadata[hostile] = "value"
        HostileKey.armed = True
        original_metadata = self.material.definition.metadata
        try:
            object.__setattr__(self.material.definition, "metadata", metadata)
            with self.assertRaises(BookTrainingError) as caught:
                self.material.as_dict()
        finally:
            HostileKey.armed = False
            object.__setattr__(
                self.material.definition,
                "metadata",
                original_metadata,
            )

        self.assertEqual(caught.exception.code, BookTrainingErrorCode.INVALID_FIELD)

    def test_export_rejects_mutated_metadata_container_before_hooks(self):
        class HostileDict(dict):
            def __len__(self):
                raise AssertionError("metadata subclass length hook must not execute")

            def items(self):
                raise AssertionError("metadata subclass items hook must not execute")

        original_metadata = self.material.definition.metadata
        try:
            object.__setattr__(
                self.material.definition,
                "metadata",
                HostileDict({"content_kind": "book_exercise"}),
            )
            with self.assertRaises(BookTrainingError) as caught:
                self.material.as_dict()
        finally:
            object.__setattr__(self.material.definition, "metadata", original_metadata)
        self.assertEqual(caught.exception.code, BookTrainingErrorCode.INVALID_FIELD)

    def test_export_rejects_substituted_definition_authority(self):
        class DefinitionSubclass(type(self.material.definition)):
            pass

        substituted = DefinitionSubclass(
            exercise_id=self.material.definition.exercise_id,
            start_fen=self.material.definition.start_fen,
            steps=self.material.definition.steps,
            title=self.material.definition.title,
            tags=self.material.definition.tags,
            source_id=self.material.definition.source_id,
            metadata=dict(self.material.definition.metadata),
        )
        original_definition = self.material.definition
        try:
            object.__setattr__(self.material, "definition", substituted)
            with self.assertRaisesRegex(TypeError, "exact ExerciseDefinition"):
                self.material.as_dict()
        finally:
            object.__setattr__(self.material, "definition", original_definition)

    def test_mutated_book_aux_text_bound_is_normalized_to_contract_error(self):
        exercise = self.book.blocks[0]
        assert isinstance(exercise, Exercise)
        exercise.prompt = "x" * 4097

        with self.assertRaises(BookTrainingError) as caught:
            build_book_training_material(self.book, "block:opening-1")
        self.assertEqual(caught.exception.code, BookTrainingErrorCode.INVALID_FIELD)

        exercise.prompt = "Opening"
        exercise.difficulty = "x" * 4097
        with self.assertRaises(BookTrainingError) as caught:
            build_book_training_material(self.book, "block:opening-1")
        self.assertEqual(caught.exception.code, BookTrainingErrorCode.INVALID_FIELD)

    def test_mutated_definition_metadata_cannot_be_exported_as_false_valid(self):
        # ExerciseDefinition is frozen, but its copied Mapping is intentionally a
        # normal dict.  The D08 wire boundary must still reject post-build scalar
        # corruption rather than serializing it by coercion.
        self.material.definition.metadata["bad"] = 7
        with self.assertRaises(BookTrainingError) as caught:
            self.material.as_dict()
        self.assertEqual(caught.exception.code, BookTrainingErrorCode.INVALID_FIELD)


if __name__ == "__main__":
    unittest.main()
