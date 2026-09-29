import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import (
    BookProgressStore,
    BookProgressStoreError,
    BookProgressStoreErrorCode,
)
from acs.chesscore import Board
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
        self.projected_positions = []

        def project_position(fen):
            self.projected_positions.append(fen)
            return {"ok": True}

        self.app = Version2Application(self.database, progress_store=BookProgressStore(self.root / "progress.json"),
            engine_assistance=EngineAssistedWorkflowService(self.analysis), board_dispatch=lambda *_: None,
            board_position_projector=project_position, copy_text=self.copied.append)
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

    def _open_book_game(self):
        book = self.root / "study.md"
        book.write_text("# Навчання\n\nТекст\n\n```pgn\n" + PGN + "```\n\nПісля\n", encoding="utf-8")
        self.app.open_book_dialog = lambda: book
        self.assertEqual(self.app.browser_command("shell", "book.open")["kind"], "delegated")
        self.app.browser_command("books", "book.next_game")
        return book, self.app.reader.location()

    def test_book_native_open_board_exact_return_and_persistent_resume(self):
        book, origin = self._open_book_game()
        self.projected_positions.clear()
        self.assertEqual(self.app.browser_command("books", "book.open_position")["kind"], "delegated")
        self.assertTrue(self.app.book_workflow.active)
        self.assertEqual(self.projected_positions[-1], Board.START)

        self.app.router.dispatch("book.board_next_move")
        expected = Board()
        expected.push_text("e4")
        self.assertEqual(self.projected_positions[-1], expected.fen())
        self.assertEqual(self.app.book_delegate.board_snapshot().fen(), expected.fen())

        self.assertEqual(self.app.browser_command("books", "book.return_from_board")["kind"], "render")
        self.assertEqual(self.app.reader.location(), origin)
        self.app.open_book(book)
        self.assertEqual(self.app.reader.location(), origin)

    def _restarted_application(self, store):
        restarted = Version2Application(
            self.database,
            progress_store=store,
            engine_assistance=self.app.engine_assistance,
            board_dispatch=lambda *_: None,
            board_position_projector=lambda fen: {"ok": True},
            copy_text=self.copied.append,
        )
        return restarted

    def test_book_open_can_explicitly_recover_corrupt_progress_from_valid_backup(self):
        book, origin = self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key

        # Pin a previous-valid backup to the exact current semantic cursor, then
        # simulate a crash/torn primary. The restarted app has no in-memory Book
        # state that could hide the persistence failure.
        store.save(key, self.app.reader)
        backup_before = store.backup_path.read_bytes()
        store.path.write_bytes(b'{"schema_version":2,"generation":')
        corrupt_primary = store.path.read_bytes()

        restarted = self._restarted_application(store)
        confirmations = []
        restarted.confirm_book_progress_recovery = lambda: confirmations.append(True) or True

        restarted.open_book(book)

        self.assertEqual(confirmations, [True])
        self.assertEqual(restarted.shell.current_route.route_id, "books")
        self.assertEqual(restarted.reader.location(), origin)
        self.assertEqual(store.restore(key, restarted.reader.document).location(), origin)
        self.assertNotEqual(store.path.read_bytes(), corrupt_primary)
        self.assertTrue(store.backup_path.exists())
        self.assertNotEqual(backup_before, b"")

    def test_book_open_can_explicitly_recover_missing_primary_from_valid_backup(self):
        book, origin = self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key

        # Create a previous-valid generation at the exact current semantic cursor,
        # then simulate loss of only the primary file.
        store.save(key, self.app.reader)
        backup_before = store.backup_path.read_bytes()
        store.path.unlink()

        restarted = self._restarted_application(store)
        confirmations = []
        restarted.confirm_book_progress_recovery = lambda: confirmations.append(True) or True

        restarted.open_book(book)

        self.assertEqual(confirmations, [True])
        self.assertEqual(restarted.shell.current_route.route_id, "books")
        self.assertEqual(restarted.reader.location(), origin)
        self.assertEqual(store.restore(key, restarted.reader.document).location(), origin)
        self.assertTrue(store.path.exists())
        self.assertTrue(store.backup_path.exists())
        self.assertEqual(store.backup_path.read_bytes(), backup_before)

    def test_book_open_declined_missing_primary_recovery_is_atomic_and_non_destructive(self):
        book, origin = self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key
        store.save(key, self.app.reader)
        backup_before = store.backup_path.read_bytes()
        store.path.unlink()

        restarted = self._restarted_application(store)
        route_before = restarted.shell.current_route.route_id
        confirmations = []
        restarted.confirm_book_progress_recovery = lambda: confirmations.append(True) or False

        with self.assertRaises(BookProgressStoreError) as caught:
            restarted.open_book(book)

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.CORRUPT_STORE)
        self.assertEqual(confirmations, [True])
        self.assertIsNone(restarted.reader)
        self.assertIsNone(restarted.books)
        self.assertIsNone(restarted.book_workflow)
        self.assertEqual(restarted.shell.current_route.route_id, route_before)
        self.assertFalse(store.path.exists())
        self.assertEqual(store.backup_path.read_bytes(), backup_before)
        restored = store.restore(key, self.app.reader.document)
        self.assertEqual(restored.location(), origin)

    def test_book_open_missing_primary_recovery_rejects_backup_swap_after_confirmation(self):
        book, _origin = self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key
        store.save(key, self.app.reader)
        store.path.unlink()

        swapped_backup = b'{"entries":{},"generation":7,"schema_version":2}'
        restarted = self._restarted_application(store)
        route_before = restarted.shell.current_route.route_id
        confirmations = []

        def confirm_and_swap_backup():
            confirmations.append(True)
            store.backup_path.write_bytes(swapped_backup)
            return True

        restarted.confirm_book_progress_recovery = confirm_and_swap_backup
        with self.assertRaises(BookProgressStoreError) as caught:
            restarted.open_book(book)

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(confirmations, [True])
        self.assertIsNone(restarted.reader)
        self.assertIsNone(restarted.books)
        self.assertIsNone(restarted.book_workflow)
        self.assertEqual(restarted.shell.current_route.route_id, route_before)
        self.assertFalse(store.path.exists())
        self.assertEqual(store.backup_path.read_bytes(), swapped_backup)

    def test_book_open_missing_primary_future_backup_never_offers_rollback(self):
        book, _origin = self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key
        store.save(key, self.app.reader)
        future_backup = b'{"entries":{},"generation":9,"schema_version":999}'
        store.backup_path.write_bytes(future_backup)
        store.path.unlink()

        restarted = self._restarted_application(store)
        route_before = restarted.shell.current_route.route_id
        confirmations = []
        restarted.confirm_book_progress_recovery = lambda: confirmations.append(True) or True

        with self.assertRaises(BookProgressStoreError) as caught:
            restarted.open_book(book)

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.UNSUPPORTED_SCHEMA)
        self.assertEqual(confirmations, [])
        self.assertIsNone(restarted.reader)
        self.assertIsNone(restarted.books)
        self.assertEqual(restarted.shell.current_route.route_id, route_before)
        self.assertFalse(store.path.exists())
        self.assertEqual(store.backup_path.read_bytes(), future_backup)

    def test_book_open_missing_primary_unrelated_backup_never_offers_cross_book_recovery(self):
        book, _origin = self._open_book_game()
        store = self.app.progress_store
        store.path.unlink()
        unrelated_backup = b'{"entries":{},"generation":7,"schema_version":2}'
        store.backup_path.write_bytes(unrelated_backup)

        restarted = self._restarted_application(store)
        route_before = restarted.shell.current_route.route_id
        confirmations = []
        restarted.confirm_book_progress_recovery = lambda: confirmations.append(True) or True

        with self.assertRaises(BookProgressStoreError) as caught:
            restarted.open_book(book)

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.CORRUPT_STORE)
        self.assertEqual(confirmations, [])
        self.assertIsNone(restarted.reader)
        self.assertIsNone(restarted.books)
        self.assertEqual(restarted.shell.current_route.route_id, route_before)
        self.assertFalse(store.path.exists())
        self.assertEqual(store.backup_path.read_bytes(), unrelated_backup)

    def test_book_open_declined_progress_recovery_is_atomic_and_non_destructive(self):
        book, _origin = self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key
        store.save(key, self.app.reader)
        backup_before = store.backup_path.read_bytes()
        corrupt_primary = b'{"schema_version":2,"generation":'
        store.path.write_bytes(corrupt_primary)

        restarted = self._restarted_application(store)
        route_before = restarted.shell.current_route.route_id
        confirmations = []
        restarted.confirm_book_progress_recovery = lambda: confirmations.append(True) or False

        with self.assertRaises(BookProgressStoreError) as caught:
            restarted.open_book(book)

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.CORRUPT_STORE)
        self.assertEqual(confirmations, [True])
        self.assertIsNone(restarted.reader)
        self.assertIsNone(restarted.books)
        self.assertIsNone(restarted.book_workflow)
        self.assertEqual(restarted.shell.current_route.route_id, route_before)
        self.assertEqual(store.path.read_bytes(), corrupt_primary)
        self.assertEqual(store.backup_path.read_bytes(), backup_before)

    def test_book_open_future_progress_schema_never_offers_backup_rollback(self):
        book, _origin = self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key
        store.save(key, self.app.reader)
        backup_before = store.backup_path.read_bytes()
        future_primary = b'{"schema_version":999,"entries":{}}'
        store.path.write_bytes(future_primary)

        restarted = self._restarted_application(store)
        confirmations = []
        restarted.confirm_book_progress_recovery = lambda: confirmations.append(True) or True

        with self.assertRaises(BookProgressStoreError) as caught:
            restarted.open_book(book)

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.UNSUPPORTED_SCHEMA)
        self.assertEqual(confirmations, [])
        self.assertIsNone(restarted.reader)
        self.assertIsNone(restarted.books)
        self.assertEqual(store.path.read_bytes(), future_primary)
        self.assertEqual(store.backup_path.read_bytes(), backup_before)

    def test_book_open_recovery_confirmation_failure_preserves_all_progress_bytes(self):
        book, _origin = self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key
        store.save(key, self.app.reader)
        backup_before = store.backup_path.read_bytes()
        corrupt_primary = b'{"schema_version":2,"generation":'
        store.path.write_bytes(corrupt_primary)

        restarted = self._restarted_application(store)

        def broken_confirmation():
            raise RuntimeError("private dialog failure")

        restarted.confirm_book_progress_recovery = broken_confirmation
        with self.assertRaises(BookProgressStoreError) as caught:
            restarted.open_book(book)

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.CORRUPT_STORE)
        self.assertIsNone(restarted.reader)
        self.assertIsNone(restarted.books)
        self.assertEqual(store.path.read_bytes(), corrupt_primary)
        self.assertEqual(store.backup_path.read_bytes(), backup_before)
        self.assertNotIn("private dialog failure", str(caught.exception))


    def test_runtime_book_save_does_not_offer_recovery_without_backup(self):
        self._open_book_game()
        store = self.app.progress_store
        store.backup_path.unlink(missing_ok=True)
        corrupt_primary = b'{"schema_version":2,"generation":'
        store.path.write_bytes(corrupt_primary)
        confirmations = []
        self.app.confirm_book_progress_recovery = (
            lambda: confirmations.append(True) or True
        )

        with self.assertRaises(BookProgressStoreError) as caught:
            self.app.save_book_progress()

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.CORRUPT_STORE)
        self.assertEqual(confirmations, [])
        self.assertEqual(store.path.read_bytes(), corrupt_primary)
        self.assertFalse(store.backup_path.exists())

    def test_runtime_book_save_does_not_offer_recovery_from_corrupt_backup(self):
        self._open_book_game()
        store = self.app.progress_store
        corrupt_primary = b'{"schema_version":2,"generation":'
        corrupt_backup = b'{"schema_version":2,"entries":'
        store.path.write_bytes(corrupt_primary)
        store.backup_path.write_bytes(corrupt_backup)
        confirmations = []
        self.app.confirm_book_progress_recovery = (
            lambda: confirmations.append(True) or True
        )

        with self.assertRaises(BookProgressStoreError) as caught:
            self.app.save_book_progress()

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.CORRUPT_STORE)
        self.assertEqual(confirmations, [])
        self.assertEqual(store.path.read_bytes(), corrupt_primary)
        self.assertEqual(store.backup_path.read_bytes(), corrupt_backup)



    def test_runtime_book_save_does_not_offer_recovery_from_unrelated_valid_backup(self):
        self._open_book_game()
        store = self.app.progress_store
        corrupt_primary = b'{"schema_version":2,"generation":'
        unrelated_backup = b'{"entries":{},"generation":1,"schema_version":2}'
        store.path.write_bytes(corrupt_primary)
        store.backup_path.write_bytes(unrelated_backup)
        confirmations = []
        self.app.confirm_book_progress_recovery = (
            lambda: confirmations.append(True) or True
        )

        with self.assertRaises(BookProgressStoreError) as caught:
            self.app.save_book_progress()

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.CORRUPT_STORE)
        self.assertEqual(confirmations, [])
        self.assertEqual(store.path.read_bytes(), corrupt_primary)
        self.assertEqual(store.backup_path.read_bytes(), unrelated_backup)



    def test_runtime_book_save_recovers_only_after_usable_backup_confirmation(self):
        self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key
        # A second successful write pins a valid previous generation as backup.
        store.save(key, self.app.reader)
        self.assertTrue(store.backup_path.exists())
        corrupt_primary = b'{"schema_version":2,"generation":'
        store.path.write_bytes(corrupt_primary)
        confirmations = []
        self.app.confirm_book_progress_recovery = (
            lambda: confirmations.append(True) or True
        )
        expected = self.app.reader.snapshot()

        self.app.save_book_progress()

        self.assertEqual(confirmations, [True])
        self.assertNotEqual(store.path.read_bytes(), corrupt_primary)
        restored = store.restore(key, self.app.reader.document)
        self.assertEqual(restored.snapshot(), expected)


    def test_book_recovery_publishes_only_the_semantically_validated_backup_revision(self):
        self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key
        store.save(key, self.app.reader)
        self.assertTrue(store.backup_path.exists())

        corrupt_primary = b'{"schema_version":2,"generation":'
        store.path.write_bytes(corrupt_primary)
        swapped_backup = b'{"entries":{},"generation":1,"schema_version":2}'
        confirmations = []

        def confirm_and_swap_backup():
            confirmations.append(True)
            store.backup_path.write_bytes(swapped_backup)
            return True

        self.app.confirm_book_progress_recovery = confirm_and_swap_backup
        with self.assertRaises(BookProgressStoreError) as caught:
            self.app.save_book_progress()

        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.STALE_WRITE)
        self.assertEqual(confirmations, [True])
        self.assertEqual(store.path.read_bytes(), corrupt_primary)
        self.assertEqual(store.backup_path.read_bytes(), swapped_backup)

    def test_book_store_expected_backup_revision_is_exact_and_backward_compatible(self):
        self._open_book_game()
        store = self.app.progress_store
        key = self.app.book_key
        store.save(key, self.app.reader)
        revision = store.validated_backup_revision(key, self.app.reader.document)
        self.assertEqual(len(revision), 64)
        self.assertTrue(all(character in "0123456789abcdef" for character in revision))

        corrupt_primary = b'{"schema_version":2,"generation":'
        store.path.write_bytes(corrupt_primary)
        self.assertTrue(store.recover_from_backup(expected_backup_revision=revision))
        self.assertNotEqual(store.path.read_bytes(), corrupt_primary)

        store.path.write_bytes(corrupt_primary)
        with self.assertRaises(BookProgressStoreError) as caught:
            store.recover_from_backup(expected_backup_revision="not-a-revision")
        self.assertEqual(caught.exception.code, BookProgressStoreErrorCode.INVALID_ARGUMENT)
        self.assertEqual(store.path.read_bytes(), corrupt_primary)

    def test_book_open_fails_closed_when_release_board_rejects_position(self):
        _book, origin = self._open_book_game()
        self.app._board_position_projector = lambda _fen: {"ok": False}

        result = self.app.browser_command("books", "book.open_position")

        self.assertEqual(result["kind"], "error")
        self.assertFalse(self.app.book_workflow.active)
        self.assertEqual(self.app.reader.location(), origin)
        self.assertEqual(self.app.shell.current_route.route_id, "books")

    def test_book_navigation_projection_failure_restores_canonical_cursor(self):
        _book, _origin = self._open_book_game()
        self.assertEqual(self.app.browser_command("books", "book.open_position")["kind"], "delegated")
        before = self.app.book_delegate.view()
        projected = []

        def reject_changed_position(fen):
            projected.append(fen)
            return {"ok": fen == before.current_fen}

        self.app._board_position_projector = reject_changed_position
        result = self.app.browser_command("review", "book.board_next_move")

        self.assertEqual(result["kind"], "error")
        after = self.app.book_delegate.view()
        self.assertEqual(after.cursor, before.cursor)
        self.assertEqual(after.current_fen, before.current_fen)
        self.assertTrue(self.app.book_workflow.active)
        self.assertEqual(self.app.shell.current_route.route_id, "board")
        self.assertEqual(projected[-1], before.current_fen)

    def test_browser_path_payload_rejected_before_native_picker(self):
        self.dialogs.open_pgn = lambda: self.fail("must not open dialog")
        result = self.app.browser_command("shell", "pgn.open", {"path": str(self.source)})
        self.assertEqual(result["kind"], "error")
        self.assertIsNone(self.app.session)


if __name__ == "__main__": unittest.main()
