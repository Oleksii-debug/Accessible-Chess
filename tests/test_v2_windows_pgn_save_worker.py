from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from acs.pgn_document import PgnDocumentSession
from acs.pgn_save_snapshot import PgnSaveCancelledError
from acs.version2_windows_file_workflows import (
    FileWorkflowEvent,
    FileWorkflowEventKind,
    Version2ImportWorkerServices,
    Version2WindowsFileActionDelegate,
)


PGN_TEXT = """[Event "Background save"]
[Site "?"]
[Date "2026.10.05"]
[Round "1"]
[White "White"]
[Black "Black"]
[Result "*"]

1. e4 e5 *
"""


class _Dialogs:
    def __init__(self) -> None:
        self.save_destination: Path | None = None
        self.save_calls = 0
        self.open_calls = 0
        self.import_calls = 0
        self.on_save_dialog = None

    def confirm_discard_unsaved_pgn(self) -> bool:
        return True

    def open_pgn(self) -> Path | None:
        self.open_calls += 1
        return None

    def save_pgn_as(self, suggested_filename: str = "game.pgn") -> Path | None:
        self.save_calls += 1
        callback = self.on_save_dialog
        if callback is not None:
            callback()
        return self.save_destination

    def select_library_import(self) -> Path | None:
        self.import_calls += 1
        return None


class _UnusedLibrary:
    def import_games(self, *args, **kwargs):
        raise AssertionError("unexpected Library import")


class _OwnerQueuePoster:
    def __init__(self) -> None:
        self.owner_thread_id = threading.get_ident()
        self.post_threads: list[int] = []
        self.callbacks: list[object] = []
        self._lock = threading.Lock()

    def __call__(self, callback) -> None:
        with self._lock:
            self.post_threads.append(threading.get_ident())
            self.callbacks.append(callback)

    def drain(self) -> None:
        if threading.get_ident() != self.owner_thread_id:
            raise AssertionError("owner queue drained off owner thread")
        while True:
            with self._lock:
                if not self.callbacks:
                    return
                callback = self.callbacks.pop(0)
            callback()


