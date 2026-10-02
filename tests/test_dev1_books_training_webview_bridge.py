from __future__ import annotations

import unittest

from acs.bookdocument import BookDocument, Diagram, Heading, Paragraph
from acs.bookreader import BookReader
from acs.book_webview_bridge import BookWebViewBridge
from acs.book_webview_projection import BookWebViewProjection
from acs.full_product_presenters import BookReaderPresenter, TrainingPresenter
from acs.full_product_ui_shell import UILanguage
from acs.training import ExerciseDefinition, ExerciseSession, ExerciseStep
from acs.training_webview_bridge import TrainingWebViewBridge
from acs.training_webview_projection import TrainingWebViewProjection


FEN = "8/8/8/8/8/8/4P3/4K2k w - - 0 1"


class BooksTrainingWebViewBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.book_calls = []

        def dispatch(action_id, payload):
            self.book_calls.append((action_id, dict(payload)))
            return {"token": "SECRET", "path": r"C:\\private\\x"}

        document = BookDocument(
            title="Book",
            blocks=[
                Heading(text="Chapter", level=1),
                Paragraph(text="Text"),
                Diagram(fen=FEN, caption="Position", alt_text="Board position"),
            ],
        )
        book_presenter = BookReaderPresenter(BookReader(document), language=UILanguage.EN)
        self.book = BookWebViewBridge(
            BookWebViewProjection(book_presenter, dispatch, language=UILanguage.EN)
        )

        definition = ExerciseDefinition(
            exercise_id="ex",
            start_fen=FEN,
            steps=(ExerciseStep(frozenset({"e4"}), hint="Hint"),),
            title="Training",
        )
        training_presenter = TrainingPresenter(ExerciseSession(definition), language=UILanguage.EN)
        self.training = TrainingWebViewBridge(
            TrainingWebViewProjection(training_presenter, language=UILanguage.EN)
        )

    def test_book_unknown_arbitrary_action_and_extra_fields_fail_closed(self) -> None:
        for command, payload in (
            ("board.input", {}),
            ("book.next", {"fen": FEN}),
            ("book.bookmark.save", {"name": "x", "path": r"C:\\private"}),
        ):
            result = self.book.dispatch(command, payload)
            self.assertEqual("error", result.kind)
            self.assertNotIn(command, repr(result))
            self.assertNotIn(FEN, repr(result))
        self.assertEqual([], self.book_calls)

    def test_book_open_position_keeps_backend_return_private(self) -> None:
        self.book.dispatch("book.next_position", {})
        event = self.book.dispatch("book.open_position", {})
        self.assertEqual("delegated", event.kind)
        self.assertEqual("book.open_position", self.book_calls[-1][0])
        self.assertEqual(FEN, self.book_calls[-1][1]["fen"])
        self.assertNotIn("SECRET", repr(event))
        self.assertNotIn("private", repr(event))
        self.assertNotIn(FEN, repr(event))

    def test_book_bookmark_requires_exact_single_name_field(self) -> None:
        saved = self.book.dispatch("book.bookmark.save", {"name": "chapter"})
        self.assertEqual("render", saved.kind)
        bad = self.book.dispatch("book.bookmark.restore", {"name": 123})
        self.assertEqual("error", bad.kind)

    def test_training_rejects_arbitrary_action_scalar_payload_and_extra_fields(self) -> None:
        for command, payload in (
            ("student.move", {}),
            ("training.submit", "e4"),
            ("training.submit", {"answer": "e4", "fen": FEN}),
            ("training.hint", {"answer": "e4"}),
        ):
            result = self.training.dispatch(command, payload)
            self.assertEqual("error", result.kind)
            self.assertNotIn(FEN, repr(result))
            self.assertNotIn("student.move", repr(result))

    def test_training_reset_requires_exact_boolean_true(self) -> None:
        for value in (False, 1, "true", None):
            result = self.training.dispatch("training.reset", {"confirmed": value})
            self.assertEqual("error", result.kind)
        good = self.training.dispatch("training.reset", {"confirmed": True})
        self.assertEqual("render", good.kind)

    def test_training_answer_type_and_bound_fail_closed_without_echo(self) -> None:
        for answer in (123, "x" * 129, "   ", "bad\x00move"):
            result = self.training.dispatch("training.submit", {"answer": answer})
            self.assertEqual("error", result.kind)
            self.assertNotIn("bad", repr(result))
            self.assertNotIn("x" * 20, repr(result))

    def test_explicit_training_solution_reveal_is_the_only_solution_crossing(self) -> None:
        passive = self.training.projection.snapshot()
        self.assertNotIn("e4", repr(passive))
        revealed = self.training.dispatch("training.reveal", {})
        self.assertEqual(("e4",), revealed.payload["solution"])


if __name__ == "__main__":
    unittest.main()
