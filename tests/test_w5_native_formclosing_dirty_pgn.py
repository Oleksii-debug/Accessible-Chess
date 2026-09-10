from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest

from acs.full_product_native_menu import NativeMenuItemKind
from acs.version2_application import Version2Application
from acs.version2_profile import (
    Version2NativeMenuController,
    build_version2_router,
    build_version2_shell,
    build_version2_webview_adapter,
)
from acs.version2_release_app import (
    _Version2OwnedBookDialogs,
    _install_close_guard_or_shutdown,
    _install_unsaved_pgn_close_guard,
)
from acs.version2_release_ui import (
    Version2ReleaseAccessibleChessAPI,
    run_version2_release_window,
)


class _FormClosingEvent:
    def __init__(self) -> None:
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self):
        event = SimpleNamespace(Cancel=False)
        for handler in tuple(self.handlers):
            handler(None, event)
        return event


class _OwnerForm:
    def __init__(self) -> None:
        self.FormClosing = _FormClosingEvent()
        self.InvokeRequired = False
        self.IsDisposed = False
        self.Disposing = False
        self.sources = []

    def request_close(self, source: str):
        self.sources.append(source)
        return self.FormClosing.fire()


class _Dialogs:
    def __init__(self, *results, error: Exception | None = None) -> None:
        self.results = list(results) or [True]
        self.error = error
        self.calls = 0

    def confirm_discard_unsaved_pgn_on_exit(self) -> bool:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if len(self.results) > 1:
            return bool(self.results.pop(0))
        return bool(self.results[0])


class _LifecycleFiles:
    def __init__(self, trace, *, result: bool = True) -> None:
        self.trace = trace
        self.result = result
        self.timeouts = []

    def shutdown(self, timeout=None):
        self.timeouts.append(timeout)
        self.trace.append("import-cancel-join")
        return self.result


class _LifecycleProgress:
    def __init__(self, trace) -> None:
        self.trace = trace

    def save(self, key, reader) -> None:
        self.trace.append(("book-progress-save", key, reader))


class _LifecycleDatabase:
    def __init__(self, trace) -> None:
        self.trace = trace
        self.closed = 0

    def close(self) -> None:
        self.trace.append("database-close")
        self.closed += 1


class _UnboundRuntime:
    def __init__(self, result=True) -> None:
        self.result = result
        self.shutdown_calls = 0

    def shutdown(self):
        self.shutdown_calls += 1
        return self.result


def _lifecycle_application(*, dirty: bool, content: str = "edited PGN"):
    trace = []
    application = Version2Application.__new__(Version2Application)
    application._thread = threading.get_ident()
    application._files = _LifecycleFiles(trace)
    application.reader = object()
    application.book_key = "book-key"
    application.progress_store = _LifecycleProgress(trace)
    application.database = _LifecycleDatabase(trace)
    application.session = SimpleNamespace(dirty=dirty, content=content)
    return application, trace


def _file_exit(controller: Version2NativeMenuController) -> None:
    file_menu = next(menu for menu in controller.spec() if menu.menu_id == "file")
    exit_item = next(item for item in file_menu.items if item.kind is NativeMenuItemKind.HOST)
    controller.activate(exit_item)


class _Event:
    def __init__(self) -> None:
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self):
        return [handler() for handler in tuple(self.handlers)]


class _Events:
    def __init__(self) -> None:
        self.before_show = _Event()
        self.loaded = _Event()
        self.closing = _Event()


class _ReleaseApplication:
    def __init__(self) -> None:
        self.shell = build_version2_shell()
        self.router = build_version2_router(
            self.shell, lambda action, payload: {"action": action, "payload": payload}
        )
        self.adapter = build_version2_webview_adapter(self.shell, self.router)
        self._focus = ""
        self.session = SimpleNamespace(dirty=True, content="unsaved")
        self.files = None
        self.shutdown_calls = 0

    def _assert_thread(self):
        return None

    def snapshot(self):
        return {**self.adapter.snapshot(), "pgn": None, "library": {}, "books": None}

    def browser_command(self, area, command, payload=None):
        return {"kind": "delegated", "payload": {}}

    def drain_events(self):
        return ()

    def record_focus(self, token):
        self._focus = token

    def native_command(self, value):
        return None

    def bind_files(self, runtime):
        self.files = runtime

    def shutdown(self):
        self.shutdown_calls += 1
        return True


