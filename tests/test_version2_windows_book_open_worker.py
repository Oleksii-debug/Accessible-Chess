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
        events = []

        def reject_post(_callback):
            raise RuntimeError("owner temporarily unavailable")

        worker = Version2BookOpenWorker(
            prepare=lambda source, *, cancel_check: "prepared-book",
            commit=commits.append,
            post_to_ui=reject_post,
            event_sink=lambda event: events.append(event.kind),
        )
        worker.start(Path("book.md"), focus_target="book-open")
        self._wait(lambda: not worker.active)

        self.assertEqual(commits, [])
        self.assertEqual(events, [BookOpenWorkerEventKind.STARTED])

        # Recovery occurs only when the existing UI owner asks for pending
        # presentation work; the background thread never calls the event sink.
        worker.flush_pending_terminal()
        self.assertEqual(
            events,
            [BookOpenWorkerEventKind.STARTED, BookOpenWorkerEventKind.FAILED],
        )
        worker.flush_pending_terminal()
        self.assertEqual(
            events,
            [BookOpenWorkerEventKind.STARTED, BookOpenWorkerEventKind.FAILED],
        )

    def test_post_failure_retains_one_owner_thread_failure_terminal(self) -> None:
        commits = []
        events = []

        def reject_post(_callback):
            raise RuntimeError("transient owner post failure")

        worker = Version2BookOpenWorker(
            prepare=lambda source, *, cancel_check: "prepared-book",
            commit=commits.append,
            post_to_ui=reject_post,
            event_sink=lambda event: events.append(event.kind),
        )

        self.assertTrue(worker.start(Path("book.md"), focus_target="book-open"))
        self._wait(lambda: not worker.active)
        self.assertEqual(events, [BookOpenWorkerEventKind.STARTED])
        self.assertEqual(commits, [])

        worker.flush_pending_terminal()
        self.assertEqual(
            events,
            [BookOpenWorkerEventKind.STARTED, BookOpenWorkerEventKind.FAILED],
        )
        self.assertEqual(commits, [])

        # Delivery consumes the retained terminal exactly once.
        worker.flush_pending_terminal()
        self.assertEqual(
            events,
            [BookOpenWorkerEventKind.STARTED, BookOpenWorkerEventKind.FAILED],
        )
        self.assertTrue(worker.shutdown())

    def test_post_failure_terminal_survives_observer_failure_for_retry(self) -> None:
        events = []
        failures = [True]

        def reject_post(_callback):
            raise RuntimeError("transient owner post failure")

        def sink(event):
            if event.kind is BookOpenWorkerEventKind.FAILED and failures[0]:
                failures[0] = False
                raise RuntimeError("transient presentation failure")
            events.append(event.kind)

        worker = Version2BookOpenWorker(
            prepare=lambda source, *, cancel_check: "prepared-book",
            commit=lambda _value: None,
            post_to_ui=reject_post,
            event_sink=sink,
        )
        self.assertTrue(worker.start(Path("book.md")))
        self._wait(lambda: not worker.active)

        with self.assertRaisesRegex(RuntimeError, "presentation failure"):
            worker.flush_pending_terminal()
        worker.flush_pending_terminal()
        self.assertEqual(
            events,
            [BookOpenWorkerEventKind.STARTED, BookOpenWorkerEventKind.FAILED],
        )
        self.assertTrue(worker.shutdown())

    def test_completed_terminal_observer_failure_is_retained_for_retry(self) -> None:
        callbacks = []
        commits = []
        events = []
        fail_terminal_once = [True]

        def sink(event):
            if (
                event.kind is BookOpenWorkerEventKind.COMPLETED
                and fail_terminal_once[0]
            ):
                fail_terminal_once[0] = False
                raise RuntimeError("transient completed presentation failure")
            events.append(event.kind)

        worker = Version2BookOpenWorker(
            prepare=lambda source, *, cancel_check: "prepared-book",
            commit=commits.append,
            post_to_ui=callbacks.append,
            event_sink=sink,
        )
        self.assertTrue(worker.start(Path("book.md"), focus_target="book-open"))
        self._wait(lambda: len(callbacks) == 1)

        with self.assertRaisesRegex(RuntimeError, "completed presentation failure"):
            callbacks.pop(0)()

        self.assertFalse(worker.active)
        self.assertEqual(commits, ["prepared-book"])
        self.assertEqual(events, [BookOpenWorkerEventKind.STARTED])

        worker.flush_pending_terminal()
        self.assertEqual(
            events,
            [BookOpenWorkerEventKind.STARTED, BookOpenWorkerEventKind.COMPLETED],
        )
        self.assertEqual(commits, ["prepared-book"])
        worker.flush_pending_terminal()
        self.assertEqual(
            events,
            [BookOpenWorkerEventKind.STARTED, BookOpenWorkerEventKind.COMPLETED],
        )

    def test_failed_terminal_observer_failure_is_retained_for_retry(self) -> None:
        callbacks = []
        commits = []
        events = []
        fail_terminal_once = [True]

        def prepare(source, *, cancel_check):
            raise RuntimeError("fixed preparation failure")

        def sink(event):
            if event.kind is BookOpenWorkerEventKind.FAILED and fail_terminal_once[0]:
                fail_terminal_once[0] = False
                raise RuntimeError("transient failed presentation failure")
            events.append(event.kind)

        worker = Version2BookOpenWorker(
            prepare=prepare,
            commit=commits.append,
            post_to_ui=callbacks.append,
            event_sink=sink,
        )
        self.assertTrue(worker.start(Path("book.md"), focus_target="book-open"))
        self._wait(lambda: len(callbacks) == 1)

        with self.assertRaisesRegex(RuntimeError, "failed presentation failure"):
            callbacks.pop(0)()

        self.assertFalse(worker.active)
        self.assertEqual(commits, [])
        self.assertEqual(events, [BookOpenWorkerEventKind.STARTED])

        worker.flush_pending_terminal()
        self.assertEqual(
            events,
            [BookOpenWorkerEventKind.STARTED, BookOpenWorkerEventKind.FAILED],
        )
        worker.flush_pending_terminal()
        self.assertEqual(
            events,
            [BookOpenWorkerEventKind.STARTED, BookOpenWorkerEventKind.FAILED],
        )

    def test_cancelled_terminal_observer_failure_is_retained_for_retry(self) -> None:
        callbacks = []
        commits = []
        events = []
        fail_terminal_once = [True]

        def sink(event):
            if (
                event.kind is BookOpenWorkerEventKind.CANCELLED
                and fail_terminal_once[0]
            ):
                fail_terminal_once[0] = False
                raise RuntimeError("transient cancelled presentation failure")
            events.append(event.kind)

        worker = Version2BookOpenWorker(
            prepare=lambda source, *, cancel_check: "prepared-book",
            commit=commits.append,
            post_to_ui=callbacks.append,
            event_sink=sink,
        )
        self.assertTrue(worker.start(Path("book.md"), focus_target="book-open"))
        self._wait(lambda: len(callbacks) == 1)
        self.assertTrue(worker.cancel(focus_target="book-cancel"))

        with self.assertRaisesRegex(RuntimeError, "cancelled presentation failure"):
            callbacks.pop(0)()

        self.assertFalse(worker.active)
        self.assertEqual(commits, [])
        self.assertEqual(
            events,
            [
                BookOpenWorkerEventKind.STARTED,
                BookOpenWorkerEventKind.CANCELLING,
            ],
        )

        worker.flush_pending_terminal()
        self.assertEqual(
            events,
            [
                BookOpenWorkerEventKind.STARTED,
                BookOpenWorkerEventKind.CANCELLING,
                BookOpenWorkerEventKind.CANCELLED,
            ],
        )
        worker.flush_pending_terminal()
        self.assertEqual(
            events,
            [
                BookOpenWorkerEventKind.STARTED,
                BookOpenWorkerEventKind.CANCELLING,
                BookOpenWorkerEventKind.CANCELLED,
            ],
        )

    def test_prestart_cancel_terminal_observer_failure_retries_without_failed_terminal(
        self,
    ) -> None:
        events = []
        holder = {}
        fail_terminal_once = [True]

        def sink(event):
            if event.kind is BookOpenWorkerEventKind.STARTED:
                events.append(event.kind)
                self.assertTrue(holder["worker"].cancel(focus_target="book-cancel"))
                return
            if (
                event.kind is BookOpenWorkerEventKind.CANCELLED
                and fail_terminal_once[0]
            ):
                fail_terminal_once[0] = False
                raise RuntimeError("transient prestart terminal failure")
            events.append(event.kind)

        worker = Version2BookOpenWorker(
            prepare=lambda source, *, cancel_check: "must-not-run",
            commit=lambda value: None,
            post_to_ui=lambda callback: callback(),
            event_sink=sink,
        )
        holder["worker"] = worker

        with unittest.mock.patch.object(threading.Thread, "start", autospec=True) as start:
            with self.assertRaisesRegex(RuntimeError, "prestart terminal failure"):
                worker.start(Path("book.md"), focus_target="book-open")

        start.assert_not_called()
        self.assertFalse(worker.active)
        self.assertEqual(
            events,
            [
                BookOpenWorkerEventKind.STARTED,
                BookOpenWorkerEventKind.CANCELLING,
            ],
        )

        worker.flush_pending_terminal()
        self.assertEqual(
            events,
            [
                BookOpenWorkerEventKind.STARTED,
                BookOpenWorkerEventKind.CANCELLING,
                BookOpenWorkerEventKind.CANCELLED,
            ],
        )

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

    def test_started_event_reentrant_cancel_does_not_start_reserved_worker(self) -> None:
        events = []
        cancel_results = []
        holder = {}

        def sink(event):
            events.append(event.kind)
            if event.kind is BookOpenWorkerEventKind.STARTED:
                cancel_results.append(
                    holder["worker"].cancel(focus_target="book-cancel")
                )

        worker = Version2BookOpenWorker(
            prepare=lambda source, *, cancel_check: "must-not-run",
            commit=lambda value: None,
            post_to_ui=lambda callback: callback(),
            event_sink=sink,
        )
        holder["worker"] = worker

        with unittest.mock.patch.object(threading.Thread, "start", autospec=True) as start:
            self.assertFalse(worker.start(Path("book.md"), focus_target="book-open"))

        self.assertEqual(cancel_results, [True])
        start.assert_not_called()
        self.assertFalse(worker.closed)
        self.assertFalse(worker.active)
        self.assertEqual(
            events,
            [
                BookOpenWorkerEventKind.STARTED,
                BookOpenWorkerEventKind.CANCELLING,
                BookOpenWorkerEventKind.CANCELLED,
            ],
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
        self.assertEqual(
            events,
            [BookOpenWorkerEventKind.STARTED, BookOpenWorkerEventKind.CANCELLED],
        )

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


    def test_refused_close_preserves_retired_pending_book_failure_terminal(self) -> None:
        callbacks = []
        events = []
        commits = []
        prepared = threading.Event()

        def prepare(source, *, cancel_check):
            prepared.set()
            raise RuntimeError("fixed Book preparation failure")

        worker = Version2BookOpenWorker(
            prepare=prepare,
            commit=commits.append,
            post_to_ui=callbacks.append,
            event_sink=lambda event: events.append(event.kind),
        )

        self.assertTrue(worker.start(Path("book.md"), focus_target="book-open"))
        self.assertTrue(prepared.wait(2.0))
        self._wait(lambda: len(callbacks) == 1)
        self.assertTrue(worker.shutdown())

        self.assertTrue(worker.resume_after_refused_shutdown())
        self.assertEqual(
            events,
            [BookOpenWorkerEventKind.STARTED, BookOpenWorkerEventKind.FAILED],
        )
        self.assertFalse(worker.active)
        self.assertEqual(commits, [])

        event_count = len(events)
        callbacks.pop(0)()
        self.assertEqual(len(events), event_count)
        self.assertEqual(commits, [])
        self.assertTrue(worker.shutdown())
    def test_refused_close_reconciles_retired_pending_book_terminal(self) -> None:
        callbacks = []
        events = []
        commits = []
        prepared = threading.Event()

        def prepare(source, *, cancel_check):
            prepared.set()
            return "must-not-commit-after-shutdown"

        worker = Version2BookOpenWorker(
            prepare=prepare,
            commit=commits.append,
            post_to_ui=callbacks.append,
            event_sink=lambda event: events.append(event.kind),
        )

        self.assertTrue(worker.start(Path("book.md"), focus_target="book-open"))
        self.assertTrue(prepared.wait(2.0))
        self._wait(lambda: len(callbacks) == 1)

        # Preparation finished, but publication still belongs to a queued owner
        # callback. Shutdown retires that candidate and fences its generation.
        self.assertTrue(worker.shutdown())
        self.assertTrue(worker.closed)
        self.assertTrue(worker.resume_after_refused_shutdown())
        self.assertFalse(worker.closed)
        self.assertEqual(
            events,
            [BookOpenWorkerEventKind.STARTED, BookOpenWorkerEventKind.CANCELLED],
        )

        # A WinForms callback queued before shutdown may still arrive. It must
        # stay stale and cannot duplicate the recovery terminal or commit Book.
        callbacks.pop(0)()
        self.assertEqual(commits, [])
        self.assertEqual(
            events,
            [BookOpenWorkerEventKind.STARTED, BookOpenWorkerEventKind.CANCELLED],
        )
        self.assertFalse(worker.active)
        self.assertTrue(worker.shutdown())
    def test_recovery_cancel_observer_reentrant_shutdown_does_not_report_live(self) -> None:
        callbacks = []
        events = []
        commits = []
        prepared = threading.Event()
        reentrant_shutdown = []
        holder = {}

        def prepare(source, *, cancel_check):
            prepared.set()
            return "retired-book"

        def sink(event):
            events.append(event.kind)
            if event.kind is BookOpenWorkerEventKind.CANCELLED:
                reentrant_shutdown.append(holder["worker"].shutdown())

        worker = Version2BookOpenWorker(
            prepare=prepare,
            commit=commits.append,
            post_to_ui=callbacks.append,
            event_sink=sink,
        )
        holder["worker"] = worker

        self.assertTrue(worker.start(Path("book.md"), focus_target="book-open"))
        self.assertTrue(prepared.wait(2.0))
        self._wait(lambda: len(callbacks) == 1)
        self.assertTrue(worker.shutdown())

        self.assertFalse(worker.resume_after_refused_shutdown())
        self.assertTrue(worker.closed)
        self.assertEqual(reentrant_shutdown, [True])
        self.assertEqual(
            events,
            [BookOpenWorkerEventKind.STARTED, BookOpenWorkerEventKind.CANCELLED],
        )
        callbacks.pop(0)()
        self.assertEqual(commits, [])

        self.assertTrue(worker.resume_after_refused_shutdown())
        self.assertFalse(worker.closed)
        self.assertTrue(worker.shutdown())
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

    def test_refused_close_reopens_draining_cancelled_worker_and_returns_idle(self) -> None:
        callbacks = []
        events = []
        commits = []
        entered = threading.Event()
        release = threading.Event()

        def prepare(source, *, cancel_check):
            entered.set()
            release.wait(2)
            return "stale-book"

        worker = Version2BookOpenWorker(
            prepare=prepare,
            commit=commits.append,
            post_to_ui=callbacks.append,
            event_sink=lambda event: events.append(event.kind),
        )
        self.assertTrue(worker.start(Path("book.md"), focus_target="book-open"))
        self.assertTrue(entered.wait(2))

        self.assertFalse(worker.shutdown(timeout=0))
        self.assertTrue(worker.closed)
        self.assertTrue(worker.resume_after_refused_shutdown())
        self.assertFalse(worker.closed)
        self.assertTrue(worker.active)

        release.set()
        self._wait(lambda: len(callbacks) == 1)
        callbacks.pop(0)()

        self.assertEqual(commits, [])
        self.assertFalse(worker.active)
        self.assertEqual(
            events,
            [BookOpenWorkerEventKind.STARTED, BookOpenWorkerEventKind.CANCELLED],
        )

        # The refused-close recovery is a real product recovery, not merely a
        # shutdown retry seam: a fresh Book Open can run after the stale
        # cancelled generation drains.
        self.assertTrue(worker.start(Path("book-2.md")))
        self._wait(lambda: len(callbacks) == 1)
        callbacks.pop(0)()
        self.assertEqual(commits, ["stale-book"])
        self.assertTrue(worker.shutdown())

    def test_refused_close_post_failure_clears_stale_busy_lease(self) -> None:
        callbacks = []
        commits = []
        entered = threading.Event()
        release = threading.Event()
        reject_post = [True]

        def prepare(source, *, cancel_check):
            entered.set()
            release.wait(2)
            return "prepared-book"

        def post(callback):
            if reject_post[0]:
                raise RuntimeError("owner temporarily unavailable")
            callbacks.append(callback)

        worker = Version2BookOpenWorker(
            prepare=prepare,
            commit=commits.append,
            post_to_ui=post,
            event_sink=lambda event: None,
        )
        self.assertTrue(worker.start(Path("book.md")))
        self.assertTrue(entered.wait(2))
        self.assertFalse(worker.shutdown(timeout=0))
        self.assertTrue(worker.resume_after_refused_shutdown())

        release.set()
        self._wait(lambda: not worker.active)
        self.assertEqual(commits, [])

        reject_post[0] = False
        self.assertTrue(worker.start(Path("book-2.md")))
        self._wait(lambda: len(callbacks) == 1)
        callbacks.pop(0)()
        self.assertEqual(commits, ["prepared-book"])
        self.assertTrue(worker.shutdown())



    def test_reentrant_terminal_flush_is_single_delivery_and_blocks_new_generation(self) -> None:
        callbacks = []
        events = []
        reentrant_flushes = []
        reentrant_start_errors = []
        commits = []
        reject_post = [True]
        holder = {}

        def post(callback):
            if reject_post[0]:
                raise RuntimeError("owner temporarily unavailable")
            callbacks.append(callback)

        def sink(event):
            events.append(event.kind)
            if event.kind is BookOpenWorkerEventKind.FAILED:
                # A retained terminal is still being delivered on this owner
                # stack. Re-entering the drain must be a no-op, and a fresh Book
                # Open must not overtake the terminal transaction.
                holder["worker"].flush_pending_terminal()
                reentrant_flushes.append(True)
                try:
                    holder["worker"].start(Path("reentrant-book.md"))
                except BaseException as exc:
                    reentrant_start_errors.append(exc)

        worker = Version2BookOpenWorker(
            prepare=lambda source, *, cancel_check: "prepared-book",
            commit=commits.append,
            post_to_ui=post,
            event_sink=sink,
        )
        holder["worker"] = worker

        self.assertTrue(worker.start(Path("book.md"), focus_target="book-open"))
        self._wait(lambda: not worker.active)
        self.assertEqual(events, [BookOpenWorkerEventKind.STARTED])

        worker.flush_pending_terminal()

        self.assertEqual(reentrant_flushes, [True])
        self.assertEqual(len(reentrant_start_errors), 1)
        self.assertIsInstance(reentrant_start_errors[0], RuntimeError)
        self.assertIn("terminal delivery", str(reentrant_start_errors[0]))
        self.assertEqual(
            events,
            [BookOpenWorkerEventKind.STARTED, BookOpenWorkerEventKind.FAILED],
        )
        worker.flush_pending_terminal()
        self.assertEqual(
            events,
            [BookOpenWorkerEventKind.STARTED, BookOpenWorkerEventKind.FAILED],
        )

        # Once the accepted terminal transaction is retired, a new generation is
        # allowed to start normally and cannot inherit the stale terminal.
        reject_post[0] = False
        self.assertTrue(worker.start(Path("book-2.md"), focus_target="book-open-2"))
        self._wait(lambda: len(callbacks) == 1)
        callbacks.pop(0)()
        self.assertEqual(commits, ["prepared-book"])
        self.assertEqual(events[-2:], [
            BookOpenWorkerEventKind.STARTED,
            BookOpenWorkerEventKind.COMPLETED,
        ])
        self.assertTrue(worker.shutdown())



if __name__ == "__main__":
    unittest.main()
