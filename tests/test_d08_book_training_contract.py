import copy
import json
import unittest

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
