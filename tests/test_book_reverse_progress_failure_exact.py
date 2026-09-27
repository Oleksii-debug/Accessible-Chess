from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.bookdocument import BookDocument
from acs.chesscore import Board
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.full_product_ui_shell import UILanguage
from acs.version2_application import Version2Application


PGN_ONE = """[Event "Reverse progress one"]
[Result "*"]

1. e4 e5 *
"""

PGN_TWO = """[Event "Reverse progress two"]
[Result "*"]

1. d4 d5 *
"""


class BookReverseProgressFailureExactTests(unittest.TestCase):
    @contextmanager
    def _app(self, root: Path):
        database = AcsDatabase(root / "library.acsdb")
        analysis = None
        try:
            analysis = AnalysisService(lambda: None)
            progress = BookProgressStore(root / "book-progress.json")
            app = Version2Application(
                database,
                progress_store=progress,
                engine_assistance=EngineAssistedWorkflowService(analysis),
                board_dispatch=lambda *_: None,
            )
            book = root / "reverse-progress.md"
            book.write_text(
                "# Reverse progress\n\n"
                "First position.\n\n"
                "```fen\n" + Board.START + "\nFirst position\n```\n\n"
                "Between positions.\n\n"
                "```fen\n" + Board.START + "\nSecond position\n```\n\n"
                "```pgn\n" + PGN_ONE + "```\n\n"
                "Between games.\n\n"
                "```pgn\n" + PGN_TWO + "```\n",
                encoding="utf-8",
            )
            app.open_book(book)
            yield app, progress
        finally:
            if analysis is not None:
                analysis.close()
            database.close()

    def _durable_snapshot(self, app: Version2Application, progress: BookProgressStore):
        restored = progress.restore(
            app.book_key,
            BookDocument.from_dict(app.reader.document.as_dict()),
        )
        return restored.snapshot()

    def _assert_failed_reverse_is_atomic(self, app, progress, command: str) -> None:
        language_result = app.browser_command(
            "books",
            "book.language",
            {"language": UILanguage.EN.value},
        )
        self.assertEqual(language_result["kind"], "render")
        bookmark_result = app.browser_command(
            "books",
            "book.bookmark.save",
            {"name": "atomic-origin"},
        )
        self.assertEqual(bookmark_result["kind"], "render")

        before_reader = app.reader.snapshot()
        before_durable = self._durable_snapshot(app, progress)
        before_language = app.books.projection.language
        before_bookmark_name = app.books.projection.bookmark_name

        with patch.object(
            progress,
            "save",
            side_effect=OSError(f"simulated {command} progress failure"),
        ):
            result = app.browser_command("books", command)

        self.assertEqual(result["kind"], "error")
        self.assertEqual(app.reader.snapshot(), before_reader)
        self.assertEqual(self._durable_snapshot(app, progress), before_durable)
        self.assertEqual(app.books.projection.language, before_language)
        self.assertEqual(app.books.projection.bookmark_name, before_bookmark_name)
        self.assertEqual(before_language, UILanguage.EN)
        self.assertEqual(before_bookmark_name, "atomic-origin")

    def test_previous_position_rolls_back_exact_reader_and_durable_progress(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            with self._app(Path(root_text)) as (app, progress):
                self.assertEqual(
                    app.browser_command("books", "book.next_position")["kind"],
                    "render",
                )
                self.assertEqual(
                    app.browser_command("books", "book.next_position")["kind"],
                    "render",
                )
                self._assert_failed_reverse_is_atomic(
                    app,
                    progress,
                    "book.previous_position",
                )

    def test_previous_game_rolls_back_exact_reader_and_durable_progress(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            with self._app(Path(root_text)) as (app, progress):
                self.assertEqual(
                    app.browser_command("books", "book.next_game")["kind"],
                    "render",
                )
                self.assertEqual(
                    app.browser_command("books", "book.next_game")["kind"],
                    "render",
                )
                self._assert_failed_reverse_is_atomic(
                    app,
                    progress,
                    "book.previous_game",
                )


    def test_shared_action_adapter_keeps_reverse_progress_failure_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as root_text:
            with self._app(Path(root_text)) as (app, progress):
                self.assertEqual(
                    app.browser_command("books", "book.next_position")["kind"],
                    "render",
                )
                self.assertEqual(
                    app.browser_command("books", "book.next_position")["kind"],
                    "render",
                )
                before_reader = app.reader.snapshot()
                before_durable = self._durable_snapshot(app, progress)

                with patch.object(
                    progress,
                    "save",
                    side_effect=OSError("simulated native-route progress failure"),
                ):
                    result = app.adapter.activate_action("book.previous_position")

                self.assertEqual(result.kind, "error")
                self.assertEqual(app.reader.snapshot(), before_reader)
                self.assertEqual(self._durable_snapshot(app, progress), before_durable)



if __name__ == "__main__":
    unittest.main()
