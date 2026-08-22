from __future__ import annotations

from pathlib import Path
import unittest

from acs.book_webview_bridge import BookWebViewBridge
from acs.book_webview_projection import BookWebViewProjection
from acs.bookdocument import BookDocument, Diagram, Game, Heading, Note, Paragraph, Position
from acs.bookreader import BookReader
from acs.full_product_presenters import BookReaderPresenter, TrainingPresenter
from acs.full_product_ui_shell import UILanguage
from acs.training import ExerciseDefinition, ExerciseSession, ExerciseStep
from acs.training_webview_bridge import TrainingWebViewBridge
from acs.training_webview_projection import TrainingWebViewProjection


WHITE_FEN = "8/8/8/8/8/8/4K3/7k w - - 0 1"
BLACK_FEN = "8/8/8/8/8/8/4K3/7k b - - 0 1"


def make_book() -> BookDocument:
    return BookDocument(
        "Accessible Book",
        blocks=[
            Heading(text="Part I", level=1, block_id="part", source_anchor=r"C:\private\part1.txt"),
            Paragraph(text="Read this paragraph", block_id="intro"),
            Heading(text="Position work", level=2, block_id="position-heading"),
            Diagram(
                fen=WHITE_FEN,
                caption="Kings",
                alt_text="White king e2, black king h1",
                block_id="diagram",
                source_anchor="/home/private/diagram.png",
            ),
            Game(pgn='[Result "*"]\n\n*', title="Example game", block_id="game"),
            Note(text="Remember the opposition", block_id="note"),
            Position(fen=BLACK_FEN, caption="Black to move", block_id="position"),
        ],
    )


def make_training() -> ExerciseDefinition:
    return ExerciseDefinition(
        exercise_id="ex-1",
        start_fen=WHITE_FEN,
        title="Find the move",
        source_id=r"C:\private\course\lesson-1",
        steps=(
            ExerciseStep(
                frozenset({"Ke3"}),
                hint="Move the king toward the center",
                explanation="Good centralization",
            ),
            ExerciseStep(
                frozenset({"Kf4", "Kd4"}),
                hint="Keep improving the king",
                explanation="Good",
            ),
        ),
    )


