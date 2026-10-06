from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import unittest

from acs.pgn_document import PgnDocumentSession
from acs.version2_windows_file_workflows import (
    FileWorkflowEvent,
    FileWorkflowEventKind,
    Version2ImportWorkerServices,
    Version2WindowsFileActionDelegate,
)


class _Dialogs:
    def __init__(self, path: Path) -> None:
        self.path = path

    def open_pgn(self) -> Path:
        return self.path

    def save_pgn_as(self, suggested_filename: str = "game.pgn") -> Path | None:
        return None

    def select_library_import(self) -> Path | None:
        return None


def _noop_services() -> Version2ImportWorkerServices:
    class Library:
        def import_games(self, *args, **kwargs):
            raise AssertionError("import path must not run")

    return Version2ImportWorkerServices(
        library=Library(),
        chessbase=None,
        close=lambda: None,
    )


class WindowsPgnModalGenerationOwnerPublicationTests(unittest.TestCase):
    def _session(self, path: Path) -> PgnDocumentSession:
        return PgnDocumentSession.open(path)

    def _delegate(self, current: list[PgnDocumentSession | None], events: list[FileWorkflowEvent]) -> Version2WindowsFileActionDelegate:
        return Version2WindowsFileActionDelegate(
            dialogs=_Dialogs(Path("unused.pgn")),
            get_pgn_session=lambda: current[0],
            set_pgn_session=lambda session: current.__setitem__(0, session),
            import_services_factory=_noop_services,
            event_sink=events.append,
            next_delegate=lambda action_id, payload: None,
            post_to_ui=lambda callback: None,
        )

    def _prepare_worker_state(
        self,
        delegate: Version2WindowsFileActionDelegate,
        cancel_event: threading.Event,
    ) -> tuple[int, threading.Thread]:
        worker = threading.Thread(target=lambda: None, name="test-pgn-open-worker")
        with delegate._lock:
            delegate._generation = 1
            delegate._worker = worker
            delegate._worker_started = False
            delegate._worker_kind = "pgn_open"
            delegate._cancel_event = cancel_event
            delegate._terminal_pending = None
        return 1, worker

    def _run_owner_publication_after_persistence_drift(
        self,
        mutate,
    ) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old_path = root / "old.pgn"
            new_path = root / "new.pgn"
            old_path.write_text('[Event "old"]\n\n1. e4 *\n', encoding="utf-8")
            new_path.write_text('[Event "new"]\n\n1. d4 *\n', encoding="utf-8")

            current = self._session(old_path)
            prepared = self._session(new_path)
            prepared_view = prepared.view()
            expected_generation_delegate = self._delegate([current], [])

            expected_generation = expected_generation_delegate._pgn_session_generation(current)
            mutate(current)

            events: list[FileWorkflowEvent] = []
            delegate = self._delegate([current], events)
            cancel_event = threading.Event()
            generation, _ = self._prepare_worker_state(delegate, cancel_event)

            delegate._finish_pgn_open_on_owner(
                generation,
                prepared,
                prepared_view,
                "",
                "",
                cancel_event,
                current,
                expected_generation,
            )

            self.assertIs(
                delegate._get_pgn_session(),
                current,
                "stale owner publication must preserve the live session",
            )
            self.assertTrue(events, "owner publication must emit a stale terminal")
            terminal = events[-1]
            self.assertIs(terminal.kind, FileWorkflowEventKind.FAILED)
            self.assertEqual(terminal.action_id, "pgn.open")
            self.assertEqual(terminal.error_code, "pgn_open_stale")
            self.assertFalse(
                any(event.kind is FileWorkflowEventKind.PGN_OPENED for event in events),
                "stale owner publication must never replace the live document",
            )

    def test_open_owner_publication_rejects_same_session_source_overwrite_safety_drift(self):
        self._run_owner_publication_after_persistence_drift(
            lambda session: setattr(
                session,
                "_source_overwrite_safe",
                not session._source_overwrite_safe,
            )
        )

    def test_open_owner_publication_rejects_same_session_saved_digest_drift(self):
        def mutate(session: PgnDocumentSession) -> None:
            old = session._saved_digest
            candidate = "0" * 64
            if old == candidate:
                candidate = "1" * 64
            session._saved_digest = candidate

        self._run_owner_publication_after_persistence_drift(mutate)

    def test_open_owner_publication_rechecks_cancellation_before_session_publish(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_path = root / "replacement.pgn"
            current_path = root / "current.pgn"
            source_path.write_text('[Event "replacement"]\n\n1. d4 *\n', encoding="utf-8")
            current_path.write_text('[Event "current"]\n\n1. e4 *\n', encoding="utf-8")

            current = self._session(current_path)
            prepared = self._session(source_path)
            prepared_view = prepared.view()
            cancel_event = threading.Event()
            events: list[FileWorkflowEvent] = []
            live_box: list[PgnDocumentSession | None] = [current]
            reads = 0

            def get_live_session() -> PgnDocumentSession:
                nonlocal reads
                reads += 1
                if reads == 1:
                    cancel_event.set()
                return current

            delegate = Version2WindowsFileActionDelegate(
                dialogs=_Dialogs(source_path),
                get_pgn_session=get_live_session,
                set_pgn_session=lambda session: live_box.__setitem__(0, session),
                import_services_factory=_noop_services,
                event_sink=events.append,
                next_delegate=lambda action_id, payload: None,
                post_to_ui=lambda callback: None,
            )
            generation, _ = self._prepare_worker_state(delegate, cancel_event)
            expected_generation = delegate._pgn_session_generation(current)

            # The injected cancellation lands after the owner callback's initial
            # cancellation snapshot, but before its final session publication.
            # Cancellation remains allowed to win until the publication boundary.
            delegate._finish_pgn_open_on_owner(
                generation,
                prepared,
                prepared_view,
                "",
                "",
                cancel_event,
                current,
                expected_generation,
            )

            self.assertIs(
                live_box[0],
                current,
                "cancelled Open must not publish the prepared session",
            )
            self.assertTrue(events)
            terminal = events[-1]
            self.assertIs(terminal.kind, FileWorkflowEventKind.PGN_OPEN_CANCELLED)
            self.assertEqual(terminal.action_id, "pgn.open")


if __name__ == "__main__":
    unittest.main()
