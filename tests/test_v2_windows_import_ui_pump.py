from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch

from acs.version2_windows_file_workflows import FileWorkflowEvent, FileWorkflowEventKind
from acs.version2_windows_import_event_mailbox import Version2ImportUiEventMailbox
from acs.version2_windows_import_ui_pump import (
    Version2ImportUiWakeupPump,
    Version2WinFormsUiPoster,
)


def _run_thread(callback):
    errors: list[BaseException] = []

    def target() -> None:
        try:
            callback()
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=target, name="ui-pump-test-worker")
    worker.start()
    worker.join(5.0)
    if worker.is_alive():
        raise AssertionError("UI pump test worker did not terminate")
    return errors


class _QueuedPoster:
    def __init__(self) -> None:
        self.callbacks = []
        self.calls = 0
        self.fail_next = False

    def __call__(self, callback) -> None:
        self.calls += 1
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("poster failed")
        self.callbacks.append(callback)


class _CountedFailurePoster(_QueuedPoster):
    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures

    def __call__(self, callback) -> None:
        self.calls += 1
        if self.failures:
            self.failures -= 1
            raise RuntimeError("poster failed")
        self.callbacks.append(callback)


class _FakeControl:
    def __init__(self) -> None:
        self.IsDisposed = False
        self.Disposing = False
        self.delegates = []

    def BeginInvoke(self, delegate):
        self.delegates.append(delegate)
        return "posted"


