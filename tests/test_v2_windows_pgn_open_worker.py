from __future__ import annotations

import tempfile
import threading
from pathlib import Path
import unittest
from unittest import mock

from acs.gametree import Comment
from acs.gametree_annotations import MoveAnnotationPatch, move_annotation_target
from acs.import_contract import fingerprint
from acs.pgn_document import PgnDocumentSession, PgnDocumentView
from acs.version2_windows_file_workflows import (
    FileWorkflowEvent,
    FileWorkflowEventKind,
    Version2ImportWorkerServices,
    Version2WindowsFileActionDelegate,
)
from acs.version2_windows_import_event_mailbox import Version2ImportUiEventMailbox
from acs.version2_windows_import_ui_pump import Version2ImportUiWakeupPump


PGN_TEXT = """[Event \"Async open\"]
[Site \"?\"]
[Date \"2026.10.05\"]
[Round \"1\"]
[White \"White\"]
[Black \"Black\"]
[Result \"*\"]

1. e4 e5 2. Nf3 Nc6 *
"""


class _Dialogs:
    def __init__(self, open_path: Path) -> None:
        self.open_path = open_path
        self.import_path: Path | None = None
        self.open_calls = 0
        self.import_calls = 0

    def open_pgn(self) -> Path | None:
        self.open_calls += 1
        return self.open_path

    def save_pgn_as(self, suggested_filename: str = "game.pgn") -> Path | None:
        return None

    def select_library_import(self) -> Path | None:
        self.import_calls += 1
        return self.import_path


class _UnusedLibrary:
    def import_games(self, *args, **kwargs):
        raise AssertionError("unexpected Library import")


class _OwnerQueuePoster:
    def __init__(self) -> None:
        self.owner_thread_id = threading.get_ident()
        self.post_thread_ids: list[int] = []
        self.callbacks: list[object] = []
        self._lock = threading.Lock()

    def __call__(self, callback):
        with self._lock:
            self.post_thread_ids.append(threading.get_ident())
            self.callbacks.append(callback)

    def drain(self) -> None:
        if threading.get_ident() != self.owner_thread_id:
            raise AssertionError("test poster drained off owner thread")
        while True:
            with self._lock:
                if not self.callbacks:
                    return
                callback = self.callbacks.pop(0)
            callback()


