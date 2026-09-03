from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest

from acs.acsdb import AcsDatabase
from acs.library_import_service import LibraryImportService
from acs.version2_windows_file_workflows import (
    FileWorkflowEvent,
    FileWorkflowEventKind,
    Version2ImportWorkerServices,
    Version2WindowsFileActionDelegate,
)
from acs.version2_windows_import_event_mailbox import Version2ImportUiEventMailbox


_PGN = """[Event "Mailbox"]
[Site "?"]
[Date "2026.08.28"]
[Round "1"]
[White "White"]
[Black "Black"]
[Result "*"]

1. e4 e5 *
"""


class _Dialogs:
    def __init__(self, import_path: Path | None = None) -> None:
        self.import_path = import_path

    def open_pgn(self):
        return None

    def save_pgn_as(self, suggested_filename: str = "game.pgn"):
        return None

    def select_library_import(self):
        return self.import_path


def _run_thread(callback):
    errors: list[BaseException] = []

    def target() -> None:
        try:
            callback()
        except BaseException as exc:  # test transport must surface worker failures
            errors.append(exc)

    worker = threading.Thread(target=target, name="mailbox-test-worker")
    worker.start()
    worker.join(5.0)
    if worker.is_alive():
        raise AssertionError("mailbox test worker did not terminate")
    if errors:
        raise errors[0]


