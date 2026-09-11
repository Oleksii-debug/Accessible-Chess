from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.version2_application import Version2Application


class Version2BookTransactionCurrentRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = AcsDatabase(self.root / "library.acsdb")
        self.addCleanup(self.database.close)
        self.analysis = AnalysisService(lambda: None)
        self.addCleanup(self.analysis.close)
        self.progress_store = BookProgressStore(self.root / "book-progress.json")
        self.app = Version2Application(
            self.database,
            progress_store=self.progress_store,
            engine_assistance=EngineAssistedWorkflowService(self.analysis),
            board_dispatch=lambda *_args: None,
        )

    def _book(self, name: str, title: str) -> Path:
        source = self.root / name
        source.write_text(
            f"# {title}\n\nFirst paragraph.\n\nSecond paragraph.\n",
            encoding="utf-8",
        )
        return source

    def test_first_open_initial_progress_failure_publishes_nothing(self):
        source = self._book("first-failure.md", "First failure")
        before_route = self.app.shell.current_route.route_id

        class FailingProgressStore:
            def has(self, _book_key):
                return False

            def restore(self, _book_key, _document):
                raise AssertionError("restore must not run without saved progress")

            def save(self, _book_key, _reader):
                raise OSError("simulated initial progress write failure")

        self.app.progress_store = FailingProgressStore()

        with self.assertRaisesRegex(OSError, "initial progress write failure"):
            self.app.open_book(source)

        self.assertIsNone(self.app.reader)
        self.assertIsNone(self.app.book_key)
        self.assertIsNone(self.app.book_workflow)
        self.assertIsNone(self.app.book_delegate)
        self.assertIsNone(self.app.books)
        self.assertEqual(self.app.shell.current_route.route_id, before_route)

    def test_replacement_failure_preserves_reader_workflow_bridge_and_route(self):
        first = self._book("first.md", "First")
        second = self._book("second.md", "Second")
        self.app.open_book(first)

        real_store = self.app.progress_store
        old_reader = self.app.reader
        old_key = self.app.book_key
        old_workflow = self.app.book_workflow
        old_delegate = self.app.book_delegate
        old_books = self.app.books
        old_route = self.app.shell.current_route.route_id
        old_snapshot = self.app.reader.snapshot()

        class FailReplacementProgressStore:
            def has(self, book_key):
                return real_store.has(book_key)

            def restore(self, book_key, document):
                return real_store.restore(book_key, document)

            def save(self, book_key, reader):
                if book_key != old_key:
                    raise OSError("simulated replacement progress write failure")
                return real_store.save(book_key, reader)

        self.app.progress_store = FailReplacementProgressStore()

        with self.assertRaisesRegex(OSError, "replacement progress write failure"):
            self.app.open_book(second)

        self.assertIs(self.app.reader, old_reader)
        self.assertEqual(self.app.reader.snapshot(), old_snapshot)
        self.assertEqual(self.app.book_key, old_key)
        self.assertIs(self.app.book_workflow, old_workflow)
        self.assertIs(self.app.book_delegate, old_delegate)
        self.assertIs(self.app.books, old_books)
        self.assertEqual(self.app.shell.current_route.route_id, old_route)

    def test_navigation_save_failure_restores_exact_reader_state(self):
        source = self._book("navigation.md", "Navigation")
        self.app.open_book(source)
        before = self.app.reader.snapshot()
        before_route = self.app.shell.current_route.route_id
        before_key = self.app.book_key

        with patch.object(
            self.progress_store,
            "save",
            side_effect=OSError("simulated navigation progress failure"),
        ):
            result = self.app.browser_command("books", "book.next")

        self.assertEqual(result["kind"], "error")
        self.assertEqual(self.app.reader.snapshot(), before)
        self.assertEqual(self.app.book_key, before_key)
        self.assertEqual(self.app.shell.current_route.route_id, before_route)

    def test_bookmark_save_failure_restores_reader_and_transient_name(self):
        source = self._book("bookmark.md", "Bookmark")
        self.app.open_book(source)
        initial = self.app.browser_command(
            "books",
            "book.bookmark.save",
            {"name": "prior"},
        )
        self.assertEqual(initial["kind"], "render")
        before = self.app.reader.snapshot()
        self.assertEqual(self.app.books.projection.bookmark_name, "prior")

        with patch.object(
            self.progress_store,
            "save",
            side_effect=OSError("simulated bookmark progress failure"),
        ):
            result = self.app.browser_command(
                "books",
                "book.bookmark.save",
                {"name": "not-committed"},
            )

        self.assertEqual(result["kind"], "error")
        self.assertEqual(self.app.reader.snapshot(), before)
        self.assertEqual(self.app.books.projection.bookmark_name, "prior")

    def test_presentation_only_language_is_independent_of_progress_io(self):
        source = self._book("language.md", "Language")
        self.app.open_book(source)
        before = self.app.reader.snapshot()

        with patch.object(
            self.progress_store,
            "save",
            side_effect=OSError("progress store intentionally unavailable"),
        ):
            result = self.app.browser_command(
                "books",
                "book.language",
                {"language": "en"},
            )

        self.assertEqual(result["kind"], "render")
        self.assertEqual(result["payload"]["snapshot"]["document"]["lang"], "en")
        self.assertEqual(self.app.reader.snapshot(), before)

    def test_action_registry_navigation_uses_same_transaction(self):
        source = self._book("registry.md", "Registry")
        self.app.open_book(source)
        before = self.app.reader.snapshot()

        with patch.object(
            self.progress_store,
            "save",
            side_effect=OSError("simulated registry progress failure"),
        ):
            with self.assertRaisesRegex(ValueError, "book command failed"):
                self.app.router.dispatch("book.next_block")

        self.assertEqual(self.app.reader.snapshot(), before)

    def test_browser_open_failure_is_sanitized_and_atomic(self):
        source = self._book("private-book.md", "Private")
        before_route = self.app.shell.current_route.route_id
        self.app.open_book_dialog = lambda: source

        class FailingProgressStore:
            def has(self, _book_key):
                return False

            def restore(self, _book_key, _document):
                raise AssertionError("restore must not run without saved progress")

            def save(self, _book_key, _reader):
                raise OSError(f"provider private progress path: {source}")

        self.app.progress_store = FailingProgressStore()
        result = self.app.browser_command("shell", "book.open")
        serialized = json.dumps(result, ensure_ascii=False)

        self.assertEqual(result["kind"], "error")
        self.assertNotIn(str(source), serialized)
        self.assertNotIn("OSError", serialized)
        self.assertNotIn("provider private progress path", serialized)
        self.assertIsNone(self.app.reader)
        self.assertIsNone(self.app.book_key)
        self.assertIsNone(self.app.book_workflow)
        self.assertIsNone(self.app.book_delegate)
        self.assertIsNone(self.app.books)
        self.assertEqual(self.app.shell.current_route.route_id, before_route)


if __name__ == "__main__":
    unittest.main()
