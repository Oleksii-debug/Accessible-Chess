from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from . import webapp as _webapp
from .chesscore import Board
from .history import PositionSnapshot
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
        self._analysis_origin_node_id = self.review_history.cursor_node_id
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
            if not self.analysis_ui.available:
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
        for line in lines[: int(analysis.get("multipv", 5))]:
            idx = line.get("multipv", len(rendered) + 1)
            pv = " ".join(
                _shared_spoken_san(str(move), self.lang)
                for move in line.get("pv", ())
            )
            score = str(line.get("scoreText") or "")
            if self.lang == "uk":
                rendered.append(
                    f"Варіант {idx}: глибина {line.get('depth', 0)}, оцінка "
                    f"{score}. {pv}".strip()
                )
            else:
                rendered.append(
                    f"Variation {idx}: depth {line.get('depth', 0)}, evaluation "
                    f"{score}. {pv}".strip()
                )
        lock = analysis.get("targetLocked")
        if lock:
            rendered.insert(
                0,
                "Ціль аналізу зафіксовано."
                if self.lang == "uk"
                else "Analysis target is locked.",
            )
        return "\n".join(rendered)

    def _analysis_origin_matches(self) -> bool:
        target_fen = self.analysis_ui.target_fen
        if target_fen is None:
            return False
        records = self.review_history.tree_nodes()
        node_id = self._analysis_origin_node_id
        return (
            type(node_id) is int
            and 0 <= node_id < len(records)
            and records[node_id].snapshot.fen == target_fen
        )

    def _analysis_line_message(self, index: int) -> str:
        return self.analysis_ui.read_pv(
            index,
            self._display_review().fen,
            lang=self.lang,
        )

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
            if self.analysis_ui.enabled and not self.analysis_ui.target_locked:
                self._analysis_origin_node_id = self._display_review().node_id
            snapshot = self.analysis_ui.snapshot(displayed_fen)
            analysis = snapshot.as_dict()
            for projected, line in zip(analysis["lines"], snapshot.lines):
                projected["scoreText"] = self.analysis_ui.score_text(line, lang=self.lang)
                projected["pvText"] = " ".join(
                    _shared_spoken_san(move, self.lang) for move in line.pv
                )
        except Exception:
            analysis = {
                "enabled": self.analysis_ui.enabled, "fen": displayed_fen, "running": False,
                "multipv": self.analysis_ui.multipv,
                "depth": self.analysis_ui.depth,
                "lines": [], "error": "engine_error", "stale": False,
                "targetLocked": self.analysis_ui.target_locked,
                "selectedPv": self.analysis_ui.selected_pv,
                "exploring": False, "explorationPly": 0,
                "explorationLength": 0, "explorationFen": None,
            }
        state["analysis"] = analysis
        state["engineEnabled"] = analysis["enabled"]
        state["engineStatus"] = self._analysis_status_text(analysis)
        exploration = self.analysis_ui.exploration
        if exploration is not None and self._analysis_origin_matches():
            board = Board(exploration.fen)
            state["fen"] = exploration.fen
            state["board"] = self._board_cells(board)
            state["whitePieces"] = self._pieces_text("w", board)
            state["blackPieces"] = self._pieces_text("b", board)
            state["gameStatus"] = self._game_status(board)
            state["lastMove"] = _shared_spoken_san(exploration.san, self.lang)
            state["reviewStatus"] = (
                f"Тимчасовий перегляд варіанта {exploration.line.multipv}, "
                f"хід {exploration.ply} з {len(exploration.line.pv)}."
                if self.lang == "uk"
                else f"Temporary variation {exploration.line.multipv}, "
                f"move {exploration.ply} of {len(exploration.line.pv)}."
            )
            state["analysisViewingTemporaryPosition"] = True
        else:
            state["analysisViewingTemporaryPosition"] = False
        return state

    def set_language(self, lang: str) -> dict[str, Any]:
        result = super().set_language(lang)
        if result.get("ok"):
            self.keymap_service.set_language(self.lang)
        return result

    def _temporary_exploration_error(self) -> dict[str, Any] | None:
        if self.analysis_ui.exploration is None:
            return None
        return self._error(
            "Спочатку поверніться з тимчасового варіанта Stockfish."
            if self.lang == "uk"
            else "Return from the temporary Stockfish variation first."
        )

    def _reanchor_analysis_after_reset(self) -> None:
        if not self.analysis_ui.enabled:
            self._analysis_origin_node_id = self.review_history.cursor_node_id
            return
        displayed = self._display_review()
        if self.analysis_ui.target_locked:
            self.analysis_ui.unlock_target(displayed.fen)
        else:
            self.analysis_ui.sync_position(displayed.fen)
        self._analysis_origin_node_id = displayed.node_id

    def _canonical_reset_result(self, operation: Any) -> dict[str, Any]:
        blocked = self._temporary_exploration_error()
        if blocked is not None:
            return blocked
        result = operation()
        if not result.get("ok"):
            return result
        message = str(result.get("announcement") or "")
        try:
            self._reanchor_analysis_after_reset()
        except Exception:
            try:
                self.analysis_ui.disable()
            except Exception:
                pass
        return self._ok(message)

    def new_game(self) -> dict[str, Any]:
        return self._canonical_reset_result(super().new_game)

    def clear_board(self) -> dict[str, Any]:
        return self._canonical_reset_result(super().clear_board)

    def set_position_text(self, text: str, turn: str | None = None) -> dict[str, Any]:
        return self._canonical_reset_result(lambda: super(KeymapAwareAccessibleChessAPI, self).set_position_text(text, turn))

    def set_turn(self, color: str) -> dict[str, Any]:
        return self._canonical_reset_result(lambda: super(KeymapAwareAccessibleChessAPI, self).set_turn(color))

    def set_fen(self, fen: str) -> dict[str, Any]:
        return self._canonical_reset_result(lambda: super(KeymapAwareAccessibleChessAPI, self).set_fen(fen))

    def review_previous(self) -> dict[str, Any]:
        blocked = self._temporary_exploration_error()
        return blocked if blocked is not None else super().review_previous()

    def review_next(self) -> dict[str, Any]:
        blocked = self._temporary_exploration_error()
        return blocked if blocked is not None else super().review_next()

    def go_to_move(self, target: str) -> dict[str, Any]:
        blocked = self._temporary_exploration_error()
        return blocked if blocked is not None else super().go_to_move(target)

    def undo(self) -> dict[str, Any]:
        blocked = self._temporary_exploration_error()
        return blocked if blocked is not None else super().undo()

    def redo(self) -> dict[str, Any]:
        blocked = self._temporary_exploration_error()
        return blocked if blocked is not None else super().redo()

    def activate_square(self, square: str) -> dict[str, Any]:
        blocked = self._temporary_exploration_error()
        return blocked if blocked is not None else super().activate_square(square)

    def toggle_engine(self) -> dict[str, Any]:
        return self.stop_analysis() if self.analysis_ui.enabled else self.start_analysis()

    def start_analysis(self) -> dict[str, Any]:
        displayed = self._display_review()
        try:
            if not self.analysis_ui.enabled:
                self.analysis_ui.enable(displayed.fen)
                self._analysis_origin_node_id = displayed.node_id
            return self._ok(
                "Аналіз Stockfish увімкнено."
                if self.lang == "uk"
                else "Stockfish analysis enabled."
            )
        except Exception:
            return self._error("Stockfish недоступний." if self.lang == "uk" else "Stockfish unavailable.")

    def stop_analysis(self) -> dict[str, Any]:
        try:
            self.analysis_ui.disable()
            return self._ok(
                "Аналіз Stockfish вимкнено."
                if self.lang == "uk"
                else "Stockfish analysis disabled."
            )
        except Exception:
            return self._error(
                "Не вдалося зупинити Stockfish."
                if self.lang == "uk"
                else "Stockfish could not be stopped."
            )

    def restart_analysis(self) -> dict[str, Any]:
        try:
            displayed = self._display_review()
            self.analysis_ui.restart(displayed.fen)
            if not self.analysis_ui.target_locked:
                self._analysis_origin_node_id = displayed.node_id
            return self._ok(
                "Аналіз Stockfish перезапущено."
                if self.lang == "uk"
                else "Stockfish analysis restarted."
            )
        except Exception:
            return self._error("Stockfish недоступний." if self.lang == "uk" else "Stockfish unavailable.")

    def configure_analysis(self, multipv: int, depth: int) -> dict[str, Any]:
        if not self.analysis_ui.available:
            return self._error("Stockfish недоступний." if self.lang == "uk" else "Stockfish unavailable.")
        try:
            self.analysis_ui.configure(multipv=multipv, depth=depth)
            return self._ok(
                f"Налаштування аналізу застосовано: MultiPV "
                f"{self.analysis_ui.multipv}, глибина {self.analysis_ui.depth}."
                if self.lang == "uk"
                else f"Analysis settings applied: MultiPV {self.analysis_ui.multipv}, "
                f"depth {self.analysis_ui.depth}."
            )
        except Exception:
            return self._error(
                "Некоректні налаштування аналізу."
                if self.lang == "uk"
                else "Invalid analysis settings."
            )

    def toggle_analysis_lock(self) -> dict[str, Any]:
        displayed = self._display_review()
        try:
            if self.analysis_ui.target_locked:
                self.analysis_ui.unlock_target(displayed.fen)
                self._analysis_origin_node_id = displayed.node_id
                message = "Аналіз знову стежить за поточною позицією." if self.lang == "uk" else "Analysis now follows the current position."
            else:
                self.analysis_ui.sync_position(displayed.fen)
                self._analysis_origin_node_id = displayed.node_id
                self.analysis_ui.lock_target()
                message = "Ціль аналізу зафіксовано." if self.lang == "uk" else "Analysis target locked."
            return self._ok(message)
        except Exception:
            return self._error(
                "Ціль аналізу недоступна."
                if self.lang == "uk"
                else "Analysis target is unavailable."
            )

    def read_analysis_pv(self, index: int) -> dict[str, Any]:
        try:
            if type(index) is not int:
                raise TypeError("PV index must be an exact integer")
            message = self._analysis_line_message(index)
            return self._ok(message)
        except Exception:
            return self._error("Варіант недоступний." if self.lang == "uk" else "Variation unavailable.")

    def select_analysis_pv(self, index: int) -> dict[str, Any]:
        return self.read_analysis_pv(index)

    def select_relative_analysis_pv(self, delta: int) -> dict[str, Any]:
        try:
            line = self.analysis_ui.select_relative_pv(delta, self._display_review().fen)
            return self._ok(self._analysis_line_message(line.multipv))
        except Exception:
            return self._error("Варіант недоступний." if self.lang == "uk" else "Variation unavailable.")

    def explore_analysis_pv(self) -> dict[str, Any]:
        try:
            if not self._analysis_origin_matches():
                raise RuntimeError("analysis origin changed")
            exploration = self.analysis_ui.begin_exploration(self._display_review().fen)
            self.selected_source = None
            return self._ok(
                f"Тимчасовий перегляд варіанта {exploration.line.multipv}: "
                f"{_shared_spoken_san(exploration.san, self.lang)}."
                if self.lang == "uk"
                else f"Temporarily exploring variation {exploration.line.multipv}: "
                f"{_shared_spoken_san(exploration.san, self.lang)}."
            )
        except Exception:
            return self._error("Варіант недоступний." if self.lang == "uk" else "Variation unavailable.")

    def step_analysis_exploration(self, delta: int) -> dict[str, Any]:
        try:
            exploration = self.analysis_ui.step_exploration(delta)
            return self._ok(
                f"Хід {exploration.ply} з {len(exploration.line.pv)}: "
                f"{_shared_spoken_san(exploration.san, self.lang)}."
                if self.lang == "uk"
                else f"Move {exploration.ply} of {len(exploration.line.pv)}: "
                f"{_shared_spoken_san(exploration.san, self.lang)}."
            )
        except Exception:
            return self._error(
                "Тимчасовий перегляд не активний."
                if self.lang == "uk"
                else "Temporary exploration is not active."
            )

    def return_from_analysis(self) -> dict[str, Any]:
        try:
            if not self._analysis_origin_matches():
                raise RuntimeError("analysis origin changed")
            self.review_history.select_node(self._analysis_origin_node_id)
            self.analysis_ui.return_from_exploration()
            self.selected_source = None
            return self._ok(
                "Повернено точну вихідну позицію аналізу."
                if self.lang == "uk"
                else "Returned to the exact analysis source position."
            )
        except Exception:
            return self._error(
                "Не вдалося відновити вихідну позицію аналізу."
                if self.lang == "uk"
                else "The analysis source position could not be restored."
            )

    def _insert_analysis_line(self, *, one_move: bool) -> dict[str, Any]:
        try:
            if not self._analysis_origin_matches():
                raise RuntimeError("analysis origin changed")
            line = self.analysis_ui.selected_line(self._display_review().fen)
            count = 1 if one_move else len(line.pv)
            if count == 0:
                raise RuntimeError("analysis line is empty")
            board = Board(str(self.analysis_ui.target_fen))
            snapshots: list[PositionSnapshot] = []
            for ply, (san, expected_fen) in enumerate(
                zip(line.pv[:count], line.position_fens[:count]),
                start=1,
            ):
                side = board.turn
                canonical_san = board.push_text(san)
                if canonical_san != san or board.fen() != expected_fen:
                    raise RuntimeError("validated analysis line changed")
                snapshots.append(
                    PositionSnapshot(
                        board.fen(),
                        san=san,
                        side=side,
                        last_move=san,
                        context={
                            "source": "stockfish-analysis",
                            "multipv": line.multipv,
                            "sourceFen": str(self.analysis_ui.target_fen),
                            "pvPly": ply,
                        },
                    )
                )
            inserted = self.review_history.append_branch(
                self._analysis_origin_node_id,
                tuple(snapshots),
            )
            self.review_history.select_node(self._analysis_origin_node_id)
            self.analysis_ui.return_from_exploration()
            self.selected_source = None
            subject = "Хід" if one_move else "Варіант"
            subject_en = "Move" if one_move else "Variation"
            status = "додано" if inserted.created_count else "вже існує"
            status_en = "inserted" if inserted.created_count else "already exists"
            return self._ok(
                f"{subject} Stockfish {status} як окрему гілку; основну лінію не змінено."
                if self.lang == "uk"
                else f"Stockfish {subject_en.lower()} {status_en} as a separate branch; the main line was not changed."
            )
        except Exception:
            return self._error(
                "Не вдалося безпечно вставити варіант Stockfish."
                if self.lang == "uk"
                else "The Stockfish variation could not be inserted safely."
            )

    def insert_analysis_move(self) -> dict[str, Any]:
        return self._insert_analysis_line(one_move=True)

    def insert_analysis_line(self) -> dict[str, Any]:
        return self._insert_analysis_line(one_move=False)

    def dispatch_action(self, action_id: str) -> dict[str, Any]:
        action_id = str(action_id or "")
        pv_actions = {f"analysis.pv{i}": i for i in range(1, 6)}
        if action_id in pv_actions:
            return self.read_analysis_pv(pv_actions[action_id])
        analysis_actions = {
            "analysis.start": self.start_analysis,
            "analysis.stop": self.stop_analysis,
            "analysis.restart": self.restart_analysis,
            "analysis.previous_pv": lambda: self.select_relative_analysis_pv(-1),
            "analysis.next_pv": lambda: self.select_relative_analysis_pv(1),
            "analysis.lock_target": self.toggle_analysis_lock,
            "analysis.explore_pv": self.explore_analysis_pv,
            "analysis.return": self.return_from_analysis,
            "analysis.insert_move": self.insert_analysis_move,
            "analysis.insert_line": self.insert_analysis_line,
        }
        handler = analysis_actions.get(action_id)
        if handler is not None:
            return handler()
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
        blocked = self._temporary_exploration_error()
        if blocked is not None:
            return blocked
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

    def install_menu_on_native_host(*_args: Any) -> None:
        # pywebview's before_show event fires only after the platform BrowserForm
        # exists and window.native has been assigned, but before that Form is
        # shown. Attach the native MenuStrip at that exact lifecycle point so
        # the first exposed Windows UIA tree already contains the application
        # menu. Never fall back to a WebView/HTML menu.
        if not install_windows_native_menu(window, api):
            raise RuntimeError("Accessible native Windows menu could not be attached to the WebView2 host.")

    window.events.before_show += install_menu_on_native_host
    webview.start(gui="edgechromium", private_mode=True)
