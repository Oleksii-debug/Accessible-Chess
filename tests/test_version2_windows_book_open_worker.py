from __future__ import annotations

from pathlib import Path
import threading
import time
import unittest
import unittest.mock

from acs.version2_windows_book_open_worker import (
    BookOpenWorkerEventKind,
    Version2BookOpenWorker,
)


class BookOpenWorkerTests(unittest.TestCase):
    def _wait(self, predicate, timeout: float = 2.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.005)
        self.fail("timed out waiting for Book Open worker condition")

    def test_single_flight_extends_through_pending_ui_commit(self) -> None:
        callbacks = []
        events = []
        commits = []
        prepared = threading.Event()

        def prepare(source, *, cancel_check):
            self.assertEqual(source, Path("book.md"))
            self.assertFalse(cancel_check())
            prepared.set()
            return "prepared-book"

        worker = Version2BookOpenWorker(
            prepare=prepare,
            commit=commits.append,
            post_to_ui=callbacks.append,
            event_sink=events.append,
        )
        self.assertTrue(worker.start(Path("book.md"), focus_target="book-open"))
        self.assertTrue(prepared.wait(2))
        self._wait(lambda: len(callbacks) == 1)

        # Background preparation is finished, but the UI callback has not run.
        # This remains one in-flight transaction and cannot be overtaken.
        self.assertTrue(worker.active)
        with self.assertRaisesRegex(RuntimeError, "already running"):
            worker.start(Path("other.md"))

        callbacks.pop(0)()
        self.assertFalse(worker.active)
        self.assertEqual(commits, ["prepared-book"])
        self.assertEqual(
            [event.kind for event in events],
            [BookOpenWorkerEventKind.STARTED, BookOpenWorkerEventKind.COMPLETED],
        )

    def test_cancel_after_prepare_before_ui_callback_prevents_commit(self) -> None:
        callbacks = []
        events = []
        commits = []

        worker = Version2BookOpenWorker(
            prepare=lambda source, *, cancel_check: "prepared-book",
            commit=commits.append,
            post_to_ui=callbacks.append,
            event_sink=events.append,
        )
        worker.start(Path("book.md"), focus_target="book-open")
        self._wait(lambda: len(callbacks) == 1)
        self.assertTrue(worker.cancel(focus_target="book-cancel"))
        callbacks.pop(0)()

        self.assertEqual(commits, [])
        self.assertFalse(worker.active)
        self.assertEqual(
            [event.kind for event in events],
            [
                BookOpenWorkerEventKind.STARTED,
                BookOpenWorkerEventKind.CANCELLING,
                BookOpenWorkerEventKind.CANCELLED,
            ],
        )

    def test_shutdown_cancels_and_joins_without_late_commit(self) -> None:
        callbacks = []
        commits = []
        entered = threading.Event()

        def prepare(source, *, cancel_check):
            entered.set()
            while not cancel_check():
                time.sleep(0.005)
            return "must-not-commit"

        worker = Version2BookOpenWorker(
            prepare=prepare,
            commit=commits.append,
            post_to_ui=callbacks.append,
            event_sink=lambda event: None,
        )
        worker.start(Path("book.md"))
        self.assertTrue(entered.wait(2))
        self.assertTrue(worker.shutdown(timeout=2))
        self.assertTrue(worker.closed)
        self.assertFalse(worker.active)

        for callback in callbacks:
            callback()
        self.assertEqual(commits, [])

    def test_post_failure_never_commits_from_worker_thread(self) -> None:
        commits = []

        def reject_post(_callback):
            raise RuntimeError("owner closing")

        worker = Version2BookOpenWorker(
            prepare=lambda source, *, cancel_check: "prepared-book",
            commit=commits.append,
            post_to_ui=reject_post,
            event_sink=lambda event: None,
        )
        worker.start(Path("book.md"))
        self._wait(lambda: not worker.active)
        self.assertEqual(commits, [])

    def test_thread_start_failure_does_not_leave_worker_busy(self) -> None:
        events = []
        worker = Version2BookOpenWorker(
            prepare=lambda source, *, cancel_check: "prepared-book",
            commit=lambda value: None,
            post_to_ui=lambda callback: None,
            event_sink=events.append,
        )
        with unittest.mock.patch("threading.Thread.start", side_effect=RuntimeError("cannot start")):
            with self.assertRaisesRegex(RuntimeError, "cannot start"):
                worker.start(Path("book.md"), focus_target="book-open")
        self.assertFalse(worker.active)
        self.assertEqual(
            [event.kind for event in events],
            [BookOpenWorkerEventKind.STARTED, BookOpenWorkerEventKind.FAILED],
        )

    def test_started_event_reentrant_shutdown_does_not_start_reserved_worker(self) -> None:
        events = []
        shutdown_results = []
        holder = {}

        def sink(event):
            events.append(event.kind)
            if event.kind is BookOpenWorkerEventKind.STARTED:
                shutdown_results.append(holder["worker"].shutdown(0.0))

        worker = Version2BookOpenWorker(
            prepare=lambda source, *, cancel_check: "must-not-run",
            commit=lambda value: None,
            post_to_ui=lambda callback: callback(),
            event_sink=sink,
        )
        holder["worker"] = worker

        with unittest.mock.patch.object(threading.Thread, "start", autospec=True) as start:
            self.assertFalse(worker.start(Path("book.md"), focus_target="book-open"))

        self.assertEqual(shutdown_results, [True])
        start.assert_not_called()
        self.assertEqual(events, [BookOpenWorkerEventKind.STARTED])
        self.assertTrue(worker.closed)
        self.assertFalse(worker.active)
        self.assertTrue(worker.resume_after_refused_shutdown())

    def test_started_event_failure_does_not_leave_worker_busy(self) -> None:
        def reject_event(_event):
            raise RuntimeError("event sink failed")

        worker = Version2BookOpenWorker(
            prepare=lambda source, *, cancel_check: "prepared-book",
            commit=lambda value: None,
            post_to_ui=lambda callback: None,
            event_sink=reject_event,
        )
        with self.assertRaisesRegex(RuntimeError, "event sink failed"):
            worker.start(Path("book.md"))
        self.assertFalse(worker.active)

    def test_control_methods_are_ui_thread_only(self) -> None:
        worker = Version2BookOpenWorker(
            prepare=lambda source, *, cancel_check: None,
            commit=lambda value: None,
            post_to_ui=lambda callback: callback(),
            event_sink=lambda event: None,
        )
        errors = []

        def background():
            try:
                worker.start(Path("book.md"))
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(target=background)
        thread.start()
        thread.join(2)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertIn("UI thread", str(errors[0]))


    def test_refused_close_can_reopen_fully_retired_worker(self) -> None:
        callbacks = []
        commits = []
        worker = Version2BookOpenWorker(
            prepare=lambda source, *, cancel_check: "reopened-book",
            commit=commits.append,
            post_to_ui=callbacks.append,
            event_sink=lambda event: None,
        )

        self.assertTrue(worker.shutdown())
        self.assertTrue(worker.closed)
        self.assertTrue(worker.resume_after_refused_shutdown())
        self.assertFalse(worker.closed)

        self.assertTrue(worker.start(Path("book.md")))
        self._wait(lambda: len(callbacks) == 1)
        callbacks.pop(0)()
        self.assertEqual(commits, ["reopened-book"])
        self.assertTrue(worker.shutdown())

    def test_refused_close_does_not_reopen_live_worker(self) -> None:
        callbacks = []
        entered = threading.Event()
        release = threading.Event()

        def prepare(source, *, cancel_check):
            entered.set()
            release.wait(2)
            return "stale-book"

        worker = Version2BookOpenWorker(
            prepare=prepare,
            commit=lambda value: None,
            post_to_ui=callbacks.append,
            event_sink=lambda event: None,
        )
        self.assertTrue(worker.start(Path("book.md")))
        self.assertTrue(entered.wait(2))

        self.assertFalse(worker.shutdown(timeout=0))
        self.assertTrue(worker.closed)
        self.assertFalse(worker.resume_after_refused_shutdown())

        release.set()
        self.assertTrue(worker.shutdown(timeout=2))
        self.assertTrue(worker.resume_after_refused_shutdown())
        for callback in callbacks:
            callback()
        self.assertFalse(worker.active)



if __name__ == "__main__":
    unittest.main()