class _ReleaseWindow:
    def __init__(self, owner: _OwnerForm, application: _ReleaseApplication) -> None:
        self.owner = owner
        self.application = application
        self.events = _Events()
        self.sources = []
        self.destroyed = False
        self.shutdown_calls_after_pywebview_closing = None

    def evaluate_js(self, source):
        self.sources.append(source)

    def destroy(self):
        # Exercise the dangerous order explicitly: pywebview's abstract closing
        # callback first, then the real WinForms FormClosing event.
        self.events.closing.fire()
        self.shutdown_calls_after_pywebview_closing = self.application.shutdown_calls
        event = self.owner.request_close("programmatic-window-destroy")
        if not event.Cancel:
            self.destroyed = True


class _WebView:
    def __init__(self, owner: _OwnerForm, application: _ReleaseApplication) -> None:
        self.window = _ReleaseWindow(owner, application)
        self.created = None
        self.started = None

    def create_window(self, title, **kwargs):
        self.created = (title, kwargs)
        return self.window

    def start(self, **kwargs):
        self.started = kwargs
        self.window.events.before_show.fire()
        self.window.events.loaded.fire()
        controller = self.window._accessible_chess_native_menu_controller
        _file_exit(controller)


class W5NativeFormClosingDirtyPgnTests(unittest.TestCase):
    def test_owner_bound_exit_confirmation_uses_exact_form(self) -> None:
        owner = _OwnerForm()
        captured = []
        DialogResult = SimpleNamespace(Yes="yes")

        class MessageBox:
            @staticmethod
            def Show(actual_owner, text, title, buttons, icon):
                captured.append((actual_owner, text, title, buttons, icon))
                return "yes"

        dialogs = _Version2OwnedBookDialogs(
            lambda: owner,
            forms_loader=lambda: (DialogResult, object, object),
            message_box_loader=lambda: (MessageBox, SimpleNamespace(YesNo="yes-no"), SimpleNamespace(Warning="warning")),
        )

        self.assertTrue(dialogs.confirm_discard_unsaved_pgn_on_exit())
        self.assertEqual(len(captured), 1)
        self.assertIs(captured[0][0], owner)

    def test_clean_pgn_closes_without_prompt_and_runs_normal_cleanup(self) -> None:
        application, trace = _lifecycle_application(dirty=False)
        owner = _OwnerForm()
        dialogs = _Dialogs(False)

        _install_unsaved_pgn_close_guard(application, owner, dialogs)
        event = owner.request_close("clean")

        self.assertFalse(event.Cancel)
        self.assertEqual(dialogs.calls, 0)
        self.assertEqual(application._files.timeouts, [None])
        self.assertEqual(trace[0], "import-cancel-join")
        self.assertEqual(trace[1][0], "book-progress-save")
        self.assertEqual(trace[2], "database-close")
        self.assertTrue(application._native_close_shutdown_complete)

    def test_dirty_refusal_and_confirmation_failure_preserve_content_before_shutdown(self) -> None:
        for label, dialogs in (
            ("no", _Dialogs(False)),
            ("failure", _Dialogs(error=RuntimeError("synthetic dialog failure"))),
        ):
            with self.subTest(label=label):
                application, trace = _lifecycle_application(dirty=True, content="must survive")
                owner = _OwnerForm()
                _install_unsaved_pgn_close_guard(application, owner, dialogs)

                event = owner.request_close(label)

                self.assertTrue(event.Cancel)
                self.assertEqual(dialogs.calls, 1)
                self.assertEqual(trace, [])
                self.assertTrue(application.session.dirty)
                self.assertEqual(application.session.content, "must survive")
                self.assertFalse(getattr(application, "_native_close_shutdown_complete", False))

    def test_dirty_yes_cleans_import_book_and_database_once(self) -> None:
        application, trace = _lifecycle_application(dirty=True)
        owner = _OwnerForm()
        dialogs = _Dialogs(True)

        _install_unsaved_pgn_close_guard(application, owner, dialogs)
        event = owner.request_close("accepted")

        self.assertFalse(event.Cancel)
        self.assertEqual(dialogs.calls, 1)
        self.assertEqual(application._files.timeouts, [None])
        self.assertEqual(trace[0], "import-cancel-join")
        self.assertEqual(trace[1][0], "book-progress-save")
        self.assertEqual(trace[2], "database-close")
        self.assertEqual(application.database.closed, 1)

    def test_cleanup_refusal_cancels_native_close(self) -> None:
        application, trace = _lifecycle_application(dirty=False)
        application._files.result = False
        owner = _OwnerForm()
        dialogs = _Dialogs(True)

        _install_unsaved_pgn_close_guard(application, owner, dialogs)
        event = owner.request_close("worker-still-alive")

        self.assertTrue(event.Cancel)
        self.assertEqual(dialogs.calls, 0)
        self.assertEqual(trace, ["import-cancel-join"])
        self.assertEqual(application.database.closed, 0)
        self.assertFalse(getattr(application, "_native_close_shutdown_complete", False))

    def test_file_exit_alt_f4_title_x_and_programmatic_close_share_one_boundary(self) -> None:
        for source in ("file-exit", "alt-f4", "title-bar-x", "programmatic-host-close"):
            with self.subTest(source=source):
                application, trace = _lifecycle_application(dirty=True)
                owner = _OwnerForm()
                dialogs = _Dialogs(True)
                _install_unsaved_pgn_close_guard(application, owner, dialogs)

                if source == "file-exit":
                    shell = build_version2_shell()
                    router = build_version2_router(shell, lambda *_: None)
                    adapter = build_version2_webview_adapter(shell, router)
                    controller = Version2NativeMenuController(
                        adapter,
                        lambda _command: None,
                        exit_callback=lambda: owner.request_close(source),
                    )
                    _file_exit(controller)
                else:
                    owner.request_close(source)

                self.assertEqual(dialogs.calls, 1)
                self.assertEqual(application._files.timeouts, [None])
                self.assertEqual(trace.count("import-cancel-join"), 1)
                self.assertEqual(trace.count("database-close"), 1)
                self.assertEqual(owner.sources, [source])

    def test_refusal_can_retry_without_duplicate_prompt_in_one_attempt(self) -> None:
        application, trace = _lifecycle_application(dirty=True, content="retry-safe")
        owner = _OwnerForm()
        dialogs = _Dialogs(False, True)
        _install_unsaved_pgn_close_guard(application, owner, dialogs)

        first = owner.request_close("first")
        self.assertTrue(first.Cancel)
        self.assertEqual(dialogs.calls, 1)
        self.assertEqual(trace, [])
        self.assertEqual(application.session.content, "retry-safe")

        second = owner.request_close("second")
        self.assertFalse(second.Cancel)
        self.assertEqual(dialogs.calls, 2)
        self.assertEqual(trace.count("import-cancel-join"), 1)
        self.assertEqual(trace.count("database-close"), 1)

    def test_duplicate_guard_installation_is_rejected(self) -> None:
        application, _ = _lifecycle_application(dirty=False)
        owner = _OwnerForm()
        dialogs = _Dialogs(True)

        _install_unsaved_pgn_close_guard(application, owner, dialogs)
        with self.assertRaisesRegex(RuntimeError, "already installed"):
            _install_unsaved_pgn_close_guard(application, owner, dialogs)
        self.assertEqual(len(owner.FormClosing.handlers), 1)

    def test_unbound_file_runtime_is_closed_when_guard_installation_fails(self) -> None:
        application, _ = _lifecycle_application(dirty=False)
        runtime = _UnboundRuntime()
        dialogs = _Dialogs(True)

        with self.assertRaisesRegex(RuntimeError, "does not expose FormClosing"):
            _install_close_guard_or_shutdown(runtime, application, object(), dialogs)
        self.assertEqual(runtime.shutdown_calls, 1)

    def test_pywebview_closing_never_preempts_native_guard_or_duplicates_shutdown(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        api = Version2ReleaseAccessibleChessAPI(keymap_path=Path(temp.name) / "keymap.json")
        application = _ReleaseApplication()
        owner = _OwnerForm()
        dialogs = _Dialogs(True)
        webview = _WebView(owner, application)
        runtime = object()

        def install_menu(window, controller):
            window._accessible_chess_native_menu_host = owner
            window._accessible_chess_native_menu_controller = controller
            return True

        def build_files(actual_owner):
            self.assertIs(actual_owner, owner)
            _install_unsaved_pgn_close_guard(application, owner, dialogs)
            return runtime

        run_version2_release_window(
            api,
            application,
            webview_module=webview,
            menu_installer=install_menu,
            file_runtime_factory=build_files,
        )

        self.assertTrue(webview.window.destroyed)
        self.assertEqual(webview.window.shutdown_calls_after_pywebview_closing, 0)
        self.assertEqual(dialogs.calls, 1)
        self.assertEqual(application.shutdown_calls, 1)
        self.assertTrue(application._native_close_shutdown_complete)


if __name__ == "__main__":
    unittest.main()
