from __future__ import annotations

"""Keymap-aware composition root for the semantic WebView2 UI.

The legacy :mod:`acs.webapp` class still contains compatibility shortcut logic.
This module is the release-facing API used by the launcher: it routes move-entry
aliases through :class:`KeymapService`, persists the user's profile outside the
installation directory, and exposes JSON-friendly keymap operations to WebView2.

Action IDs remain stable; only their user-facing bindings/aliases are mutable.
The release composition root also redirects the legacy presentation SAN helper
to the shared notation formatter so move lists, last-move text and announcements
do not maintain a second notation implementation.
"""

import os
from pathlib import Path
from typing import Any

from . import webapp as _legacy_webapp
from .keybindings import BindingContext
from .notation import NotationError, format_san
from .ui_keymap_service import KeymapService
from .ui_native_menu import make_keymap_menu


AccessibleChessAPI = _legacy_webapp.AccessibleChessAPI
_asset_root = _legacy_webapp._asset_root


def _shared_spoken_san(san: str, lang: str = "uk") -> str:
    """Render SAN through the one shared notation layer used by release UI.

    ``AccessibleChessAPI`` still calls its historical module-level helper from
    several inherited methods. Rebinding that helper here is a bounded
    compatibility shim: it fixes the release-facing WebView without copying
    notation rules into presentation code or forcing a big-bang rewrite of the
    legacy module. Once the legacy API is retired this shim can disappear.
    """

    profile = "uk_literal" if lang == "uk" else "en_literal"
    try:
        return format_san(san, profile)
    except NotationError:
        # A Board-produced SAN token should normally be supported. Keep the UI
        # readable if an unexpected future SAN extension appears, while leaving
        # the canonical formatter as the only place that interprets notation.
        return str(san).strip().replace("0-0-0", "O-O-O").replace("0-0", "O-O")


# The inherited API resolves ``_spoken_san`` in acs.webapp globals. Patch that
# single compatibility seam at the composition root rather than forking every
# inherited move/history method. No chess/domain rule is changed here.
_legacy_webapp._spoken_san = _shared_spoken_san


def default_keymap_path() -> Path:
    """Return a per-user writable keymap path suitable for packaged Windows builds."""

    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / ".accessible-chess"
    return base / "AccessibleChess" / "keymap.json" if appdata else base / "keymap.json"


class KeymapAwareAccessibleChessAPI(AccessibleChessAPI):
    """Release API that makes the central registry authoritative for commands."""

    def __init__(
        self,
        lang: str = "uk",
        *,
        keymap_path: str | Path | None = None,
    ) -> None:
        super().__init__(lang)
        self.keymap_service = KeymapService(keymap_path or default_keymap_path(), lang=self.lang)

    # JSON-friendly bridge methods. WebView2 must call these rather than
    # reproducing normalization/conflict/persistence rules in JavaScript.
    def keymap_snapshot(self) -> dict[str, Any]:
        return self.keymap_service.snapshot()

    def keymap_search(self, query: str = "", context: str | None = None) -> list[dict[str, Any]]:
        return self.keymap_service.search(query, context)

    def keymap_preview(self, action_id: str, value: str) -> dict[str, Any]:
        return self.keymap_service.preview(action_id, value)

    def keymap_capture_shortcut(
        self,
        action_id: str,
        key: str,
        ctrl: bool = False,
        alt: bool = False,
        shift: bool = False,
        win: bool = False,
    ) -> dict[str, Any]:
        return self.keymap_service.capture_shortcut(
            action_id, key, ctrl=ctrl, alt=alt, shift=shift, win=win
        )

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
        """Import a profile through the same warning-confirmation policy as edits."""

        return self.keymap_service.import_profile(text, allow_warnings=allow_warnings)

    def keymap_resolve_binding(self, context: str, binding: str) -> dict[str, Any] | None:
        return self.keymap_service.resolve_binding(context, binding)

    def keymap_resolve_alias(self, context: str, alias: str) -> dict[str, Any] | None:
        return self.keymap_service.resolve_alias(context, alias)

    def set_language(self, lang: str) -> dict[str, Any]:
        result = super().set_language(lang)
        if result.get("ok"):
            self.keymap_service.set_language(self.lang)
        return result

    def make_move(self, text: str) -> dict[str, Any]:
        """Execute a remappable move-entry command or parse literal chess input.

        This deliberately does not call ``AccessibleChessAPI.make_move`` because
        that compatibility method contains the old hardcoded one-letter command
        dictionary. A removed/remapped alias must become ordinary chess input,
        never remain a hidden second shortcut.
        """

        text = (text or "").strip()
        if not text:
            return self._error("Введіть хід." if self.lang == "uk" else "Enter a move.")

        resolution = self.keymap_service.resolve_alias(BindingContext.MOVE_ENTRY.value, text)
        if resolution is not None:
            return self._dispatch_move_entry_action(str(resolution["actionId"]))

        if not self._at_history_end():
            return self._error(self._t("review_before_move"))
        if not self._position_complete():
            return self._error(self._t("setup_incomplete"))
        try:
            side = self.board.turn
            san = self.board.push_text(text)
            self.sans.append(san)
            self.move_sides.append(side)
            self.redo_meta.clear()
            self.selected_source = None
            self._record_position_after_move()
            return self._ok(("Зіграно: " if self.lang == "uk" else "Played: ") + _shared_spoken_san(san, self.lang))
        except Exception as exc:
            return self._error(str(exc))

    def _dispatch_move_entry_action(self, action_id: str) -> dict[str, Any]:
        handlers = {
            "move.undo": self.undo,
            "move.redo": self.redo,
            "move.white_to_move": lambda: self.set_turn("w"),
            "move.black_to_move": lambda: self.set_turn("b"),
            "move.clear": self.clear_board,
            "move.standard": self.new_game,
            "move.empty": self.clear_board,
        }
        if action_id == "move.last":
            prefix = "Останній хід: " if self.lang == "uk" else "Last move: "
            return self._ok(prefix + self.get_state()["lastMove"])
        handler = handlers.get(action_id)
        if handler is None:
            return self._error(
                ("Команда ще не підключена до інтерфейсу: " if self.lang == "uk" else
                 "Command is not wired to the UI yet: ") + action_id
            )
        return handler()


def main() -> None:
    import webview

    api = KeymapAwareAccessibleChessAPI()
    window_holder: dict[str, Any] = {}
    html = _asset_root() / "web" / "index.html"
    if not html.exists():
        raise RuntimeError(f"Accessible HTML UI not found: {html}")
    menu = make_keymap_menu(webview, api, window_holder)
    window = webview.create_window(
        "Accessible Chess — 0.4 NVDA architecture",
        url=str(html),
        js_api=api,
        width=1150,
        height=820,
        min_size=(800, 600),
        text_select=True,
        menu=menu,
    )
    window_holder["window"] = window
    webview.start(gui="edgechromium", private_mode=True)
