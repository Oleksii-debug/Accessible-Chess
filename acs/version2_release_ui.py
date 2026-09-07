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

from .chesscore import Board
from .full_product_native_menu import install_full_product_windows_native_menu
from .stage1_release_ui import Stage1ReleaseAccessibleChessAPI, _asset_root
from .ui_review_adapter import ReviewView
from .version2_profile import Version2NativeMenuController


class Version2ReleaseAccessibleChessAPI(Stage1ReleaseAccessibleChessAPI):
    """One pywebview API object for the frozen board and accepted V2 shell.

    Stage 1 public methods remain inherited unchanged.  V2 methods are explicit
    additions so pywebview does not need a second ``js_api`` object and therefore
    cannot accidentally create a second board/engine authority.

    PGN and Book review positions are a presentation projection over that same
    semantic board.  They never replace ``self.board`` or its ReviewHistory.  This
    mirrors the existing Stage 1 non-destructive history-review contract while
    keeping the V2 format cursor owned by its canonical PGN/Book workflow.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._version2_application: Any | None = None
        self._version2_review_fen: str | None = None

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

    def _active_version2_review_fen(self) -> str | None:
        """Return the external review FEN only while its owner says review is active.

        The V2 application already owns PGN/Book review lifecycle.  The release
        board therefore does not invent a second cursor or explicit clear command:
        once the owner leaves review, the stored presentation value is discarded
        lazily and the inherited board immediately exposes the untouched live game.
        """

        fen = self._version2_review_fen
        if fen is None:
            return None
        application = self._version2_application
        if application is None:
            return None
        pgn_active = bool(getattr(application, "pgn_board_active", False))
        workflow = getattr(application, "book_workflow", None)
        book_active = workflow is not None and bool(getattr(workflow, "active", False))
        if pgn_active or book_active:
            return fen
        self._version2_review_fen = None
        return None

    def project_review_position(self, fen: str) -> dict[str, object]:
        """Project one canonical review FEN without mutating the live chess game.

        ``set_fen`` remains the destructive Position/FEN command.  This method is
        intentionally separate so PGN/Book review cannot erase SAN, history,
        engine-game identity, undo/redo or other live state merely to render the
        selected position on the existing accessible 64-square board.
        """

        if not isinstance(fen, str) or not fen.strip():
            return {"ok": False, "message": "Review position is unavailable."}
        try:
            canonical = Board(fen).fen()
        except Exception:
            return {"ok": False, "message": "Review position is invalid."}
        self._version2_review_fen = canonical
        return {"ok": True, "fen": canonical, "message": ""}

    def _display_review(self) -> ReviewView:
        fen = self._active_version2_review_fen()
        if fen is None:
            return super()._display_review()
        return ReviewView(
            fen=fen,
            ply=0,
            node_id=-1,
            at_start=False,
            at_end=False,
            status=(
                "Позиція зовнішнього перегляду."
                if self.lang == "uk"
                else "External review position."
            ),
            last_move=None,
        )

    def _at_history_end(self) -> bool:
        if self._active_version2_review_fen() is not None:
            return False
        return super()._at_history_end()

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
