from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
import unittest

from acs.acsdb import AcsDatabase
from acs.library_import_service import (
    LibraryImportCancelledError,
    LibraryImportProgress,
    LibraryImportResult,
    LibraryImportService,
)
from acs.pgn_document import PgnDocumentSession
from acs.version2_windows_file_workflows import (
    FileWorkflowEventKind,
    Version2ImportWorkerServices,
    Version2WindowsFileActionDelegate,
)


PGN_TEXT = """[Event \"UI journey\"]
[Site \"?\"]
[Date \"2026.08.28\"]
[Round \"1\"]
[White \"White\"]
[Black \"Black\"]
[Result \"*\"]

1. e4 e5 2. Nf3 Nc6 *
"""

PGN_TEXT_TWO = PGN_TEXT + "\n" + PGN_TEXT.replace("UI journey", "Second game")


class _Dialogs:
    def __init__(self) -> None:
        self.open_path: Path | None = None
        self.save_path: Path | None = None
        self.import_path: Path | None = None
        self.open_calls = 0
        self.save_calls = 0
        self.import_calls = 0
        self.suggested = ""

    def open_pgn(self) -> Path | None:
        self.open_calls += 1
        return self.open_path

    def save_pgn_as(self, suggested_filename: str = "game.pgn") -> Path | None:
        self.save_calls += 1
        self.suggested = suggested_filename
        return self.save_path

    def select_library_import(self) -> Path | None:
        self.import_calls += 1
        return self.import_path


class _UnusedLibrary:
    def import_games(self, *args, **kwargs):
        raise AssertionError("unexpected PGN Library import")


