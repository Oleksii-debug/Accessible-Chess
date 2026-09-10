from __future__ import annotations

"""Production-facing Version 2 WebView composition over the frozen Stage 1 board.

The Version 2 host deliberately keeps the existing ``web/index.html`` and its
64-square board as the only chess UI/state authority.  It adds the accepted V2
shell/PGN/Library/Books projections around that document and routes native menu
commands through the same V2 adapter.  No chess, PGN, database or Book semantics
live in this module.
"""

from collections.abc import Mapping
from functools import wraps
import threading
from typing import Any, Callable

from .full_product_native_menu import install_full_product_windows_native_menu
from .stage1_release_ui import Stage1ReleaseAccessibleChessAPI, _asset_root
from .ui_native_menu import _resolve_windows_host_form
from .version2_profile import Version2NativeMenuController


class Version2ReleaseAccessibleChessAPI(Stage1ReleaseAccessibleChessAPI):
    """One pywebview API object for the frozen board and accepted V2 shell.

    Stage 1 public methods remain inherited unchanged.  V2 methods are explicit
    additions so pywebview does not need a second ``js_api`` object and therefore
    cannot accidentally create a second board/engine authority.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._ui_thread = threading.get_ident()
        self._ui_owner: Any | None = None
        self._ui_action: Callable | None = None
        self._ui_closed = False
        super().__init__(*args, **kwargs)
        self._version2_application: Any | None = None

    def _bind_ui_owner(self, owner: Any, *, action_factory: Callable | None = None) -> None:
        """Trusted host seam: called on the actual Form thread before DB creation."""
        if owner is None or getattr(owner, "InvokeRequired", True):
            raise RuntimeError("Version 2 native UI owner thread is required")
        if self._ui_owner is not None and self._ui_owner is not owner:
            raise RuntimeError("Version 2 native UI owner is already bound")
        if action_factory is None:
            from System import Action  # type: ignore
            action_factory = Action
        self._ui_owner, self._ui_action = owner, action_factory
        self._ui_thread = threading.get_ident()

    def _invoke_ui(self, callback: Callable[[], Any]) -> Any:
        if self._ui_closed:
            raise RuntimeError("Version 2 application is closed")
        if threading.get_ident() == self._ui_thread:
            return callback()
        owner, action = self._ui_owner, self._ui_action
        if owner is None or action is None or getattr(owner, "IsDisposed", True):
            raise RuntimeError("Version 2 native UI is unavailable")
        results, errors = [], []

        def invoke() -> None:
            try:
                if self._ui_closed:
                    raise RuntimeError("Version 2 application is closed")
                results.append(callback())
            except Exception as error:
                errors.append(error)

        owner.Invoke(action(invoke))
        if errors:
            raise errors[0]
        if not results:
            raise RuntimeError("Version 2 UI command did not complete")
        return results[0]

    def bind_version2_application(self, application: Any) -> None:
        if self._version2_application is not None and self._version2_application is not application:
            raise RuntimeError("Version 2 application is already bound")
        for name in (
            "snapshot",
            "browser_command",
            "drain_events",
            "record_focus",
            "native_command",
            "shutdown",
        ):
            if not callable(getattr(application, name, None)):
                raise TypeError("Version 2 application host contract is incomplete")
        if getattr(application, "adapter", None) is None:
            raise TypeError("Version 2 application requires its accepted WebView adapter")
        self._version2_application = application

    def _version2(self) -> Any:
        application = self._version2_application
        if application is None:
            raise RuntimeError("Version 2 application is not bound")
        return application

    def v2_snapshot(self) -> dict[str, object]:
        return self._version2().snapshot()

    def v2_browser_command(
        self,
        area: str,
        command: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        return self._version2().browser_command(area, command, payload)

    def v2_drain_events(self) -> tuple[dict[str, object], ...]:
        return tuple(self._version2().drain_events())

    def v2_record_focus(self, token: str) -> None:
        self._version2().record_focus(token)

    def v2_board_dispatch(
        self,
        action_id: str,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        """Delegate V2 board/global actions to the canonical Stage 1 API.

        The only payload accepted at this seam is an optional board square.  All
        richer V2 domain payloads remain owned by their format/library adapters.
        """

        if not isinstance(action_id, str) or not action_id.strip():
            raise ValueError("board action id is required")
        values = {} if payload is None else payload
        if not isinstance(values, Mapping):
            raise TypeError("board action payload must be a mapping")
        square: str | None = None
        if values:
            if set(values) != {"square"} or not isinstance(values.get("square"), str):
                raise ValueError("board action payload is not supported")
            square = str(values["square"])
        result = self.dispatch_action(action_id.strip(), square)
        if not isinstance(result, dict):
            raise RuntimeError("canonical board action returned an invalid result")
        if result.get("ok") is False:
            raise ValueError("canonical board action was rejected")
        return result


def _ui_method(method: Callable) -> Callable:
    @wraps(method)
    def invoke(self, *args, **kwargs):
        return self._invoke_ui(lambda: method(self, *args, **kwargs))
    return invoke


# pywebview invokes public API methods on background threads. Serialize the
# inherited board API as well as V2 commands on the same native owner, retaining
# signatures for pywebview's introspection and the original Stage 1 implementation.
for _name in dir(Version2ReleaseAccessibleChessAPI):
    _method = getattr(Version2ReleaseAccessibleChessAPI, _name)
    if not _name.startswith("_") and callable(_method):
        setattr(Version2ReleaseAccessibleChessAPI, _name, _ui_method(_method))


def _resource_sources() -> tuple[tuple[str, str], ...]:
    root = _asset_root() / "web"
    resources = (
        ("Stage 1 WebView bootstrap", root / "stage1_release_bootstrap.js"),
        ("Stage 1 board action bridge", root / "stage1_board_actions.js"),
        ("V2 PGN surface", root / "full_product_pgn.js"),
        ("V2 Library surface", root / "full_product_library.js"),
        ("V2 Books surface", root / "full_product_books_training.js"),
        ("V2 release bootstrap", root / "version2_release_bootstrap.js"),
    )
    output: list[tuple[str, str]] = []
    for label, path in resources:
        if not path.exists():
            raise RuntimeError(f"{label} not found in packaged resources.")
        output.append((label, path.read_text(encoding="utf-8")))
    return tuple(output)


def run_version2_release_window(
    api: Version2ReleaseAccessibleChessAPI,
    application: Any,
    runtime: Any | None = None,
    *,
    webview_module: Any | None = None,
    menu_installer: Callable[[Any, Any], bool] = install_full_product_windows_native_menu,
    file_runtime_factory: Callable[[object], Any] | None = None,
    loaded_hook: Callable[[Any], None] | None = None,
) -> None:
    """Run V2 on the original Stage 1 document and real Edge/WebView2 host."""

    if not isinstance(api, Version2ReleaseAccessibleChessAPI):
        raise TypeError("V2 release window requires Version2ReleaseAccessibleChessAPI")
    if not callable(menu_installer):
        raise TypeError("V2 native menu installer must be callable")
    if file_runtime_factory is not None and not callable(file_runtime_factory):
        raise TypeError("V2 file runtime factory must be callable or None")
    application_factory = application if callable(application) else None
    if application_factory is not None:
        application = None
    else:
        api.bind_version2_application(application)

    html = _asset_root() / "web" / "index.html"
    if not html.exists():
        if runtime is not None:
            runtime.close()
        raise RuntimeError("Accessible HTML UI not found in packaged resources.")
    sources = _resource_sources()

    if webview_module is None:
        import webview as webview_module  # type: ignore[no-redef]

    window = webview_module.create_window(
        "Accessible Chess",
        url=str(html),
        js_api=api,
        width=1150,
        height=820,
        min_size=(800, 600),
        text_select=True,
    )

    def exit_application() -> None:
        destroy = getattr(window, "destroy", None)
        if callable(destroy):
            destroy()

    native_files: Any | None = None
    application_closed = False
    startup_errors: list[Exception] = []

    def close_application(*_args: Any) -> bool:
        nonlocal application_closed
        if application is not None and not application_closed:
            # A production native FormClosing guard shuts application-owned state
            # down while the owner Form is still alive.  The release loop only
            # records that completed shutdown here; it must never run it twice.
            if getattr(application, "_native_close_shutdown_complete", False):
                application_closed = True
            else:
                if not api._invoke_ui(application.shutdown):
                    return False
                application_closed = True
        api._ui_closed = True
        return True

    def window_closing_without_destructive_shutdown(*_args: Any) -> bool:
        # pywebview's closing event can run before or after later WinForms
        # FormClosing subscribers.  Once the native guard exists, doing cleanup
        # here would make refusal too late and would duplicate the accepted path.
        if application is not None and getattr(
            application, "_native_unsaved_close_guard", None
        ) is not None:
            return True
        return close_application()

    def install_menu_on_native_host(*_args: Any) -> None:
        nonlocal application, native_files
        if application_factory is not None:
            owner = _resolve_windows_host_form(window)
            api._bind_ui_owner(owner)
            application = application_factory()
            api.bind_version2_application(application)
        elif api._ui_owner is None:
            # Real already-composed applications must already belong to this
            # thread; never migrate an open SQLite connection to another thread.
            assert_thread = getattr(application, "_assert_thread", None)
            if callable(assert_thread):
                assert_thread()
        controller = Version2NativeMenuController(
            application.adapter,
            application.native_command,
            exit_callback=exit_application,
            current_focus_provider=lambda: str(getattr(application, "_focus", "")),
        )
        if not menu_installer(window, controller):
            raise RuntimeError("Accessible Version 2 native Windows menu could not be attached.")
        if file_runtime_factory is None or native_files is not None:
            return
        owner = getattr(window, "_accessible_chess_native_menu_host", None)
        if owner is None:
            raise RuntimeError("Accessible Version 2 native Windows owner could not be resolved.")
        native_files = file_runtime_factory(owner)
        application.bind_files(native_files)

    def start_native_host(*_args: Any) -> None:
        try:
            install_menu_on_native_host()
        except Exception as error:
            # pywebview logs event-handler exceptions and continues by default.
            # Retain failure for the caller and close before exposing a partial UI.
            startup_errors.append(error)
            close_application()
            window.destroy()
            raise

    def install_release_web_contract(*_args: Any) -> None:
        if startup_errors:
            return
        for _label, source in sources:
            window.evaluate_js(source)
        if loaded_hook is not None:
            loaded_hook(window)

    window.events.before_show += start_native_host
    window.events.loaded += install_release_web_contract
    closing = getattr(window.events, "closing", None)
    if closing is not None:
        window.events.closing += window_closing_without_destructive_shutdown
    try:
        webview_module.start(gui="edgechromium", private_mode=True)
        if startup_errors:
            raise startup_errors[0]
    finally:
        try:
            if application is not None and not application_closed:
                close_application()
        finally:
            try:
                # Engine cleanup has no SQLite/UI work and runs after Form disposal.
                Stage1ReleaseAccessibleChessAPI.close_analysis(api)
            finally:
                if runtime is not None:
                    runtime.close()


__all__ = [
    "Version2ReleaseAccessibleChessAPI",
    "run_version2_release_window",
]