class Version2ImportUiEventMailboxTests(unittest.TestCase):
    def test_ui_thread_events_are_not_requeued_or_duplicated(self) -> None:
        mailbox = Version2ImportUiEventMailbox()
        event = FileWorkflowEvent(
            FileWorkflowEventKind.IMPORT_STARTED,
            "library.import",
            focus_target="library-import-cancel",
        )

        returned = mailbox(event)

        self.assertIs(returned, event)
        self.assertEqual(mailbox.pending_count, 0)
        self.assertEqual(mailbox.drain(), ())

    def test_worker_event_is_drained_only_by_captured_ui_thread(self) -> None:
        mailbox = Version2ImportUiEventMailbox()
        event = FileWorkflowEvent(
            FileWorkflowEventKind.IMPORT_CANCELLED,
            "library.import",
            focus_target="library-import-file",
        )
        _run_thread(lambda: mailbox(event))
        self.assertEqual(mailbox.pending_count, 1)

        worker_errors: list[str] = []

        def illegal_drain() -> None:
            try:
                mailbox.drain()
            except RuntimeError as exc:
                worker_errors.append(str(exc))

        _run_thread(illegal_drain)
        self.assertEqual(worker_errors, ["Library import UI events must be drained on the UI thread"])
        self.assertEqual(mailbox.drain(), (event,))

    def test_fast_progress_is_coalesced_without_losing_start_or_terminal_state(self) -> None:
        mailbox = Version2ImportUiEventMailbox(max_events=8)

        def produce() -> None:
            mailbox(
                FileWorkflowEvent(
                    FileWorkflowEventKind.IMPORT_STARTED,
                    "library.import",
                    focus_target="library-import-cancel",
                    total_games=10_000,
                )
            )
            for processed in range(10_001):
                mailbox(
                    FileWorkflowEvent(
                        FileWorkflowEventKind.IMPORT_PROGRESS,
                        "library.import",
                        processed_games=processed,
                        total_games=10_000,
                    )
                )
            mailbox(
                FileWorkflowEvent(
                    FileWorkflowEventKind.IMPORT_COMPLETED,
                    "library.import",
                    focus_target="library-import-file",
                    processed_games=10_000,
                    total_games=10_000,
                    game_count=10_000,
                )
            )

        _run_thread(produce)
        self.assertEqual(mailbox.pending_count, 3)
        self.assertEqual(mailbox.coalesced_progress_count, 10_000)
        events = mailbox.drain()
        self.assertEqual(
            [event.kind for event in events],
            [
                FileWorkflowEventKind.IMPORT_STARTED,
                FileWorkflowEventKind.IMPORT_PROGRESS,
                FileWorkflowEventKind.IMPORT_COMPLETED,
            ],
        )
        self.assertEqual(events[1].processed_games, 10_000)
        self.assertEqual(events[1].total_games, 10_000)

    def test_overflow_fails_closed_to_one_sanitized_status(self) -> None:
        mailbox = Version2ImportUiEventMailbox(max_events=4)

        def produce() -> None:
            for index in range(5):
                mailbox(
                    FileWorkflowEvent(
                        FileWorkflowEventKind.FAILED,
                        "library.import",
                        focus_target="library-import-file",
                        error_code=f"safe_error_{index}",
                    )
                )
            # Once overflowed, later worker events cannot replace the fail-closed marker
            # until the UI has drained it.
            mailbox(
                FileWorkflowEvent(
                    FileWorkflowEventKind.IMPORT_COMPLETED,
                    "library.import",
                    focus_target="library-import-file",
                    processed_games=1,
                    total_games=1,
                    game_count=1,
                )
            )

        _run_thread(produce)
        self.assertTrue(mailbox.overflowed)
        self.assertEqual(mailbox.pending_count, 1)
        events = mailbox.drain()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].kind, FileWorkflowEventKind.FAILED)
        self.assertEqual(events[0].error_code, "ui_event_queue_overflow")
        self.assertNotIn("safe_error_", repr(events[0]))
        self.assertFalse(mailbox.overflowed)

    def test_non_import_worker_event_is_rejected(self) -> None:
        mailbox = Version2ImportUiEventMailbox()
        errors: list[BaseException] = []

        def produce() -> None:
            try:
                mailbox(
                    FileWorkflowEvent(
                        FileWorkflowEventKind.PGN_SAVED,
                        "pgn.save",
                    )
                )
            except BaseException as exc:
                errors.append(exc)

        _run_thread(produce)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ValueError)
        self.assertEqual(mailbox.pending_count, 0)

    def test_real_background_import_uses_mailbox_without_cross_thread_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.pgn"
            database_path = root / "library.acsdb"
            source.write_text(_PGN, encoding="utf-8")
            mailbox = Version2ImportUiEventMailbox()
            factory_threads: list[int] = []

            def services_factory() -> Version2ImportWorkerServices:
                factory_threads.append(threading.get_ident())
                database = AcsDatabase(database_path)
                return Version2ImportWorkerServices(
                    LibraryImportService(database),
                    None,
                    database.close,
                )

            session_box = {"value": None}
            controller = Version2WindowsFileActionDelegate(
                dialogs=_Dialogs(source),
                get_pgn_session=lambda: session_box["value"],
                set_pgn_session=lambda value: session_box.__setitem__("value", value),
                import_services_factory=services_factory,
                event_sink=mailbox,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "library-search-player",
            )

            immediate = controller("library.import", {})
            self.assertEqual(immediate.kind, FileWorkflowEventKind.IMPORT_STARTED)
            self.assertEqual(immediate.focus_target, "library-import-cancel")
            # The synchronous UI-thread event is the command result, not a queued duplicate.
            self.assertEqual(mailbox.pending_count, 0)
            self.assertTrue(controller.wait_for_import(10.0))
            self.assertTrue(factory_threads)
            self.assertNotEqual(factory_threads[0], mailbox.ui_thread_id)

            async_events = mailbox.drain()
            kinds = [event.kind for event in async_events]
            self.assertEqual(kinds[0], FileWorkflowEventKind.IMPORT_STARTED)
            self.assertIn(FileWorkflowEventKind.IMPORT_PROGRESS, kinds)
            self.assertEqual(kinds[-1], FileWorkflowEventKind.IMPORT_COMPLETED)
            self.assertEqual(async_events[-1].game_count, 1)
            self.assertEqual(async_events[-1].focus_target, "library-import-file")

            with AcsDatabase(database_path) as database:
                count = database.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
            self.assertEqual(count, 1)

    def test_constructor_and_partial_drain_are_bounded(self) -> None:
        with self.assertRaises(TypeError):
            Version2ImportUiEventMailbox(max_events=4.0)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            Version2ImportUiEventMailbox(max_events=3)

        mailbox = Version2ImportUiEventMailbox(max_events=4)

        def produce() -> None:
            mailbox(FileWorkflowEvent(FileWorkflowEventKind.IMPORT_STARTED, "library.import", total_games=2))
            mailbox(FileWorkflowEvent(FileWorkflowEventKind.IMPORT_PROGRESS, "library.import", processed_games=1, total_games=2))
            mailbox(FileWorkflowEvent(FileWorkflowEventKind.IMPORT_COMPLETED, "library.import", processed_games=2, total_games=2, game_count=2))

        _run_thread(produce)
        first = mailbox.drain(max_events=1)
        self.assertEqual([event.kind for event in first], [FileWorkflowEventKind.IMPORT_STARTED])
        self.assertEqual(mailbox.pending_count, 2)
        rest = mailbox.drain()
        self.assertEqual(
            [event.kind for event in rest],
            [FileWorkflowEventKind.IMPORT_PROGRESS, FileWorkflowEventKind.IMPORT_COMPLETED],
        )


if __name__ == "__main__":
    unittest.main()