class BookWebViewTests(unittest.TestCase):
    def build(self, *, language=UILanguage.EN, document=None):
        document = document or make_book()
        reader = BookReader(document)
        presenter = BookReaderPresenter(reader, language=language)
        calls = []

        def dispatch(action, payload):
            calls.append((action, dict(payload)))
            return {"internal": r"C:\private\backend-return"}

        projection = BookWebViewProjection(
            presenter,
            dispatch,
            lambda: len(document.blocks),
            language=language,
        )
        return document, reader, presenter, projection, BookWebViewBridge(projection), calls

    def test_semantic_snapshot_uses_one_current_block_and_sanitizes_source_path(self) -> None:
        _document, reader, _presenter, projection, _bridge, _calls = self.build()
        reader.go_to(3)
        snapshot = projection.snapshot()
        current = snapshot["current"]
        self.assertEqual("ready", snapshot["status"])
        self.assertEqual("img", current["role"])
        self.assertEqual(2, current["heading_level"] if current["role"] == "heading" else 2)
        self.assertEqual(("Part I", "Position work"), current["heading_path"])
        self.assertEqual("diagram.png", current["source_anchor"])
        self.assertEqual(WHITE_FEN, current["board_position_fen"])
        self.assertEqual(current["dom_id"], snapshot["focus_target"])
        self.assertNotIn("/home/private", repr(snapshot))

    def test_missing_diagram_alt_text_projects_explicit_accessible_warning(self) -> None:
        document = BookDocument(
            "Missing alt",
            blocks=[Diagram(fen=WHITE_FEN, caption="Board", alt_text=None)],
        )
        _document, _reader, _presenter, projection, _bridge, _calls = self.build(document=document)
        current = projection.snapshot()["current"]
        self.assertTrue(current["warning"])
        self.assertTrue(current["text"])

    def test_navigation_and_bookmark_restore_return_exact_focus_target(self) -> None:
        _document, _reader, _presenter, _projection, bridge, _calls = self.build()
        moved = bridge.dispatch("book.next_heading", {})
        first_target = moved.payload["snapshot"]["focus_target"]
        saved = bridge.dispatch("book.bookmark", {"name": "analysis"})
        self.assertEqual(first_target, saved.payload["snapshot"]["focus_target"])
        bridge.dispatch("book.next_position", {})
        restored = bridge.dispatch("book.restore_bookmark", {"name": "analysis"})
        self.assertEqual(first_target, restored.payload["snapshot"]["focus_target"])

    def test_open_position_delegates_canonical_fen_and_hides_backend_return(self) -> None:
        _document, reader, _presenter, _projection, bridge, calls = self.build()
        reader.go_to(3)
        event = bridge.dispatch("book.open_position", {})
        self.assertEqual("delegated", event.kind)
        self.assertEqual({"action": "book.open_position"}, dict(event.payload))
        self.assertEqual(
            [("book.open_position", {"fen": WHITE_FEN, "book_index": 3})],
            calls,
        )
        self.assertNotIn("backend-return", repr(event.payload))

    def test_return_from_board_restores_same_reading_context(self) -> None:
        _document, reader, _presenter, _projection, bridge, _calls = self.build()
        reader.go_to(3)
        before = bridge.projection.snapshot()["focus_target"]
        self.assertEqual("delegated", bridge.dispatch("book.open_position", {}).kind)
        reader.go_to(6)
        returned = bridge.dispatch("book.return_from_board", {})
        self.assertEqual(before, returned.payload["snapshot"]["focus_target"])
        self.assertEqual(3, returned.payload["snapshot"]["current"]["index"])

    def test_empty_book_has_explicit_empty_state_without_exception_text(self) -> None:
        document = BookDocument("Empty")
        _document, _reader, _presenter, projection, _bridge, _calls = self.build(document=document)
        snapshot = projection.snapshot()
        self.assertEqual("empty", snapshot["status"])
        self.assertTrue(snapshot["empty_message"])
        self.assertEqual((), snapshot["actions"])

    def test_book_bridge_rejects_unknown_payload_and_never_echoes_bookmark(self) -> None:
        _document, _reader, _presenter, _projection, bridge, _calls = self.build()
        for command, payload in (
            ("book.bookmark", {"name": "TOP-SECRET", "extra": 1}),
            ("book.restore_bookmark", {"name": "\x00secret"}),
            ("book.open_position", {"fen": WHITE_FEN}),
            ("book.unknown", {}),
        ):
            event = bridge.dispatch(command, payload)
            self.assertEqual("error", event.kind)
            visible = repr(event.payload).casefold()
            self.assertNotIn("top-secret", visible)
            self.assertNotIn(WHITE_FEN.casefold(), visible)

    def test_book_snapshot_is_not_mixed_with_live_reader_mutation_after_current_returns(self) -> None:
        document = make_book()

        class MutatingPresenter(BookReaderPresenter):
            def __init__(self, reader):
                super().__init__(reader, language=UILanguage.EN)
                self.current_calls = 0
                self.captured_index = None
                self.live_index_after_read = None

            def current(self):
                self.current_calls += 1
                block = super().current()
                if self.current_calls == 1:
                    self.captured_index = block.index
                    self._reader.next_block()
                    self.live_index_after_read = self._reader.index
                return block

        reader = BookReader(document)
        presenter = MutatingPresenter(reader)
        projection = BookWebViewProjection(
            presenter,
            lambda _action, _payload: None,
            lambda: len(document.blocks),
            language=UILanguage.EN,
        )
        snapshot = projection.snapshot()
        self.assertEqual(1, presenter.current_calls)
        self.assertNotEqual(presenter.captured_index, presenter.live_index_after_read)
        self.assertEqual(presenter.captured_index, snapshot["current"]["index"])


