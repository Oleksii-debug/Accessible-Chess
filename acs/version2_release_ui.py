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
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._version2_application: Any | None = None
        self._external_review_fen: str | None = None

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

    def _external_review_owned(self) -> bool:
        """Whether a PGN/Book workflow still owns the external Board review.

        Ownership persists while the user temporarily visits another V2 route.
        Explicit PGN/Book Return ends it.  Keeping this separate from visible
        Board projection prevents a global/native mutation from changing the
        hidden live game while the external review session is still open.
        """

        if self._external_review_fen is None:
            return False
        application = self._version2_application
        if application is None:
            return False
        if getattr(application, "pgn_board_active", False) is True:
            return True
        workflow = getattr(application, "book_workflow", None)
        return workflow is not None and getattr(workflow, "active", False) is True

    def _external_review_active(self) -> bool:
        """Whether the V2 shell is visibly projecting external review on Board."""

        if not self._external_review_owned():
            return False
        application = self._version2_application
        shell = getattr(application, "shell", None)
        route = getattr(getattr(shell, "current_route", None), "route_id", "")
        return route == "board"

    def project_review_fen(self, fen: str) -> dict[str, Any]:
        """Project an external canonical position without mutating the live game.

        PGN and Book review are presentation state.  They must drive the same
        accessible 64-square board while leaving ``self.board``, SAN history,
        ReviewHistory identity and engine-game ownership untouched.  Validation
        is delegated to the canonical Board implementation; malformed input is
        rejected before the cached projection changes.
        """

        if type(fen) is not str or not fen.strip():
            return {"ok": False}
        try:
            canonical = Board(fen).fen()
        except Exception:
            return {"ok": False}
        self._external_review_fen = canonical
        return {"ok": True}

    def _display_review(self) -> ReviewView:
        if self._external_review_active():
            return ReviewView(
                fen=str(self._external_review_fen),
                ply=0,
                node_id=-1,
                at_start=False,
                at_end=False,
                status=(
                    "Зовнішня позиція для перегляду."
                    if self.lang == "uk"
                    else "External review position."
                ),
                last_move=None,
            )
        return super()._display_review()

    def _display_board(self) -> Board:
        if self._external_review_active():
            return Board(str(self._external_review_fen))
        return super()._display_board()

    def _visible_ply_count(self) -> int:
        # External review does not own the live SAN list.  Do not expose hidden
        # live-game moves or last-move text beside a PGN/Book FEN.
        if self._external_review_active():
            return 0
        return super()._visible_ply_count()

    def _at_history_end(self) -> bool:
        # A PGN/Book review position is intentionally not a live move target.
        if self._external_review_owned():
            return False
        return super()._at_history_end()

    def _analysis_origin_matches(self) -> bool:
        # External review FENs are presentation origins, never ReviewHistory
        # nodes.  Ordinary analysis may follow the displayed FEN, but PV
        # exploration/Insert Move/Insert Line must fail closed instead of
        # attaching an external document line to a coincident live-history node.
        if self._external_review_owned():
            return False
        return super()._analysis_origin_matches()

    def _external_review_mutation_error(self) -> dict[str, Any]:
        return self._error(
            "Спочатку поверніться з перегляду документа."
            if self.lang == "uk"
            else "Return from document review first."
        )

    def make_move(self, text: str) -> dict[str, Any]:
        # Stage1 make_move performs engine-state work and recognizes single-letter
        # commands (including `s` -> new_game) before its ordinary review guard.
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().make_move(text)

    def activate_square(self, square: str) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().activate_square(square)

    def undo(self) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().undo()

    def redo(self) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().redo()

    def new_game(self) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().new_game()

    def clear_board(self) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().clear_board()

    def set_fen(self, fen: str) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().set_fen(fen)

    def set_position_text(self, text: str, turn: str | None = None) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().set_position_text(text, turn)

    def set_turn(self, color: str) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().set_turn(color)

    def start_engine_game(
        self,
        human_side: str = "white",
        level: int = 5,
        initial_minutes: int = 0,
        increment_seconds: int = 0,
    ) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().start_engine_game(
            human_side,
            level,
            initial_minutes,
            increment_seconds,
        )

    def stop_engine_game(self) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().stop_engine_game()

    def engine_takeback(self) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().engine_takeback()

    def offer_draw_engine_game(self) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().offer_draw_engine_game()

    def resign_engine_game(self) -> dict[str, Any]:
        if self._external_review_owned():
            return self._external_review_mutation_error()
        return super().resign_engine_game()

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        if self._external_review_active():
            state["historyLength"] = 0
        return state

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
