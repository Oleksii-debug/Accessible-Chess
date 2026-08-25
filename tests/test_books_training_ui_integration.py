from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from acs.analysis_service import AnalysisService
from acs.book_training import (
    build_current_book_training_material,
    return_reader_to_book_training_origin,
)
from acs.bookdocument import BookDocument, Exercise, Heading, Paragraph
from acs.bookreader import BookReader
from acs.book_webview_bridge import BookWebViewBridge
from acs.book_webview_projection import BookWebViewProjection
from acs.engine_assisted_workflows import (
    EngineAssistedWorkflowService,
    EngineVisibility,
)
from acs.engine_ports import RawAnalysisLine
from acs.full_product_presenters import BookReaderPresenter, TrainingPresenter
from acs.full_product_ui_shell import AccessibleShellState, UILanguage
from acs.training import ExerciseSession
from acs.training_progress_store import TrainingProgressConflictError, TrainingProgressStore
from acs.training_webview_bridge import TrainingWebViewBridge
from acs.training_webview_projection import TrainingWebViewProjection


START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class FakeAnalysisEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, int]] = []
        self.closed = False

    def analyze(self, fen: str, multipv: int = 5, depth: int = 16):
        self.calls.append((fen, multipv, depth))
        return [
            RawAnalysisLine(
                depth=depth,
                score_kind="cp",
                score_value=24,
                pv=("e2e4", "e7e5"),
            )
        ]

    def close(self) -> None:
        self.closed = True


def make_book() -> tuple[BookDocument, Exercise]:
    exercise = Exercise(
        fen=START_FEN,
        prompt="Play the opening line.",
        solution_pgn="1. e4 e5 2. Nf3 *",
        block_id="opening-line",
        source_anchor="chapter-1:exercise-1",
    )
    document = BookDocument(
        title="Accessible training book",
        language="en",
        source_name=r"C:\\Users\\Reader\\private-book.docx",
        blocks=[
            Heading(text="Chapter one", level=1, block_id="chapter-one"),
            Paragraph(text="Read before solving.", source_anchor="chapter-1:p1"),
            exercise,
            Paragraph(text="Continue reading here.", source_anchor="chapter-1:p2"),
        ],
    )
    return document, exercise


class BooksTrainingUIIntegrationTests(unittest.TestCase):
    def test_book_position_engine_round_trip_restores_exact_block_and_focus(self) -> None:
        document, exercise = make_book()
        reader = BookReader(document)
        reader.go_to(2)
        presenter = BookReaderPresenter(reader, language=UILanguage.EN)
        shell = AccessibleShellState(language=UILanguage.EN, initial_route="books")
        engine = FakeAnalysisEngine()
        analysis = AnalysisService(lambda: engine)
        assisted = EngineAssistedWorkflowService(analysis)
        projected_analysis = []

        def dispatch(action_id, payload):
            self.assertEqual("book.open_position", action_id)
            self.assertEqual({"fen": START_FEN, "book_index": 2}, dict(payload))
            self.assertEqual(
                "move-input",
                shell.open_route("board", current_focus_id="book-block-2"),
            )
            result = assisted.analyze_book_block(
                exercise,
                visibility=EngineVisibility.VISIBLE_TO_STUDENT,
                multipv=1,
                depth=10,
            )
            projected_analysis.append(result)
            return {"provider_path": r"C:\\private\\stockfish.exe"}

        bridge = BookWebViewBridge(
            BookWebViewProjection(presenter, dispatch, language=UILanguage.EN)
        )
        before = document.as_dict()
        try:
            delegated = bridge.dispatch("book.open_position", {})
        finally:
            analysis.close()

        self.assertEqual("delegated", delegated.kind)
        self.assertNotIn(START_FEN, repr(delegated))
        self.assertNotIn("stockfish", repr(delegated).lower())
        self.assertEqual([(START_FEN, 1, 10)], engine.calls)
        self.assertEqual(1, len(projected_analysis[0].student_lines))
        self.assertEqual(before, document.as_dict())

        reader.next_block()
        returned = bridge.dispatch("book.return_from_board", {})
        self.assertEqual(2, returned.payload["snapshot"]["block"]["index"])
        self.assertEqual("book-block-2", returned.payload["focus_target"])
        self.assertEqual(
            "book-block-2",
            shell.open_route("books", current_focus_id="move-input"),
        )

    def test_book_exercise_training_progress_retry_resume_and_exact_return(self) -> None:
        document, _exercise = make_book()
        reader = BookReader(document)
        reader.go_to(2)
        material = build_current_book_training_material(reader)
        shell = AccessibleShellState(language=UILanguage.EN, initial_route="books")
        self.assertEqual(
            "training-prompt",
            shell.open_route("training", current_focus_id="book-block-2"),
        )

        session = ExerciseSession(material.definition)
        bridge = TrainingWebViewBridge(
            TrainingWebViewProjection(
                TrainingPresenter(session, language=UILanguage.EN),
                language=UILanguage.EN,
            )
        )
        passive = bridge.dispatch("training.retry", {}).payload["snapshot"]
        passive_text = repr(passive)
        self.assertNotIn(START_FEN, passive_text)
        self.assertNotIn("private-book", passive_text)
        self.assertNotIn(material.definition.source_id, passive_text)

        before = session.snapshot()
        hint = bridge.dispatch("training.hint", {})
        reveal = bridge.dispatch("training.reveal", {})
        self.assertEqual(before["step_index"], session.step_index)
        self.assertTrue(hint.payload["announcement"])
        self.assertEqual(("e4",), reveal.payload["solution"])

        wrong = bridge.dispatch("training.submit", {"answer": "d4"})
        self.assertFalse(wrong.payload["clear_answer"])
        retry_before = session.snapshot()
        bridge.dispatch("training.retry", {})
        self.assertEqual(retry_before, session.snapshot())
        accepted = bridge.dispatch("training.submit", {"answer": "e4"})
        self.assertTrue(accepted.payload["clear_answer"])
        self.assertEqual(("e4",), session.accepted_path)

        with tempfile.TemporaryDirectory() as directory:
            progress_path = Path(directory) / "progress.json"
            store = TrainingProgressStore(progress_path)
            first_revision = store.save(session, expected_revision=None)
            loaded = store.load(material.definition)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(session.snapshot(), loaded.session.snapshot())
            with self.assertRaises(TrainingProgressConflictError):
                store.save(session, expected_revision=None)

            resumed_bridge = TrainingWebViewBridge(
                TrainingWebViewProjection(
                    TrainingPresenter(loaded.session, language=UILanguage.EN),
                    language=UILanguage.EN,
                )
            )
            resumed_bridge.dispatch("training.submit", {"answer": "e5"})
            completed = resumed_bridge.dispatch("training.submit", {"answer": "Nf3"})
            self.assertTrue(completed.payload["snapshot"]["progress"]["completed"])
            second_revision = store.save(
                loaded.session,
                expected_revision=loaded.revision,
            )
            self.assertNotEqual(first_revision, second_revision)

        reader.next_block()
        location = return_reader_to_book_training_origin(reader, material.origin)
        self.assertEqual(2, location.index)
        self.assertEqual(
            "book-block-2",
            shell.open_route("books", current_focus_id="training-answer"),
        )


if __name__ == "__main__":
    unittest.main()
