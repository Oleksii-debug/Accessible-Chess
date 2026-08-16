from __future__ import annotations

"""Release-facing Stage 1 UI boundary and broad user-flow diagnostic.

The WebView surface, native Windows menu, real engine composition and semantic
sound runtime meet at this boundary. Normal user-input failures are converted to
short messages so Python exception text never becomes screen-reader output.
"""

from pathlib import Path
import tempfile
from typing import Any

from .chesscore import parse_sq
from .sound_events import MoveSoundFacts, SoundEvent
from .ui_native_menu import install_windows_native_menu
from .webapp_keymap import KeymapAwareAccessibleChessAPI, _asset_root


class Stage1ReleaseAccessibleChessAPI(KeymapAwareAccessibleChessAPI):
    """One release API for chess state, analysis, sounds and accessible UI."""

    def __init__(
        self,
        *args: Any,
        game_sounds: Any | None = None,
        sound_runtime: Any | None = None,
        settings: Any | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._game_sounds = game_sounds
        self._sound_runtime = sound_runtime
        self._settings = settings

    def _concise_error(self, uk: str, en: str) -> dict[str, Any]:
        return self._error(uk if self.lang == "uk" else en)

    def _sound_message(self, uk: str, en: str) -> str:
        return uk if self.lang == "uk" else en

    def _sound_state(self) -> dict[str, Any]:
        enabled = True
        volume = 80
        if self._settings is not None:
            try:
                enabled = bool(self._settings.get("sounds", True))
                volume = int(self._settings.get("volume", 80))
            except Exception:
                enabled, volume = True, 80
        return {
            "enabled": enabled,
            "volume": max(0, min(100, volume)),
            "events": [event.value for event in SoundEvent],
        }

    def get_sound_settings(self) -> dict[str, Any]:
        state = self._sound_state()
        return {"ok": True, **state, "message": ""}

    def set_sound_enabled(self, enabled: bool) -> dict[str, Any]:
        if not isinstance(enabled, bool) or self._settings is None:
            return {
                "ok": False,
                **self._sound_state(),
                "message": self._sound_message(
                    "Не вдалося змінити налаштування звуку.",
                    "Sound setting could not be changed.",
                ),
            }
        try:
            self._settings.set("sounds", enabled)
        except Exception:
            return {
                "ok": False,
                **self._sound_state(),
                "message": self._sound_message(
                    "Не вдалося зберегти налаштування звуку.",
                    "Sound setting could not be saved.",
                ),
            }
        return {
            "ok": True,
            **self._sound_state(),
            "message": self._sound_message(
                "Звуки увімкнено." if enabled else "Звуки вимкнено.",
                "Sounds enabled." if enabled else "Sounds disabled.",
            ),
        }

    def set_sound_volume(self, volume: int) -> dict[str, Any]:
        if isinstance(volume, bool) or not isinstance(volume, int) or not 0 <= volume <= 100 or self._settings is None:
            return {
                "ok": False,
                **self._sound_state(),
                "message": self._sound_message(
                    "Гучність має бути від 0 до 100.",
                    "Volume must be from 0 to 100.",
                ),
            }
        try:
            self._settings.set("volume", volume)
        except Exception:
            return {
                "ok": False,
                **self._sound_state(),
                "message": self._sound_message(
                    "Не вдалося зберегти гучність.",
                    "Volume could not be saved.",
                ),
            }
        return {
            "ok": True,
            **self._sound_state(),
            "message": self._sound_message(
                f"Гучність {volume} відсотків.",
                f"Volume {volume} percent.",
            ),
        }

    def preview_sound(self, event_id: str) -> dict[str, Any]:
        try:
            event = SoundEvent(str(event_id))
        except Exception:
            return {
                "ok": False,
                **self._sound_state(),
                "message": self._sound_message("Невідомий звук.", "Unknown sound."),
            }
        if self._sound_runtime is None:
            return {
                "ok": False,
                **self._sound_state(),
                "message": self._sound_message(
                    "Прослуховування звуку недоступне.",
                    "Sound preview is unavailable.",
                ),
            }
        try:
            report = self._sound_runtime.dispatch((event,))
        except Exception:
            return {
                "ok": False,
                **self._sound_state(),
                "message": self._sound_message(
                    "Не вдалося відтворити звук.",
                    "Sound could not be played.",
                ),
            }
        if getattr(report, "disabled", False):
            return {
                "ok": False,
                **self._sound_state(),
                "message": self._sound_message(
                    "Спочатку увімкніть звуки та гучність.",
                    "Enable sounds and volume first.",
                ),
            }
        if getattr(report, "failures", ()):
            return {
                "ok": False,
                **self._sound_state(),
                "message": self._sound_message(
                    "Не вдалося відтворити звук.",
                    "Sound could not be played.",
                ),
            }
        return {
            "ok": True,
            **self._sound_state(),
            "message": self._sound_message("Звук відтворено.", "Sound played."),
        }

    def _play_latest_move(self) -> None:
        if self._game_sounds is None or not self.sans:
            return
        san = str(self.sans[-1])
        facts = MoveSoundFacts(
            legal=True,
            capture="x" in san,
            check=("+" in san or "#" in san),
            castle=san.startswith("O-O"),
            promotion="=" in san,
            game_ended=not bool(self.board.legal_moves()),
        )
        self._game_sounds.move(facts)

    def new_game(self) -> dict[str, Any]:
        result = super().new_game()
        if result.get("ok") and self._game_sounds is not None:
            self._game_sounds.start()
        return result

    def make_move(self, text: str) -> dict[str, Any]:
        before = len(self.sans)
        result = super().make_move(text)
        after = len(self.sans)
        if self._game_sounds is not None:
            if result.get("ok") and after > before:
                self._play_latest_move()
            elif not result.get("ok"):
                self._game_sounds.illegal()
        return result

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
        before = len(self.sans)
        try:
            parse_sq(square)
        except Exception:
            result = self._concise_error("Некоректне поле.", "Invalid square.")
        else:
            result = super().activate_square(square)
            if not result.get("ok"):
                allowed = {
                    self._t("review_before_move"),
                    self._t("setup_incomplete"),
                    self._t("illegal"),
                }
                message = str(result.get("announcement") or "")
                if not (
                    message in allowed
                    or message.startswith("Зараз хід іншої сторони")
                    or message.startswith("It is the other side's turn")
                    or (
                        message
                        and not any(
                            token in message
                            for token in ("Traceback", "ValueError", "RuntimeError", "Exception", " at 0x")
                        )
                    )
                ):
                    result = self._concise_error(
                        "Не вдалося виконати дію на дошці.",
                        "Board action failed.",
                    )
        after = len(self.sans)
        if self._game_sounds is not None:
            if result.get("ok") and after > before:
                self._play_latest_move()
            elif not result.get("ok"):
                self._game_sounds.illegal()
        return result


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
        checks["startup"] = bool(start.get("ok")) and len(start.get("board") or []) == 64 and start.get("historyLength") == 0
        checks["initial_focus_semantics"] = all(bool(cell.get("square")) and bool(cell.get("label")) for cell in start.get("board") or [])

        played = api.make_move("e4")
        e4_fen = str(played.get("fen"))
        checks["e4"] = bool(played.get("ok")) and played.get("historyLength") == 1 and e4_fen != start_fen
        checks["e4_board"] = any(cell.get("square") == "e4" and cell.get("occupied") for cell in played.get("board") or [])
        checks["black_to_move"] = " b " in e4_fen and bool(played.get("moves"))

        bad = api.make_move("e9")
        checks["invalid_move_atomic"] = not bad.get("ok") and bad.get("fen") == e4_fen and bad.get("historyLength") == 1
        checks["invalid_move_concise"] = str(bad.get("announcement")) in {"Нелегальний хід.", "Illegal move."}

        reviewed = api.review_previous()
        checks["history_review"] = bool(reviewed.get("ok")) and reviewed.get("fen") == start_fen and api.board.fen() == e4_fen
        live_again = api.go_to_move("end")
        checks["history_return"] = bool(live_again.get("ok")) and live_again.get("fen") == e4_fen

        undone = api.undo()
        checks["undo"] = bool(undone.get("ok")) and undone.get("fen") == start_fen and undone.get("historyLength") == 0
        redone = api.redo()
        checks["redo"] = bool(redone.get("ok")) and redone.get("fen") == e4_fen and redone.get("historyLength") == 1

        before_bad_fen = api.board.fen()
        bad_fen = api.set_fen("not a fen")
        checks["fen_error_concise"] = not bad_fen.get("ok") and bad_fen.get("announcement") in {"Некоректний FEN.", "Invalid FEN."} and api.board.fen() == before_bad_fen

        initial_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        loaded = api.set_fen(initial_fen)
        checks["fen_load"] = bool(loaded.get("ok")) and loaded.get("fen") == initial_fen and loaded.get("historyLength") == 0

        edited = api.set_position_text("W: K e1 Q d1 B: K e8", "w")
        checks["editor_load"] = bool(edited.get("ok")) and edited.get("positionComplete") is True and edited.get("historyLength") == 0
        before_bad_editor = api.board.fen()
        bad_editor = api.set_position_text("broken position", "w")
        checks["editor_error_concise"] = not bad_editor.get("ok") and bad_editor.get("announcement") in {"Некоректна позиція.", "Invalid position."} and api.board.fen() == before_bad_editor

        bad_square = api.activate_square("z9")
        checks["square_error_concise"] = not bad_square.get("ok") and bad_square.get("announcement") in {"Некоректне поле.", "Invalid square."}

        final = api.new_game()
        checks["final_board_64"] = len(final.get("board") or []) == 64
        checks["no_raw_exception_text"] = not any(token in str(final.get("announcement") or "") for token in ("Traceback", "ValueError", "RuntimeError", "Exception"))
        sound = api.get_sound_settings()
        checks["sound_settings_contract"] = bool(sound.get("ok")) and isinstance(sound.get("enabled"), bool) and 0 <= int(sound.get("volume", -1)) <= 100

        return {
            "ok": all(checks.values()),
            "checks": checks,
            "boardCells": len(final.get("board") or []),
            "finalFen": final.get("fen"),
        }
    finally:
        if owned_temp is not None:
            owned_temp.cleanup()


def run_release_window(api: Stage1ReleaseAccessibleChessAPI, runtime: Any | None = None) -> None:
    import webview

    html = _asset_root() / "web" / "index.html"
    bootstrap = _asset_root() / "web" / "stage1_release_bootstrap.js"
    if not html.exists():
        if runtime is not None:
            runtime.close()
        raise RuntimeError(f"Accessible HTML UI not found: {html}")
    if not bootstrap.exists():
        if runtime is not None:
            runtime.close()
        raise RuntimeError(f"Stage 1 WebView bootstrap not found: {bootstrap}")
    bootstrap_source = bootstrap.read_text(encoding="utf-8")

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
            raise RuntimeError("Accessible native Windows menu could not be attached to the WebView2 host.")

    def install_release_web_contract(*_args: Any) -> None:
        window.evaluate_js(bootstrap_source)

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
    # Import at execution time so release_app can depend on this API without a
    # module-import cycle. The packaged launcher and the tested production
    # composition therefore use exactly the same API instance.
    from .release_app import create_release_api

    api, runtime = create_release_api()
    run_release_window(api, runtime)
