from __future__ import annotations

"""Stage 1 saturation facade over the frozen release UI implementation.

The exact 656e8ec release UI remains byte-for-byte in ``stage1_release_ui_core``.
This facade widens only the Stage 1 board-action bridge and loads its small
WebView integration script.  The QA-owned strict Windows harness is untouched.
"""

from pathlib import Path
import tempfile
from typing import Any

from . import stage1_release_ui_core as _core
from .stage1_release_ui_core import *  # noqa: F401,F403 - compatibility surface
from .stage1_release_ui_core import _asset_root, _shared_spoken_san
from .engine_play_service import EngineGameIntent
from .game_lifecycle import EndReason, GameStatus
from .stage1_native_menu_router import Stage1NativeMenuActionProxy
from .webapp_keymap import KeymapAwareAccessibleChessAPI


class Stage1ReleaseAccessibleChessAPI(_core.Stage1ReleaseAccessibleChessAPI):
    """Release API with the saturation board-command dispatcher enabled."""

    @staticmethod
    def _binding_context(value: object) -> str:
        raw = getattr(value, "value", value)
        return str(raw or "").strip().lower()

    def keymap_resolve_binding(self, context: str, binding: str) -> dict[str, Any] | None:
        """Keep analysis shortcuts usable while focus is inside the 64-square board.

        The board application owns ordinary board keys, but analysis shortcuts are
        intentionally global to the analysis workflow.  Resolve an exact board
        binding first, then an exact analysis binding, and only then keep the
        inherited GLOBAL fallback.  This preserves board precedence and makes the
        existing ``apiAction`` announcement path reachable for Alt+1..Alt+5 and
        every remapped analysis shortcut without adding a second speech layer.
        """

        direct = super().keymap_resolve_binding(context, binding)
        if self._binding_context(context) != "board":
            return direct
        if direct is not None and self._binding_context(direct.get("context")) == "board":
            return direct

        analysis = super().keymap_resolve_binding("analysis", binding)
        if analysis is not None and self._binding_context(analysis.get("context")) == "analysis":
            return analysis
        return direct

    def _capture_engine_human_commit_context(self) -> dict[str, Any]:
        moved_side = self.board.turn
        return {
            "history": self.review_history.export_tree(),
            "board_fen": self.board.fen(),
            "sans_len": len(self.sans),
            "move_sides_len": len(self.move_sides),
            "redo_meta": tuple(self.redo_meta),
            "board_redo": tuple(self.board.redo_stack),
            "timeout_opponent_can_mate": self._timeout_mating_capability(moved_side),
        }

    def _rollback_expired_human_move(self, context: dict[str, Any]) -> bool:
        """Remove only the move rejected by the canonical game clock."""
        try:
            restored_history = type(self.review_history).from_tree(context["history"])
            expected_fen = context["board_fen"]
            if len(self.sans) != context["sans_len"] + 1:
                return False
            if len(self.move_sides) != context["move_sides_len"] + 1:
                return False
            undone = self.board.undo()
            if undone is None:
                return False
            if self.board.fen() != expected_fen:
                try:
                    self.board.redo()
                except Exception:
                    pass
                return False
        except Exception:
            return False

        self.sans.pop()
        self.move_sides.pop()
        self.redo_meta[:] = list(context["redo_meta"])
        self.board.redo_stack[:] = list(context["board_redo"])
        self.review_history = restored_history
        self.review_adapter = self.review_adapter.__class__(
            restored_history,
            language=self.lang,
        )
        self.live_history_node = context["history"].cursor_node_id
        self.selected_source = None
        return True

    def _play_latest_move(self) -> None:
        if getattr(self, "_defer_engine_human_move_sound", False):
            return
        super()._play_latest_move()

    def make_move(self, text: str) -> dict[str, Any]:
        if self._engine_game_phase != "active":
            return super().make_move(text)
        previous_context = getattr(self, "_engine_human_commit_context", None)
        previous_defer = getattr(self, "_defer_engine_human_move_sound", False)
        self._engine_human_commit_context = self._capture_engine_human_commit_context()
        self._defer_engine_human_move_sound = True
        try:
            return super().make_move(text)
        finally:
            self._engine_human_commit_context = previous_context
            self._defer_engine_human_move_sound = previous_defer

    def activate_square(self, square: str) -> dict[str, Any]:
        if self._engine_game_phase != "active":
            return super().activate_square(square)
        previous_context = getattr(self, "_engine_human_commit_context", None)
        previous_defer = getattr(self, "_defer_engine_human_move_sound", False)
        self._engine_human_commit_context = self._capture_engine_human_commit_context()
        self._defer_engine_human_move_sound = True
        try:
            return super().activate_square(square)
        finally:
            self._engine_human_commit_context = previous_context
            self._defer_engine_human_move_sound = previous_defer

    def _after_human_engine_move(self, moved_side: str, human_san: str) -> dict[str, Any]:
        session = self._engine_session
        context = getattr(self, "_engine_human_commit_context", None)
        if session is None or not isinstance(context, dict):
            return super()._after_human_engine_move(moved_side, human_san)

        try:
            after_move = session.on_human_move_committed(
                moved_side,
                timeout_opponent_can_mate=context["timeout_opponent_can_mate"],
            )
            self._record_engine_clock(after_move)
        except Exception:
            self._defer_engine_human_move_sound = False
            if self._game_sounds is not None:
                super()._play_latest_move()
            warning = self._pause_engine_after_failure()
            return self._ok(
                (f"Зіграно: {human_san}. {warning}" if self.lang == "uk"
                 else f"Played: {human_san}. {warning}")
            )

        outcome = after_move.lifecycle.outcome
        if (
            after_move.lifecycle.status is GameStatus.FINISHED
            and outcome is not None
            and outcome.reason is EndReason.TIMEOUT
        ):
            if not self._rollback_expired_human_move(context):
                self._engine_game_phase = "error"
                self._engine_game_error = (
                    "Не вдалося безпечно відкотити хід після завершення часу."
                    if self.lang == "uk"
                    else "The move could not be safely rolled back after time expired."
                )
                return self._concise_error(
                    "Не вдалося безпечно відкотити хід після завершення часу.",
                    "The move could not be safely rolled back after time expired.",
                )
            self._engine_game_phase = "finished"
            self._engine_game_error = None
            self._play_game_end_sound()
            message = self._outcome_text(after_move)
            return self._concise_error(message, message)

        self._defer_engine_human_move_sound = False
        if self._game_sounds is not None:
            super()._play_latest_move()

        if after_move.lifecycle.status is GameStatus.FINISHED:
            self._engine_game_phase = "finished"
            self._play_game_end_sound()
            return self._ok(
                (f"Зіграно: {human_san}. {self._outcome_text(after_move)}" if self.lang == "uk"
                 else f"Played: {human_san}. {self._outcome_text(after_move)}")
            )
        terminal = self._finish_engine_game_from_board()
        if terminal is not None:
            return self._ok(
                (f"Зіграно: {human_san}. {self._outcome_text(terminal)}" if self.lang == "uk"
                 else f"Played: {human_san}. {self._outcome_text(terminal)}")
            )
        _replied, message = self._request_engine_reply()
        return self._ok(
            (f"Зіграно: {human_san}. {message}" if self.lang == "uk"
             else f"Played: {human_san}. {message}")
        )

    def dispatch_action(self, action_id: str, square: str | None = None) -> dict[str, Any]:
        actions = {
            "edit.undo": self.undo,
            "edit.redo": self.redo,
            "history.previous": self.review_previous,
            "history.next": self.review_next,
            "engine_play.start": self.start_engine_game,
            "engine_play.stop": self.stop_engine_game,
            "game.takeback": self.engine_takeback,
            "game.offer_draw": self.offer_draw_engine_game,
            "game.resign": self.resign_engine_game,
        }
        action = action_id.strip() if isinstance(action_id, str) else ""
        handler = actions.get(action)
        if handler is not None:
            return handler()
        # Bypass the frozen one-argument Stage1 override only after preserving
        # all engine-game/global/history actions above.  The canonical keymap
        # layer owns the widened optional board-square argument and analysis IDs.
        return KeymapAwareAccessibleChessAPI.dispatch_action(self, action, square)