class Version2WindowsPgnOpenWorkerTests(unittest.TestCase):
    def _controller(
        self,
        source: Path,
        *,
        previous: PgnDocumentSession | None = None,
        owner_async_events: list[FileWorkflowEvent] | None = None,
    ):
        dialogs = _Dialogs(source)
        poster = _OwnerQueuePoster()
        events = []
        session_box = {"value": previous}
        publication_threads: list[int] = []

        def set_session(session: PgnDocumentSession) -> None:
            publication_threads.append(threading.get_ident())
            session_box["value"] = session

        controller = Version2WindowsFileActionDelegate(
            dialogs=dialogs,
            get_pgn_session=lambda: session_box["value"],
            set_pgn_session=set_session,
            import_services_factory=lambda: Version2ImportWorkerServices(
                _UnusedLibrary(), None, lambda: None
            ),
            event_sink=events.append,
            next_delegate=lambda action_id, payload: None,
            current_focus_provider=lambda: "pgn-tree",
            post_to_ui=poster,
            owner_async_event_sink=(
                None if owner_async_events is None else owner_async_events.append
            ),
        )
        return controller, dialogs, poster, events, session_box, publication_threads

    def test_unsaved_confirmation_contains_lookup_abort(self) -> None:
        class DialogLookupAbort(BaseException):
            pass

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "replacement-confirmation-lookup.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            previous = PgnDocumentSession.from_text(PGN_TEXT)
            previous.edit_tag("Event", "Dirty previous")
            controller, dialogs, poster, events, session_box, publications = self._controller(
                source,
                previous=previous,
            )
            original_getattribute = _Dialogs.__getattribute__

            def abort_confirmation_lookup(instance, name):
                if name == "confirm_discard_unsaved_pgn":
                    raise DialogLookupAbort("dialog provider aborted attribute lookup")
                return original_getattribute(instance, name)

            with mock.patch.object(
                _Dialogs,
                "__getattribute__",
                new=abort_confirmation_lookup,
            ):
                result = controller("pgn.open", {})

            self.assertEqual(result.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(result.error_code, "unsaved_confirmation_failed")
            self.assertIs(session_box["value"], previous)
            self.assertEqual(dialogs.open_calls, 0)
            self.assertEqual(publications, [])
            self.assertEqual(poster.callbacks, [])
            self.assertFalse(controller.pgn_open_running)
            self.assertEqual(events[-1], result)

    def test_unsaved_confirmation_rejects_active_truthiness(self) -> None:
        class ActiveDecision:
            def __bool__(self):
                raise AssertionError("confirmation truthiness hook executed")

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "replacement-confirmation.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            previous = PgnDocumentSession.from_text(PGN_TEXT)
            previous.edit_tag("Event", "Dirty previous")
            controller, dialogs, poster, events, session_box, publications = self._controller(
                source,
                previous=previous,
            )
            dialogs.confirm_discard_unsaved_pgn = lambda: ActiveDecision()

            result = controller("pgn.open", {})

            self.assertEqual(result.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(result.error_code, "unsaved_confirmation_failed")
            self.assertIs(session_box["value"], previous)
            self.assertEqual(dialogs.open_calls, 0)
            self.assertEqual(publications, [])
            self.assertEqual(poster.callbacks, [])
            self.assertFalse(controller.pgn_open_running)
            self.assertEqual(events[-1], result)

    def test_unsaved_confirmation_rejects_integer_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "replacement-confirmation-int.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            previous = PgnDocumentSession.from_text(PGN_TEXT)
            previous.edit_tag("Event", "Dirty previous")
            controller, dialogs, poster, events, session_box, publications = self._controller(
                source,
                previous=previous,
            )
            dialogs.confirm_discard_unsaved_pgn = lambda: 1

            result = controller("pgn.open", {})

            self.assertEqual(result.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(result.error_code, "unsaved_confirmation_failed")
            self.assertIs(session_box["value"], previous)
            self.assertEqual(dialogs.open_calls, 0)
            self.assertEqual(publications, [])
            self.assertEqual(poster.callbacks, [])
            self.assertFalse(controller.pgn_open_running)
            self.assertEqual(events[-1], result)

    def test_unsaved_confirmation_false_remains_dialog_cancel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "replacement-confirmation-cancel.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            previous = PgnDocumentSession.from_text(PGN_TEXT)
            previous.edit_tag("Event", "Dirty previous")
            controller, dialogs, poster, events, session_box, publications = self._controller(
                source,
                previous=previous,
            )
            dialogs.confirm_discard_unsaved_pgn = lambda: False

            result = controller("pgn.open", {})

            self.assertEqual(result.kind, FileWorkflowEventKind.DIALOG_CANCELLED)
            self.assertIs(session_box["value"], previous)
            self.assertEqual(dialogs.open_calls, 0)
            self.assertEqual(publications, [])
            self.assertEqual(poster.callbacks, [])
            self.assertFalse(controller.pgn_open_running)
            self.assertEqual(events[-1], result)

    def test_open_prepare_runs_off_owner_and_publication_waits_for_owner_callback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "private-worker-source.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            controller, _, poster, events, session_box, publication_threads = self._controller(source)
            owner = threading.get_ident()
            open_threads: list[int] = []
            view_threads: list[int] = []
            real_open = PgnDocumentSession.open
            real_view = PgnDocumentSession.view

            def observed_open(path):
                open_threads.append(threading.get_ident())
                return real_open(path)

            def observed_view(session):
                view_threads.append(threading.get_ident())
                return real_view(session)

            with mock.patch(
                "acs.version2_windows_file_workflows.PgnDocumentSession.open",
                side_effect=observed_open,
            ), mock.patch.object(
                PgnDocumentSession,
                "view",
                autospec=True,
                side_effect=observed_view,
            ):
                started = controller("pgn.open", {})
                self.assertEqual(started.kind, FileWorkflowEventKind.PGN_OPEN_STARTED)
                self.assertTrue(controller.wait_for_pgn_open(2.0))
                self.assertIsNone(session_box["value"])
                self.assertEqual(publication_threads, [])
                poster.drain()

            self.assertTrue(open_threads)
            self.assertTrue(view_threads)
            self.assertTrue(all(value != owner for value in open_threads + view_threads))
            self.assertTrue(poster.post_thread_ids)
            self.assertTrue(all(value != owner for value in poster.post_thread_ids))
            self.assertEqual(publication_threads, [owner])
            self.assertIsInstance(session_box["value"], PgnDocumentSession)
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.PGN_OPENED)
            self.assertEqual(events[-1].game_count, 1)
            for event in events:
                self.assertNotIn(str(source), repr(event))
                self.assertNotIn("private-worker-source", repr(event))

    def test_active_prepared_game_count_is_rejected_before_owner_hook_or_publication(self) -> None:
        class ActiveInt(int):
            def __lt__(self, other):
                raise AssertionError("active prepared game count ordering executed")

            def __int__(self):
                raise AssertionError("active prepared game count conversion executed")

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "active-prepared-count.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            controller, _, poster, events, session_box, publications = self._controller(source)
            real_view = PgnDocumentSession.view

            def active_view(session):
                view = real_view(session)
                object.__setattr__(view, "game_count", ActiveInt(view.game_count))
                return view

            with mock.patch.object(
                PgnDocumentSession,
                "view",
                autospec=True,
                side_effect=active_view,
            ):
                started = controller("pgn.open", {})
                self.assertEqual(started.kind, FileWorkflowEventKind.PGN_OPEN_STARTED)
                self.assertTrue(controller.wait_for_pgn_open(2.0))
                poster.drain()

            self.assertIsNone(session_box["value"])
            self.assertEqual(publications, [])
            self.assertFalse(controller.pgn_open_running)
            terminal = events[-1]
            self.assertEqual(terminal.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(terminal.error_code, "pgn_open_failed")

    def test_active_prepared_warnings_are_rejected_before_owner_len_or_publication(self) -> None:
        class ActiveWarnings(tuple):
            def __len__(self):
                raise AssertionError("active prepared warnings length executed")

            def __iter__(self):
                raise AssertionError("active prepared warnings iteration executed")

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "active-prepared-warnings.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            controller, _, poster, events, session_box, publications = self._controller(source)
            real_view = PgnDocumentSession.view

            def active_view(session):
                view = real_view(session)
                object.__setattr__(view, "global_warnings", ActiveWarnings())
                return view

            with mock.patch.object(
                PgnDocumentSession,
                "view",
                autospec=True,
                side_effect=active_view,
            ):
                started = controller("pgn.open", {})
                self.assertEqual(started.kind, FileWorkflowEventKind.PGN_OPEN_STARTED)
                self.assertTrue(controller.wait_for_pgn_open(2.0))
                poster.drain()

            self.assertIsNone(session_box["value"])
            self.assertEqual(publications, [])
            self.assertFalse(controller.pgn_open_running)
            terminal = events[-1]
            self.assertEqual(terminal.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(terminal.error_code, "pgn_open_failed")

    def test_prepared_session_subclass_is_rejected_before_owner_publication(self) -> None:
        class DerivedSession(PgnDocumentSession):
            pass

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "derived-prepared-session.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            controller, _, poster, events, session_box, publications = self._controller(source)
            derived = DerivedSession.from_text(PGN_TEXT)

            with mock.patch(
                "acs.version2_windows_file_workflows.PgnDocumentSession.open",
                return_value=derived,
            ):
                started = controller("pgn.open", {})
                self.assertEqual(started.kind, FileWorkflowEventKind.PGN_OPEN_STARTED)
                self.assertTrue(controller.wait_for_pgn_open(2.0))
                poster.drain()

            self.assertIsNone(session_box["value"])
            self.assertEqual(publications, [])
            self.assertFalse(controller.pgn_open_running)
            terminal = events[-1]
            self.assertEqual(terminal.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(terminal.error_code, "pgn_open_failed")

    def test_owner_live_session_base_exception_becomes_terminal_and_releases_worker(self) -> None:
        class OwnerAbort(BaseException):
            pass

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "owner-session-abort.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            dialogs = _Dialogs(source)
            poster = _OwnerQueuePoster()
            events: list[FileWorkflowEvent] = []
            get_calls = 0

            def get_session():
                nonlocal get_calls
                get_calls += 1
                if get_calls == 1:
                    return None
                raise OwnerAbort("owner session access abort")

            controller = Version2WindowsFileActionDelegate(
                dialogs=dialogs,
                get_pgn_session=get_session,
                set_pgn_session=lambda session: None,
                import_services_factory=lambda: Version2ImportWorkerServices(
                    _UnusedLibrary(), None, lambda: None
                ),
                event_sink=events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "pgn-tree",
                post_to_ui=poster,
            )

            started = controller("pgn.open", {})
            self.assertEqual(started.kind, FileWorkflowEventKind.PGN_OPEN_STARTED)
            self.assertTrue(controller.wait_for_pgn_open(2.0))
            poster.drain()

            self.assertFalse(controller.pgn_open_running)
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(events[-1].error_code, "pgn_session_unavailable")
            self.assertNotIn("owner session access abort", repr(events[-1]))

    def test_owner_session_publication_base_exception_becomes_terminal_and_releases_worker(self) -> None:
        class PublicationAbort(BaseException):
            pass

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "owner-publication-abort.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            dialogs = _Dialogs(source)
            poster = _OwnerQueuePoster()
            events: list[FileWorkflowEvent] = []

            def set_session(session):
                raise PublicationAbort("owner publication abort")

            controller = Version2WindowsFileActionDelegate(
                dialogs=dialogs,
                get_pgn_session=lambda: None,
                set_pgn_session=set_session,
                import_services_factory=lambda: Version2ImportWorkerServices(
                    _UnusedLibrary(), None, lambda: None
                ),
                event_sink=events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "pgn-tree",
                post_to_ui=poster,
            )

            started = controller("pgn.open", {})
            self.assertEqual(started.kind, FileWorkflowEventKind.PGN_OPEN_STARTED)
            self.assertTrue(controller.wait_for_pgn_open(2.0))
            poster.drain()

            self.assertFalse(controller.pgn_open_running)
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(events[-1].error_code, "pgn_open_publish_failed")
            self.assertNotIn("owner publication abort", repr(events[-1]))

    def test_recovered_legacy_open_preserves_warning_count_and_overwrite_fence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "legacy-warning.pgn"
            source.write_bytes(
                (
                    '[Event "Русская шахматная книга"]\n'
                    '[Result "*"]\n\n'
                    '1. e4 {главный план} e5 *\n'
                ).encode("cp1251")
            )
            owner_async_events: list[FileWorkflowEvent] = []
            controller, _, poster, sync_events, session_box, _ = self._controller(
                source,
                owner_async_events=owner_async_events,
            )

            started = controller("pgn.open", {})
            self.assertEqual(started.kind, FileWorkflowEventKind.PGN_OPEN_STARTED)
            self.assertTrue(controller.wait_for_pgn_open(2.0))
            poster.drain()

            terminal = owner_async_events[-1]
            self.assertEqual(terminal.kind, FileWorkflowEventKind.PGN_OPENED)
            self.assertGreaterEqual(terminal.warning_count, 1)
            session = session_box["value"]
            self.assertIsInstance(session, PgnDocumentSession)
            view = session.view()
            self.assertFalse(view.source_overwrite_safe)
            self.assertGreaterEqual(len(view.global_warnings), 1)
            self.assertEqual(sync_events, [started])
            self.assertNotIn(str(source), repr(terminal))

    def test_owner_async_terminal_uses_distinct_delivery_sink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "owner-async.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            owner_async_events: list[FileWorkflowEvent] = []
            controller, _, poster, sync_events, session_box, _ = self._controller(
                source,
                owner_async_events=owner_async_events,
            )

            started = controller("pgn.open", {})
            self.assertEqual(started.kind, FileWorkflowEventKind.PGN_OPEN_STARTED)
            self.assertEqual(sync_events, [started])
            self.assertTrue(controller.wait_for_pgn_open(2.0))
            self.assertEqual(owner_async_events, [])

            poster.drain()

            self.assertIsInstance(session_box["value"], PgnDocumentSession)
            self.assertEqual(len(owner_async_events), 1)
            self.assertEqual(
                owner_async_events[0].kind,
                FileWorkflowEventKind.PGN_OPENED,
            )
            self.assertEqual(sync_events, [started])

    def test_bounded_mailbox_delivers_pgn_open_owner_and_worker_terminals(self) -> None:
        mailbox = Version2ImportUiEventMailbox()
        posted: list[object] = []
        delivered: list[FileWorkflowEvent] = []

        def ui_ready() -> None:
            delivered.extend(mailbox.drain())

        pump = Version2ImportUiWakeupPump(
            mailbox,
            posted.append,
            ui_ready,
        )
        opened = FileWorkflowEvent(
            FileWorkflowEventKind.PGN_OPENED,
            "pgn.open",
            focus_target="pgn-game-list",
            game_count=1,
        )
        pump.owner_async_event_sink(opened)
        self.assertEqual(delivered, [opened])
        self.assertEqual(mailbox.pending_count, 0)
        self.assertEqual(posted, [])

        failed = FileWorkflowEvent(
            FileWorkflowEventKind.FAILED,
            "pgn.open",
            focus_target="pgn-tree",
            error_code="pgn_open_ui_post_failed",
        )

        errors: list[BaseException] = []
        def worker_emit() -> None:
            try:
                pump.event_sink(failed)
            except BaseException as exc:
                errors.append(exc)

        worker = threading.Thread(target=worker_emit)
        worker.start()
        worker.join(2.0)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(mailbox.pending_count, 1)
        self.assertEqual(len(posted), 1)

        callback = posted.pop(0)
        callback()
        self.assertEqual(delivered, [opened, failed])
        self.assertEqual(mailbox.pending_count, 0)

    def test_slow_open_returns_started_without_waiting_for_parse(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "slow.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            controller, _, poster, events, _, _ = self._controller(source)
            entered = threading.Event()
            release = threading.Event()
            real_open = PgnDocumentSession.open

            def slow_open(path):
                entered.set()
                if not release.wait(2.0):
                    raise AssertionError("test did not release slow open")
                return real_open(path)

            with mock.patch(
                "acs.version2_windows_file_workflows.PgnDocumentSession.open",
                side_effect=slow_open,
            ):
                result = controller("pgn.open", {})
                self.assertEqual(result.kind, FileWorkflowEventKind.PGN_OPEN_STARTED)
                self.assertTrue(entered.wait(1.0))
                self.assertTrue(controller.pgn_open_running)
                release.set()
                self.assertTrue(controller.wait_for_pgn_open(2.0))
                poster.drain()

            self.assertEqual(events[-1].kind, FileWorkflowEventKind.PGN_OPENED)

    def test_cancel_is_terminal_and_preserves_previous_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "replacement.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            previous_path = Path(tmp) / "previous.pgn"
            previous_path.write_text(PGN_TEXT.replace("Async open", "Previous"), encoding="utf-8")
            previous = PgnDocumentSession.open(previous_path)
            controller, _, poster, events, session_box, publications = self._controller(
                source, previous=previous
            )
            entered = threading.Event()
            release = threading.Event()
            real_open = PgnDocumentSession.open

            def slow_open(path):
                entered.set()
                release.wait(2.0)
                return real_open(path)

            with mock.patch(
                "acs.version2_windows_file_workflows.PgnDocumentSession.open",
                side_effect=slow_open,
            ):
                started = controller("pgn.open", {})
                self.assertEqual(started.kind, FileWorkflowEventKind.PGN_OPEN_STARTED)
                self.assertTrue(entered.wait(1.0))
                cancelling = controller("pgn.cancel_open", {})
                self.assertEqual(cancelling.kind, FileWorkflowEventKind.PGN_OPEN_CANCELLING)
                release.set()
                self.assertTrue(controller.wait_for_pgn_open(2.0))
                poster.drain()

            self.assertIs(session_box["value"], previous)
            self.assertEqual(publications, [])
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.PGN_OPEN_CANCELLED)
            self.assertFalse(controller.pgn_open_running)

    def test_open_failure_is_path_free_and_preserves_previous_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "secret-broken-name.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            previous_path = Path(tmp) / "previous.pgn"
            previous_path.write_text(PGN_TEXT.replace("Async open", "Previous"), encoding="utf-8")
            previous = PgnDocumentSession.open(previous_path)
            controller, _, poster, events, session_box, publications = self._controller(
                source, previous=previous
            )

            with mock.patch(
                "acs.version2_windows_file_workflows.PgnDocumentSession.open",
                side_effect=RuntimeError(f"private failure {source}"),
            ):
                controller("pgn.open", {})
                self.assertTrue(controller.wait_for_pgn_open(2.0))
                poster.drain()

            terminal = events[-1]
            self.assertEqual(terminal.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(terminal.error_code, "pgn_open_failed")
            self.assertIs(session_box["value"], previous)
            self.assertEqual(publications, [])
            self.assertNotIn(str(source), repr(terminal))
            self.assertNotIn("secret-broken-name", repr(terminal))

    def test_import_cannot_overlap_pgn_open_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "slow.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            controller, dialogs, poster, events, _, _ = self._controller(source)
            dialogs.import_path = source
            entered = threading.Event()
            release = threading.Event()
            real_open = PgnDocumentSession.open

            def slow_open(path):
                entered.set()
                release.wait(2.0)
                return real_open(path)

            with mock.patch(
                "acs.version2_windows_file_workflows.PgnDocumentSession.open",
                side_effect=slow_open,
            ):
                controller("pgn.open", {})
                self.assertTrue(entered.wait(1.0))
                busy = controller("library.import", {})
                self.assertEqual(busy.kind, FileWorkflowEventKind.FAILED)
                self.assertEqual(busy.error_code, "file_worker_busy")
                self.assertEqual(dialogs.import_calls, 0)
                release.set()
                self.assertTrue(controller.wait_for_pgn_open(2.0))
                poster.drain()

            self.assertEqual(events[-1].kind, FileWorkflowEventKind.PGN_OPENED)

    def test_shutdown_makes_queued_completion_stale_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "late.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            previous_path = Path(tmp) / "previous.pgn"
            previous_path.write_text(PGN_TEXT.replace("Async open", "Previous"), encoding="utf-8")
            previous = PgnDocumentSession.open(previous_path)
            controller, _, poster, events, session_box, publications = self._controller(
                source, previous=previous
            )

            controller("pgn.open", {})
            self.assertTrue(controller.wait_for_pgn_open(2.0))
            event_count_before_shutdown = len(events)
            self.assertTrue(controller.shutdown(2.0))
            poster.drain()

            self.assertIs(session_box["value"], previous)
            self.assertEqual(publications, [])
            self.assertEqual(len(events), event_count_before_shutdown)
            self.assertFalse(controller.pgn_open_running)

    def test_modal_file_picker_reentrant_edit_invalidates_open_before_worker_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "replacement.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            previous_path = Path(tmp) / "previous.pgn"
            previous_path.write_text(
                PGN_TEXT.replace("Async open", "Previous"),
                encoding="utf-8",
            )
            previous = PgnDocumentSession.open(previous_path)
            controller, dialogs, poster, events, session_box, publications = self._controller(
                source,
                previous=previous,
            )
            revision_before_dialog = previous.document_revision

            def reentrant_open():
                previous.append_text(
                    PGN_TEXT.replace("Async open", "Edited in modal message pump")
                )
                return source

            dialogs.open_pgn = reentrant_open
            result = controller("pgn.open", {})

            self.assertEqual(result.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(result.error_code, "pgn_open_stale")
            self.assertGreater(previous.document_revision, revision_before_dialog)
            self.assertIs(session_box["value"], previous)
            self.assertEqual(publications, [])
            self.assertEqual(poster.callbacks, [])
            self.assertFalse(controller.pgn_open_running)
            self.assertEqual(events[-1], result)

    def test_modal_file_picker_direct_workspace_edit_invalidates_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "replacement-workspace-edit.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            previous_path = Path(tmp) / "previous-workspace-edit.pgn"
            previous_path.write_text(PGN_TEXT.replace("Async open", "Previous"), encoding="utf-8")
            previous = PgnDocumentSession.open(previous_path)
            controller, dialogs, poster, events, session_box, publications = self._controller(source, previous=previous)

            def reentrant_open():
                game = previous.workspace.current_game()
                target = move_annotation_target(game, (), 0)
                previous.workspace.edit_move_annotations(
                    target, MoveAnnotationPatch(comments_after=(Comment("modal workspace edit"),))
                )
                return source

            dialogs.open_pgn = reentrant_open
            result = controller("pgn.open", {})
            self.assertEqual(result.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(result.error_code, "pgn_open_stale")
            self.assertIs(session_box["value"], previous)
            self.assertTrue(previous.workspace.dirty)
            self.assertEqual(publications, [])
            self.assertEqual(poster.callbacks, [])
            self.assertFalse(controller.pgn_open_running)
            self.assertEqual(events[-1], result)


    def test_modal_file_picker_source_generation_change_invalidates_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "replacement-source-generation.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            previous_path = Path(tmp) / "previous-source-generation.pgn"
            previous_path.write_text(PGN_TEXT.replace("Async open", "Previous"), encoding="utf-8")
            alternate_path = Path(tmp) / "alternate-source-generation.pgn"
            alternate_path.write_text(previous_path.read_text(encoding="utf-8"), encoding="utf-8")
            previous = PgnDocumentSession.open(previous_path)
            controller, dialogs, poster, events, session_box, publications = self._controller(source, previous=previous)

            def reentrant_open() -> Path:
                previous._source = fingerprint(alternate_path)
                return source

            dialogs.open_pgn = reentrant_open
            result = controller("pgn.open", {})
            self.assertEqual(result.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(result.error_code, "pgn_open_stale")
            self.assertIs(session_box["value"], previous)
            self.assertEqual(publications, [])
            self.assertEqual(poster.callbacks, [])
            self.assertFalse(controller.pgn_open_running)
            self.assertEqual(events[-1], result)


    def test_modal_file_picker_warning_generation_change_invalidates_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "replacement-warning-generation.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            previous_path = Path(tmp) / "previous-warning-generation.pgn"
            previous_path.write_text(PGN_TEXT.replace("Async open", "Previous"), encoding="utf-8")
            previous = PgnDocumentSession.open(previous_path)
            controller, dialogs, poster, events, session_box, publications = self._controller(source, previous=previous)

            def reentrant_open() -> Path:
                previous._global_warnings = ("new recovery warning",)
                return source

            dialogs.open_pgn = reentrant_open
            result = controller("pgn.open", {})
            self.assertEqual(result.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(result.error_code, "pgn_open_stale")
            self.assertIs(session_box["value"], previous)
            self.assertEqual(publications, [])
            self.assertEqual(poster.callbacks, [])
            self.assertFalse(controller.pgn_open_running)
            self.assertEqual(events[-1], result)

    def test_modal_file_picker_active_revision_fails_stale_without_worker_start(self) -> None:
        class ActiveInt(int):
            def __lt__(self, other):
                raise AssertionError("active modal revision ordering executed")

            def __ne__(self, other):
                raise AssertionError("active modal revision comparison executed")

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "replacement-modal-active.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            previous_path = Path(tmp) / "previous-modal-active.pgn"
            previous_path.write_text(
                PGN_TEXT.replace("Async open", "Previous"),
                encoding="utf-8",
            )
            previous = PgnDocumentSession.open(previous_path)
            controller, dialogs, poster, events, session_box, publications = self._controller(
                source,
                previous=previous,
            )

            def reentrant_open():
                previous._document_revision = ActiveInt(previous._document_revision)
                return source

            dialogs.open_pgn = reentrant_open
            result = controller("pgn.open", {})

            self.assertEqual(result.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(result.error_code, "pgn_open_stale")
            self.assertIs(session_box["value"], previous)
            self.assertEqual(publications, [])
            self.assertEqual(poster.callbacks, [])
            self.assertFalse(controller.pgn_open_running)
            self.assertEqual(events[-1], result)

    def test_prepared_open_does_not_overwrite_edits_made_before_owner_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "replacement.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            previous_path = Path(tmp) / "previous.pgn"
            previous_path.write_text(
                PGN_TEXT.replace("Async open", "Previous"),
                encoding="utf-8",
            )
            previous = PgnDocumentSession.open(previous_path)
            controller, _, poster, events, session_box, publications = self._controller(
                source,
                previous=previous,
            )

            controller("pgn.open", {})
            self.assertTrue(controller.wait_for_pgn_open(2.0))
            revision_before_edit = previous.document_revision
            previous.append_text(
                PGN_TEXT.replace("Async open", "Edited while replacement prepared")
            )
            self.assertGreater(previous.document_revision, revision_before_edit)
            self.assertTrue(previous.dirty)

            poster.drain()

            self.assertIs(session_box["value"], previous)
            self.assertEqual(publications, [])
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(events[-1].error_code, "pgn_open_stale")
            self.assertFalse(controller.pgn_open_running)

    def test_prepared_open_does_not_overwrite_direct_workspace_edit_before_owner_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "replacement-workspace-owner.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            previous_path = Path(tmp) / "previous-workspace-owner.pgn"
            previous_path.write_text(PGN_TEXT.replace("Async open", "Previous"), encoding="utf-8")
            previous = PgnDocumentSession.open(previous_path)
            controller, _, poster, events, session_box, publications = self._controller(source, previous=previous)
            controller("pgn.open", {})
            self.assertTrue(controller.wait_for_pgn_open(2.0))
            game = previous.workspace.current_game()
            target = move_annotation_target(game, (), 0)
            previous.workspace.edit_move_annotations(
                target, MoveAnnotationPatch(comments_after=(Comment("owner workspace edit"),))
            )
            poster.drain()
            self.assertIs(session_box["value"], previous)
            self.assertTrue(previous.workspace.dirty)
            self.assertEqual(publications, [])
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(events[-1].error_code, "pgn_open_stale")
            self.assertFalse(controller.pgn_open_running)

    def test_owner_stale_check_rejects_active_previous_revision_and_releases_worker(self) -> None:
        class ActiveInt(int):
            def __lt__(self, other):
                raise AssertionError("active previous revision ordering executed")

            def __ne__(self, other):
                raise AssertionError("active previous revision comparison executed")

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "replacement-active-revision.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            previous_path = Path(tmp) / "previous-active-revision.pgn"
            previous_path.write_text(
                PGN_TEXT.replace("Async open", "Previous"),
                encoding="utf-8",
            )
            previous = PgnDocumentSession.open(previous_path)
            controller, _, poster, events, session_box, publications = self._controller(
                source,
                previous=previous,
            )

            started = controller("pgn.open", {})
            self.assertEqual(started.kind, FileWorkflowEventKind.PGN_OPEN_STARTED)
            self.assertTrue(controller.wait_for_pgn_open(2.0))
            previous._document_revision = ActiveInt(previous._document_revision)

            poster.drain()

            self.assertIs(session_box["value"], previous)
            self.assertEqual(publications, [])
            self.assertFalse(controller.pgn_open_running)
            terminal = events[-1]
            self.assertEqual(terminal.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(terminal.error_code, "pgn_open_stale")

    def test_prepared_open_does_not_overwrite_replaced_current_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "replacement.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            previous_path = Path(tmp) / "previous.pgn"
            newer_path = Path(tmp) / "newer-current.pgn"
            previous_path.write_text(
                PGN_TEXT.replace("Async open", "Previous"),
                encoding="utf-8",
            )
            newer_path.write_text(
                PGN_TEXT.replace("Async open", "Newer current"),
                encoding="utf-8",
            )
            previous = PgnDocumentSession.open(previous_path)
            newer = PgnDocumentSession.open(newer_path)
            controller, _, poster, events, session_box, publications = self._controller(
                source,
                previous=previous,
            )

            controller("pgn.open", {})
            self.assertTrue(controller.wait_for_pgn_open(2.0))
            session_box["value"] = newer

            poster.drain()

            self.assertIs(session_box["value"], newer)
            self.assertEqual(publications, [])
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(events[-1].error_code, "pgn_open_stale")
            self.assertFalse(controller.pgn_open_running)

    def test_second_open_is_rejected_while_worker_is_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "slow.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            controller, dialogs, poster, _, _, _ = self._controller(source)
            entered = threading.Event()
            release = threading.Event()
            real_open = PgnDocumentSession.open

            def slow_open(path):
                entered.set()
                release.wait(2.0)
                return real_open(path)

            with mock.patch(
                "acs.version2_windows_file_workflows.PgnDocumentSession.open",
                side_effect=slow_open,
            ):
                controller("pgn.open", {})
                self.assertTrue(entered.wait(1.0))
                second = controller("pgn.open", {})
                self.assertEqual(second.kind, FileWorkflowEventKind.FAILED)
                self.assertEqual(second.error_code, "file_worker_busy")
                release.set()
                self.assertTrue(controller.wait_for_pgn_open(2.0))
                poster.drain()

            self.assertEqual(dialogs.open_calls, 1)


if __name__ == "__main__":
    unittest.main()
