from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from acs.acsdb import AcsDatabase
from acs.analysis_service import AnalysisService
from acs.book_progress_store import BookProgressStore
from acs.engine_assisted_workflows import EngineAssistedWorkflowService
from acs.import_contract import SourceReadCancelledError
from acs.version2_application import (
    BookOpenCancelled,
    PreparedBookOpen,
    Version2Application,
)
from acs.version2_windows_book_open_worker import Version2BookOpenWorker


class BookOpenPreparationTests(unittest.TestCase):
    def _source(self, root: Path) -> Path:
        source = root / "Книга.md"
        source.write_text(
            "# Доступні шахи\n\n"
            "Це локальний семантичний текст для перевірки фонового відкриття.\n\n"
            "## Розділ\n\n"
            "Навігація має залишатися канонічною.\n",
            encoding="utf-8",
        )
        return source

    def test_semantic_preparation_is_safe_off_the_application_ui_thread(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = self._source(Path(raw))
            result: list[object] = []
            errors: list[BaseException] = []

            def worker() -> None:
                try:
                    result.append(Version2Application.prepare_book_open(source))
                except BaseException as exc:  # pragma: no cover - diagnostic capture
                    errors.append(exc)

            thread = threading.Thread(target=worker)
            thread.start()
            thread.join(timeout=10)

            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(len(result), 1)
            prepared = result[0]
            self.assertIs(type(prepared), PreparedBookOpen)
            self.assertTrue(prepared.book_key)
            self.assertIsNone(prepared.document.language)
            self.assertEqual(prepared.warnings, ())
            self.assertIn("Доступні шахи", prepared.document.title)

    def test_cancel_token_reaches_semantic_import_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = self._source(Path(raw))
            calls = 0

            def cancel_after_stable_read() -> bool:
                nonlocal calls
                calls += 1
                # For this small source, calls 1..8 cover the outer checkpoint,
                # the canonical two-pass stable read, and its immediate
                # post-read checkpoint. The next poll is the text importer's
                # own control_checkpoint before semantic parsing.
                return calls >= 9

            with self.assertRaises(BookOpenCancelled):
                Version2Application.prepare_book_open(
                    source,
                    cancel_check=cancel_after_stable_read,
                )

            self.assertGreaterEqual(calls, 9)

    def test_cancel_contract_fails_closed_on_non_boolean_result(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = self._source(Path(raw))
            with self.assertRaisesRegex(
                TypeError,
                "Book Open cancel_check must return bool",
            ):
                Version2Application.prepare_book_open(
                    source,
                    cancel_check=lambda: 1,
                )

    def test_source_reader_cancellation_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = self._source(Path(raw))
            with mock.patch(
                "acs.version2_application.read_source_snapshot",
                side_effect=SourceReadCancelledError("cancelled"),
            ):
                with self.assertRaises(BookOpenCancelled):
                    Version2Application.prepare_book_open(
                        source,
                        cancel_check=lambda: False,
                    )

    def test_direct_open_preserves_fail_before_read_modal_fence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = self._source(root)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2Application(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                app.shell.open_dialog(
                    "book-open-modal",
                    opener_focus_id="books-open",
                    initial_focus_id="book-open-cancel",
                )
                with mock.patch.object(
                    Version2Application,
                    "prepare_book_open",
                    side_effect=AssertionError("Book source must not be read"),
                ) as prepare:
                    with self.assertRaisesRegex(ValueError, "active dialog"):
                        app.open_book(source)
                prepare.assert_not_called()
            finally:
                analysis.close()
                database.close()

    def test_cancel_before_read_does_not_mutate_source(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = self._source(Path(raw))
            before = source.read_bytes()

            with self.assertRaises(BookOpenCancelled):
                Version2Application.prepare_book_open(
                    source,
                    cancel_check=lambda: True,
                )

            self.assertEqual(source.read_bytes(), before)


    def test_cancel_open_action_is_in_the_shared_registry(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            try:
                app = Version2Application(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                definition = app.adapter.registry.definition("book.cancel_open")
                self.assertEqual(definition.action_id, "book.cancel_open")
                self.assertEqual(definition.context.value, "book_reader")
            finally:
                analysis.close()
                database.close()

    def test_application_book_open_returns_before_ui_commit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = self._source(root)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            callbacks = []
            try:
                app = Version2Application(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                worker = Version2BookOpenWorker(
                    prepare=app.prepare_book_open,
                    commit=app.commit_prepared_book_open,
                    post_to_ui=callbacks.append,
                    event_sink=app._book_open_event,
                )
                app.bind_book_open_worker(worker)
                app.open_book_dialog = lambda: source

                self.assertIsNone(app._delegate("book.open", {}))
                self.assertIsNone(app.reader)
                deadline = time.monotonic() + 2
                while not callbacks and time.monotonic() < deadline:
                    time.sleep(0.005)
                self.assertTrue(callbacks)
                self.assertIsNone(app.reader)

                callbacks.pop(0)()
                self.assertIsNotNone(app.reader)
                self.assertEqual(app.shell.current_route.route_id, "books")
                announcements = [
                    event["payload"].get("announcement", "")
                    for event in app.drain_events()
                    if event["kind"] in {"status", "error"}
                ]
                self.assertTrue(any("Відкриття книги розпочато" in item for item in announcements))
                self.assertTrue(any("Книгу відкрито" in item for item in announcements))
            finally:
                analysis.close()
                database.close()

    def test_application_cancel_action_prevents_pending_prepared_commit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = self._source(root)
            database = AcsDatabase(root / "library.acsdb")
            analysis = AnalysisService(lambda: None)
            callbacks = []
            release_prepare = threading.Event()
            prepare_entered = threading.Event()
            try:
                app = Version2Application(
                    database,
                    progress_store=BookProgressStore(root / "book-progress.json"),
                    engine_assistance=EngineAssistedWorkflowService(analysis),
                    board_dispatch=lambda *_: None,
                    board_position_projector=lambda _fen: {"ok": True},
                )
                prepared = app.prepare_book_open(source)

                def slow_prepare(_source, *, cancel_check):
                    prepare_entered.set()
                    release_prepare.wait(2)
                    return prepared

                worker = Version2BookOpenWorker(
                    prepare=slow_prepare,
                    commit=app.commit_prepared_book_open,
                    post_to_ui=callbacks.append,
                    event_sink=app._book_open_event,
                )
                app.bind_book_open_worker(worker)
                app.open_book_dialog = lambda: source

                app._delegate("book.open", {})
                self.assertTrue(prepare_entered.wait(2))
                self.assertIsNone(app._delegate("book.cancel_open", {}))
                release_prepare.set()
                deadline = time.monotonic() + 2
                while not callbacks and time.monotonic() < deadline:
                    time.sleep(0.005)
                self.assertTrue(callbacks)
                callbacks.pop(0)()

                self.assertIsNone(app.reader)
                self.assertNotEqual(app.shell.current_route.route_id, "books")
                events = app.drain_events()
                self.assertTrue(
                    any(
                        event["kind"] == "status"
                        and "скасовано" in event["payload"].get("announcement", "").casefold()
                        for event in events
                    )
                )
            finally:
                release_prepare.set()
                analysis.close()
                database.close()


if __name__ == "__main__":
    unittest.main()
