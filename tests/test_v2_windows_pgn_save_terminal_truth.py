from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from acs.pgn_document import PgnDocumentSession
from acs.pgn_service import (
    PgnConcurrentWriteError,
    PgnPublicationUnverifiedError,
)
from acs.version2_windows_file_workflows import (
    FileWorkflowEvent,
    FileWorkflowEventKind,
    Version2WindowsFileActionDelegate,
)


_PGN = """[Event "Failure truth"]
[Site "?"]
[Date "2026.10.05"]
[Round "1"]
[White "White"]
[Black "Black"]
[Result "*"]

1. e4 e5 *
"""


class _Dialogs:
    def open_pgn(self):
        return None

    def save_pgn_as(self, suggested_filename="game.pgn"):
        return None

    def select_library_import(self):
        return None


class _SaveAsDialogs(_Dialogs):
    def __init__(self, destination: Path) -> None:
        self.destination = destination

    def save_pgn_as(self, suggested_filename="game.pgn"):
        return self.destination


class _OwnerPoster:
    def __init__(self) -> None:
        self.owner = threading.get_ident()
        self.callbacks: list[object] = []
        self._lock = threading.Lock()

    def __call__(self, callback) -> None:
        with self._lock:
            self.callbacks.append(callback)

    def drain(self) -> None:
        if threading.get_ident() != self.owner:
            raise AssertionError("owner callback drained off owner thread")
        while True:
            with self._lock:
                if not self.callbacks:
                    return
                callback = self.callbacks.pop(0)
            callback()