class Version2WindowsFileWorkflowTests(unittest.TestCase):
    def _controller(
        self,
        dialogs: _Dialogs,
        *,
        services_factory=None,
        focus: str = "pgn-tree",
    ):
        events = []
        session_box = {"value": None}
        fallback = []

        def get_session():
            return session_box["value"]

        def set_session(value):
            session_box["value"] = value

        def default_factory():
            return Version2ImportWorkerServices(_UnusedLibrary(), None, lambda: None)

        def next_delegate(action_id, payload):
            fallback.append((action_id, dict(payload)))
            return "fallback"

        controller = Version2WindowsFileActionDelegate(
            dialogs=dialogs,
            get_pgn_session=get_session,
            set_pgn_session=set_session,
            import_services_factory=services_factory or default_factory,
            event_sink=events.append,
            next_delegate=next_delegate,
            current_focus_provider=lambda: focus,
        )
        return controller, events, session_box, fallback

    def test_host_owns_file_workflow_ports_without_claiming_registry_surface(self) -> None:
        self.assertEqual(
            Version2WindowsFileActionDelegate.OWNED_ACTIONS,
            frozenset(
                {
                    "pgn.open",
                    "pgn.save",
                    "pgn.save_as",
                    "library.import",
                    "library.cancel_import",
                }
            ),
        )

    def test_non_file_action_chains_to_existing_canonical_delegate(self) -> None:
        dialogs = _Dialogs()
        controller, events, _, fallback = self._controller(dialogs)
        value = controller("analysis.restart", {"source": "current"})
        self.assertEqual(value, "fallback")
        self.assertEqual(fallback, [("analysis.restart", {"source": "current"})])
        self.assertEqual(events, [])

    def test_browser_cannot_submit_open_or_import_paths(self) -> None:
        dialogs = _Dialogs()
        controller, events, _, _ = self._controller(dialogs)
        with self.assertRaisesRegex(ValueError, "no browser path payload"):
            controller("pgn.open", {"path": "C:/private/game.pgn"})
        with self.assertRaisesRegex(ValueError, "no browser path payload"):
            controller("library.import", {"path": "C:/private/base.cbh"})
        self.assertEqual(dialogs.open_calls, 0)
        self.assertEqual(dialogs.import_calls, 0)
        self.assertEqual(events, [])

    def test_real_pgn_open_edit_save_reopen_uses_canonical_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "private-source-name.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            dialogs = _Dialogs()
            dialogs.open_path = source
            controller, events, session_box, _ = self._controller(
                dialogs,
                focus="pgn-comment-editor",
            )

            opened = controller("pgn.open", {})
            self.assertEqual(opened.kind, FileWorkflowEventKind.PGN_OPENED)
            self.assertEqual(opened.game_count, 1)
            self.assertEqual(opened.focus_target, "pgn-game-list")
            session = session_box["value"]
            self.assertIsInstance(session, PgnDocumentSession)
            session.edit_tag("Event", "Edited through canonical session")

            saved = controller("pgn.save", {})
            self.assertEqual(saved.kind, FileWorkflowEventKind.PGN_SAVED)
            self.assertEqual(saved.focus_target, "pgn-comment-editor")
            reopened = PgnDocumentSession.open(source)
            self.assertEqual(
                reopened.workspace.current_game().tags["Event"],
                "Edited through canonical session",
            )
            for event in events:
                self.assertNotIn(str(source), repr(event))
                self.assertNotIn("private-source-name", repr(event))

    def test_save_as_existing_destination_uses_expected_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pgn"
            destination = Path(tmp) / "existing-target.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            destination.write_text(PGN_TEXT.replace("UI journey", "Old target"), encoding="utf-8")
            dialogs = _Dialogs()
            dialogs.open_path = source
            dialogs.save_path = destination
            controller, _, session_box, _ = self._controller(dialogs)
            controller("pgn.open", {})
            session_box["value"].edit_tag("Event", "Saved As")

            result = controller("pgn.save_as", {})
            self.assertEqual(result.kind, FileWorkflowEventKind.PGN_SAVED_AS)
            self.assertEqual(dialogs.suggested, "source.pgn")
            reopened = PgnDocumentSession.open(destination)
            self.assertEqual(reopened.workspace.current_game().tags["Event"], "Saved As")

    def test_save_on_new_document_routes_to_native_save_as(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "new-game.pgn"
            dialogs = _Dialogs()
            dialogs.save_path = destination
            controller, _, session_box, _ = self._controller(dialogs)
            session_box["value"] = PgnDocumentSession.new_game()

            result = controller("pgn.save", {})
            self.assertEqual(result.kind, FileWorkflowEventKind.PGN_SAVED_AS)
            self.assertTrue(destination.is_file())
            self.assertEqual(dialogs.save_calls, 1)

    def test_real_pgn_library_import_runs_off_ui_thread_and_publishes_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sensitive-family-name.pgn"
            database_path = Path(tmp) / "library.acsdb"
            source.write_text(PGN_TEXT_TWO, encoding="utf-8")
            dialogs = _Dialogs()
            dialogs.import_path = source
            factory_threads = []

            def services_factory():
                factory_threads.append(threading.current_thread().name)
                database = AcsDatabase(database_path)
                return Version2ImportWorkerServices(
                    LibraryImportService(database),
                    None,
                    database.close,
                )

            controller, events, _, _ = self._controller(
                dialogs,
                services_factory=services_factory,
                focus="library-search-player",
            )
            returned = controller("library.import", {})
            self.assertEqual(returned.kind, FileWorkflowEventKind.IMPORT_STARTED)
            self.assertEqual(returned.focus_target, "library-import-cancel")
            self.assertTrue(controller.wait_for_import(10.0))
            self.assertTrue(factory_threads)
            self.assertTrue(factory_threads[0].startswith("AccessibleChess-V2-Import-"))

            with AcsDatabase(database_path) as database:
                count = database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
                attempts = database.conn.execute(
                    "SELECT status, game_count FROM import_attempts ORDER BY id"
                ).fetchall()
            self.assertEqual(count, 2)
            self.assertEqual([(row[0], row[1]) for row in attempts], [("full", 2)])
            kinds = [event.kind for event in events]
            self.assertIn(FileWorkflowEventKind.IMPORT_PROGRESS, kinds)
            self.assertEqual(kinds[-1], FileWorkflowEventKind.IMPORT_COMPLETED)
            completed = events[-1]
            self.assertEqual(completed.game_count, 2)
            self.assertEqual(completed.total_games, 2)
            self.assertEqual(completed.focus_target, "library-import-file")
            for event in events:
                rendered = repr(event)
                self.assertNotIn(str(source), rendered)
                self.assertNotIn("sensitive-family-name", rendered)
                self.assertNotIn(str(database_path), rendered)

    def test_cancel_is_deliverable_while_background_import_is_running(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "cancel-me.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            dialogs = _Dialogs()
            dialogs.import_path = source
            entered = threading.Event()
            closed = threading.Event()

            class BlockingLibrary:
                def import_games(self, games, **kwargs):
                    progress = kwargs["progress_callback"]
                    cancel_check = kwargs["cancel_check"]
                    progress(LibraryImportProgress(1, 0, len(games)))
                    entered.set()
                    while True:
                        if cancel_check():
                            raise LibraryImportCancelledError("cancelled")
                        time.sleep(0.005)

            def services_factory():
                return Version2ImportWorkerServices(
                    BlockingLibrary(),
                    None,
                    closed.set,
                )

            controller, events, _, _ = self._controller(
                dialogs,
                services_factory=services_factory,
            )
            controller("library.import", {})
            self.assertTrue(entered.wait(5.0))
            cancelling = controller("library.cancel_import", {})
            self.assertEqual(cancelling.kind, FileWorkflowEventKind.IMPORT_CANCELLING)
            self.assertTrue(controller.wait_for_import(5.0))
            self.assertTrue(closed.is_set())
            kinds = [event.kind for event in events]
            self.assertIn(FileWorkflowEventKind.IMPORT_CANCELLED, kinds)
            self.assertNotIn(FileWorkflowEventKind.IMPORT_COMPLETED, kinds)

    def test_cbh_and_cbv_are_routed_only_to_existing_chessbase_service(self) -> None:
        for suffix in (".cbh", ".cbv"):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as tmp:
                source = Path(tmp) / ("private-source" + suffix)
                source.write_bytes(b"fixture placeholder")
                dialogs = _Dialogs()
                dialogs.import_path = source
                calls = []

                class ChessBaseService:
                    def import_database(self, path, **kwargs):
                        calls.append(Path(path).suffix.lower())
                        progress = kwargs["progress_callback"]
                        progress(LibraryImportProgress(9, 0, 2))
                        progress(LibraryImportProgress(9, 1, 2))
                        progress(LibraryImportProgress(9, 2, 2))
                        return SimpleNamespace(
                            library_result=LibraryImportResult(9, 1, 2, 0, 10, 11),
                            warning_count=0,
                        )

                def services_factory():
                    return Version2ImportWorkerServices(
                        _UnusedLibrary(),
                        ChessBaseService(),
                        lambda: None,
                    )

                controller, events, _, _ = self._controller(
                    dialogs,
                    services_factory=services_factory,
                )
                controller("library.import", {})
                self.assertTrue(controller.wait_for_import(5.0))
                self.assertEqual(calls, [suffix])
                self.assertEqual(events[-1].kind, FileWorkflowEventKind.IMPORT_COMPLETED)
                self.assertEqual(events[-1].game_count, 2)
                self.assertNotIn(str(source), repr(events[-1]))

    def test_unsupported_extension_fails_before_worker_or_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "database.cbf"
            source.write_bytes(b"not claimed")
            dialogs = _Dialogs()
            dialogs.import_path = source
            called = []

            def services_factory():
                called.append(True)
                return Version2ImportWorkerServices(_UnusedLibrary(), None, lambda: None)

            controller, events, _, _ = self._controller(
                dialogs,
                services_factory=services_factory,
            )
            result = controller("library.import", {})
            self.assertEqual(result.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(result.error_code, "unsupported_import_source")
            self.assertEqual(called, [])
            self.assertFalse(controller.import_running)
            self.assertEqual(events[-1], result)

    def test_shutdown_requests_cancel_and_does_not_orphan_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "shutdown.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            dialogs = _Dialogs()
            dialogs.import_path = source
            entered = threading.Event()

            class BlockingLibrary:
                def import_games(self, games, **kwargs):
                    entered.set()
                    while not kwargs["cancel_check"]():
                        time.sleep(0.005)
                    raise LibraryImportCancelledError("cancelled")

            controller, events, _, _ = self._controller(
                dialogs,
                services_factory=lambda: Version2ImportWorkerServices(
                    BlockingLibrary(), None, lambda: None
                ),
            )
            controller("library.import", {})
            self.assertTrue(entered.wait(5.0))
            self.assertTrue(controller.shutdown(5.0))
            self.assertFalse(controller.import_running)
            self.assertIn(
                FileWorkflowEventKind.IMPORT_CANCELLED,
                [event.kind for event in events],
            )


if __name__ == "__main__":
    unittest.main()
