from __future__ import annotations

"""Release-facing Stage 1 UI boundary and broad user-flow diagnostic.

This module keeps the proven WebView/keymap implementation intact while
hardening normal user-input errors so Python exception text never becomes
screen-reader output. It also owns one broad deterministic Stage 1 sequence
used by source/packaged diagnostics.
"""

from pathlib import Path
import tempfile
from typing import Any

from .chesscore import parse_sq
from .ui_native_menu import install_windows_native_menu
from .webapp_keymap import KeymapAwareAccessibleChessAPI, _asset_root


class Stage1ReleaseAccessibleChessAPI(KeymapAwareAccessibleChessAPI):
    """Release API with concise fail-closed user-facing error boundaries."""

    def _concise_error(self, uk: str, en: str) -> dict[str, Any]:
        return self._error(uk if self.lang == "uk" else en)

    def set_fen(self, fen: str) -> dict[str, Any]:
        result = super().set_fen(fen)
        if result.get("ok"):
            return result
        return self._concise_error("Некоректний FEN.", "Invalid FEN.")

    def set_position_text(self, text: str, turn: str | None = None) -> dict[str, Any]:
        result = super().set_position_text(text, turn)
        if result.get("ok"):
            return result
        return self._concise_error("Некоректна позиція.", "Invalid position.")

    def activate_square(self, square: str) -> dict[str, Any]:
        try:
            parse_sq(square)
        except Exception:
            return self._concise_error("Некоректне поле.", "Invalid square.")
        result = super().activate_square(square)
        if result.get("ok"):
            return result

        allowed = {
            self._t("review_before_move"),
            self._t("setup_incomplete"),
            self._t("illegal"),
        }
        message = str(result.get("announcement") or "")
        if (
            message in allowed
            or message.startswith("Зараз хід іншої сторони")
            or message.startswith("It is the other side's turn")
        ):
            return result
        if message and not any(
            token in message
            for token in ("Traceback", "ValueError", "RuntimeError", "Exception", " at 0x")
        ):
            return result
        return self._concise_error(
            "Не вдалося виконати дію на дошці.",
            "Board action failed.",
        )


def complete_user_flow_diagnostic(
    api: Stage1ReleaseAccessibleChessAPI | None = None,
) -> dict[str, Any]:
    """Exercise the coherent Stage 1 user path without OS/NVDA claims."""
    owned_temp = None
    if api is None:
        owned_temp = tempfile.TemporaryDirectory()
        api = Stage1ReleaseAccessibleChessAPI(
            keymap_path=Path(owned_temp.name) / "keymap.json"
        )

    checks: dict[str, bool] = {}
    try:
        start = api.new_game()
        start_fen = str(start["fen"])
        checks["startup"] = (
            bool(start.get("ok"))
            and len(start.get("board") or []) == 64
            and start.get("historyLength") == 0
        )
        checks["initial_focus_semantics"] = all(
            bool(cell.get("square")) and bool(cell.get("label"))
            for cell in start.get("board") or []
        )

        played = api.make_move("e4")
        e4_fen = str(played.get("fen"))
        checks["e4"] = (
            bool(played.get("ok"))
            and played.get("historyLength") == 1
            and e4_fen != start_fen
        )
        checks["e4_board"] = any(
            cell.get("square") == "e4" and cell.get("occupied")
            for cell in played.get("board") or []
        )
        checks["black_to_move"] = (
            " b " in e4_fen and bool(played.get("moves"))
        )

        bad = api.make_move("e9")
        checks["invalid_move_atomic"] = (
            not bad.get("ok")
            and bad.get("fen") == e4_fen
            and bad.get("historyLength") == 1
        )
        checks["invalid_move_concise"] = str(bad.get("announcement")) in {
            "Нелегальний хід.",
            "Illegal move.",
        }

        reviewed = api.review_previous()
        checks["history_review"] = (
            bool(reviewed.get("ok"))
            and reviewed.get("fen") == start_fen
            and api.board.fen() == e4_fen
        )
        live_again = api.go_to_move("end")
        checks["history_return"] = (
            bool(live_again.get("ok")) and live_again.get("fen") == e4_fen
        )

        undone = api.undo()
        checks["undo"] = (
            bool(undone.get("ok"))
            and undone.get("fen") == start_fen
            and undone.get("historyLength") == 0
        )
        redone = api.redo()
        checks["redo"] = (
            bool(redone.get("ok"))
            and redone.get("fen") == e4_fen
            and redone.get("historyLength") == 1
        )

        before_bad_fen = api.board.fen()
        bad_fen = api.set_fen("not a fen")
        checks["fen_error_concise"] = (
            not bad_fen.get("ok")
            and bad_fen.get("announcement")
            in {"Некоректний FEN.", "Invalid FEN."}
            and api.board.fen() == before_bad_fen
        )

        initial_fen = (
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        )
        loaded = api.set_fen(initial_fen)
        checks["fen_load"] = (
            bool(loaded.get("ok"))
            and loaded.get("fen") == initial_fen
            and loaded.get("historyLength") == 0
        )

        edited = api.set_position_text("W: K e1 Q d1 B: K e8", "w")
        checks["editor_load"] = (
            bool(edited.get("ok"))
            and edited.get("positionComplete") is True
            and edited.get("historyLength") == 0
        )
        before_bad_editor = api.board.fen()
        bad_editor = api.set_position_text("broken position", "w")
        checks["editor_error_concise"] = (
            not bad_editor.get("ok")
            and bad_editor.get("announcement")
            in {"Некоректна позиція.", "Invalid position."}
            and api.board.fen() == before_bad_editor
        )

        bad_square = api.activate_square("z9")
        checks["square_error_concise"] = (
            not bad_square.get("ok")
            and bad_square.get("announcement")
            in {"Некоректне поле.", "Invalid square."}
        )

        final = api.new_game()
        checks["final_board_64"] = len(final.get("board") or []) == 64
        checks["no_raw_exception_text"] = not any(
            token in str(final.get("announcement") or "")
            for token in ("Traceback", "ValueError", "RuntimeError", "Exception")
        )

        return {
            "ok": all(checks.values()),
            "checks": checks,
            "boardCells": len(final.get("board") or []),
            "finalFen": final.get("fen"),
        }
    finally:
        if owned_temp is not None:
            owned_temp.cleanup()


def main() -> None:
    import webview

    api = Stage1ReleaseAccessibleChessAPI()
    html = _asset_root() / "web" / "index.html"
    if not html.exists():
        raise RuntimeError(f"Accessible HTML UI not found: {html}")
    window = webview.create_window(
        "Accessible Chess",
        url=str(html),
        js_api=api,
        width=1150,
        height=820,
        min_size=(800, 600),
        text_select=True,
    )

    def install_menu_on_native_host(*_args: Any) -> None:
        if not install_windows_native_menu(window, api):
            raise RuntimeError(
                "Accessible native Windows menu could not be attached to the WebView2 host."
            )

    window.events.before_show += install_menu_on_native_host
    webview.start(gui="edgechromium", private_mode=True)