def complete_user_flow_diagnostic(
    api: Stage1ReleaseAccessibleChessAPI | None = None,
) -> dict[str, Any]:
    owned_temp = None
    if api is None:
        owned_temp = tempfile.TemporaryDirectory()
        api = Stage1ReleaseAccessibleChessAPI(
            keymap_path=Path(owned_temp.name) / "keymap.json"
        )
    try:
        result = _core.complete_user_flow_diagnostic(api)
        checks = dict(result.get("checks") or {})
        api.new_game()
        current = api.dispatch_action("board.current", "e2")
        legal = api.dispatch_action("board.legal_moves", "e2")
        cycle = api.dispatch_action("board.next_knight", "b1")
        material = api.dispatch_action("board.material", "e2")
        checks["board_current_action"] = bool(current.get("ok")) and current.get("focusSquare") == "e2"
        checks["board_legal_moves_action"] = bool(legal.get("ok")) and "e 3" in str(legal.get("announcement", "")) and "e 4" in str(legal.get("announcement", ""))
        checks["board_piece_cycle_action"] = bool(cycle.get("ok")) and cycle.get("focusSquare") == "g1"
        checks["board_material_action"] = bool(material.get("ok")) and "39" in str(material.get("announcement", ""))
        result["checks"] = checks
        result["ok"] = all(checks.values())
        return result
    finally:
        if owned_temp is not None:
            owned_temp.cleanup()


