from __future__ import annotations

"""Production-facing Version 2 WebView composition over the frozen Stage 1 board.

The Version 2 host deliberately keeps the existing ``web/index.html`` and its
64-square board as the only chess UI/state authority.  It adds the accepted V2
shell/PGN/Library/Books projections around that document and routes native menu
commands through the same V2 adapter.  No chess, PGN, database or Book semantics
live in this module.
"""

from collections.abc import Mapping
from typing import Any, Callable

from .full_product_native_menu import install_full_product_windows_native_menu
from .full_product_ui_shell import UILanguage
from .stage1_release_ui import Stage1ReleaseAccessibleChessAPI, _asset_root
from .version2_profile import Version2NativeMenuController


class Version2ReleaseAccessibleChessAPI(Stage1ReleaseAccessibleChessAPI):
    """One pywebview API object for the frozen board and accepted V2 shell.

    Stage 1 public methods remain inherited unchanged.  V2 methods are explicit
    additions so pywebview does not need a second ``js_api`` object and therefore
    cannot accidentally create a second board/engine authority.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._version2_application: Any | None = None

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

    def _apply_version2_language(self, language: UILanguage) -> None:
        """Project one language choice into every currently composed V2 surface."""

        if not isinstance(language, UILanguage):
            raise TypeError("Version 2 language must be UILanguage")
        application = self._version2_application
        if application is None:
            return

        application.adapter.set_language(language.value)
        for bridge_name in ("pgn", "library", "books"):
            bridge = getattr(application, bridge_name, None)
            if bridge is None:
                continue
            projection = getattr(bridge, "projection", None)
            setter = getattr(projection, "set_language", None)
            if not callable(setter):
                raise RuntimeError("Version 2 presentation language contract is incomplete")
            setter(language)

    def set_language(self, lang: str) -> dict[str, Any]:
        """Persist and synchronize the one release language across Stage1 and V2."""

        try:
            language = UILanguage(lang.strip().lower())
        except (AttributeError, ValueError):
            # Preserve the established Stage1 validation/error contract for
            # unsupported browser values and never persist an invalid token.
            return super().set_language(lang)

        previous = self.lang
        result = super().set_language(language.value)
        if not result.get("ok"):
            return result

        try:
            self._apply_version2_language(language)
            settings = getattr(self, "_settings", None)
            if settings is not None:
                settings.set("language", language.value)
        except Exception:
            # Runtime and persisted language are one logical setting.  If any
            # presentation/persistence boundary rejects the transition, restore
            # the previous runtime language instead of leaving split surfaces.
            try:
                previous_language = UILanguage(previous)
                super().set_language(previous_language.value)
                self._apply_version2_language(previous_language)
                settings = getattr(self, "_settings", None)
                if settings is not None:
                    settings.set("language", previous_language.value)
            except Exception:
                pass
            return self._error(
                "Не вдалося змінити мову." if previous == "uk" else "Language could not be changed."
            )
        return result

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
) -> None:
    """Run V2 on the original Stage 1 document and real Edge/WebView2 host."""

    if not isinstance(api, Version2ReleaseAccessibleChessAPI):
        raise TypeError("V2 release window requires Version2ReleaseAccessibleChessAPI")
    if not callable(menu_installer):
        raise TypeError("V2 native menu installer must be callable")
    if file_runtime_factory is not None and not callable(file_runtime_factory):
        raise TypeError("V2 file runtime factory must be callable or None")
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

    controller = Version2NativeMenuController(
        application.adapter,
        application.native_command,
        exit_callback=exit_application,
        current_focus_provider=lambda: str(getattr(application, "_focus", "")),
    )
    native_files: Any | None = None

    def install_menu_on_native_host(*_args: Any) -> None:
        nonlocal native_files
        if not menu_installer(window, controller):
            raise RuntimeError("Accessible Version 2 native Windows menu could not be attached.")
        if file_runtime_factory is None or native_files is not None:
            return
        owner = getattr(window, "_accessible_chess_native_menu_host", None)
        if owner is None:
            raise RuntimeError("Accessible Version 2 native Windows owner could not be resolved.")
        native_files = file_runtime_factory(owner)
        application.bind_files(native_files)

    def install_release_web_contract(*_args: Any) -> None:
        for _label, source in sources:
            window.evaluate_js(source)

    window.events.before_show += install_menu_on_native_host
    window.events.loaded += install_release_web_contract
    try:
        webview_module.start(gui="edgechromium", private_mode=True)
    finally:
        try:
            application.shutdown()
        finally:
            try:
                api.close_analysis()
            finally:
                if runtime is not None:
                    runtime.close()


__all__ = [
    "Version2ReleaseAccessibleChessAPI",
    "run_version2_release_window",
]