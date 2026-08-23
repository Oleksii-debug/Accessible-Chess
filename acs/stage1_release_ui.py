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
from .stage1_native_menu_router import Stage1NativeMenuActionProxy
from .webapp_keymap import KeymapAwareAccessibleChessAPI


class Stage1ReleaseAccessibleChessAPI(_core.Stage1ReleaseAccessibleChessAPI):
    """Release API with the saturation board-command dispatcher enabled."""

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