class Version2ImportUiWakeupPumpTests(unittest.TestCase):
    def test_rejects_derived_event_before_field_hooks(self) -> None:
        touched: list[str] = []

        class ActiveEvent(FileWorkflowEvent):
            def __getattribute__(self, name: str):
                if name in {"kind", "action_id", "focus_target", "error_code"}:
                    touched.append(name)
                    raise AssertionError("derived pump event field hook executed")
                return super().__getattribute__(name)

        hostile = ActiveEvent.__new__(ActiveEvent)
        mailbox = Version2ImportUiEventMailbox()
        poster = _QueuedPoster()
        pump = Version2ImportUiWakeupPump(mailbox, poster, lambda: None)

        with self.assertRaisesRegex(TypeError, "exact FileWorkflowEvent"):
            pump.event_sink(hostile)
        with self.assertRaisesRegex(TypeError, "exact FileWorkflowEvent"):
            pump.owner_async_event_sink(hostile)

        self.assertEqual(touched, [])
        self.assertEqual(mailbox.pending_count, 0)
        self.assertEqual(poster.calls, 0)

    def test_winforms_poster_uses_begininvoke_without_owning_projection(self) -> None:
        control = _FakeControl()
        wrapped = []
        poster = Version2WinFormsUiPoster(
            control,
            delegate_factory=lambda callback: ("delegate", callback),
        )

        result = poster(lambda: wrapped.append("ran"))

        self.assertEqual(result, "posted")
        self.assertEqual(len(control.delegates), 1)
        marker, callback = control.delegates[0]
        self.assertEqual(marker, "delegate")
        callback()
        self.assertEqual(wrapped, ["ran"])

        control.IsDisposed = True
        with self.assertRaisesRegex(RuntimeError, "owner is closing"):
            poster(lambda: None)

    def test_ui_thread_event_is_not_posted_or_duplicated(self) -> None:
        mailbox = Version2ImportUiEventMailbox()
        poster = _QueuedPoster()
        delivered = []
        pump = Version2ImportUiWakeupPump(
            mailbox,
            poster,
            lambda: delivered.extend(mailbox.drain()),
        )
        event = FileWorkflowEvent(
            FileWorkflowEventKind.IMPORT_CANCELLING,
            "library.cancel_import",
            focus_target="library-import-cancel",
        )

        self.assertIs(pump(event), event)
        self.assertEqual(mailbox.pending_count, 0)
        self.assertEqual(poster.calls, 0)
        self.assertEqual(delivered, [])

    def test_worker_burst_posts_one_wakeup_and_drains_on_ui_thread(self) -> None:
        mailbox = Version2ImportUiEventMailbox(max_events=8)
        poster = _QueuedPoster()
        delivered = []
        pump = Version2ImportUiWakeupPump(
            mailbox,
            poster,
            lambda: delivered.extend(mailbox.drain()),
        )

        def produce() -> None:
            pump(
                FileWorkflowEvent(
                    FileWorkflowEventKind.IMPORT_STARTED,
                    "library.import",
                    focus_target="library-import-cancel",
                    total_games=100,
                )
            )
            for value in range(101):
                pump(
                    FileWorkflowEvent(
                        FileWorkflowEventKind.IMPORT_PROGRESS,
                        "library.import",
                        processed_games=value,
                        total_games=100,
                    )
                )
            pump(
                FileWorkflowEvent(
                    FileWorkflowEventKind.IMPORT_COMPLETED,
                    "library.import",
                    focus_target="library-import-file",
                    processed_games=100,
                    total_games=100,
                    game_count=100,
                )
            )

        self.assertEqual(_run_thread(produce), [])
        self.assertEqual(poster.calls, 1)
        self.assertEqual(len(poster.callbacks), 1)
        self.assertTrue(pump.wakeup_pending)
        self.assertEqual(mailbox.pending_count, 3)

        poster.callbacks.pop(0)()

        self.assertFalse(pump.wakeup_pending)
        self.assertEqual(mailbox.pending_count, 0)
        self.assertEqual(
            [event.kind for event in delivered],
            [
                FileWorkflowEventKind.IMPORT_STARTED,
                FileWorkflowEventKind.IMPORT_PROGRESS,
                FileWorkflowEventKind.IMPORT_COMPLETED,
            ],
        )
        self.assertEqual(delivered[1].processed_games, 100)
        self.assertEqual(poster.calls, 1)

    def test_post_failure_preserves_mailbox_and_next_worker_event_can_retry(self) -> None:
        mailbox = Version2ImportUiEventMailbox()
        poster = _QueuedPoster()
        poster.fail_next = True
        delivered = []
        pump = Version2ImportUiWakeupPump(
            mailbox,
            poster,
            lambda: delivered.extend(mailbox.drain()),
        )
        first = FileWorkflowEvent(
            FileWorkflowEventKind.IMPORT_STARTED,
            "library.import",
            total_games=2,
        )
        second = FileWorkflowEvent(
            FileWorkflowEventKind.IMPORT_PROGRESS,
            "library.import",
            processed_games=1,
            total_games=2,
        )

        errors = _run_thread(lambda: pump(first))
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertEqual(mailbox.pending_count, 1)
        self.assertFalse(pump.wakeup_pending)
        self.assertEqual(pump.post_failure_count, 1)

        self.assertEqual(_run_thread(lambda: pump(second)), [])
        self.assertEqual(len(poster.callbacks), 1)
        poster.callbacks.pop(0)()
        self.assertEqual(
            [event.kind for event in delivered],
            [
                FileWorkflowEventKind.IMPORT_STARTED,
                FileWorkflowEventKind.IMPORT_PROGRESS,
            ],
        )
        self.assertEqual(mailbox.pending_count, 0)

    def test_post_failure_automatically_retries_pending_terminal_event_once(self) -> None:
        mailbox = Version2ImportUiEventMailbox()
        poster = _QueuedPoster()
        poster.fail_next = True
        delivered = []
        pump = Version2ImportUiWakeupPump(
            mailbox,
            poster,
            lambda: delivered.extend(mailbox.drain()),
        )
        terminal = FileWorkflowEvent(
            FileWorkflowEventKind.IMPORT_COMPLETED,
            "library.import",
            focus_target="library-import-file",
            processed_games=1,
            total_games=1,
            game_count=1,
        )

        errors = _run_thread(lambda: pump(terminal))
        self.assertEqual(len(errors), 1)
        self.assertEqual(mailbox.pending_count, 1)

        deadline = time.monotonic() + 1.0
        while not poster.callbacks and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(len(poster.callbacks), 1)
        self.assertEqual(poster.calls, 2)
        self.assertTrue(pump.wakeup_pending)

        poster.callbacks.pop(0)()
        self.assertEqual(delivered, [terminal])
        self.assertEqual(mailbox.pending_count, 0)
        self.assertFalse(pump.wakeup_pending)

    def test_baseexception_post_failure_preserves_terminal_and_auto_recovers(self) -> None:
        class PosterAbort(BaseException):
            pass

        class AbortOncePoster(_QueuedPoster):
            def __call__(self, callback) -> None:
                self.calls += 1
                if self.calls == 1:
                    raise PosterAbort("UI poster aborted")
                self.callbacks.append(callback)

        mailbox = Version2ImportUiEventMailbox()
        poster = AbortOncePoster()
        delivered = []
        pump = Version2ImportUiWakeupPump(
            mailbox,
            poster,
            lambda: delivered.extend(mailbox.drain()),
        )
        terminal = FileWorkflowEvent(
            FileWorkflowEventKind.IMPORT_COMPLETED,
            "library.import",
            focus_target="library-import-file",
            processed_games=1,
            total_games=1,
            game_count=1,
        )

        with patch(
            "acs.version2_windows_import_ui_pump._AUTO_RETRY_DELAY_SECONDS",
            0.01,
        ):
            errors = _run_thread(lambda: pump(terminal))
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], RuntimeError)
            self.assertEqual(mailbox.pending_count, 1)
            deadline = time.monotonic() + 1.0
            while not poster.callbacks and time.monotonic() < deadline:
                time.sleep(0.01)

        self.assertEqual(poster.calls, 2)
        self.assertEqual(pump.post_failure_count, 1)
        self.assertEqual(len(poster.callbacks), 1)
        poster.callbacks.pop(0)()
        self.assertEqual(delivered, [terminal])
        self.assertEqual(mailbox.pending_count, 0)
        self.assertFalse(pump.wakeup_pending)

    def test_owner_post_baseexception_retains_callback_and_retries(self) -> None:
        class PosterAbort(BaseException):
            pass

        class AbortOncePoster(_QueuedPoster):
            def __call__(self, callback) -> None:
                self.calls += 1
                if self.calls == 1:
                    raise PosterAbort("owner poster aborted")
                self.callbacks.append(callback)

        mailbox = Version2ImportUiEventMailbox()
        poster = AbortOncePoster()
        delivered: list[str] = []
        pump = Version2ImportUiWakeupPump(mailbox, poster, lambda: None)

        with patch(
            "acs.version2_windows_import_ui_pump._AUTO_RETRY_DELAY_SECONDS",
            0.01,
        ):
            self.assertEqual(
                _run_thread(
                    lambda: pump.post_owner_callback(
                        lambda: delivered.append("owner-complete")
                    )
                ),
                [],
            )
            self.assertTrue(pump.owner_callback_pending)
            deadline = time.monotonic() + 1.0
            while not poster.callbacks and time.monotonic() < deadline:
                time.sleep(0.01)

        self.assertEqual(poster.calls, 2)
        self.assertEqual(pump.owner_post_failure_count, 1)
        self.assertEqual(len(poster.callbacks), 1)
        poster.callbacks.pop(0)()
        self.assertEqual(delivered, ["owner-complete"])
        self.assertFalse(pump.owner_callback_pending)

    def test_owner_callback_post_failure_retries_exact_callback_once(self) -> None:
        mailbox = Version2ImportUiEventMailbox()
        poster = _CountedFailurePoster(1)
        delivered: list[int] = []
        pump = Version2ImportUiWakeupPump(mailbox, poster, lambda: None)
        errors = _run_thread(
            lambda: pump.post_owner_callback(
                lambda: delivered.append(threading.get_ident())
            )
        )
        self.assertEqual(errors, [])
        self.assertTrue(pump.owner_callback_pending)
        deadline = time.monotonic() + 1.0
        while not poster.callbacks and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(poster.calls, 2)
        self.assertEqual(pump.owner_post_failure_count, 1)
        self.assertEqual(len(poster.callbacks), 1)
        poster.callbacks.pop(0)()
        self.assertEqual(delivered, [mailbox.ui_thread_id])
        self.assertFalse(pump.owner_callback_pending)

    def test_owner_callback_survives_failed_retry_and_owner_can_recover(self) -> None:
        mailbox = Version2ImportUiEventMailbox()
        poster = _CountedFailurePoster(2)
        delivered = []
        pump = Version2ImportUiWakeupPump(mailbox, poster, lambda: None)
        with patch("acs.version2_windows_import_ui_pump._AUTO_RETRY_DELAY_SECONDS", 0.01):
            errors = _run_thread(
                lambda: pump.post_owner_callback(lambda: delivered.append("done"))
            )
            self.assertEqual(errors, [])
            deadline = time.monotonic() + 1.0
            while poster.calls < 2 and time.monotonic() < deadline:
                time.sleep(0.01)
        self.assertEqual(poster.calls, 2)
        self.assertEqual(poster.callbacks, [])
        self.assertTrue(pump.owner_callback_pending)
        self.assertEqual(pump.owner_post_failure_count, 2)
        self.assertTrue(pump.request_pending_owner_callback())
        self.assertEqual(delivered, ["done"])
        self.assertFalse(pump.owner_callback_pending)

    def test_close_cancels_scheduled_owner_callback_retry(self) -> None:
        mailbox = Version2ImportUiEventMailbox()
        poster = _CountedFailurePoster(1)
        pump = Version2ImportUiWakeupPump(mailbox, poster, lambda: None)
        with patch("acs.version2_windows_import_ui_pump._AUTO_RETRY_DELAY_SECONDS", 0.2):
            self.assertEqual(
                _run_thread(lambda: pump.post_owner_callback(lambda: None)), []
            )
            self.assertTrue(pump.owner_callback_pending)
            pump.close()
            time.sleep(0.25)
        self.assertTrue(pump.closed)
        self.assertFalse(pump.owner_callback_pending)
        self.assertEqual(poster.calls, 1)
        self.assertEqual(poster.callbacks, [])

    def test_close_cancels_scheduled_automatic_retry(self) -> None:
        mailbox = Version2ImportUiEventMailbox()
        poster = _QueuedPoster()
        poster.fail_next = True
        pump = Version2ImportUiWakeupPump(mailbox, poster, lambda: mailbox.drain())
        terminal = FileWorkflowEvent(
            FileWorkflowEventKind.IMPORT_CANCELLED,
            "library.import",
            focus_target="library-import-file",
        )

        with patch("acs.version2_windows_import_ui_pump._AUTO_RETRY_DELAY_SECONDS", 0.2):
            errors = _run_thread(lambda: pump(terminal))
            self.assertEqual(len(errors), 1)
            pump.close()
            time.sleep(0.25)

        self.assertTrue(pump.closed)
        self.assertEqual(poster.calls, 1)
        self.assertEqual(poster.callbacks, [])

    def test_wrong_thread_wakeup_fails_closed_and_ui_can_recover_pending_events(self) -> None:
        mailbox = Version2ImportUiEventMailbox()
        poster = _QueuedPoster()
        delivered = []
        pump = Version2ImportUiWakeupPump(
            mailbox,
            poster,
            lambda: delivered.extend(mailbox.drain()),
        )
        event = FileWorkflowEvent(
            FileWorkflowEventKind.IMPORT_CANCELLED,
            "library.import",
            focus_target="library-import-file",
        )

        self.assertEqual(_run_thread(lambda: pump(event)), [])
        callback = poster.callbacks.pop(0)
        errors = _run_thread(callback)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertFalse(pump.wakeup_pending)
        self.assertEqual(mailbox.pending_count, 1)
        self.assertEqual(delivered, [])

        self.assertTrue(pump.request_pending_wakeup())
        self.assertEqual(delivered, [event])
        self.assertEqual(mailbox.pending_count, 0)

    def test_ready_failure_does_not_escape_ui_loop_and_pending_event_can_be_retried(self) -> None:
        mailbox = Version2ImportUiEventMailbox()
        poster = _QueuedPoster()
        calls = []

        class ProjectionAbort(BaseException):
            pass

        def failing_ready() -> None:
            calls.append("failed")
            raise ProjectionAbort("projection unavailable")

        pump = Version2ImportUiWakeupPump(mailbox, poster, failing_ready)
        event = FileWorkflowEvent(
            FileWorkflowEventKind.IMPORT_EMPTY,
            "library.import",
            focus_target="library-import-file",
        )
        self.assertEqual(_run_thread(lambda: pump(event)), [])
        poster.callbacks.pop(0)()
        self.assertEqual(calls, ["failed"])
        self.assertEqual(pump.ready_failure_count, 1)
        self.assertEqual(mailbox.pending_count, 1)

        pump.close()
        delivered = []
        recovery = Version2ImportUiWakeupPump(
            mailbox,
            _QueuedPoster(),
            lambda: delivered.extend(mailbox.drain()),
        )
        self.assertTrue(recovery.request_pending_wakeup())
        self.assertEqual(delivered, [event])
        self.assertEqual(mailbox.pending_count, 0)

    def test_close_stops_future_worker_wakeups(self) -> None:
        mailbox = Version2ImportUiEventMailbox()
        poster = _QueuedPoster()
        pump = Version2ImportUiWakeupPump(mailbox, poster, lambda: mailbox.drain())
        pump.close()
        event = FileWorkflowEvent(
            FileWorkflowEventKind.IMPORT_CANCELLED,
            "library.import",
            focus_target="library-import-file",
        )

        self.assertEqual(_run_thread(lambda: pump(event)), [])
        self.assertTrue(pump.closed)
        self.assertEqual(poster.calls, 0)
        self.assertEqual(mailbox.pending_count, 0)


if __name__ == "__main__":
    unittest.main()