class Version2WindowsPgnSaveWorkerTests(unittest.TestCase):
    def _controller(self, session: PgnDocumentSession):
        dialogs = _Dialogs()
        poster = _OwnerQueuePoster()
        sync_events: list[FileWorkflowEvent] = []
        async_events: list[FileWorkflowEvent] = []
        box = {"session": session}
        publication_threads: list[int] = []

        def set_session(value: PgnDocumentSession) -> None:
            publication_threads.append(threading.get_ident())
            box["session"] = value

        controller = Version2WindowsFileActionDelegate(
            dialogs=dialogs,
            get_pgn_session=lambda: box["session"],
            set_pgn_session=set_session,
            import_services_factory=lambda: Version2ImportWorkerServices(
                _UnusedLibrary(), None, lambda: None
            ),
            event_sink=sync_events.append,
            next_delegate=lambda action_id, payload: None,
            current_focus_provider=lambda: "pgn-game-list",
            post_to_ui=poster,
            owner_async_event_sink=async_events.append,
        )
        return (
            controller,
            dialogs,
            poster,
            sync_events,
            async_events,
            box,
            publication_threads,
        )

    def test_save_publishes_off_owner_then_commits_on_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            session = PgnDocumentSession.open(source)
            old_source = session.source
            session.edit_tag("Event", "Worker snapshot")
            controller, _, poster, sync_events, async_events, _, _ = self._controller(
                session
            )
            owner = threading.get_ident()
            worker_threads: list[int] = []

            from acs import version2_windows_file_workflows as workflows

            real_publish = workflows.publish_pgn_save_snapshot

            def observed_publish(*args, **kwargs):
                worker_threads.append(threading.get_ident())
                return real_publish(*args, **kwargs)

            with mock.patch.object(
                workflows,
                "publish_pgn_save_snapshot",
                side_effect=observed_publish,
            ):
                started = controller("pgn.save", {})
                self.assertEqual(started.kind, FileWorkflowEventKind.PGN_SAVE_STARTED)
                self.assertTrue(controller.wait_for_pgn_save(5.0))

            self.assertIn("Worker snapshot", source.read_text(encoding="utf-8"))
            self.assertEqual(session.source, old_source)
            self.assertTrue(session.dirty)
            self.assertEqual(async_events, [])
            self.assertTrue(worker_threads)
            self.assertTrue(all(thread_id != owner for thread_id in worker_threads))
            self.assertTrue(all(thread_id != owner for thread_id in poster.post_threads))

            poster.drain()

            self.assertNotEqual(session.source, old_source)
            self.assertFalse(session.dirty)
            self.assertEqual(
                [event.kind for event in async_events],
                [FileWorkflowEventKind.PGN_SAVED],
            )
            self.assertEqual(sync_events, [started])

    def test_edit_during_save_stays_dirty_after_older_snapshot_commits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            session = PgnDocumentSession.open(source)
            session.edit_tag("Event", "Captured generation")
            controller, _, poster, _, async_events, _, _ = self._controller(session)
            entered = threading.Event()
            release = threading.Event()

            from acs import version2_windows_file_workflows as workflows

            real_publish = workflows.publish_pgn_save_snapshot

            def blocked_publish(*args, **kwargs):
                entered.set()
                if not release.wait(5.0):
                    raise AssertionError("save worker was not released")
                return real_publish(*args, **kwargs)

            with mock.patch.object(
                workflows,
                "publish_pgn_save_snapshot",
                side_effect=blocked_publish,
            ):
                controller("pgn.save", {})
                self.assertTrue(entered.wait(2.0))
                session.edit_tag("Event", "Newer in memory")
                release.set()
                self.assertTrue(controller.wait_for_pgn_save(5.0))
                poster.drain()

            file_text = source.read_text(encoding="utf-8")
            self.assertIn("Captured generation", file_text)
            self.assertNotIn("Newer in memory", file_text)
            self.assertIn("Newer in memory", session.copy_pgn())
            self.assertTrue(session.dirty)
            self.assertEqual(async_events[-1].kind, FileWorkflowEventKind.PGN_SAVED)

            second = controller("pgn.save", {})
            self.assertEqual(second.kind, FileWorkflowEventKind.PGN_SAVE_STARTED)
            self.assertTrue(controller.wait_for_pgn_save(5.0))
            poster.drain()

            self.assertIn("Newer in memory", source.read_text(encoding="utf-8"))
            self.assertFalse(session.dirty)
            self.assertEqual(
                [event.kind for event in async_events],
                [FileWorkflowEventKind.PGN_SAVED, FileWorkflowEventKind.PGN_SAVED],
            )

    def test_cancel_before_publication_preserves_source_and_dirty_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            original = source.read_bytes()
            session = PgnDocumentSession.open(source)
            session.edit_tag("Event", "Must not publish")
            controller, _, poster, sync_events, async_events, _, _ = self._controller(
                session
            )
            entered = threading.Event()

            def cancellable_publish(snapshot, *, cancel_check=None, **kwargs):
                entered.set()
                assert cancel_check is not None
                for _ in range(5000):
                    if cancel_check():
                        raise PgnSaveCancelledError("cancelled by test")
                    threading.Event().wait(0.001)
                raise AssertionError("cancel did not reach save worker")

            with mock.patch(
                "acs.version2_windows_file_workflows.publish_pgn_save_snapshot",
                side_effect=cancellable_publish,
            ):
                started = controller("pgn.save", {})
                self.assertTrue(entered.wait(2.0))
                cancelling = controller("pgn.cancel_save", {})
                self.assertEqual(
                    cancelling.kind,
                    FileWorkflowEventKind.PGN_SAVE_CANCELLING,
                )
                self.assertTrue(controller.wait_for_pgn_save(5.0))
                poster.drain()

            self.assertEqual(source.read_bytes(), original)
            self.assertTrue(session.dirty)
            self.assertEqual(async_events[-1].kind, FileWorkflowEventKind.PGN_SAVE_CANCELLED)
            self.assertEqual(sync_events, [started, cancelling])
            self.assertFalse(controller.pgn_save_running)

    def test_save_as_dialog_is_owner_owned_and_io_runs_on_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "saved-as.pgn"
            session = PgnDocumentSession.from_text(PGN_TEXT)
            session.edit_tag("Event", "Save As worker")
            controller, dialogs, poster, _, async_events, _, _ = self._controller(session)
            dialogs.save_destination = target
            owner = threading.get_ident()
            dialog_threads: list[int] = []
            publish_threads: list[int] = []
            real_dialog = dialogs.save_pgn_as

            def observed_dialog(name="game.pgn"):
                dialog_threads.append(threading.get_ident())
                return real_dialog(name)

            dialogs.save_pgn_as = observed_dialog

            from acs import version2_windows_file_workflows as workflows

            real_publish = workflows.publish_pgn_save_snapshot

            def observed_publish(*args, **kwargs):
                publish_threads.append(threading.get_ident())
                return real_publish(*args, **kwargs)

            with mock.patch.object(
                workflows,
                "publish_pgn_save_snapshot",
                side_effect=observed_publish,
            ):
                started = controller("pgn.save_as", {})
                self.assertEqual(started.kind, FileWorkflowEventKind.PGN_SAVE_STARTED)
                self.assertTrue(controller.wait_for_pgn_save(5.0))
                poster.drain()

            self.assertEqual(dialog_threads, [owner])
            self.assertTrue(publish_threads)
            self.assertTrue(all(thread_id != owner for thread_id in publish_threads))
            self.assertIn("Save As worker", target.read_text(encoding="utf-8"))
            self.assertEqual(Path(session.source.path), target)
            self.assertFalse(session.dirty)
            self.assertEqual(async_events[-1].kind, FileWorkflowEventKind.PGN_SAVED_AS)

    def test_existing_save_as_destination_hashing_runs_off_owner_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing.pgn"
            target.write_text(
                PGN_TEXT.replace("Background save", "Existing destination"),
                encoding="utf-8",
            )
            session = PgnDocumentSession.from_text(PGN_TEXT)
            session.edit_tag("Event", "Replacement generation")
            controller, dialogs, poster, _, async_events, _, _ = self._controller(session)
            dialogs.save_destination = target
            owner = threading.get_ident()
            hash_threads: list[int] = []

            from acs import version2_windows_file_workflows as workflows

            real_hash = workflows.expected_pgn_destination_sha256

            def observed_hash(*args, **kwargs):
                hash_threads.append(threading.get_ident())
                return real_hash(*args, **kwargs)

            with mock.patch.object(
                workflows,
                "expected_pgn_destination_sha256",
                side_effect=observed_hash,
            ):
                started = controller("pgn.save_as", {})
                self.assertEqual(started.kind, FileWorkflowEventKind.PGN_SAVE_STARTED)
                self.assertTrue(controller.wait_for_pgn_save(5.0))
                poster.drain()

            self.assertTrue(hash_threads)
            self.assertTrue(all(thread_id != owner for thread_id in hash_threads))
            self.assertIn("Replacement generation", target.read_text(encoding="utf-8"))
            self.assertFalse(session.dirty)
            self.assertEqual(async_events[-1].kind, FileWorkflowEventKind.PGN_SAVED_AS)

    def test_absent_save_as_target_created_after_fingerprint_is_not_clobbered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "created-by-other-writer.pgn"
            session = PgnDocumentSession.from_text(PGN_TEXT)
            session.edit_tag("Event", "Local generation")
            controller, dialogs, poster, _, async_events, _, _ = self._controller(session)
            dialogs.save_destination = target

            from acs import version2_windows_file_workflows as workflows

            real_hash = workflows.expected_pgn_destination_sha256

            def race_after_absence(*args, **kwargs):
                expected = real_hash(*args, **kwargs)
                self.assertIsNone(expected)
                target.write_text(
                    PGN_TEXT.replace("Background save", "External creator"),
                    encoding="utf-8",
                )
                return expected

            with mock.patch.object(
                workflows,
                "expected_pgn_destination_sha256",
                side_effect=race_after_absence,
            ):
                controller("pgn.save_as", {})
                self.assertTrue(controller.wait_for_pgn_save(5.0))
                poster.drain()

            self.assertIn("External creator", target.read_text(encoding="utf-8"))
            self.assertNotIn("Local generation", target.read_text(encoding="utf-8"))
            self.assertIsNone(session.source)
            self.assertTrue(session.dirty)
            self.assertEqual(async_events[-1].kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(async_events[-1].error_code, "pgn_save_conflict")

    def test_existing_save_as_target_replaced_after_fingerprint_is_not_clobbered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "replaced-by-other-writer.pgn"
            target.write_text(
                PGN_TEXT.replace("Background save", "Original destination"),
                encoding="utf-8",
            )
            session = PgnDocumentSession.from_text(PGN_TEXT)
            session.edit_tag("Event", "Local replacement")
            controller, dialogs, poster, _, async_events, _, _ = self._controller(session)
            dialogs.save_destination = target

            from acs import version2_windows_file_workflows as workflows

            real_hash = workflows.expected_pgn_destination_sha256

            def race_after_fingerprint(*args, **kwargs):
                expected = real_hash(*args, **kwargs)
                self.assertIsNotNone(expected)
                target.write_text(
                    PGN_TEXT.replace("Background save", "External replacement"),
                    encoding="utf-8",
                )
                return expected

            with mock.patch.object(
                workflows,
                "expected_pgn_destination_sha256",
                side_effect=race_after_fingerprint,
            ):
                controller("pgn.save_as", {})
                self.assertTrue(controller.wait_for_pgn_save(5.0))
                poster.drain()

            target_text = target.read_text(encoding="utf-8")
            self.assertIn("External replacement", target_text)
            self.assertNotIn("Local replacement", target_text)
            self.assertIsNone(session.source)
            self.assertTrue(session.dirty)
            self.assertEqual(async_events[-1].kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(async_events[-1].error_code, "pgn_save_conflict")

    def test_slow_save_as_worker_does_not_hold_owner_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "slow-save-as.pgn"
            session = PgnDocumentSession.from_text(PGN_TEXT)
            controller, dialogs, poster, _, _, _, _ = self._controller(session)
            dialogs.save_destination = target
            entered = threading.Event()
            release = threading.Event()

            from acs import version2_windows_file_workflows as workflows

            real_publish = workflows.publish_pgn_save_snapshot

            def slow_publish(*args, **kwargs):
                entered.set()
                if not release.wait(5.0):
                    raise AssertionError("slow Save As worker was not released")
                return real_publish(*args, **kwargs)

            with mock.patch.object(
                workflows,
                "publish_pgn_save_snapshot",
                side_effect=slow_publish,
            ):
                result = controller("pgn.save_as", {})
                self.assertEqual(result.kind, FileWorkflowEventKind.PGN_SAVE_STARTED)
                self.assertTrue(entered.wait(2.0))
                self.assertTrue(controller.pgn_save_running)
                self.assertTrue(poster.callbacks == [])
                release.set()
                self.assertTrue(controller.wait_for_pgn_save(5.0))
                poster.drain()

            self.assertTrue(target.exists())

    def test_save_as_opens_native_dialog_before_full_view_materialization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source-name.pgn"
            target = Path(tmp) / "saved-as.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            session = PgnDocumentSession.open(source)
            controller, dialogs, poster, _, async_events, _, _ = self._controller(session)
            dialogs.save_destination = target
            order: list[str] = []
            real_dialog = dialogs.save_pgn_as
            real_view = PgnDocumentSession.view

            def observed_dialog(name="game.pgn"):
                order.append("dialog")
                self.assertEqual(name, "source-name.pgn")
                return real_dialog(name)

            def observed_view(bound_session):
                order.append("view")
                if "dialog" not in order:
                    raise AssertionError(
                        "production Save As materialized the full view before the native dialog"
                    )
                return real_view(bound_session)

            dialogs.save_pgn_as = observed_dialog
            with mock.patch.object(
                PgnDocumentSession,
                "view",
                autospec=True,
                side_effect=observed_view,
            ):
                started = controller("pgn.save_as", {})
                self.assertEqual(started.kind, FileWorkflowEventKind.PGN_SAVE_STARTED)
                self.assertTrue(controller.wait_for_pgn_save(5.0))
                poster.drain()

            self.assertTrue(order)
            self.assertEqual(order[0], "dialog")
            self.assertIn("view", order)
            self.assertEqual(async_events[-1].kind, FileWorkflowEventKind.PGN_SAVED_AS)
            self.assertTrue(target.exists())

    def test_modal_save_as_edit_fails_stale_before_worker_or_file_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "must-not-exist.pgn"
            session = PgnDocumentSession.from_text(PGN_TEXT)
            controller, dialogs, poster, sync_events, async_events, _, _ = self._controller(
                session
            )
            dialogs.save_destination = target
            dialogs.on_save_dialog = lambda: session.edit_tag(
                "Event", "Edited by modal reentry"
            )

            result = controller("pgn.save_as", {})

            self.assertEqual(result.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(result.error_code, "pgn_save_preflight_stale")
            self.assertFalse(target.exists())
            self.assertFalse(controller.pgn_save_running)
            self.assertEqual(poster.callbacks, [])
            self.assertEqual(async_events, [])
            self.assertEqual(sync_events[-1], result)
            self.assertIn("Edited by modal reentry", session.copy_pgn())

    def test_async_boundary_rejects_session_subclass_before_save_as_dialog(self) -> None:
        class DerivedSession(PgnDocumentSession):
            pass

        session = DerivedSession.from_text(PGN_TEXT)
        controller, dialogs, poster, sync_events, async_events, _, _ = self._controller(session)

        result = controller("pgn.save_as", {})

        self.assertEqual(result.kind, FileWorkflowEventKind.FAILED)
        self.assertEqual(result.error_code, "pgn_session_invalid")
        self.assertEqual(dialogs.save_calls, 0)
        self.assertEqual(poster.callbacks, [])
        self.assertEqual(async_events, [])
        self.assertEqual(sync_events[-1], result)

    def test_save_worker_blocks_open_and_import_before_their_dialogs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            session = PgnDocumentSession.open(source)
            session.edit_tag("Event", "Blocked save")
            controller, dialogs, poster, _, _, _, _ = self._controller(session)
            entered = threading.Event()
            release = threading.Event()

            from acs import version2_windows_file_workflows as workflows

            real_publish = workflows.publish_pgn_save_snapshot

            def blocked_publish(*args, **kwargs):
                entered.set()
                if not release.wait(5.0):
                    raise AssertionError("save worker was not released")
                return real_publish(*args, **kwargs)

            with mock.patch.object(
                workflows,
                "publish_pgn_save_snapshot",
                side_effect=blocked_publish,
            ):
                controller("pgn.save", {})
                self.assertTrue(entered.wait(2.0))
                open_result = controller("pgn.open", {})
                import_result = controller("library.import", {})
                self.assertEqual(open_result.error_code, "file_worker_busy")
                self.assertEqual(import_result.error_code, "file_worker_busy")
                self.assertEqual(open_result.focus_target, "pgn-save-cancel")
                self.assertEqual(import_result.focus_target, "pgn-save-cancel")
                self.assertEqual(dialogs.open_calls, 0)
                self.assertEqual(dialogs.import_calls, 0)
                release.set()
                self.assertTrue(controller.wait_for_pgn_save(5.0))
                poster.drain()

    def test_external_source_change_reports_conflict_without_clobber(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source-conflict.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            session = PgnDocumentSession.open(source)
            old_source = session.source
            session.edit_tag("Event", "Local unsaved generation")
            controller, _, poster, _, async_events, _, _ = self._controller(session)

            from acs import version2_windows_file_workflows as workflows

            real_publish = workflows.publish_pgn_save_snapshot

            def external_change_before_publish(*args, **kwargs):
                source.write_text(
                    PGN_TEXT.replace("Background save", "External generation"),
                    encoding="utf-8",
                )
                return real_publish(*args, **kwargs)

            with mock.patch.object(
                workflows,
                "publish_pgn_save_snapshot",
                side_effect=external_change_before_publish,
            ):
                started = controller("pgn.save", {})
                self.assertEqual(started.kind, FileWorkflowEventKind.PGN_SAVE_STARTED)
                self.assertTrue(controller.wait_for_pgn_save(5.0))
                poster.drain()

            source_text = source.read_text(encoding="utf-8")
            self.assertIn("External generation", source_text)
            self.assertNotIn("Local unsaved generation", source_text)
            self.assertEqual(session.source, old_source)
            self.assertTrue(session.dirty)
            terminal = async_events[-1]
            self.assertEqual(terminal.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(terminal.error_code, "pgn_save_conflict")
            self.assertNotIn(str(source), repr(terminal))

    def test_worker_failure_preserves_dirty_state_and_source_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            original = source.read_bytes()
            session = PgnDocumentSession.open(source)
            old_source = session.source
            session.edit_tag("Event", "Still dirty")
            controller, _, poster, _, async_events, _, _ = self._controller(session)

            with mock.patch(
                "acs.version2_windows_file_workflows.publish_pgn_save_snapshot",
                side_effect=RuntimeError("private writer failure"),
            ):
                started = controller("pgn.save", {})
                self.assertEqual(started.kind, FileWorkflowEventKind.PGN_SAVE_STARTED)
                self.assertTrue(controller.wait_for_pgn_save(5.0))
                poster.drain()

            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(session.source, old_source)
            self.assertTrue(session.dirty)
            terminal = async_events[-1]
            self.assertEqual(terminal.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(terminal.error_code, "pgn_save_failed")
            self.assertNotIn("private writer failure", repr(terminal))

    def test_session_replacement_before_owner_commit_cannot_mutate_new_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            old_session = PgnDocumentSession.open(source)
            old_source = old_session.source
            old_session.edit_tag("Event", "Published old session")
            newer_path = Path(tmp) / "newer.pgn"
            newer_path.write_text(
                PGN_TEXT.replace("Background save", "New current session"),
                encoding="utf-8",
            )
            newer_session = PgnDocumentSession.open(newer_path)
            newer_source = newer_session.source
            controller, _, poster, _, async_events, box, _ = self._controller(old_session)

            controller("pgn.save", {})
            self.assertTrue(controller.wait_for_pgn_save(5.0))
            self.assertIn("Published old session", source.read_text(encoding="utf-8"))
            box["session"] = newer_session

            poster.drain()

            self.assertIs(box["session"], newer_session)
            self.assertEqual(newer_session.source, newer_source)
            self.assertFalse(newer_session.dirty)
            self.assertEqual(old_session.source, old_source)
            self.assertTrue(old_session.dirty)
            terminal = async_events[-1]
            self.assertEqual(terminal.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(terminal.error_code, "pgn_save_stale")

    def test_shutdown_commits_already_published_save_before_owner_callback_is_drained(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            session = PgnDocumentSession.open(source)
            old_source = session.source
            session.edit_tag("Event", "Durable before shutdown")
            controller, _, poster, _, async_events, _, _ = self._controller(session)

            controller("pgn.save", {})
            self.assertTrue(controller.wait_for_pgn_save(5.0))
            self.assertIn("Durable before shutdown", source.read_text(encoding="utf-8"))
            self.assertEqual(session.source, old_source)
            self.assertTrue(poster.callbacks)

            self.assertTrue(controller.shutdown(5.0))

            self.assertNotEqual(session.source, old_source)
            self.assertFalse(session.dirty)
            self.assertFalse(controller.pgn_save_running)
            self.assertEqual(async_events[-1].kind, FileWorkflowEventKind.PGN_SAVED)
            event_count = len(async_events)

            poster.drain()
            self.assertEqual(len(async_events), event_count)

    def test_late_cancel_after_durable_publication_cannot_contradict_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pgn"
            source.write_text(PGN_TEXT, encoding="utf-8")
            session = PgnDocumentSession.open(source)
            session.edit_tag("Event", "Published generation")
            controller, _, poster, sync_events, async_events, _, _ = self._controller(
                session
            )

            controller("pgn.save", {})
            self.assertTrue(controller.wait_for_pgn_save(5.0))
            self.assertIn("Published generation", source.read_text(encoding="utf-8"))
            cancelling = controller("pgn.cancel_save", {})
            self.assertEqual(cancelling.kind, FileWorkflowEventKind.PGN_SAVE_CANCELLING)

            poster.drain()

            self.assertEqual(async_events[-1].kind, FileWorkflowEventKind.PGN_SAVED)
            self.assertFalse(session.dirty)
            self.assertFalse(controller.pgn_save_running)
            self.assertIn(cancelling, sync_events)


if __name__ == "__main__":
    unittest.main()