def run_release_window(api: Stage1ReleaseAccessibleChessAPI, runtime: Any | None = None) -> None:
    import webview

    html = _asset_root() / "web" / "index.html"
    bootstrap = _asset_root() / "web" / "stage1_release_bootstrap.js"
    board_bridge = _asset_root() / "web" / "stage1_board_actions.js"
    for path, label in (
        (html, "Accessible HTML UI"),
        (bootstrap, "Stage 1 WebView bootstrap"),
        (board_bridge, "Stage 1 board action bridge"),
    ):
        if not path.exists():
            if runtime is not None:
                runtime.close()
            # This failure can surface during packaged startup.  Do not expose
            # a build machine/user profile path through the user-facing error.
            raise RuntimeError(f"{label} not found in packaged resources.")
    bootstrap_source = bootstrap.read_text(encoding="utf-8")
    board_bridge_source = board_bridge.read_text(encoding="utf-8")

    window = webview.create_window(
        "Accessible Chess",
        url=str(html),
        js_api=api,
        width=1150,
        height=820,
        min_size=(800, 600),
        text_select=True,
    )
    menu_api = Stage1NativeMenuActionProxy(api)

    def install_menu_on_native_host(*_args: Any) -> None:
        if not install_windows_native_menu(window, menu_api):
            raise RuntimeError("Accessible native Windows menu could not be attached to the WebView2 host.")

    def install_release_web_contract(*_args: Any) -> None:
        window.evaluate_js(bootstrap_source)
        window.evaluate_js(board_bridge_source)

    window.events.before_show += install_menu_on_native_host
    window.events.loaded += install_release_web_contract
    try:
        webview.start(gui="edgechromium", private_mode=True)
    finally:
        try:
            api.close_analysis()
        finally:
            if runtime is not None:
                runtime.close()


def main() -> None:
    from .release_app import create_release_api

    api, runtime = create_release_api()
    run_release_window(api, runtime)
