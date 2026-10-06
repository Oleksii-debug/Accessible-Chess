from __future__ import annotations

import unittest
from unittest.mock import patch

from acs.bookdocument import BookDocument, Diagram, Game, Heading, Paragraph
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
                Game(
                    pgn='[Result "*"]\n\n1. e4 *',
                    title="Private game",
                    block_id="game-1",
                ),
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

    def test_book_open_game_has_no_browser_chess_payload_and_requires_no_fields(self) -> None:
        moved = self.book.dispatch("book.next_game", {})
        self.assertEqual("render", moved.kind)
        event = self.book.dispatch("book.open_game", {})
        self.assertEqual("delegated", event.kind)
        self.assertEqual(("book.open_game", {}), self.book_calls[-1])
        self.assertNotIn("1. e4", repr(event))
        self.assertNotIn("SECRET", repr(event))
        self.assertNotIn("private", repr(event).lower())

        rejected = self.book.dispatch("book.open_game", {"pgn": "1. e4 *"})
        self.assertEqual("error", rejected.kind)
        self.assertEqual([("book.open_game", {})], self.book_calls)

    def test_book_bridge_preflights_command_payload_keys_and_language(self) -> None:
        class HostileText(str):
            stripped = 0

            def strip(self, *_args, **_kwargs):
                type(self).stripped += 1
                raise AssertionError("hostile text must not reach strip")

        before_language = self.book.projection.language

        result = self.book.dispatch(HostileText("book.next"), {})
        self.assertEqual("error", result.kind)
        self.assertEqual(0, HostileText.stripped)

        result = self.book.dispatch(
            "book.next",
            {HostileText("name"): "chapter"},
        )
        self.assertEqual("error", result.kind)
        self.assertEqual(0, HostileText.stripped)

        result = self.book.dispatch(
            "book.language",
            {"language": HostileText("en")},
        )
        self.assertEqual("error", result.kind)
        self.assertEqual(0, HostileText.stripped)
        self.assertIs(before_language, self.book.projection.language)

        result = self.book.dispatch("x" * 65, {})
        self.assertEqual("error", result.kind)
        result = self.book.dispatch(
            "book.language",
            {"language": "e" * 9},
        )
        self.assertEqual("error", result.kind)
        self.assertIs(before_language, self.book.projection.language)

    def test_book_and_training_payloads_reject_dict_subclasses_before_hooks(self) -> None:
        class HostileDict(dict):
            touched = False

            def __len__(self):
                type(self).touched = True
                raise AssertionError("payload subclass len must never execute")

            def items(self):
                type(self).touched = True
                raise AssertionError("payload subclass items must never execute")

        book_result = self.book.dispatch("book.next", HostileDict())
        self.assertEqual("error", book_result.kind)
        self.assertFalse(HostileDict.touched)

        training_result = self.training.dispatch("training.hint", HostileDict())
        self.assertEqual("error", training_result.kind)
        self.assertFalse(HostileDict.touched)

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

    def test_training_bridge_preflights_command_payload_keys_and_language(self) -> None:
        class HostileText(str):
            stripped = 0

            def strip(self, *_args, **_kwargs):
                type(self).stripped += 1
                raise AssertionError("hostile text must not reach strip")

        before_language = self.training.projection.language

        result = self.training.dispatch(HostileText("training.hint"), {})
        self.assertEqual("error", result.kind)
        self.assertEqual(0, HostileText.stripped)

        result = self.training.dispatch(
            "training.hint",
            {HostileText("answer"): "e4"},
        )
        self.assertEqual("error", result.kind)
        self.assertEqual(0, HostileText.stripped)

        result = self.training.dispatch(
            "training.language",
            {"language": HostileText("en")},
        )
        self.assertEqual("error", result.kind)
        self.assertEqual(0, HostileText.stripped)
        self.assertIs(before_language, self.training.projection.language)

        result = self.training.dispatch("x" * 65, {})
        self.assertEqual("error", result.kind)
        result = self.training.dispatch(
            "training.language",
            {"language": "e" * 9},
        )
        self.assertEqual("error", result.kind)
        self.assertIs(before_language, self.training.projection.language)

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

    def test_book_bridge_contains_projection_abort_as_accessible_error(self) -> None:
        class AbortSignal(BaseException):
            pass

        with patch.object(
            self.book.projection,
            "next",
            side_effect=AbortSignal("private book abort"),
        ):
            result = self.book.dispatch("book.next", {})

        self.assertEqual("error", result.kind)
        self.assertNotIn("private book abort", repr(result))

    def test_book_bridge_navigation_abort_reports_error_without_hidden_cursor_move(self) -> None:
        class AbortSignal(BaseException):
            pass

        presenter = self.book.projection._presenter
        reader = presenter._reader
        before_index = reader.index
        original_digest = reader._document_revision_digest
        calls = 0

        def abort_second_revision_read() -> str:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise AbortSignal("private final revision abort")
            return original_digest()

        with patch.object(
            reader,
            "_document_revision_digest",
            side_effect=abort_second_revision_read,
        ):
            result = self.book.dispatch("book.next", {})

        self.assertEqual("error", result.kind)
        self.assertEqual(before_index, reader.index)
        self.assertEqual(calls, 2)
        self.assertNotIn("private final revision abort", repr(result))

    def test_training_bridge_contains_projection_abort_as_accessible_error(self) -> None:
        class AbortSignal(BaseException):
            pass

        with patch.object(
            self.training.projection,
            "hint",
            side_effect=AbortSignal("private training abort"),
        ):
            result = self.training.dispatch("training.hint", {})

        self.assertEqual("error", result.kind)
        self.assertNotIn("private training abort", repr(result))

    def test_training_continue_callback_abort_is_bounded_to_accessible_error(self) -> None:
        class AbortSignal(BaseException):
            pass

        def abort_continue():
            raise AbortSignal("private continuation abort")

        bridge = TrainingWebViewBridge(
            self.training.projection,
            continue_callback=abort_continue,
        )
        result = bridge.dispatch("training.continue", {})
        self.assertEqual("error", result.kind)
        self.assertNotIn("private continuation abort", repr(result))


if __name__ == "__main__":
    unittest.main()
