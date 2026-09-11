from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.bookdocument import BookDocument
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.version2_application import Version2Application


PGN = '''[Event "Return failure stress"]
[Result "*"]

1. e4 (1. d4 d5 (1... Nf6) 2. c4) e5 2. Nf3 *
'''


class BookBoardProgressFailureExactTests(unittest.TestCase):
    def _app(self, root: Path):
        database = AcsDatabase(root / "library.acsdb")
        self.addCleanup(database.close)
        analysis = AnalysisService(lambda: None)
        self.addCleanup(analysis.close)
        progress = BookProgressStore(root / "book-progress.json")
        app = Version2Application(
            database,
            progress_store=progress,
            engine_assistance=EngineAssistedWorkflowService(analysis),
            board_dispatch=lambda *_: None,
            board_position_projector=lambda _fen: {"ok": True},
        )
        book = root / "return.md"
        book.write_text(
            "# Return\n\nBefore\n\n```pgn\n" + PGN + "```\n\nAfter\n",
            encoding="utf-8",
        )
        app.open_book(book)
        moved = app.browser_command("books", "book.next_game")
        self.assertEqual(moved["kind"], "render")
        return app, progress

    def test_failed_progress_write_during_return_restarts_at_exact_origin(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            app, progress = self._app(Path(root_text))
            origin = app.reader.location()
            key = app.book_key

            opened = app.browser_command("books", "book.open_position")
            self.assertEqual(opened["kind"], "delegated")
            self.assertTrue(app.book_workflow.active)
            app.router.dispatch("book.board_next_move")
            app.router.dispatch("book.board_enter_variation")
            app.router.dispatch("book.board_next_move")

            with patch.object(
                progress,
                "save",
                side_effect=OSError("simulated return progress failure"),
            ):
                result = app.browser_command("books", "book.return_from_board")

            self.assertEqual(result["kind"], "error")
            self.assertFalse(app.book_workflow.active)
            self.assertEqual(app.reader.location(), origin)

            restarted = progress.restore(
                key,
                BookDocument.from_dict(app.reader.document.as_dict()),
            )
            self.assertEqual(restarted.location().block_id, origin.block_id)
            self.assertEqual(restarted.location().source_anchor, origin.source_anchor)
            self.assertEqual(restarted.location().kind, origin.kind)

    def test_failed_required_progress_write_while_opening_board_does_not_partially_transition(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            app, progress = self._app(Path(root_text))
            before_reader = app.reader.snapshot()
            before_route = app.shell.current_route.route_id

            with patch.object(
                progress,
                "save",
                side_effect=OSError("simulated board-open progress failure"),
            ):
                result = app.browser_command("books", "book.open_position")

            self.assertEqual(result["kind"], "error")
            self.assertEqual(
                app.reader.snapshot(),
                before_reader,
                "failed board-open progress publication changed BookReader return anchors",
            )
            self.assertFalse(
                app.book_workflow.active,
                "failed board-open progress publication left Board workflow active",
            )
            self.assertEqual(
                app.shell.current_route.route_id,
                before_route,
                "failed board-open progress publication changed the application route",
            )


if __name__ == "__main__":
    unittest.main()
