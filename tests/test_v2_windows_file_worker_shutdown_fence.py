from __future__ import annotations

import tempfile
import threading
from pathlib import Path
import unittest
from unittest import mock

from acs.library_import_service import LibraryImportProgress, LibraryImportResult
from acs.pgn_document import PgnDocumentSession
from acs.version2_windows_file_workflows import (
    FileWorkflowEvent,
    FileWorkflowEventKind,
    Version2ImportWorkerServices,
    Version2WindowsFileActionDelegate,
)


PGN_TEXT = """[Event \"Shutdown fence\"]
[Site \"?\"]
[Date \"2026.10.05\"]
[Round \"1\"]
[White \"White\"]
[Black \"Black\"]
[Result \"*\"]

1. e4 e5 *
"""


class _Dialogs:
    def __init__(self, source: Path) -> None:
        self.source = source

    def open_pgn(self):
        return self.source

    def save_pgn_as(self, suggested_filename: str = "game.pgn"):
        return None

    def select_library_import(self):
        return self.source


class _UnusedLibrary:
    def import_games(self, *args, **kwargs):
        raise AssertionError("worker must not start after shutdown")


class Version2WindowsFileWorkerShutdownFenceTests(unittest.TestCase):
    def _delegate(self, source: Path, *, event_sink, post_to_ui=None):
        return Version2WindowsFileActionDelegate(
            dialogs=_Dialogs(source),
            get_pgn_session=lambda: None,
            set_pgn_session=lambda session: None,
            import_services_factory=lambda: Version2ImportWorkerServices(
                _UnusedLibrary(), None, lambda: None
            ),
            event_sink=event_sink,
            next_delegate=lambda action_id, payload: None,
            current_focus_provider=lambda: "pgn-tree",
            post_to_ui=post_to_ui,
        )

    def test_open_and_save_contain_session_provider_base_exception(self) -> None:
        class SessionAbort(BaseException):
            pass

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "session-provider-abort.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            events = []
            delegate = Version2WindowsFileActionDelegate(
                dialogs=_Dialogs(source),
                get_pgn_session=lambda: (_ for _ in ()).throw(
                    SessionAbort("session provider aborted")
                ),
                set_pgn_session=lambda session: None,
                import_services_factory=lambda: Version2ImportWorkerServices(
                    _UnusedLibrary(), None, lambda: None
                ),
                event_sink=events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "pgn-tree",
            )

            opened = delegate("pgn.open", {})
            saved = delegate("pgn.save", {})

            for event, action in ((opened, "pgn.open"), (saved, "pgn.save")):
                self.assertEqual(event.kind, FileWorkflowEventKind.FAILED)
                self.assertEqual(event.action_id, action)
                self.assertEqual(event.error_code, "pgn_session_unavailable")
                self.assertEqual(event.focus_target, "pgn-tree")
            self.assertFalse(delegate.pgn_open_running)
            self.assertFalse(delegate.pgn_save_running)

    def test_save_as_contains_post_dialog_session_provider_base_exception(self) -> None:
        class SessionAbort(BaseException):
            pass

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "save-as-source.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            destination = Path(tmp) / "save-as-destination.pgn"
            session = PgnDocumentSession.open(source)
            calls = 0

            def provider():
                nonlocal calls
                calls += 1
                if calls == 1:
                    return session
                raise SessionAbort("post-dialog session provider aborted")

            class SaveAsDialogs(_Dialogs):
                def save_pgn_as(self, suggested_filename: str = "game.pgn"):
                    return destination

            events = []
            delegate = Version2WindowsFileActionDelegate(
                dialogs=SaveAsDialogs(source),
                get_pgn_session=provider,
                set_pgn_session=lambda value: None,
                import_services_factory=lambda: Version2ImportWorkerServices(
                    _UnusedLibrary(), None, lambda: None
                ),
                event_sink=events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "pgn-tree",
                post_to_ui=lambda callback: self.fail("worker must not start"),
            )

            result = delegate("pgn.save_as", {})

            self.assertEqual(calls, 2)
            self.assertEqual(result.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(result.error_code, "pgn_session_unavailable")
            self.assertEqual(result.focus_target, "pgn-tree")
            self.assertFalse(destination.exists())
            self.assertFalse(delegate.pgn_save_running)

    def test_native_file_dialog_base_exceptions_are_sanitized(self) -> None:
        class DialogAbort(BaseException):
            pass

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "dialog-abort.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            session = PgnDocumentSession.open(source)

            class AbortDialogs(_Dialogs):
                def open_pgn(self):
                    raise DialogAbort("open dialog aborted")

                def save_pgn_as(self, suggested_filename: str = "game.pgn"):
                    raise DialogAbort("save dialog aborted")

                def select_library_import(self):
                    raise DialogAbort("import dialog aborted")

            events = []
            delegate = Version2WindowsFileActionDelegate(
                dialogs=AbortDialogs(source),
                get_pgn_session=lambda: session,
                set_pgn_session=lambda value: None,
                import_services_factory=lambda: Version2ImportWorkerServices(
                    _UnusedLibrary(), None, lambda: None
                ),
                event_sink=events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "pgn-tree",
            )

            opened = delegate("pgn.open", {})
            saved_as = delegate("pgn.save_as", {})
            imported = delegate("library.import", {})

            for event, action in (
                (opened, "pgn.open"),
                (saved_as, "pgn.save_as"),
                (imported, "library.import"),
            ):
                self.assertEqual(event.kind, FileWorkflowEventKind.FAILED)
                self.assertEqual(event.action_id, action)
                self.assertEqual(event.error_code, "file_dialog_failed")
                self.assertEqual(event.focus_target, "pgn-tree")
            self.assertFalse(delegate.pgn_open_running)
            self.assertFalse(delegate.pgn_save_running)
            self.assertFalse(delegate.import_running)

    def test_unsaved_confirmation_base_exception_is_sanitized(self) -> None:
        class ConfirmationAbort(BaseException):
            pass

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "confirmation-abort.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            session = PgnDocumentSession.open(source)
            session.edit_tag("Event", "Dirty before confirmation")

            class AbortConfirmationDialogs(_Dialogs):
                def confirm_discard_unsaved_pgn(self):
                    raise ConfirmationAbort("confirmation aborted")

                def open_pgn(self):
                    self.fail_if_called = True
                    raise AssertionError("open dialog must not run after failed confirmation")

            dialogs = AbortConfirmationDialogs(source)
            events = []
            delegate = Version2WindowsFileActionDelegate(
                dialogs=dialogs,
                get_pgn_session=lambda: session,
                set_pgn_session=lambda value: None,
                import_services_factory=lambda: Version2ImportWorkerServices(
                    _UnusedLibrary(), None, lambda: None
                ),
                event_sink=events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "pgn-tree",
            )

            result = delegate("pgn.open", {})

            self.assertEqual(result.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(result.action_id, "pgn.open")
            self.assertEqual(result.error_code, "unsaved_confirmation_failed")
            self.assertEqual(result.focus_target, "pgn-tree")
            self.assertFalse(delegate.pgn_open_running)

    def test_file_workflow_event_rejects_derived_root_before_field_hooks(self) -> None:
        touched = []

        class ActiveEvent(FileWorkflowEvent):
            def __getattribute__(self, name):
                if name in {"kind", "action_id", "focus_target", "error_code"}:
                    touched.append(name)
                    raise AssertionError("derived event field hook executed")
                return super().__getattribute__(name)

        with self.assertRaisesRegex(TypeError, "exact passive DTO"):
            ActiveEvent(
                FileWorkflowEventKind.FAILED,
                "pgn.open",
                focus_target="pgn-tree",
                error_code="pgn_open_failed",
            )

        self.assertEqual(touched, [])

    def test_focus_provider_base_exception_degrades_without_blocking_open(self) -> None:
        class FocusAbort(BaseException):
            pass

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "focus-abort.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            events = []
            delegate = Version2WindowsFileActionDelegate(
                dialogs=_Dialogs(source),
                get_pgn_session=lambda: None,
                set_pgn_session=lambda session: None,
                import_services_factory=lambda: Version2ImportWorkerServices(
                    _UnusedLibrary(), None, lambda: None
                ),
                event_sink=events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: (_ for _ in ()).throw(
                    FocusAbort("focus provider aborted")
                ),
            )

            result = delegate("pgn.open", {})

            self.assertEqual(result.kind, FileWorkflowEventKind.PGN_OPENED)
            self.assertEqual(result.focus_target, "pgn-game-list")
            self.assertEqual(events[-1], result)
            self.assertFalse(delegate.pgn_open_running)

    def test_file_action_rejects_active_action_id_before_hash_or_equality(self) -> None:
        touched = []

        class ActiveActionId(str):
            def __hash__(self):
                touched.append("hash")
                raise AssertionError("active action-id hash executed")

            def __eq__(self, other):
                touched.append("eq")
                raise AssertionError("active action-id equality executed")

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "passive-action.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            delegate = self._delegate(source, event_sink=lambda _event: None)

            with self.assertRaisesRegex(TypeError, "file action id must be exact text"):
                delegate(ActiveActionId("pgn.open"), {})

            self.assertEqual(touched, [])

    def test_file_action_rejects_active_owned_payload_before_truthiness(self) -> None:
        touched = []

        class ActivePayload(dict):
            def __bool__(self):
                touched.append("bool")
                raise AssertionError("active payload truthiness executed")

            def __len__(self):
                touched.append("len")
                raise AssertionError("active payload length executed")

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "passive-payload.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            delegate = self._delegate(source, event_sink=lambda _event: None)

            with self.assertRaisesRegex(TypeError, "file action payload must be an exact object"):
                delegate("pgn.open", ActivePayload())

            self.assertEqual(touched, [])

    def test_file_action_preserves_unknown_exact_string_fallback_without_payload_probe(self) -> None:
        forwarded = []
        marker = object()

        class OpaquePayload(dict):
            def __bool__(self):
                raise AssertionError("unknown-action payload must not be probed")

            def __len__(self):
                raise AssertionError("unknown-action payload must not be probed")

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "fallback.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            delegate = Version2WindowsFileActionDelegate(
                dialogs=_Dialogs(source),
                get_pgn_session=lambda: None,
                set_pgn_session=lambda session: None,
                import_services_factory=lambda: Version2ImportWorkerServices(
                    _UnusedLibrary(), None, lambda: None
                ),
                event_sink=lambda _event: None,
                next_delegate=lambda action_id, payload: (
                    forwarded.append((action_id, payload)),
                    marker,
                )[1],
                current_focus_provider=lambda: "pgn-tree",
            )
            payload = OpaquePayload({"opaque": object()})

            result = delegate("screen.home", payload)

            self.assertIs(result, marker)
            self.assertEqual(len(forwarded), 1)
            self.assertEqual(forwarded[0][0], "screen.home")
            self.assertIs(forwarded[0][1], payload)

    def test_import_started_sink_base_exception_does_not_strand_reserved_worker(self) -> None:
        class SinkAbort(BaseException):
            pass

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "import-sink-abort.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            events = []

            def sink(event):
                events.append(event)
                if event.kind is FileWorkflowEventKind.IMPORT_STARTED:
                    raise SinkAbort("presentation sink aborted")

            delegate = self._delegate(source, event_sink=sink)
            started = delegate("library.import", {})

            self.assertEqual(started.kind, FileWorkflowEventKind.IMPORT_STARTED)
            self.assertTrue(delegate.wait_for_import(2.0))
            self.assertFalse(delegate.import_running)
            self.assertIn(FileWorkflowEventKind.FAILED, [event.kind for event in events])

            reopened = delegate("pgn.open", {})
            self.assertEqual(reopened.kind, FileWorkflowEventKind.PGN_OPENED)
            self.assertFalse(delegate.pgn_open_running)

    def test_pgn_open_owner_terminal_sink_base_exception_is_contained(self) -> None:
        class SinkAbort(BaseException):
            pass

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "owner-terminal-sink.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            posted = []
            owner_events = []
            delegate = Version2WindowsFileActionDelegate(
                dialogs=_Dialogs(source),
                get_pgn_session=lambda: None,
                set_pgn_session=lambda session: None,
                import_services_factory=lambda: Version2ImportWorkerServices(
                    _UnusedLibrary(), None, lambda: None
                ),
                event_sink=lambda _event: None,
                owner_async_event_sink=lambda event: (
                    owner_events.append(event),
                    (_ for _ in ()).throw(SinkAbort("owner terminal sink aborted")),
                )[1],
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "pgn-tree",
                post_to_ui=posted.append,
            )

            started = delegate("pgn.open", {})
            self.assertEqual(started.kind, FileWorkflowEventKind.PGN_OPEN_STARTED)
            self.assertTrue(delegate.wait_for_pgn_open(2.0))
            self.assertEqual(len(posted), 1)

            posted.pop()()

            self.assertFalse(delegate.pgn_open_running)
            self.assertEqual(len(owner_events), 1)
            self.assertEqual(owner_events[0].kind, FileWorkflowEventKind.PGN_OPENED)

    def test_import_started_reentrant_shutdown_does_not_start_reserved_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "import-shutdown.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            events = []
            shutdown_results = []
            holder = {}

            def sink(event):
                events.append(event)
                if event.kind is FileWorkflowEventKind.IMPORT_STARTED:
                    shutdown_results.append(holder["delegate"].shutdown(0.0))

            delegate = self._delegate(source, event_sink=sink, post_to_ui=lambda cb: None)
            holder["delegate"] = delegate

            with mock.patch.object(threading.Thread, "start", autospec=True) as start:
                result = delegate("library.import", {})

            self.assertEqual(shutdown_results, [False])
            self.assertEqual(start.call_count, 0)
            self.assertEqual(result.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(result.error_code, "file_workflow_closed")
            self.assertEqual(
                [event.kind for event in events],
                [FileWorkflowEventKind.IMPORT_STARTED, FileWorkflowEventKind.FAILED],
            )
            self.assertFalse(delegate.import_running)

    def test_import_cleanup_base_exception_releases_shared_worker_slot(self) -> None:
        class CleanupAbort(BaseException):
            pass

        class SuccessfulLibrary:
            def import_games(self, *args, **kwargs):
                return LibraryImportResult(
                    attempt_id=1,
                    source_id=1,
                    game_count=1,
                    warning_count=0,
                    first_game_id=1,
                    last_game_id=1,
                )

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "import-cleanup-abort.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            events = []
            cleanup_calls = []

            def cleanup() -> None:
                cleanup_calls.append("close")
                raise CleanupAbort("secondary cleanup failure")

            delegate = Version2WindowsFileActionDelegate(
                dialogs=_Dialogs(source),
                get_pgn_session=lambda: None,
                set_pgn_session=lambda session: None,
                import_services_factory=lambda: Version2ImportWorkerServices(
                    SuccessfulLibrary(), None, cleanup
                ),
                event_sink=events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "pgn-tree",
                post_to_ui=None,
            )

            started = delegate("library.import", {})
            self.assertEqual(started.kind, FileWorkflowEventKind.IMPORT_STARTED)
            self.assertTrue(delegate.wait_for_import(2.0))
            self.assertEqual(cleanup_calls, ["close"])
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.IMPORT_COMPLETED)
            self.assertFalse(delegate.import_running)

            reopened = delegate("pgn.open", {})
            self.assertEqual(reopened.kind, FileWorkflowEventKind.PGN_OPENED)
            self.assertFalse(delegate.pgn_open_running)

    def test_import_worker_base_exception_publishes_failure_and_releases_slot(self) -> None:
        class WorkerAbort(BaseException):
            pass

        class AbortingLibrary:
            def import_games(self, *args, **kwargs):
                raise WorkerAbort("provider abort")

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "worker-abort.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            events = []
            delegate = Version2WindowsFileActionDelegate(
                dialogs=_Dialogs(source),
                get_pgn_session=lambda: None,
                set_pgn_session=lambda session: None,
                import_services_factory=lambda: Version2ImportWorkerServices(
                    AbortingLibrary(), None, lambda: None
                ),
                event_sink=events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "pgn-tree",
            )

            delegate("library.import", {})
            self.assertTrue(delegate.wait_for_import(2.0))
            self.assertFalse(delegate.import_running)
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(events[-1].error_code, "library_import_failed")

    def test_import_rejects_derived_worker_services_before_field_or_cleanup_hooks(self) -> None:
        touched = []

        class HostileServices(Version2ImportWorkerServices):
            def __getattribute__(self, name):
                if name in {"library", "close"}:
                    touched.append(name)
                    raise AssertionError("rejected service hook executed")
                return super().__getattribute__(name)

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "hostile-services.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            hostile = HostileServices.__new__(HostileServices)
            object.__setattr__(hostile, "library", _UnusedLibrary())
            object.__setattr__(hostile, "chessbase", None)
            object.__setattr__(hostile, "close", lambda: None)
            events = []
            delegate = Version2WindowsFileActionDelegate(
                dialogs=_Dialogs(source),
                get_pgn_session=lambda: None,
                set_pgn_session=lambda session: None,
                import_services_factory=lambda: hostile,
                event_sink=events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "pgn-tree",
            )

            started = delegate("library.import", {})
            self.assertEqual(started.kind, FileWorkflowEventKind.IMPORT_STARTED)
            self.assertTrue(delegate.wait_for_import(2.0))
            self.assertEqual(touched, [])
            self.assertFalse(delegate.import_running)
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(events[-1].error_code, "library_import_failed")

    def test_import_rejects_derived_progress_before_field_hooks(self) -> None:
        touched = []

        class HostileProgress(LibraryImportProgress):
            def __getattribute__(self, name):
                if name in {"attempt_id", "processed_games", "total_games"}:
                    touched.append(name)
                    raise AssertionError("rejected progress hook executed")
                return super().__getattribute__(name)

        hostile = HostileProgress.__new__(HostileProgress)
        object.__setattr__(hostile, "attempt_id", 1)
        object.__setattr__(hostile, "processed_games", 1)
        object.__setattr__(hostile, "total_games", 1)

        class ProgressLibrary:
            def import_games(self, *args, **kwargs):
                kwargs["progress_callback"](hostile)
                raise AssertionError("progress rejection must stop import")

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "hostile-progress.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            events = []
            delegate = Version2WindowsFileActionDelegate(
                dialogs=_Dialogs(source),
                get_pgn_session=lambda: None,
                set_pgn_session=lambda session: None,
                import_services_factory=lambda: Version2ImportWorkerServices(
                    ProgressLibrary(), None, lambda: None
                ),
                event_sink=events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "pgn-tree",
            )

            delegate("library.import", {})
            self.assertTrue(delegate.wait_for_import(2.0))
            self.assertEqual(touched, [])
            self.assertFalse(delegate.import_running)
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(events[-1].error_code, "library_import_failed")

    def test_import_rejects_derived_result_before_field_hooks(self) -> None:
        touched = []

        class HostileResult(LibraryImportResult):
            def __getattribute__(self, name):
                if name in {"game_count", "warning_count"}:
                    touched.append(name)
                    raise AssertionError("rejected result hook executed")
                return super().__getattribute__(name)

        hostile = HostileResult.__new__(HostileResult)
        for name, value in (
            ("attempt_id", 1),
            ("source_id", 1),
            ("game_count", 1),
            ("warning_count", 0),
            ("first_game_id", 1),
            ("last_game_id", 1),
            ("reused", False),
        ):
            object.__setattr__(hostile, name, value)

        class ResultLibrary:
            def import_games(self, *args, **kwargs):
                return hostile

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "hostile-result.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            events = []
            delegate = Version2WindowsFileActionDelegate(
                dialogs=_Dialogs(source),
                get_pgn_session=lambda: None,
                set_pgn_session=lambda session: None,
                import_services_factory=lambda: Version2ImportWorkerServices(
                    ResultLibrary(), None, lambda: None
                ),
                event_sink=events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "pgn-tree",
            )

            delegate("library.import", {})
            self.assertTrue(delegate.wait_for_import(2.0))
            self.assertEqual(touched, [])
            self.assertFalse(delegate.import_running)
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(events[-1].error_code, "library_import_failed")

    def test_pgn_open_preparation_base_exception_reaches_owner_terminal(self) -> None:
        class PreparationAbort(BaseException):
            pass

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "open-preparation-abort.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            events = []
            posted = []
            delegate = self._delegate(
                source,
                event_sink=events.append,
                post_to_ui=posted.append,
            )

            with mock.patch(
                "acs.version2_windows_file_workflows.PgnDocumentSession.open",
                side_effect=PreparationAbort("preparation abort"),
            ):
                started = delegate("pgn.open", {})
                self.assertEqual(started.kind, FileWorkflowEventKind.PGN_OPEN_STARTED)
                self.assertTrue(delegate.wait_for_pgn_open(2.0))

            self.assertEqual(len(posted), 1)
            self.assertTrue(delegate.pgn_open_running)
            posted.pop()()
            self.assertFalse(delegate.pgn_open_running)
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(events[-1].error_code, "pgn_open_failed")

    def test_pgn_open_ui_post_base_exception_releases_shared_worker_slot(self) -> None:
        class PosterAbort(BaseException):
            pass

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "open-poster-abort.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            events = []

            def aborting_post(callback):
                raise PosterAbort("owner post abort")

            delegate = self._delegate(
                source,
                event_sink=events.append,
                post_to_ui=aborting_post,
            )
            started = delegate("pgn.open", {})
            self.assertEqual(started.kind, FileWorkflowEventKind.PGN_OPEN_STARTED)
            self.assertTrue(delegate.wait_for_pgn_open(2.0))
            self.assertFalse(delegate.pgn_open_running)
            self.assertEqual(events[-1].kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(events[-1].error_code, "pgn_open_ui_post_failed")

    def test_pgn_open_started_reentrant_shutdown_does_not_start_reserved_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "open-shutdown.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            events = []
            shutdown_results = []
            posted = []
            holder = {}

            def sink(event):
                events.append(event)
                if event.kind is FileWorkflowEventKind.PGN_OPEN_STARTED:
                    shutdown_results.append(holder["delegate"].shutdown(0.0))

            delegate = self._delegate(source, event_sink=sink, post_to_ui=posted.append)
            holder["delegate"] = delegate

            with mock.patch.object(threading.Thread, "start", autospec=True) as start:
                result = delegate("pgn.open", {})

            self.assertEqual(shutdown_results, [False])
            self.assertEqual(start.call_count, 0)
            self.assertEqual(result.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(result.error_code, "file_workflow_closed")
            self.assertEqual(posted, [])
            self.assertEqual(
                [event.kind for event in events],
                [FileWorkflowEventKind.PGN_OPEN_STARTED, FileWorkflowEventKind.FAILED],
            )
            self.assertFalse(delegate.pgn_open_running)

    def test_pgn_ui_post_failure_after_shutdown_does_not_publish_late_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "late-post-failure.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            events = []
            post_entered = threading.Event()
            release_post = threading.Event()

            def failing_post(callback):
                post_entered.set()
                if not release_post.wait(2.0):
                    raise AssertionError("test did not release owner post")
                raise RuntimeError("owner window already closing")

            delegate = self._delegate(source, event_sink=events.append, post_to_ui=failing_post)
            started = delegate("pgn.open", {})
            self.assertEqual(started.kind, FileWorkflowEventKind.PGN_OPEN_STARTED)
            self.assertTrue(post_entered.wait(2.0))

            self.assertFalse(delegate.shutdown(0.0))
            event_count_at_shutdown = len(events)
            release_post.set()
            self.assertTrue(delegate.shutdown(2.0))

            self.assertEqual(len(events), event_count_at_shutdown)
            self.assertEqual(events, [started])
            self.assertFalse(delegate.pgn_open_running)


if __name__ == "__main__":
    unittest.main()