class Version2WindowsPgnSaveTerminalTruthTests(unittest.TestCase):
    def test_direct_save_as_reports_post_publication_uncertainty_without_rebinding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "direct-published-unverified.pgn"
            session = PgnDocumentSession.from_text(_PGN)
            original_source = session.source
            sync_events: list[FileWorkflowEvent] = []
            controller = Version2WindowsFileActionDelegate(
                dialogs=_SaveAsDialogs(target),
                get_pgn_session=lambda: session,
                set_pgn_session=lambda value: None,
                import_services_factory=lambda: None,
                event_sink=sync_events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "pgn-game-list",
            )

            with mock.patch(
                "acs.pgn_service.fingerprint",
                side_effect=OSError("private post-publication verification failure"),
            ):
                terminal = controller("pgn.save_as", {})

            self.assertEqual(terminal.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(
                terminal.error_code,
                "pgn_save_publication_unverified",
            )
            self.assertTrue(target.exists())
            self.assertIn('[Event "Failure truth"]', target.read_text(encoding="utf-8"))
            self.assertEqual(session.source, original_source)
            self.assertTrue(session.dirty)
            self.assertNotIn("private post-publication", repr(terminal))
            self.assertEqual(sync_events[-1], terminal)

    def test_post_publication_verification_failure_is_not_generic_save_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "post-publication-unverified.pgn"
            source.write_text(_PGN, encoding="utf-8")
            session = PgnDocumentSession.open(source)
            old_source = session.source
            session.edit_tag("Event", "Potentially published generation")
            poster = _OwnerPoster()
            sync_events: list[FileWorkflowEvent] = []
            async_events: list[FileWorkflowEvent] = []
            controller = Version2WindowsFileActionDelegate(
                dialogs=_Dialogs(),
                get_pgn_session=lambda: session,
                set_pgn_session=lambda value: None,
                import_services_factory=lambda: None,
                event_sink=sync_events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "pgn-game-list",
                post_to_ui=poster,
                owner_async_event_sink=async_events.append,
            )

            with mock.patch(
                "acs.version2_windows_file_workflows.publish_pgn_save_snapshot",
                side_effect=PgnPublicationUnverifiedError(
                    "private post-publication verification detail"
                ),
            ):
                started = controller("pgn.save", {})
                self.assertEqual(started.kind, FileWorkflowEventKind.PGN_SAVE_STARTED)
                self.assertTrue(controller.wait_for_pgn_save(5.0))

            poster.drain()

            terminal = async_events[-1]
            self.assertEqual(terminal.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(
                terminal.error_code,
                "pgn_save_publication_unverified",
            )
            self.assertEqual(session.source, old_source)
            self.assertTrue(session.dirty)
            self.assertNotIn("private post-publication", repr(terminal))
            self.assertFalse(controller.pgn_save_running)

    def test_late_cancel_resolves_completed_worker_failure_without_false_cancelling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "failure.pgn"
            source.write_text(_PGN, encoding="utf-8")
            session = PgnDocumentSession.open(source)
            session.edit_tag("Event", "Still dirty after failure")
            poster = _OwnerPoster()
            sync_events: list[FileWorkflowEvent] = []
            async_events: list[FileWorkflowEvent] = []
            controller = Version2WindowsFileActionDelegate(
                dialogs=_Dialogs(),
                get_pgn_session=lambda: session,
                set_pgn_session=lambda value: None,
                import_services_factory=lambda: None,
                event_sink=sync_events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "pgn-game-list",
                post_to_ui=poster,
                owner_async_event_sink=async_events.append,
            )

            with mock.patch(
                "acs.version2_windows_file_workflows.publish_pgn_save_snapshot",
                side_effect=RuntimeError("private writer failure"),
            ):
                started = controller("pgn.save", {})
                self.assertEqual(started.kind, FileWorkflowEventKind.PGN_SAVE_STARTED)
                self.assertTrue(controller.wait_for_pgn_save(5.0))

            # The worker has already classified a real publication failure.
            # A later Cancel click cannot affect publication and therefore must
            # resolve that exact terminal immediately instead of announcing a
            # false new cancellation request to NVDA/browser status surfaces.
            terminal = controller("pgn.cancel_save", {})
            self.assertEqual(terminal.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(terminal.error_code, "pgn_save_failed")
            self.assertEqual(async_events, [terminal])
            self.assertEqual(sync_events, [started])
            self.assertTrue(session.dirty)
            self.assertNotIn("private writer failure", repr(terminal))
            self.assertFalse(controller.pgn_save_running)

            # The worker's already-queued owner callback is now stale and must
            # not publish the same terminal a second time when the UI pump drains.
            self.assertTrue(poster.callbacks)
            event_count = len(async_events)
            poster.drain()
            self.assertEqual(len(async_events), event_count)

    def test_late_cancel_preserves_completed_conflict_classification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "conflict.pgn"
            source.write_text(_PGN, encoding="utf-8")
            original = source.read_bytes()
            session = PgnDocumentSession.open(source)
            old_source = session.source
            session.edit_tag("Event", "Must remain dirty after conflict")
            poster = _OwnerPoster()
            sync_events: list[FileWorkflowEvent] = []
            async_events: list[FileWorkflowEvent] = []
            controller = Version2WindowsFileActionDelegate(
                dialogs=_Dialogs(),
                get_pgn_session=lambda: session,
                set_pgn_session=lambda value: None,
                import_services_factory=lambda: None,
                event_sink=sync_events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "pgn-game-list",
                post_to_ui=poster,
                owner_async_event_sink=async_events.append,
            )

            with mock.patch(
                "acs.version2_windows_file_workflows.publish_pgn_save_snapshot",
                side_effect=PgnConcurrentWriteError("private conflict detail"),
            ):
                started = controller("pgn.save", {})
                self.assertEqual(started.kind, FileWorkflowEventKind.PGN_SAVE_STARTED)
                self.assertTrue(controller.wait_for_pgn_save(5.0))

            # A no-clobber conflict has already been classified. Late Cancel must
            # preserve that actionable safety result instead of rewriting it to
            # cancellation or a generic failure in the accessible status path.
            terminal = controller("pgn.cancel_save", {})
            self.assertEqual(terminal.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(terminal.error_code, "pgn_save_conflict")
            self.assertEqual(async_events, [terminal])
            self.assertEqual(sync_events, [started])
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(session.source, old_source)
            self.assertTrue(session.dirty)
            self.assertNotIn("private conflict detail", repr(terminal))
            self.assertFalse(controller.pgn_save_running)

            # The worker's queued owner callback becomes stale once the exact
            # conflict terminal has been synchronously resolved on the UI thread.
            self.assertTrue(poster.callbacks)
            event_count = len(async_events)
            poster.drain()
            self.assertEqual(len(async_events), event_count)

    def test_late_cancel_resolves_completed_durable_save_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "success.pgn"
            source.write_text(_PGN, encoding="utf-8")
            session = PgnDocumentSession.open(source)
            session.edit_tag("Event", "Durably saved before late cancel")
            poster = _OwnerPoster()
            sync_events: list[FileWorkflowEvent] = []
            async_events: list[FileWorkflowEvent] = []
            controller = Version2WindowsFileActionDelegate(
                dialogs=_Dialogs(),
                get_pgn_session=lambda: session,
                set_pgn_session=lambda value: None,
                import_services_factory=lambda: None,
                event_sink=sync_events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "pgn-game-list",
                post_to_ui=poster,
                owner_async_event_sink=async_events.append,
            )

            started = controller("pgn.save", {})
            self.assertEqual(started.kind, FileWorkflowEventKind.PGN_SAVE_STARTED)
            self.assertTrue(controller.wait_for_pgn_save(5.0))

            # Publication is already durable, but the owner commit is queued.
            # Cancel can no longer affect disk bytes, so it must resolve the
            # already-fixed success terminal without first announcing CANCELLING.
            self.assertIn(
                '[Event "Durably saved before late cancel"]',
                source.read_text(encoding="utf-8"),
            )
            self.assertTrue(session.dirty)
            terminal = controller("pgn.cancel_save", {})
            self.assertEqual(terminal.kind, FileWorkflowEventKind.PGN_SAVED)
            self.assertEqual(terminal.action_id, "pgn.save")
            self.assertEqual(terminal.focus_target, "pgn-game-list")
            self.assertEqual(async_events, [terminal])
            self.assertEqual(sync_events, [started])
            self.assertFalse(session.dirty)
            self.assertFalse(controller.pgn_save_running)

            # The callback queued by the worker is stale after immediate owner
            # resolution and cannot publish a duplicate terminal later.
            self.assertTrue(poster.callbacks)
            event_count = len(async_events)
            poster.drain()
            self.assertEqual(len(async_events), event_count)

    def test_durable_save_owner_session_access_failure_reports_commit_failure_truth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "owner-session-unavailable.pgn"
            source.write_text(_PGN, encoding="utf-8")
            session = PgnDocumentSession.open(source)
            old_source = session.source
            session.edit_tag("Event", "Durable bytes despite owner access failure")
            poster = _OwnerPoster()
            sync_events: list[FileWorkflowEvent] = []
            async_events: list[FileWorkflowEvent] = []
            get_calls = 0

            def get_session():
                nonlocal get_calls
                get_calls += 1
                if get_calls == 1:
                    return session
                raise RuntimeError("private owner session access failure")

            controller = Version2WindowsFileActionDelegate(
                dialogs=_Dialogs(),
                get_pgn_session=get_session,
                set_pgn_session=lambda value: None,
                import_services_factory=lambda: None,
                event_sink=sync_events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "pgn-game-list",
                post_to_ui=poster,
                owner_async_event_sink=async_events.append,
            )

            started = controller("pgn.save", {})
            self.assertEqual(started.kind, FileWorkflowEventKind.PGN_SAVE_STARTED)
            self.assertTrue(controller.wait_for_pgn_save(5.0))
            self.assertIn(
                '[Event "Durable bytes despite owner access failure"]',
                source.read_text(encoding="utf-8"),
            )
            self.assertTrue(session.dirty)
            self.assertEqual(session.source, old_source)

            poster.drain()

            self.assertEqual(len(async_events), 1)
            terminal = async_events[0]
            self.assertEqual(terminal.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(terminal.error_code, "pgn_save_commit_failed")
            self.assertEqual(terminal.focus_target, "pgn-game-list")
            self.assertEqual(sync_events, [started])
            self.assertTrue(session.dirty)
            self.assertEqual(session.source, old_source)
            self.assertFalse(controller.pgn_save_running)
            self.assertNotIn("private owner session access failure", repr(terminal))

    def test_durable_save_rejects_active_live_source_without_executing_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "active-live-source-after-publish.pgn"
            source.write_text(_PGN, encoding="utf-8")
            session = PgnDocumentSession.open(source)
            session.edit_tag("Event", "Durable bytes before live provenance tamper")
            poster = _OwnerPoster()
            sync_events: list[FileWorkflowEvent] = []
            async_events: list[FileWorkflowEvent] = []
            controller = Version2WindowsFileActionDelegate(
                dialogs=_Dialogs(),
                get_pgn_session=lambda: session,
                set_pgn_session=lambda value: None,
                import_services_factory=lambda: None,
                event_sink=sync_events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "pgn-game-list",
                post_to_ui=poster,
                owner_async_event_sink=async_events.append,
            )

            started = controller("pgn.save", {})
            self.assertEqual(started.kind, FileWorkflowEventKind.PGN_SAVE_STARTED)
            self.assertTrue(controller.wait_for_pgn_save(5.0))
            self.assertIn(
                '[Event "Durable bytes before live provenance tamper"]',
                source.read_text(encoding="utf-8"),
            )
            live_source = session.source
            assert live_source is not None
            touched: list[str] = []

            class ActiveText(str):
                def __eq__(self, other):
                    touched.append("eq")
                    raise AssertionError("active live source equality executed")

                def __ne__(self, other):
                    touched.append("ne")
                    raise AssertionError("active live source inequality executed")

            object.__setattr__(
                live_source,
                "sha256",
                ActiveText(live_source.sha256),
            )

            poster.drain()

            self.assertEqual([], touched)
            self.assertEqual(len(async_events), 1)
            terminal = async_events[0]
            self.assertEqual(terminal.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(terminal.error_code, "pgn_save_commit_failed")
            self.assertEqual(terminal.focus_target, "pgn-game-list")
            self.assertEqual(sync_events, [started])
            self.assertEqual(Path(session.source.path), source)
            self.assertTrue(session.dirty)
            self.assertFalse(controller.pgn_save_running)

    def test_late_cancel_resolves_completed_durable_save_as_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "save-as-source.pgn"
            destination = Path(directory) / "save-as-destination.pgn"
            source.write_text(_PGN, encoding="utf-8")
            session = PgnDocumentSession.open(source)
            session.edit_tag("Event", "Durable Save As before late cancel")
            dialogs = _Dialogs()
            dialogs.save_pgn_as = lambda suggested_filename="game.pgn": destination
            poster = _OwnerPoster()
            sync_events: list[FileWorkflowEvent] = []
            async_events: list[FileWorkflowEvent] = []
            controller = Version2WindowsFileActionDelegate(
                dialogs=dialogs,
                get_pgn_session=lambda: session,
                set_pgn_session=lambda value: None,
                import_services_factory=lambda: None,
                event_sink=sync_events.append,
                next_delegate=lambda action_id, payload: None,
                current_focus_provider=lambda: "pgn-game-list",
                post_to_ui=poster,
                owner_async_event_sink=async_events.append,
            )

            started = controller("pgn.save_as", {})
            self.assertEqual(started.kind, FileWorkflowEventKind.PGN_SAVE_STARTED)
            self.assertEqual(started.action_id, "pgn.save_as")
            self.assertTrue(controller.wait_for_pgn_save(5.0))

            # Save As has already published the detached bytes, while the owner
            # commit that rebinds source provenance is intentionally still queued.
            self.assertIn(
                '[Event "Durable Save As before late cancel"]',
                destination.read_text(encoding="utf-8"),
            )
            self.assertEqual(Path(session.source.path), source)
            self.assertTrue(session.dirty)

            terminal = controller("pgn.cancel_save", {})
            self.assertEqual(terminal.kind, FileWorkflowEventKind.PGN_SAVED_AS)
            self.assertEqual(terminal.action_id, "pgn.save_as")
            self.assertEqual(terminal.focus_target, "pgn-game-list")
            self.assertEqual(async_events, [terminal])
            self.assertEqual(sync_events, [started])
            self.assertEqual(Path(session.source.path), destination)
            self.assertFalse(session.dirty)
            self.assertFalse(controller.pgn_save_running)

            # The worker callback queued before the late Cancel is stale after
            # immediate owner resolution, so success cannot be announced twice.
            self.assertTrue(poster.callbacks)
            event_count = len(async_events)
            poster.drain()
            self.assertEqual(len(async_events), event_count)


if __name__ == "__main__":
    unittest.main()
