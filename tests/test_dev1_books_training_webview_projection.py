from __future__ import annotations

import unittest

from acs.bookdocument import BookDocument, Diagram, Heading, Paragraph
from acs.bookreader import BookReader
from acs.book_webview_projection import BookWebViewProjection
from acs.full_product_presenters import BookReaderPresenter, TrainingPresenter
from acs.full_product_ui_shell import UILanguage
from acs.training import ExerciseDefinition, ExerciseSession, ExerciseStep
from acs.training_webview_projection import TrainingWebViewProjection


FEN = "8/8/8/8/8/8/4P3/4K2k w - - 0 1"


class BookProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = BookDocument(
            title="Accessible book",
            blocks=[
                Heading(text="Chapter 1", level=1, block_id="h1"),
                Paragraph(text="Read this paragraph.", source_anchor="chapter-1:p1"),
                Diagram(
                    fen=FEN,
                    caption="Critical position",
                    alt_text=None,
                    source_anchor=r"C:\\Users\\Oleksii\\private\\book-source.docx",
                ),
                Paragraph(text="After the board.", source_anchor="chapter-1:p2"),
            ],
        )
        self.calls = []

        def dispatch(action_id, payload):
            self.calls.append((action_id, dict(payload)))
            return {"fen": "SECRET", "path": r"C:\\private\\internal"}

        self.presenter = BookReaderPresenter(BookReader(self.document), language=UILanguage.EN)
        self.projection = BookWebViewProjection(self.presenter, dispatch, language=UILanguage.EN)

    def test_passive_snapshot_is_semantic_and_never_contains_raw_fen(self) -> None:
        first = self.projection.snapshot()
        self.assertEqual("heading", first["block"]["role"])
        self.assertEqual(1, first["block"]["heading_level"])
        self.assertFalse(first["block"]["has_position"])
        self.assertNotIn(FEN, repr(first))
        self.assertNotIn("position_fen", repr(first))

        diagram_event = self.projection.next_position()
        diagram = diagram_event.payload["snapshot"]
        self.assertEqual("img", diagram["block"]["role"])
        self.assertTrue(diagram["block"]["has_position"])
        self.assertIn("No separate diagram description", diagram["block"]["warning"])
        self.assertEqual("book-source.docx", diagram["block"]["source_anchor"])
        self.assertNotIn(FEN, repr(diagram))
        self.assertNotIn("Users", repr(diagram))

    def test_open_position_keeps_fen_inside_python_dispatch_boundary(self) -> None:
        self.projection.next_position()
        event = self.projection.open_position()
        self.assertEqual("delegated", event.kind)
        self.assertEqual("book.open_position", self.calls[-1][0])
        self.assertEqual(FEN, self.calls[-1][1]["fen"])
        self.assertNotIn(FEN, repr(event))
        self.assertNotIn("SECRET", repr(event))
        self.assertNotIn("private", repr(event))

    def test_bookmark_and_board_return_restore_exact_reading_location(self) -> None:
        saved = self.projection.save_bookmark("chapter start")
        self.assertEqual(0, saved.payload["snapshot"]["block"]["index"])
        self.projection.next_position()
        restored = self.projection.restore_bookmark("chapter start")
        self.assertEqual(0, restored.payload["snapshot"]["block"]["index"])

        self.projection.next_position()
        self.projection.open_position()
        self.projection.next()
        returned = self.projection.return_from_board()
        self.assertEqual(2, returned.payload["snapshot"]["block"]["index"])

    def test_bookmark_name_is_bounded_before_reader_mutation(self) -> None:
        with self.assertRaises(ValueError):
            self.projection.save_bookmark("x" * 81)
        with self.assertRaises(ValueError):
            self.projection.save_bookmark("   ")
        self.assertEqual(0, self.presenter.current().index)

    def test_language_switch_changes_labels_without_changing_location(self) -> None:
        before = self.projection.snapshot()
        after = self.projection.set_language(UILanguage.UA).payload["snapshot"]
        self.assertEqual(before["block"]["index"], after["block"]["index"])
        self.assertEqual(before["block"]["dom_id"], after["block"]["dom_id"])
        self.assertNotEqual(before["heading"], after["heading"])


class TrainingProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.definition = ExerciseDefinition(
            exercise_id="ex-1",
            start_fen=FEN,
            steps=(
                ExerciseStep(
                    frozenset({"e4"}),
                    hint="Move the pawn two squares.",
                    explanation="Good.",
                ),
                ExerciseStep(frozenset({"Kh2"}), hint="Move the king."),
            ),
            title="Pawn practice",
            source_id="private-book-id",
            metadata={"path": r"C:\\private\\training.json"},
        )
        self.presenter = TrainingPresenter(ExerciseSession(self.definition), language=UILanguage.EN)
        self.projection = TrainingWebViewProjection(self.presenter, language=UILanguage.EN)

    def test_passive_snapshot_excludes_solution_fen_source_and_metadata(self) -> None:
        snapshot = self.projection.snapshot()
        text = repr(snapshot)
        self.assertEqual("ready", snapshot["status"])
        self.assertEqual(1, snapshot["progress"]["step"])
        self.assertEqual(2, snapshot["progress"]["total"])
        self.assertNotIn(FEN, text)
        self.assertNotIn("private-book-id", text)
        self.assertNotIn("training.json", text)
        self.assertNotIn("accepted_moves", text)
        self.assertNotIn("e4", text)

    def test_hint_and_reveal_do_not_advance_canonical_progress(self) -> None:
        before = self.presenter.snapshot()
        hinted = self.projection.hint()
        self.assertIn("Move the pawn two squares", hinted.payload["announcement"])
        self.assertEqual(before["step_index"], self.presenter.snapshot()["step_index"])

        revealed = self.projection.reveal()
        self.assertEqual(("e4",), revealed.payload["solution"])
        self.assertEqual(before["step_index"], self.presenter.snapshot()["step_index"])
        self.assertNotIn(FEN, repr(revealed))

    def test_wrong_answer_is_not_clear_signal_and_correct_answer_is(self) -> None:
        wrong = self.projection.submit("e3")
        self.assertFalse(wrong.payload["clear_answer"])
        self.assertEqual(1, wrong.payload["snapshot"]["progress"]["attempts"])
        self.assertEqual(1, wrong.payload["snapshot"]["progress"]["mistakes"])
        self.assertIn("Try again", wrong.payload["announcement"])

        correct = self.projection.submit("e4")
        self.assertTrue(correct.payload["clear_answer"])
        self.assertEqual(2, correct.payload["snapshot"]["progress"]["step"])
        self.assertEqual(2, correct.payload["snapshot"]["progress"]["attempts"])
        self.assertEqual(1, correct.payload["snapshot"]["progress"]["mistakes"])

        completed = self.projection.submit("Kh2")
        self.assertTrue(completed.payload["clear_answer"])
        self.assertTrue(completed.payload["snapshot"]["progress"]["completed"])
        self.assertTrue(completed.payload["snapshot"]["answer"]["disabled"])

    def test_answer_bound_and_type_fail_before_session_mutation(self) -> None:
        before = self.presenter.snapshot()
        with self.assertRaises(TypeError):
            self.projection.submit(123)
        with self.assertRaises(ValueError):
            self.projection.submit("x" * 129)
        with self.assertRaises(ValueError):
            self.projection.submit("  ")
        self.assertEqual(before, self.presenter.snapshot())

    def test_reset_requires_exact_true_and_resets_canonical_session(self) -> None:
        self.projection.submit("e3")
        before = self.presenter.snapshot()
        with self.assertRaises(ValueError):
            self.projection.reset(confirmed=False)
        with self.assertRaises(ValueError):
            self.projection.reset(confirmed=1)
        self.assertEqual(before, self.presenter.snapshot())
        reset = self.projection.reset(confirmed=True)
        self.assertEqual(0, reset.payload["snapshot"]["progress"]["attempts"])
        self.assertEqual("ready", reset.payload["snapshot"]["status"])
        self.assertTrue(reset.payload["clear_answer"])

    def test_language_switch_preserves_progress_identity(self) -> None:
        self.projection.submit("e4")
        en = self.projection.snapshot()
        ua = self.projection.set_language(UILanguage.UA).payload["snapshot"]
        for key in ("step", "total", "attempts", "mistakes", "hints_used", "completed"):
            self.assertEqual(en["progress"][key], ua["progress"][key])
        self.assertEqual(en["title"], ua["title"])
        self.assertNotEqual(en["progress"]["step_label"], ua["progress"]["step_label"])
        self.assertNotEqual(en["heading"], ua["heading"])


if __name__ == "__main__":
    unittest.main()
