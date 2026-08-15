from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from . import webapp as _webapp
from .keybindings import BindingContext
from .notation import NotationError, format_san
from .ui_analysis_adapter import AnalysisPresentationAdapter
from .ui_entitlement import project_entitlement, semantic_contract
from .ui_keymap_service import KeymapService
from .ui_native_menu import install_windows_native_menu

AccessibleChessAPI = _webapp.AccessibleChessAPI
_asset_root = _webapp._asset_root


def _shared_spoken_san(san: str, lang: str = "uk") -> str:
    profile = "uk_literal" if lang == "uk" else "en_literal"
    try:
        return format_san(san, profile)
    except NotationError:
        return str(san).strip().replace("0-0-0", "O-O-O").replace("0-0", "O-O")


def default_keymap_path() -> Path:
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / ".accessible-chess"
    return base / "AccessibleChess" / "keymap.json" if appdata else base / "keymap.json"


class KeymapAwareAccessibleChessAPI(AccessibleChessAPI):
    def __init__(
        self,
        lang: str = "uk",
        *,
        keymap_path: str | Path | None = None,
        entitlement_payload: Mapping[str, Any] | None = None,
        continuous_analysis: Any | None = None,
    ) -> None:
        super().__init__(lang)
        self.keymap_service = KeymapService(keymap_path or default_keymap_path(), lang=self.lang)
        self.analysis_ui = AnalysisPresentationAdapter(continuous_analysis, multipv=5, depth=16)
        self._entitlement_payload = dict(entitlement_payload or {"state": "free_beta"})

    def keymap_snapshot(self) -> dict[str, Any]:
        data = self.keymap_service.snapshot()
        # Never expose a Python exception or malformed persisted binding text to
        # the normal user document. The service has already fallen back to sane
        # defaults; the UI only needs to know that recovery happened.
        if data.get("recoveryMessage"):
            data["recoveryMessage"] = (
                "Keyboard settings restored." if self.lang == "en"
                else "Налаштування клавіш відновлено."
            )
        return data

    def keymap_search(self, query: str = "", context: str | None = None) -> list[dict[str, Any]]:
        return self.keymap_service.search(query, context)

    def keymap_preview(self, action_id: str, value: str) -> dict[str, Any]:
        try:
            return self.keymap_service.preview(action_id, value)
        except Exception:
            return {
                "actionId": action_id,
                "value": value,
                "canSave": False,
                "requiresConfirmation": False,
                "status": "error",
                "message": "Invalid shortcut" if self.lang == "en" else "Некоректна комбінація.",
                "conflicts": [],
            }

    def keymap_capture_shortcut(self, action_id: str, key: str, ctrl: bool = False, alt: bool = False,
                                shift: bool = False, win: bool = False) -> dict[str, Any]:
        try:
            return self.keymap_service.capture_shortcut(
                action_id, key, ctrl=ctrl, alt=alt, shift=shift, win=win
            )
        except Exception:
            return {
                "captured": False, "reason": "invalid", "binding": "", "status": "error",
                "message": "Invalid shortcut" if self.lang == "en" else "Некоректна комбінація.",
                "canSave": False, "requiresConfirmation": False, "conflicts": [],
            }

    def keymap_save(self, action_id: str, value: str, allow_warnings: bool = False) -> dict[str, Any]:
        return self.keymap_service.save(action_id, value, allow_warnings=allow_warnings)

    def keymap_reset_action(self, action_id: str) -> dict[str, Any]:
        return self.keymap_service.reset_action(action_id)

    def keymap_reset_context(self, context: str) -> dict[str, Any]:
        return self.keymap_service.reset_context(context)

    def keymap_reset_all(self) -> dict[str, Any]:
        return self.keymap_service.reset_all()

    def keymap_export_profile(self) -> str:
        return self.keymap_service.export_profile()

    def keymap_import_profile(self, text: str, allow_warnings: bool = False) -> dict[str, Any]:
        return self.keymap_service.import_profile(text, allow_warnings=allow_warnings)

    def keymap_resolve_binding(self, context: str, binding: str) -> dict[str, Any] | None:
        try:
            return self.keymap_service.resolve_binding(context, binding)
        except Exception:
            return None

    def keymap_resolve_alias(self, context: str, alias: str) -> dict[str, Any] | None:
        try:
            return self.keymap_service.resolve_alias(context, alias)
        except Exception:
            return None

    def _moves_text(self) -> str:
        count = self._visible_ply_count()
        if count == 0:
            return self._t("no_moves")
        sans, sides = self.sans[:count], self.move_sides[:count]
        out: list[str] = []
        move_no = 1
        i = 0
        while i < len(sans):
            if sides[i] == "w":
                white = _shared_spoken_san(sans[i], self.lang)
                if i + 1 < len(sans) and sides[i + 1] == "b":
                    black = _shared_spoken_san(sans[i + 1], self.lang)
                    out.append(f"{move_no}. {white}, {black}.")
                    i += 2
                else:
                    out.append(f"{move_no}. {white}.")
                    i += 1
                move_no += 1
            else:
                out.append(f"{move_no}... {_shared_spoken_san(sans[i], self.lang)}.")
                move_no += 1
                i += 1
        return "\n".join(out)

    def _analysis_status_text(self, analysis: dict[str, Any]) -> str:
        if not analysis["enabled"]:
            if analysis.get("error") == "analysis service is not configured":
                return "Stockfish недоступний." if self.lang == "uk" else "Stockfish unavailable."
            return "Stockfish вимкнено." if self.lang == "uk" else "Stockfish disabled."
        if analysis.get("error"):
            return "Помилка Stockfish." if self.lang == "uk" else "Stockfish error."
        if analysis.get("stale"):
            return "Очікую новий аналіз." if self.lang == "uk" else "Waiting for fresh analysis."
        lines = analysis.get("lines") or []
        if not lines:
            return "Stockfish аналізує позицію." if self.lang == "uk" else "Stockfish is analysing the position."
        rendered: list[str] = []
        for line in lines[:5]:
            idx = line.get("multipv", len(rendered) + 1)
            pv = " ".join(str(move) for move in line.get("pv", ()))
            if self.lang == "uk":
                rendered.append(
                    f"Варіант {idx}: глибина {line.get('depth', 0)}, оцінка "
                    f"{line.get('scoreKind', 'cp')} {line.get('scoreValue', 0)}. {pv}".strip()
                )
            else:
                rendered.append(
                    f"Variation {idx}: depth {line.get('depth', 0)}, evaluation "
                    f"{line.get('scoreKind', 'cp')} {line.get('scoreValue', 0)}. {pv}".strip()
                )
        return "\n".join(rendered)

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        visible = self._visible_ply_count()
        state["lastMove"] = _shared_spoken_san(self.sans[visible - 1], self.lang) if visible else self._t("no_last")
        state["moves"] = self._moves_text()
        entitlement_view = project_entitlement(self._entitlement_payload, lang=self.lang)
        state["entitlement"] = semantic_contract(entitlement_view)
        state["gameInfo"] = f"{state['gameInfo']}\n{entitlement_view.heading}: {entitlement_view.summary}"
        displayed_fen = str(state["fen"])
        try:
            self.analysis_ui.sync_position(displayed_fen)
            analysis = self.analysis_ui.snapshot(displayed_fen).as_dict()
        except Exception:
            analysis = {
                "enabled": self.analysis_ui.enabled, "fen": displayed_fen, "running": False,
                "multipv": 5, "depth": 16, "lines": [], "error": "analysis unavailable", "stale": False,
            }
        state["analysis"] = analysis
        state["engineEnabled"] = analysis["enabled"]
        state["engineStatus"] = self._analysis_status_text(analysis)
        return state

    def set_language(self, lang: str) -> dict[str, Any]:
        result = super().set_language(lang)
        if result.get("ok"):
            self.keymap_service.set_language(self.lang)
        return result

    def toggle_engine(self) -> dict[str, Any]:
        displayed_fen = self._display_review().fen
        try:
            if self.analysis_ui.enabled:
                self.analysis_ui.disable()
                return self._ok("Аналіз Stockfish вимкнено." if self.lang == "uk" else "Stockfish analysis disabled.")
            self.analysis_ui.enable(displayed_fen)
            return self._ok("Аналіз Stockfish увімкнено." if self.lang == "uk" else "Stockfish analysis enabled.")
        except Exception:
            return self._error("Stockfish недоступний." if self.lang == "uk" else "Stockfish unavailable.")

    def read_analysis_pv(self, index: int) -> dict[str, Any]:
        try:
            message = self.analysis_ui.read_pv(int(index), self._display_review().fen, lang=self.lang)
            return self._ok(message)
        except Exception:
            return self._error("Варіант недоступний." if self.lang == "uk" else "Variation unavailable.")

    def dispatch_action(self, action_id: str) -> dict[str, Any]:
        action_id = str(action_id or "")
        pv_actions = {f"analysis.pv{i}": i for i in range(1, 6)}
        if action_id in pv_actions:
            return self.read_analysis_pv(pv_actions[action_id])
        if action_id == "board.evaluation":
            try:
                return self._ok(self.analysis_ui.evaluation_text(self._display_review().fen, lang=self.lang))
            except Exception:
                return self._error("Оцінка недоступна." if self.lang == "uk" else "Evaluation unavailable.")
        if action_id == "board.best_move":
            try:
                return self._ok(self.analysis_ui.best_move_text(self._display_review().fen, lang=self.lang))
            except Exception:
                return self._error("Найкращий хід недоступний." if self.lang == "uk" else "Best move unavailable.")
        return self._error("Команда недоступна." if self.lang == "uk" else "Command unavailable.")

    def make_move(self, text: str) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            return self._error("Введіть хід." if self.lang == "uk" else "Enter a move.")
        resolution = self.keymap_service.resolve_alias(BindingContext.MOVE_ENTRY.value, text)
        if resolution is not None:
            return self._dispatch_move_entry_action(str(resolution["actionId"]))
        if not self._at_history_end():
            return self._error(self._t("review_before_move"))
        if not self._position_complete(self.board):
            return self._error(self._t("setup_incomplete"))
        try:
            side = self.board.turn
            san = self.board.push_text(text)
            self.sans.append(san)
            self.move_sides.append(side)
            self.redo_meta.clear()
            self.selected_source = None
            self._record_position_after_move(san, side)
            return self._ok(("Зіграно: " if self.lang == "uk" else "Played: ") + _shared_spoken_san(san, self.lang))
        except Exception:
            return self._error("Нелегальний хід." if self.lang == "uk" else "Illegal move.")

    def _dispatch_move_entry_action(self, action_id: str) -> dict[str, Any]:
        handlers = {
            "move.undo": self.undo, "move.redo": self.redo,
            "move.white_to_move": lambda: self.set_turn("w"),
            "move.black_to_move": lambda: self.set_turn("b"),
            "move.clear": self.clear_board, "move.standard": self.new_game, "move.empty": self.clear_board,
        }
        if action_id == "move.last":
            return self._ok(("Останній хід: " if self.lang == "uk" else "Last move: ") + self.get_state()["lastMove"])
        handler = handlers.get(action_id)
        return handler() if handler else self._error("Команда недоступна." if self.lang == "uk" else "Command unavailable.")

    def close_analysis(self) -> dict[str, Any]:
        self.analysis_ui.close()
        return {"ok": True}


def main() -> None:
    import webview

    api = KeymapAwareAccessibleChessAPI()
    html = _asset_root() / "web" / "index.html"
    if not html.exists():
        raise RuntimeError(f"Accessible HTML UI not found: {html}")
    window = webview.create_window(
        "Accessible Chess",
        url=str(html), js_api=api, width=1150, height=820, min_size=(800, 600),
        text_select=True,
    )

    def install_menu() -> None:
        # Human acceptance requires a Windows-native Alt menu. The installer
        # returns False rather than silently falling back to the inaccessible
        # pywebview MenuStrip.
        install_windows_native_menu(window, api)

    webview.start(install_menu, gui="edgechromium", private_mode=True)