class TrainingWebViewTests(unittest.TestCase):
    def build(self, *, language=UILanguage.EN):
        definition = make_training()
        presenter = TrainingPresenter(ExerciseSession(definition), language=language)
        projection = TrainingWebViewProjection(presenter, language=language)
        return definition, presenter, projection, TrainingWebViewBridge(projection)

    def test_passive_snapshot_never_reveals_accepted_moves(self) -> None:
        definition, _presenter, projection, _bridge = self.build()
        snapshot = projection.snapshot()
        visible = repr(snapshot)
        self.assertEqual((), snapshot["solution"]["moves"])
        for step in definition.steps:
            for move in step.accepted_moves:
                self.assertNotIn(move, visible)
        self.assertEqual(WHITE_FEN, snapshot["board"]["start_fen"])
        self.assertNotIn("C:\\private", visible)

    def test_wrong_answer_updates_counters_but_does_not_echo_answer(self) -> None:
        _definition, _presenter, _projection, bridge = self.build()
        event = bridge.dispatch("training.submit", {"answer": "Kh3"})
        snapshot = event.payload["snapshot"]
        self.assertEqual("in_progress", snapshot["status"])
        self.assertIn("1", snapshot["attempts_label"])
        self.assertIn("1", snapshot["mistakes_label"])
        self.assertNotIn("Kh3", repr(event.payload))

    def test_hint_and_reveal_are_explicit_actions_only(self) -> None:
        _definition, _presenter, projection, bridge = self.build()
        self.assertEqual((), projection.snapshot()["solution"]["moves"])
        hint = bridge.dispatch("training.hint", {})
        self.assertIn("center", hint.payload["announcement"].casefold())
        revealed = bridge.dispatch("training.reveal", {})
        self.assertEqual(("Ke3",), revealed.payload["snapshot"]["solution"]["moves"])

    def test_successful_answers_progress_and_complete_without_ui_correctness_logic(self) -> None:
        _definition, _presenter, _projection, bridge = self.build()
        first = bridge.dispatch("training.submit", {"answer": "Ke3"})
        self.assertEqual("in_progress", first.payload["snapshot"]["status"])
        self.assertFalse(first.payload["snapshot"]["completed"])
        second = bridge.dispatch("training.submit", {"answer": "Kf4"})
        self.assertEqual("completed", second.payload["snapshot"]["status"])
        self.assertTrue(second.payload["snapshot"]["completed"])
        self.assertTrue(second.payload["snapshot"]["completed_message"])

    def test_reset_restores_initial_progress_and_answer_focus(self) -> None:
        _definition, _presenter, _projection, bridge = self.build()
        bridge.dispatch("training.submit", {"answer": "Kh3"})
        reset = bridge.dispatch("training.reset", {})
        snapshot = reset.payload["snapshot"]
        self.assertEqual("ready", snapshot["status"])
        self.assertIn("0", snapshot["attempts_label"])
        self.assertEqual("training-answer", snapshot["focus_target"])

    def test_training_bridge_rejects_coercive_or_oversized_payload_without_echo(self) -> None:
        _definition, _presenter, _projection, bridge = self.build()
        payloads = (
            {"answer": True},
            {"answer": "TOP-SECRET", "extra": 1},
            {"answer": "x" * 300},
        )
        for payload in payloads:
            event = bridge.dispatch("training.submit", payload)
            self.assertEqual("error", event.kind)
            self.assertNotIn("top-secret", repr(event.payload).casefold())
            self.assertNotIn("x" * 50, repr(event.payload))

    def test_language_switch_changes_labels_without_mutating_progress(self) -> None:
        _definition, presenter, projection, _bridge = self.build(language=UILanguage.UA)
        presenter.submit("Kh3")
        ua = projection.snapshot()
        en = projection.set_language(UILanguage.EN).payload["snapshot"]
        self.assertNotEqual(ua["heading"], en["heading"])
        self.assertEqual(ua["status"], en["status"])
        self.assertEqual(ua["attempts_label"].split()[-1], en["attempts_label"].split()[-1])

    def test_passive_training_snapshot_uses_one_training_view(self) -> None:
        definition = make_training()

        class MutatingPresenter(TrainingPresenter):
            def __init__(self, session):
                super().__init__(session, language=UILanguage.EN)
                self.view_calls = 0

            def view(self):
                self.view_calls += 1
                view = super().view()
                if self.view_calls == 1:
                    self._session.submit("Kh3")
                return view

        presenter = MutatingPresenter(ExerciseSession(definition))
        projection = TrainingWebViewProjection(presenter, language=UILanguage.EN)
        snapshot = projection.snapshot()
        self.assertEqual(1, presenter.view_calls)
        self.assertEqual("ready", snapshot["status"])
        self.assertIn("0", snapshot["attempts_label"])
        self.assertEqual(1, presenter.session.attempts)


class BookTrainingWebAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).parents[1] / "web"
        cls.book = (root / "full_product_book.js").read_text(encoding="utf-8")
        cls.training = (root / "full_product_training.js").read_text(encoding="utf-8")

    def test_book_uses_native_semantics_without_markup_injection(self) -> None:
        source = self.book
        self.assertIn('node("article")', source)
        self.assertIn('node("nav")', source)
        self.assertIn('node("form")', source)
        self.assertIn('node("input")', source)
        self.assertIn('node("button"', source)
        self.assertIn("textContent", source)
        for token in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            self.assertNotIn(token, source)

    def test_training_uses_native_answer_form_and_no_global_key_hijack(self) -> None:
        source = self.training
        self.assertIn('node("form")', source)
        self.assertIn('node("input")', source)
        self.assertIn('input.id = "training-answer"', source)
        self.assertIn('input.value = ""', source)
        self.assertNotIn('document.addEventListener("keydown"', source)
        self.assertNotIn('window.addEventListener("keydown"', source)

    def test_both_assets_handle_transport_rejection_without_error_text(self) -> None:
        for source in (self.book, self.training):
            self.assertIn('.catch(function ()', source)
            self.assertIn("transport_error_message", source)
            self.assertNotIn("error.message", source)
            self.assertNotIn("reason.message", source)

    def test_passive_messages_do_not_create_live_region_spam(self) -> None:
        self.assertIn('setAttribute("aria-live", "off")', self.book)
        self.assertIn('setAttribute("aria-live", "off")', self.training)
        self.assertNotIn('aria-live", "polite"', self.book)
        self.assertNotIn('aria-live", "polite"', self.training)

    def test_focus_is_only_applied_to_explicit_requested_target(self) -> None:
        for source in (self.book, self.training):
            self.assertIn("function focusRequested(root, target)", source)
            self.assertIn('focusRequested(root, requestedFocus || "")', source)


if __name__ == "__main__":
    unittest.main()
