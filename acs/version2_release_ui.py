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

    @staticmethod
    def _projection_language(projection: Any) -> UILanguage | None:
        language = getattr(projection, "language", None)
        return language if isinstance(language, UILanguage) else None

    def _set_bound_version2_language(self, language: UILanguage) -> None:
        """Synchronize all currently reachable V2 presentation surfaces atomically.

        The V2 shell, PGN, Library/import and Books projections already own their
        bilingual presentation rules.  This coordinator only invokes those
        existing transitions and rolls changed surfaces back if one rejects the
        update; no content/chess state is recreated here.
        """

        if not isinstance(language, UILanguage):
            raise TypeError("Version 2 language must be UILanguage")
        application = self._version2_application
        if application is None:
            return

        shell = application.adapter.shell
        previous_shell = shell.language
        projections: list[Any] = [application.library.projection]
        if application.pgn is not None:
            projections.append(application.pgn.projection)
        if application.books is not None:
            projections.append(application.books.projection)

        changed: list[tuple[Any, UILanguage]] = []
        try:
            for projection in projections:
                previous = self._projection_language(projection)
                if previous is None:
                    raise TypeError("Version 2 projection has no language contract")
                projection.set_language(language)
                changed.append((projection, previous))
            application.adapter.set_language(language.value)
        except Exception:
            for projection, previous in reversed(changed):
                try:
                    projection.set_language(previous)
                except Exception:
                    pass
            try:
                application.adapter.set_language(previous_shell.value)
            except Exception:
                pass
            raise

    def set_language(self, lang: str) -> dict[str, Any]:
        """Persist and synchronize one language across the Stage 1 board and V2 UI."""

        if lang not in ("uk", "en"):
            return super().set_language(lang)
        target = UILanguage(lang)
        previous = self.lang
        previous_ui = UILanguage(previous)
        settings = getattr(self, "_settings", None)
        result: dict[str, Any] | None = None
        try:
            result = super().set_language(lang)
            if result.get("ok") is not True:
                return result
            self._set_bound_version2_language(target)
            if settings is not None:
                setter = getattr(settings, "set", None)
                if not callable(setter):
                    raise TypeError("settings language persistence is unavailable")
                setter("language", lang)
            return result
        except Exception:
            # Restore presentation state before projecting the bounded failure.
            try:
                self._set_bound_version2_language(previous_ui)
            except Exception:
                pass
            try:
                super().set_language(previous)
            except Exception:
                self.lang = previous
            if settings is not None:
                data = getattr(settings, "data", None)
                if isinstance(data, dict):
                    data["language"] = previous
            return self._error(
                "Не вдалося змінити мову." if previous == "uk" else "Language could not be changed."
            )

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
