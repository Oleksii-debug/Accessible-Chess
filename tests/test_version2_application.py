import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.pgn_service import open_pgn
from acs.version2_application import Version2Application
from acs.version2_windows_file_workflows import Version2WindowsFileActionDelegate
from acs.version2_windows_import_event_mailbox import Version2ImportUiEventMailbox


PGN = '[Event "Україна"]\n[White "Петренко"]\n[Black "Smith"]\n[Result "*"]\n\n1. e4 {before} (1. d4 $1 d5) e5 *\n'


class Version2ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "input.pgn"
        self.source.write_text(PGN, encoding="utf-8")
        self.database = AcsDatabase(self.root / "library.acsdb")
        self.addCleanup(self.database.close)
        self.analysis = AnalysisService(lambda: None)
        self.addCleanup(self.analysis.close)
        self.copied = []
        self.app = Version2Application(self.database, progress_store=BookProgressStore(self.root / "progress.json"),
            engine_assistance=EngineAssistedWorkflowService(self.analysis), board_dispatch=lambda *_: None, copy_text=self.copied.append)
        self.mailbox = Version2ImportUiEventMailbox()
        self.dialogs = SimpleNamespace(open_pgn=lambda: self.source, save_pgn_as=lambda *_: self.root / "saved.pgn", select_library_import=lambda: self.source)
        self.files = Version2WindowsFileActionDelegate(dialogs=self.dialogs, get_pgn_session=lambda: self.app.session,
            set_pgn_session=self.app.set_document, import_services_factory=self.app.worker_factory(self.root / "library.acsdb"),
            event_sink=self.mailbox, next_delegate=lambda *_: None)
        self.app.bind_files(self.files)
        self.addCleanup(lambda: self.files.shutdown(timeout=5))

    def test_native_file_open_browser_edit_save_and_reopen(self):
        self.app.browser_command("shell", "pgn.open")
        self.assertEqual(self.app.shell.current_route.route_id, "pgn")
        selected = self.app.browser_command("pgn", "pgn.select", {"node_id": "g0:main/m0"})
        self.assertEqual(selected["kind"], "selection")
        edited = self.app.browser_command("pgn", "pgn.comment_edit", {"text": "новий коментар"})
        self.assertEqual(edited["kind"], "selection")
        self.assertTrue(self.app.session.dirty)
        self.app.browser_command("shell", "pgn.save")
        self.assertFalse(self.app.session.dirty)
        reopened = open_pgn(self.source)
        self.assertEqual(reopened.games[0].line.moves[0].comments_after[0].text, "новий коментар")
        self.assertEqual(len(reopened.games[0].line.moves[0].variations), 1)

    def test_real_import_observer_search_open_detached_game(self):
        self.app.browser_command("library", "library.import")
        self.assertTrue(self.files.wait_for_import(5))
        self.app.import_ui_ready(self.mailbox)
        snapshot = self.app.snapshot()
        self.assertEqual(snapshot["library"]["import"]["phase"], "completed")
        self.assertEqual(snapshot["library"]["import"]["processed_games"], 1)
        searched = self.app.browser_command("library", "library.search", {"player": "петренко"})
        self.assertEqual(searched["kind"], "render")
        before = self.database.get_game(1)["pgn_text"]
        self.assertEqual(self.app.browser_command("library", "library.open_game")["kind"], "delegated")
        self.app.browser_command("pgn", "pgn.select", {"node_id": "g0:main/m0"})
        self.app.browser_command("pgn", "pgn.comment_edit", {"text": "detached edit"})
        self.assertEqual(self.database.get_game(1)["pgn_text"], before)
        serialized = json.dumps(self.app.snapshot(), ensure_ascii=False)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn("attempt_id", serialized)

    def test_empty_source_has_terminal_ui_and_can_retry(self):
        self.source.write_text("", encoding="utf-8")
        self.app.browser_command("library", "library.import")
        self.assertTrue(self.files.wait_for_import(5))
        self.app.import_ui_ready(self.mailbox)
        self.assertEqual(self.app.snapshot()["library"]["import"]["phase"], "empty")
        self.source.write_text(PGN, encoding="utf-8")
        self.app.browser_command("library", "library.import")
        self.assertTrue(self.files.wait_for_import(5))
        self.app.import_ui_ready(self.mailbox)
        self.assertEqual(self.app.snapshot()["library"]["import"]["phase"], "completed")

    def test_book_native_open_board_exact_return_and_persistent_resume(self):
        book = self.root / "study.md"
        book.write_text("# Навчання\n\nТекст\n\n```pgn\n" + PGN + "```\n\nПісля\n", encoding="utf-8")
        self.app.open_book_dialog = lambda: book
        self.assertEqual(self.app.browser_command("shell", "book.open")["kind"], "delegated")
        self.app.browser_command("books", "book.next_game")
        origin = self.app.reader.location()
        self.assertEqual(self.app.browser_command("books", "book.open_position")["kind"], "delegated")
        self.assertTrue(self.app.book_workflow.active)
        self.app.router.dispatch("book.board_next_move")
        self.assertEqual(self.app.browser_command("books", "book.return_from_board")["kind"], "render")
        self.assertEqual(self.app.reader.location(), origin)
        self.app.open_book(book)
        self.assertEqual(self.app.reader.location(), origin)

    def test_book_open_progress_failure_is_atomic(self):
        book = self.root / "atomic.md"
        book.write_text("# Atomic\n\nText\n", encoding="utf-8")
        before_route = self.app.shell.current_route.route_id

        class FailingProgressStore:
            def has(self, _book_key):
                return False

            def restore(self, _book_key, _document):
                raise AssertionError("restore must not run without saved progress")

            def save(self, _book_key, _reader):
                raise OSError("simulated progress write failure")

        self.app.progress_store = FailingProgressStore()

        with self.assertRaisesRegex(OSError, "simulated progress write failure"):
            self.app.open_book(book)

        self.assertIsNone(self.app.reader)
        self.assertIsNone(self.app.book_key)
        self.assertIsNone(self.app.book_workflow)
        self.assertIsNone(self.app.book_delegate)
        self.assertIsNone(self.app.books)
        self.assertEqual(self.app.shell.current_route.route_id, before_route)

    def test_replacing_book_progress_failure_preserves_current_book(self):
        first = self.root / "first.md"
        second = self.root / "second.md"
        first.write_text("# First\n\nOriginal book\n", encoding="utf-8")
        second.write_text("# Second\n\nReplacement book\n", encoding="utf-8")
        self.app.open_book(first)

        real_store = self.app.progress_store
        old_reader = self.app.reader
        old_key = self.app.book_key
        old_workflow = self.app.book_workflow
        old_delegate = self.app.book_delegate
        old_books = self.app.books
        old_route = self.app.shell.current_route.route_id

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

        with self.assertRaisesRegex(OSError, "simulated replacement progress write failure"):
            self.app.open_book(second)

        self.assertIs(self.app.reader, old_reader)
        self.assertEqual(self.app.book_key, old_key)
        self.assertIs(self.app.book_workflow, old_workflow)
        self.assertIs(self.app.book_delegate, old_delegate)
        self.assertIs(self.app.books, old_books)
        self.assertEqual(self.app.shell.current_route.route_id, old_route)

    def test_browser_path_payload_rejected_before_native_picker(self):
        self.dialogs.open_pgn = lambda: self.fail("must not open dialog")
        result = self.app.browser_command("shell", "pgn.open", {"path": str(self.source)})
        self.assertEqual(result["kind"], "error")
        self.assertIsNone(self.app.session)


if __name__ == "__main__": unittest.main()