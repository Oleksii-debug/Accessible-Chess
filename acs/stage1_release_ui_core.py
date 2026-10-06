from __future__ import annotations

"""Release-facing Stage 1 UI boundary and broad user-flow diagnostic.

The WebView surface, native Windows menu, real engine composition and semantic
sound runtime meet at this boundary. Normal user-input failures are converted to
short messages so Python exception text never becomes screen-reader output.
"""

from pathlib import Path
import copy
import logging
import tempfile
import time
from typing import Any

from .chesscore import parse_sq
from .clock_service import ClockSnapshot, TimeControl
from .engine_game_session import (
    EngineGameSessionCoordinator,
    TakebackTransaction,
    EngineNoMoveHandoff,
    EngineNoMoveResolution,
    EngineTurnState,
)
from .engine_play_service import (
    EngineGameConfig,
    EngineGameHandoff,
    EngineGameIntent,
    EnginePlayService,
    EngineSideMode,
)
from .engine_ports import EngineContractError, EngineContractErrorCode
from .game_lifecycle import EndReason, GameStatus
from .sound_events import MoveSoundFacts, SoundEvent
from .ui_native_menu import install_windows_native_menu
from .webapp_keymap import (
    KeymapAwareAccessibleChessAPI,
    _asset_root,
    _shared_spoken_san,
)


_LOG = logging.getLogger(__name__)


class Stage1ReleaseAccessibleChessAPI(KeymapAwareAccessibleChessAPI):
    """One release API for chess state, analysis, sounds and accessible UI."""

    def __init__(
        self,
        *args: Any,
        game_sounds: Any | None = None,
        sound_runtime: Any | None = None,
        settings: Any | None = None,
        sound_asset_resolver: Any | None = None,
        engine_play_service: EnginePlayService | None = None,
        **kwargs: Any,
    ) -> None:
        if engine_play_service is not None and not isinstance(
            engine_play_service,
            EnginePlayService,
        ):
            raise TypeError("engine_play_service must be EnginePlayService or None")
        super().__init__(*args, **kwargs)
        self._game_sounds = game_sounds
        self._sound_runtime = sound_runtime
        self._settings = settings
        self._sound_asset_resolver = sound_asset_resolver
        self._engine_play_service = engine_play_service
        self._engine_session: EngineGameSessionCoordinator | None = None
        self._engine_game_phase = "idle"
        self._engine_game_error: str | None = None
        self._engine_takeback_unsafe = False
        self._engine_thinking = False
        self._engine_clock_history: list[ClockSnapshot] = []
        self._clock_sound_not_before = 0.0
        self._low_time_warned_sides: set[str] = set()
        self._suppress_next_engine_move_sound_for_start = False

    def _concise_error(self, uk: str, en: str) -> dict[str, Any]:
        return self._error(uk if self.lang == "uk" else en)

    def _sound_message(self, uk: str, en: str) -> str:
        return uk if self.lang == "uk" else en

    def _stop_current_sound(self) -> None:
        runtime = self._sound_runtime
        stop = getattr(runtime, "stop_current", None) if runtime is not None else None
        if callable(stop):
            try:
                stop()
            except Exception:
                pass
        self._clock_sound_not_before = 0.0

    def _sound_variant_options(self, event: SoundEvent) -> tuple[dict[str, str], ...]:
        options = ()
        resolver = self._sound_asset_resolver
        if resolver is not None and callable(getattr(resolver, "variants_for", None)):
            try:
                options = tuple(resolver.variants_for(event))
            except Exception:
                options = ()
        if not options:
            return ({"id": "1", "labelUk": "Варіант 1", "labelEn": "Variant 1"},)
        return tuple(
            {
                "id": str(option.variant_id),
                "labelUk": str(option.label_uk),
                "labelEn": str(option.label_en),
            }
            for option in options
        )

    def _sound_state(self) -> dict[str, Any]:
        enabled = True
        newgame_animation = True
        volume = 80
        tick_policy = "my_turn"
        tick_last_seconds = 0
        low_time_policy = "my_turn"
        low_time_seconds = 30
        if self._settings is not None:
            try:
                enabled = bool(self._settings.get("sounds", True))
                newgame_animation = bool(self._settings.get("newgame_animation", True))
                volume = int(self._settings.get("volume", 80))
                tick_policy = str(self._settings.get("tick_policy", "my_turn"))
                tick_last_seconds = int(self._settings.get("tick_last_seconds", 0))
                low_time_policy = str(self._settings.get("low_time_policy", "my_turn"))
                low_time_seconds = int(self._settings.get("low_time_seconds", 30))
            except Exception:
                enabled = True
                newgame_animation = True
                volume = 80
                tick_policy = "my_turn"
                tick_last_seconds = 0
                low_time_policy = "my_turn"
                low_time_seconds = 30

        variants: dict[str, list[dict[str, str]]] = {}
        selected: dict[str, str] = {}
        for event in SoundEvent:
            options = self._sound_variant_options(event)
            variants[event.value] = list(options)
            available = {item["id"] for item in options}
            choice = "1"
            if self._settings is not None:
                try:
                    choice = str(
                        self._settings.get(f"sound_{event.value}_variant", "1")
                    )
                except Exception:
                    choice = "1"
            selected[event.value] = choice if choice in available else "1"

        return {
            "enabled": enabled,
            "newGameAnimation": newgame_animation,
            "volume": max(0, min(100, volume)),
            "tickPolicy": tick_policy if tick_policy in {"off", "my_turn", "both"} else "my_turn",
            "tickLastSeconds": max(0, min(3600, tick_last_seconds)),
            "lowTimePolicy": low_time_policy if low_time_policy in {"off", "my_turn", "both"} else "my_turn",
            "lowTimeSeconds": max(0, min(3600, low_time_seconds)),
            "events": [event.value for event in SoundEvent],
            "variants": variants,
            "selectedVariants": selected,
        }

    def get_sound_settings(self) -> dict[str, Any]:
        state = self._sound_state()
        return {"ok": True, **state, "message": ""}

    def set_sound_variant(self, event_id: str, variant_id: str) -> dict[str, Any]:
        try:
            event = SoundEvent(str(event_id))
        except Exception:
            return {
                "ok": False,
                **self._sound_state(),
                "message": self._sound_message("Невідомий звук.", "Unknown sound."),
            }
        if self._settings is None or not isinstance(variant_id, str):
            return {
                "ok": False,
                **self._sound_state(),
                "message": self._sound_message(
                    "Не вдалося змінити варіант звуку.",
                    "Sound variant could not be changed.",
                ),
            }
        options = self._sound_variant_options(event)
        available = {item["id"] for item in options}
        if variant_id not in available:
            return {
                "ok": False,
                **self._sound_state(),
                "message": self._sound_message(
                    "Такого варіанта звуку немає.",
                    "That sound variant is not available.",
                ),
            }
        try:
            self._settings.set(f"sound_{event.value}_variant", variant_id)
        except Exception:
            return {
                "ok": False,
                **self._sound_state(),
                "message": self._sound_message(
                    "Не вдалося зберегти варіант звуку.",
                    "Sound variant could not be saved.",
                ),
            }
        return {
            "ok": True,
            **self._sound_state(),
            "message": self._sound_message(
                f"Вибрано варіант {variant_id}.",
                f"Variant {variant_id} selected.",
            ),
        }

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
            if not enabled:
                self._stop_current_sound()
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

    def set_newgame_animation_enabled(self, enabled: bool) -> dict[str, Any]:
        if not isinstance(enabled, bool) or self._settings is None:
            return {
                "ok": False,
                **self._sound_state(),
                "message": self._sound_message(
                    "Не вдалося змінити анімацію нової партії.",
                    "New-game animation setting could not be changed.",
                ),
            }
        try:
            self._settings.set("newgame_animation", enabled)
        except Exception:
            return {
                "ok": False,
                **self._sound_state(),
                "message": self._sound_message(
                    "Не вдалося зберегти анімацію нової партії.",
                    "New-game animation setting could not be saved.",
                ),
            }
        return {
            "ok": True,
            **self._sound_state(),
            "message": self._sound_message(
                "Анімацію нової партії увімкнено."
                if enabled
                else "Анімацію нової партії вимкнено.",
                "New-game animation enabled."
                if enabled
                else "New-game animation disabled.",
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
            if volume == 0:
                self._stop_current_sound()
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

    def set_clock_sound_policy(self, policy: str) -> dict[str, Any]:
        if policy not in {"off", "my_turn", "both"} or self._settings is None:
            return {
                "ok": False,
                **self._sound_state(),
                "message": self._sound_message(
                    "Некоректний режим звуку годинника.",
                    "Invalid clock sound mode.",
                ),
            }
        try:
            self._settings.set("tick_policy", policy)
        except Exception:
            return {
                "ok": False,
                **self._sound_state(),
                "message": self._sound_message(
                    "Не вдалося зберегти режим годинника.",
                    "Clock sound mode could not be saved.",
                ),
            }
        labels = {
            "off": ("Звук годинника вимкнено.", "Clock sound disabled."),
            "my_turn": ("Годинник звучить лише під час мого ходу.", "Clock sounds only on my turn."),
            "both": ("Годинник звучить під час ходу обох сторін.", "Clock sounds on both turns."),
        }
        uk, en = labels[policy]
        return {"ok": True, **self._sound_state(), "message": self._sound_message(uk, en)}

    def set_clock_sound_last_seconds(self, seconds: int) -> dict[str, Any]:
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, int)
            or not 0 <= seconds <= 3600
            or self._settings is None
        ):
            return {
                "ok": False,
                **self._sound_state(),
                "message": self._sound_message(
                    "Кількість секунд має бути від 0 до 3600.",
                    "Seconds must be from 0 to 3600.",
                ),
            }
        try:
            self._settings.set("tick_last_seconds", seconds)
        except Exception:
            return {
                "ok": False,
                **self._sound_state(),
                "message": self._sound_message(
                    "Не вдалося зберегти межу звуку годинника.",
                    "Clock sound threshold could not be saved.",
                ),
            }
        return {
            "ok": True,
            **self._sound_state(),
            "message": self._sound_message(
                "Годинник звучить увесь час."
                if seconds == 0
                else f"Годинник звучить останні {seconds} секунд.",
                "Clock sounds for the whole timed game."
                if seconds == 0
                else f"Clock sounds during the last {seconds} seconds.",
            ),
        }

    def set_low_time_policy(self, policy: str) -> dict[str, Any]:
        if policy not in {"off", "my_turn", "both"} or self._settings is None:
            return {
                "ok": False,
                **self._sound_state(),
                "message": self._sound_message(
                    "Некоректний режим попередження про малий час.",
                    "Invalid low-time warning mode.",
                ),
            }
        try:
            self._settings.set("low_time_policy", policy)
            if policy == "off":
                self._low_time_warned_sides.clear()
        except Exception:
            return {
                "ok": False,
                **self._sound_state(),
                "message": self._sound_message(
                    "Не вдалося зберегти режим попередження про малий час.",
                    "Low-time warning mode could not be saved.",
                ),
            }
        labels = {
            "off": ("Попередження про малий час вимкнено.", "Low-time warning disabled."),
            "my_turn": ("Попередження звучить лише для мого часу.", "Low-time warning sounds only for my clock."),
            "both": ("Попередження звучить для обох сторін.", "Low-time warning sounds for both clocks."),
        }
        uk, en = labels[policy]
        return {"ok": True, **self._sound_state(), "message": self._sound_message(uk, en)}

    def set_low_time_seconds(self, seconds: int) -> dict[str, Any]:
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, int)
            or not 0 <= seconds <= 3600
            or self._settings is None
        ):
            return {
                "ok": False,
                **self._sound_state(),
                "message": self._sound_message(
                    "Межа малого часу має бути від 0 до 3600 секунд.",
                    "Low-time threshold must be from 0 to 3600 seconds.",
                ),
            }
        try:
            self._settings.set("low_time_seconds", seconds)
            self._low_time_warned_sides.clear()
        except Exception:
            return {
                "ok": False,
                **self._sound_state(),
                "message": self._sound_message(
                    "Не вдалося зберегти межу малого часу.",
                    "Low-time threshold could not be saved.",
                ),
            }
        return {
            "ok": True,
            **self._sound_state(),
            "message": self._sound_message(
                "Попередження про малий час вимкнено."
                if seconds == 0
                else f"Попередження звучить при {seconds} секундах.",
                "Low-time warning disabled."
                if seconds == 0
                else f"Low-time warning sounds at {seconds} seconds.",
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
        preview_guard_seconds = {
            SoundEvent.START: 8.7,
            SoundEvent.TICK: 3.5,
            SoundEvent.LOW_TIME: 4.0,
        }.get(event)
        if preview_guard_seconds is not None and getattr(report, "delivered", ()):
            self._clock_sound_not_before = max(
                self._clock_sound_not_before,
                time.monotonic() + preview_guard_seconds,
            )
        return {
            "ok": True,
            **self._sound_state(),
            "message": self._sound_message("Звук відтворено.", "Sound played."),
        }

    def _play_game_start_sound(self) -> None:
        if self._game_sounds is None:
            return
        report = self._game_sounds.start()
        if not getattr(report, "disabled", False) and not getattr(report, "failures", ()):
            # Both supplied NEWGAME variants are a little over eight seconds.
            # Keep the long clock ambience from taking over the same Windows
            # playback channel before that cue has completed.
            self._clock_sound_not_before = time.monotonic() + 8.7

    def clock_sound_pulse(self) -> dict[str, Any]:
        """Play one complete clock ambience segment when current policy allows it."""

        base = {"ok": True, "played": False, "disabled": False}
        if time.monotonic() < self._clock_sound_not_before:
            return base
        session = self._engine_session
        if (
            self._game_sounds is None
            or self._settings is None
            or session is None
            or self._engine_game_phase != "active"
        ):
            return base
        try:
            tick_policy = str(self._settings.get("tick_policy", "my_turn"))
            tick_last_seconds = int(self._settings.get("tick_last_seconds", 0))
            low_time_policy = str(self._settings.get("low_time_policy", "my_turn"))
            low_time_seconds = int(self._settings.get("low_time_seconds", 30))
            snapshot = session.snapshot()
            if snapshot.config.time_control.untimed:
                return base
            human = "b" if snapshot.config.engine_side == "w" else "w"
            if snapshot.turn_state is EngineTurnState.HUMAN:
                active_side = human
            elif snapshot.turn_state is EngineTurnState.ENGINE:
                active_side = snapshot.config.engine_side
            else:
                return base
            remaining_ms = (
                snapshot.clock.white_ms if active_side == "w" else snapshot.clock.black_ms
            )
            if remaining_ms <= 0:
                return base

            if low_time_seconds <= 0 or remaining_ms > low_time_seconds * 1000:
                self._low_time_warned_sides.discard(active_side)
            low_time_allowed = (
                low_time_seconds > 0
                and low_time_policy != "off"
                and (low_time_policy == "both" or active_side == human)
            )
            if (
                low_time_allowed
                and remaining_ms <= low_time_seconds * 1000
                and active_side not in self._low_time_warned_sides
            ):
                report = self._game_sounds.low_time()
                delivered = bool(getattr(report, "delivered", ()))
                failed = bool(getattr(report, "failures", ()))
                disabled = bool(getattr(report, "disabled", False))
                if delivered and not failed and not disabled:
                    self._low_time_warned_sides.add(active_side)
                    # The default aooga warning is longer than one 3.4-second
                    # clock-pump interval. Do not let the next Tick restart the
                    # shared Windows playback channel before it completes.
                    self._clock_sound_not_before = time.monotonic() + 4.0
                return {
                    "ok": not failed,
                    "played": delivered,
                    "disabled": disabled,
                    "event": "low_time",
                }

            if tick_policy == "off":
                return {**base, "disabled": True}
            if tick_policy == "my_turn" and active_side != human:
                return base
            if tick_last_seconds > 0 and remaining_ms > tick_last_seconds * 1000:
                return base
            report = self._game_sounds.tick()
            return {
                "ok": not bool(getattr(report, "failures", ())),
                "played": bool(getattr(report, "delivered", ())),
                "disabled": bool(getattr(report, "disabled", False)),
                "event": "tick",
            }
        except Exception:
            return {"ok": False, "played": False, "disabled": False}

    def _play_latest_move(self) -> None:
        if self._game_sounds is None or not self.sans:
            return
        san = str(self.sans[-1])
        terminal = not bool(self.board.legal_moves())
        facts = MoveSoundFacts(
            legal=True,
            capture="x" in san,
            check=("+" in san or "#" in san),
            castle=san.startswith("O-O"),
            promotion="=" in san,
            game_ended=False,
        )
        self._game_sounds.move(facts)
        if terminal:
            if self.board.in_check(self.board.turn):
                self._game_sounds.checkmate()
            else:
                self._game_sounds.draw()

    def _play_game_end_sound(self) -> None:
        if self._game_sounds is None:
            return
        try:
            self._game_sounds.end()
        except Exception:
            pass

    def _resume_game_sound_after_takeback(self) -> None:
        if self._game_sounds is None:
            return
        try:
            self._game_sounds.resume_after_takeback()
        except Exception:
            pass

    def _reset_engine_game_state(self) -> None:
        self._engine_session = None
        self._engine_game_phase = "idle"
        self._engine_game_error = None
        self._engine_takeback_unsafe = False
        self._engine_thinking = False
        self._engine_clock_history = []
        self._low_time_warned_sides.clear()

    @staticmethod
    def _bounded_int(value: Any, *, low: int, high: int) -> int:
        if isinstance(value, bool):
            raise ValueError("boolean is not an integer setting")
        if isinstance(value, str):
            text = value.strip()
            if not text or not text.isdecimal():
                raise ValueError("setting must be an integer")
            value = int(text)
        if not isinstance(value, int) or not low <= value <= high:
            raise ValueError("setting is outside supported bounds")
        return value

    def _engine_human_side(self) -> str | None:
        session = self._engine_session
        if session is None:
            return None
        try:
            engine_side = session.snapshot().config.engine_side
        except Exception:
            return None
        return "b" if engine_side == "w" else "w"

    def _engine_side_name(self, side: str | None) -> str:
        if side == "w":
            return "білі" if self.lang == "uk" else "White"
        if side == "b":
            return "чорні" if self.lang == "uk" else "Black"
        return "—"

    @staticmethod
    def _clock_text(milliseconds: int) -> str:
        remaining = max(0, int(milliseconds))
        seconds = (remaining + 999) // 1000
        return f"{seconds // 60}:{seconds % 60:02d}"

    def _record_engine_clock(self, snapshot: Any) -> None:
        clock = snapshot.clock
        if not isinstance(clock, ClockSnapshot):
            raise TypeError("engine session snapshot must carry ClockSnapshot")
        ply = len(self.sans)
        if len(self._engine_clock_history) > ply + 1:
            del self._engine_clock_history[ply + 1:]
        if len(self._engine_clock_history) == ply:
            self._engine_clock_history.append(clock)
        elif len(self._engine_clock_history) == ply + 1:
            self._engine_clock_history[ply] = clock
        else:
            raise RuntimeError("engine clock history is not aligned with move history")

    def _engine_clock_restore_snapshot(self) -> ClockSnapshot:
        ply = len(self.sans)
        if not 0 <= ply < len(self._engine_clock_history):
            raise RuntimeError("historical engine clock is unavailable")
        return self._engine_clock_history[ply]

    def _undo_engine_game_to_human_turn(self) -> None:
        human = self._engine_human_side()
        if human is None:
            raise RuntimeError("engine game side is unavailable")
        undone = 0
        while self.sans and undone < 2:
            result = super().undo()
            if not result.get("ok"):
                break
            undone += 1
            if self.board.turn == human:
                break
        if undone == 0 or self.board.turn != human:
            raise RuntimeError("engine takeback could not restore the human turn")
        # Redo and historical clock entries must remain intact until both
        # the restored-ply provider and clock/lifecycle acceptance succeed.

    def _capture_engine_takeback_state(self) -> dict[str, Any]:
        return {
            "fen": self.board.fen(),
            "undo_stack": copy.deepcopy(self.board.undo_stack),
            "redo_stack": copy.deepcopy(self.board.redo_stack),
            "last_move": self.board.last_move,
            "sans": list(self.sans),
            "move_sides": list(self.move_sides),
            "redo_meta": copy.deepcopy(self.redo_meta),
            "history": self.review_history.export_tree(),
            "live_history_node": self.live_history_node,
            "selected_source": self.selected_source,
            "clock_history": list(self._engine_clock_history),
            "phase": self._engine_game_phase,
            "error": self._engine_game_error,
            "announcement": self.announcement,
        }

    def _restore_engine_takeback_state(self, state: dict[str, Any]) -> None:
        # Rebuild from canonical, previously validated Board/ReviewHistory
        # snapshots while retaining the original Board object's identity.
        history = type(self.review_history).from_tree(state["history"])
        self.board.set_fen(state["fen"], clear_history=False)
        self.board.undo_stack[:] = copy.deepcopy(state["undo_stack"])
        self.board.redo_stack[:] = copy.deepcopy(state["redo_stack"])
        self.board.last_move = state["last_move"]
        self.sans[:] = state["sans"]
        self.move_sides[:] = state["move_sides"]
        self.redo_meta[:] = copy.deepcopy(state["redo_meta"])
        self.review_history = history
        self.review_adapter = self.review_adapter.__class__(
            history, language=self.lang,
        )
        self.live_history_node = state["live_history_node"]
        self.selected_source = state["selected_source"]
        self._engine_clock_history[:] = state["clock_history"]
        self._engine_game_phase = state["phase"]
        self._engine_game_error = state["error"]
        self.announcement = state["announcement"]
        if (self.board.fen() != state["fen"]
                or self.review_history.export_tree() != state["history"]):
            raise RuntimeError("engine takeback checkpoint recovery failed")

    def _commit_engine_takeback_state(self) -> None:
        self.redo_meta.clear()
        self.board.redo_stack.clear()
        del self._engine_clock_history[len(self.sans) + 1:]

    def _prepare_engine_takeback_transaction(self) -> TakebackTransaction:
        state = self._capture_engine_takeback_state()
        return TakebackTransaction(
            undo=self._undo_engine_game_to_human_turn,
            rollback=lambda: self._restore_engine_takeback_state(state),
            commit=self._commit_engine_takeback_state,
        )

    def _outcome_text(self, snapshot: Any) -> str:
        outcome = snapshot.lifecycle.outcome
        if outcome is None:
            return "Партію завершено." if self.lang == "uk" else "Game finished."
        human = "b" if snapshot.config.engine_side == "w" else "w"
        if outcome.winner == human:
            result = "Ви перемогли." if self.lang == "uk" else "You won."
        elif outcome.winner is None:
            result = "Нічия." if self.lang == "uk" else "Draw."
        else:
            result = "Stockfish переміг." if self.lang == "uk" else "Stockfish won."
        reasons = {
            EndReason.CHECKMATE: ("Мат.", "Checkmate."),
            EndReason.STALEMATE: ("Пат.", "Stalemate."),
            EndReason.RESIGNATION: ("Здача.", "Resignation."),
            EndReason.TIMEOUT: ("Час вичерпано.", "Time expired."),
            EndReason.DRAW_AGREEMENT: ("Нічия за згодою.", "Draw by agreement."),
        }
        reason = reasons.get(outcome.reason)
        if reason is None:
            return result
        return f"{reason[0] if self.lang == 'uk' else reason[1]} {result}"

    def _engine_game_projection(self) -> dict[str, Any]:
        available = self._engine_play_service is not None
        session = self._engine_session
        base = {
            "available": available,
            "configured": session is not None,
            "active": self._engine_game_phase == "active",
            "phase": self._engine_game_phase,
            "thinking": self._engine_thinking,
            "humanSide": None,
            "engineSide": None,
            "level": None,
            "initialMinutes": 0,
            "incrementSeconds": 0,
            "turn": "idle",
            "whiteClock": "0:00",
            "blackClock": "0:00",
            "clockStatus": "",
            "canTakeback": False,
            "canOfferDraw": False,
            "canStop": self._engine_game_phase in {"active", "error"} and session is not None,
            "canRetry": (self._engine_game_phase == "error" and session is not None
                         and not self._engine_takeback_unsafe),
            "error": self._engine_game_error,
            "status": "",
        }
        if session is None:
            if self._engine_game_phase == "error" and self._engine_game_error:
                base["status"] = self._engine_game_error
            else:
                base["status"] = (
                    "Гра проти Stockfish недоступна."
                    if not available and self.lang == "uk"
                    else "Stockfish game is unavailable."
                    if not available
                    else "Гру проти Stockfish не розпочато."
                    if self.lang == "uk"
                    else "No Stockfish game is running."
                )
            return base
        try:
            snapshot = session.snapshot()
        except Exception:
            base["phase"] = "error"
            base["active"] = False
            base["turn"] = "error"
            base["canRetry"] = not self._engine_takeback_unsafe
            base["status"] = self._engine_game_error or (
                "Гру проти Stockfish призупинено."
                if self.lang == "uk"
                else "The Stockfish game is paused."
            )
            return base

        human = "b" if snapshot.config.engine_side == "w" else "w"
        control = snapshot.config.time_control
        base.update({
            "humanSide": human,
            "engineSide": snapshot.config.engine_side,
            "level": snapshot.config.level.level,
            "initialMinutes": control.initial_ms // 60_000,
            "incrementSeconds": control.increment_ms // 1_000,
            "turn": snapshot.turn_state.value,
            "whiteClock": self._clock_text(snapshot.clock.white_ms),
            "blackClock": self._clock_text(snapshot.clock.black_ms),
            "canTakeback": (
                self._engine_game_phase in {"active", "finished", "error"}
                and not self._engine_takeback_unsafe
                and any(side == human for side in self.move_sides)
            ),
            "canOfferDraw": (
                self._engine_game_phase == "active"
                and snapshot.turn_state is EngineTurnState.HUMAN
            ),
        })
        if not control.untimed:
            base["clockStatus"] = (
                f"Час: білі {base['whiteClock']}, чорні {base['blackClock']}."
                if self.lang == "uk"
                else f"Clocks: White {base['whiteClock']}, Black {base['blackClock']}."
            )
        if self._engine_takeback_unsafe:
            base["status"] = self._engine_game_error or self._takeback_recovery_message()
        elif self._engine_game_phase == "error":
            base["status"] = self._engine_game_error or (
                "Гру проти Stockfish призупинено."
                if self.lang == "uk"
                else "The Stockfish game is paused."
            )
        elif self._engine_game_phase == "stopped":
            base["status"] = (
                "Гру проти Stockfish зупинено."
                if self.lang == "uk"
                else "The Stockfish game was stopped."
            )
        elif snapshot.lifecycle.status is GameStatus.FINISHED:
            self._engine_game_phase = "finished"
            base["phase"] = "finished"
            base["active"] = False
            base["canOfferDraw"] = False
            base["canStop"] = False
            self._play_game_end_sound()
            base["status"] = self._outcome_text(snapshot)
        elif self._engine_thinking or snapshot.turn_state is EngineTurnState.ENGINE:
            base["status"] = (
                f"Stockfish думає. Рівень {snapshot.config.level.level}."
                if self.lang == "uk"
                else f"Stockfish is thinking. Level {snapshot.config.level.level}."
            )
        else:
            side = self._engine_side_name(human)
            clocks = ""
            if not control.untimed:
                clocks = (
                    f" Час: білі {base['whiteClock']}, чорні {base['blackClock']}."
                    if self.lang == "uk"
                    else f" Clocks: White {base['whiteClock']}, Black {base['blackClock']}."
                )
            base["status"] = (
                f"Ви граєте за {side}. Рівень {snapshot.config.level.level}. Ваш хід.{clocks}"
                if self.lang == "uk"
                else f"You play {side}. Level {snapshot.config.level.level}. Your move.{clocks}"
            )
        return base

    def get_state(self) -> dict[str, Any]:
        state = super().get_state()
        game = self._engine_game_projection()
        state["engineGame"] = game
        state["engineGameStatus"] = game["status"]
        if game["configured"]:
            state["mode"] = "engine_play"
        return state

    def _timeout_mating_capability(self, flagged_side: str) -> bool:
        opponent = "b" if flagged_side == "w" else "w"
        material = [
            piece.upper()
            for piece in self.board.board
            if piece and (piece.isupper() if opponent == "w" else piece.islower())
            and piece.upper() != "K"
        ]
        if not material:
            return False
        if len(material) == 1 and material[0] in {"B", "N"}:
            flagged_material = [
                piece
                for piece in self.board.board
                if piece and (piece.isupper() if flagged_side == "w" else piece.islower())
                and piece.upper() != "K"
            ]
            return bool(flagged_material)
        return True

    def _resolve_engine_no_move(
        self,
        handoff: EngineNoMoveHandoff,
    ) -> EngineNoMoveResolution | None:
        if handoff.fen != self.board.fen() or self.board.legal_moves():
            return None
        if self.board.in_check(self.board.turn):
            winner = "b" if self.board.turn == "w" else "w"
            result = "1-0" if winner == "w" else "0-1"
            return EngineNoMoveResolution(result, EndReason.CHECKMATE, winner)
        return EngineNoMoveResolution("1/2-1/2", EndReason.STALEMATE)

    def _commit_engine_move(self, move: str) -> None:
        # Engine callbacks use the exact same Board/history transaction as
        # manual moves.  Provider or history failures therefore publish nothing
        # instead of leaving a moved Board with stale review metadata.
        san = self._commit_move_text_transaction(move)
        if self._suppress_next_engine_move_sound_for_start:
            self._suppress_next_engine_move_sound_for_start = False
        else:
            self._play_latest_move()

    def _finish_engine_game_from_board(self) -> Any | None:
        session = self._engine_session
        if session is None or self.board.legal_moves():
            return None
        if self.board.in_check(self.board.turn):
            winner = "b" if self.board.turn == "w" else "w"
            result = "1-0" if winner == "w" else "0-1"
            snapshot = session.sync_position_outcome(
                result,
                EndReason.CHECKMATE,
                winner=winner,
            )
        else:
            snapshot = session.sync_position_outcome(
                "1/2-1/2",
                EndReason.STALEMATE,
            )
        self._engine_game_phase = "finished"
        return snapshot

    def _takeback_recovery_message(self) -> str:
        return (
            "Відновити стан партії не вдалося. Повтор і ходи заблоковано; "
            "зупиніть партію та почніть нову."
            if self.lang == "uk" else
            "Game recovery failed. Retry and moves are blocked; "
            "stop this game and start a new one."
        )

    def _block_unrecoverable_takeback(self, exc: Exception) -> dict[str, Any]:
        # The canonical Board owner reported unsuccessful compensation. Never
        # allow a retry, direct undo or ordinary move on an untrusted history.
        _LOG.error("Unrecoverable engine takeback compensation: %s", type(exc).__name__, exc_info=True)
        self._engine_takeback_unsafe = True
        self._engine_game_phase = "error"
        self._engine_game_error = self._takeback_recovery_message()
        return self._error(self._engine_game_error)

    def _pause_engine_after_failure(self) -> str:
        session = self._engine_session
        if session is not None:
            try:
                session.pause()
            except Exception:
                pass
        self._engine_game_phase = "error"
        self._engine_game_error = (
            "Stockfish не відповів. Гру призупинено; спробуйте ще раз або зупиніть її."
            if self.lang == "uk"
            else "Stockfish did not respond. The game is paused; retry or stop it."
        )
        return self._engine_game_error

    def _request_engine_reply(self) -> tuple[bool, str]:
        session = self._engine_session
        if session is None:
            return False, self._pause_engine_after_failure()
        self._engine_thinking = True
        before = len(self.sans)
        try:
            result = session.request_engine_move()
        except Exception:
            return False, self._pause_engine_after_failure()
        finally:
            self._engine_thinking = False

        if result.move is None:
            try:
                snapshot = session.snapshot()
            except Exception:
                return False, self._pause_engine_after_failure()
            if snapshot.lifecycle.status is GameStatus.FINISHED:
                self._engine_game_phase = "finished"
                return True, self._outcome_text(snapshot)
            return False, self._pause_engine_after_failure()
        if len(self.sans) != before + 1:
            return False, self._pause_engine_after_failure()
        try:
            after_move = session.snapshot()
            self._record_engine_clock(after_move)
        except Exception:
            return False, self._pause_engine_after_failure()
        engine_san = _shared_spoken_san(self.sans[-1], self.lang)
        if after_move.lifecycle.status is GameStatus.FINISHED:
            self._engine_game_phase = "finished"
            self._play_game_end_sound()
            return True, (
                f"Stockfish зіграв: {engine_san}. {self._outcome_text(after_move)}"
                if self.lang == "uk"
                else f"Stockfish played: {engine_san}. {self._outcome_text(after_move)}"
            )
        terminal = self._finish_engine_game_from_board()
        if terminal is not None:
            return True, (
                f"Stockfish зіграв: {engine_san}. {self._outcome_text(terminal)}"
                if self.lang == "uk"
                else f"Stockfish played: {engine_san}. {self._outcome_text(terminal)}"
            )
        return True, (
            f"Stockfish зіграв: {engine_san}. Ваш хід."
            if self.lang == "uk"
            else f"Stockfish played: {engine_san}. Your move."
        )

    def _human_engine_move_guard(self) -> dict[str, Any] | None:
        if self._engine_takeback_unsafe:
            return self._concise_error(
                "Стан партії не вдалося відновити. Почніть нову партію.",
                "The game state could not be recovered. Start a new game.",
            )
        if self._engine_game_phase == "error":
            return self._concise_error(
                "Спочатку повторіть хід Stockfish або зупиніть гру.",
                "Retry the Stockfish move or stop the game first.",
            )
        if self._engine_game_phase == "finished":
            return self._concise_error(
                "Партію завершено. Почніть нову гру.",
                "The game is finished. Start a new game.",
            )
        if self._engine_game_phase != "active":
            return None
        session = self._engine_session
        if session is None:
            return self._concise_error(
                "Гра проти Stockfish недоступна.",
                "The Stockfish game is unavailable.",
            )
        try:
            snapshot = session.snapshot()
            human = "b" if snapshot.config.engine_side == "w" else "w"
            if snapshot.turn_state is not EngineTurnState.HUMAN or self.board.turn != human:
                return self._concise_error(
                    "Зараз хід Stockfish.",
                    "It is Stockfish's turn.",
                )
            session.assert_move_allowed(self.board.turn)
        except Exception:
            try:
                snapshot = session.snapshot()
                if snapshot.lifecycle.status is GameStatus.FINISHED:
                    self._engine_game_phase = "finished"
                    return self._concise_error(
                        self._outcome_text(snapshot),
                        self._outcome_text(snapshot),
                    )
            except Exception:
                pass
            return self._concise_error(
                "Не вдалося продовжити гру проти Stockfish.",
                "The Stockfish game could not continue.",
            )
        return None

    def _after_human_engine_move(self, moved_side: str, human_san: str) -> dict[str, Any]:
        session = self._engine_session
        if session is None:
            return self._ok(human_san)
        try:
            after_move = session.on_human_move_committed(moved_side)
            self._record_engine_clock(after_move)
        except Exception:
            warning = self._pause_engine_after_failure()
            return self._ok(
                (f"Зіграно: {human_san}. {warning}" if self.lang == "uk"
                 else f"Played: {human_san}. {warning}")
            )
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

    def start_engine_game(
        self,
        human_side: str = "white",
        level: int = 5,
        initial_minutes: int = 0,
        increment_seconds: int = 0,
    ) -> dict[str, Any]:
        blocked = self._temporary_exploration_error()
        if blocked is not None:
            return blocked
        if self._engine_play_service is None:
            return self._concise_error(
                "Stockfish для гри недоступний.",
                "Stockfish play is unavailable.",
            )
        try:
            selected_side = str(human_side or "").strip().lower()
            if selected_side not in {"white", "black", "random", "w", "b"}:
                raise ValueError("invalid side")
            selected_side = {"w": "white", "b": "black"}.get(selected_side, selected_side)
            resolved_level = self._bounded_int(level, low=1, high=10)
            minutes = self._bounded_int(initial_minutes, low=0, high=180)
            increment = self._bounded_int(increment_seconds, low=0, high=60)
            if minutes == 0 and increment != 0:
                raise ValueError("untimed games cannot use increment")
            engine_side = {
                "white": EngineSideMode.BLACK,
                "black": EngineSideMode.WHITE,
                "random": EngineSideMode.RANDOM,
            }[selected_side]
            config = EngineGameConfig(
                level=resolved_level,
                engine_side=engine_side,
                time_control=TimeControl(minutes * 60_000, increment * 1_000),
            )
        except Exception:
            return self._concise_error(
                "Перевірте сторону, рівень і контроль часу.",
                "Check side, level, and time control.",
            )

        reset = super().new_game()
        if not reset.get("ok"):
            return self._concise_error(
                "Не вдалося підготувати стандартну позицію для гри.",
                "The standard position could not be prepared for play.",
            )
        # The existing engine-game lifecycle remains authoritative until the
        # standard board/history root has actually published.  Only then may a
        # replacement game discard the prior session state.
        self._reset_engine_game_state()
        session = EngineGameSessionCoordinator(
            self._engine_play_service,
            # Board publication is transactional and may replace self.board.
            # Resolve FEN at call time instead of binding the session forever to
            # the Board object that happened to exist at game start.
            fen_provider=lambda: self.board.fen(),
            side_to_move_provider=lambda: self.board.turn,
            commit_engine_move=self._commit_engine_move,
            history_node_provider=lambda: str(self.live_history_node),
            undo_committed_move=self._undo_engine_game_to_human_turn,
            clock_restore_provider=self._engine_clock_restore_snapshot,
            takeback_transaction=self._prepare_engine_takeback_transaction,
            no_move_resolver=self._resolve_engine_no_move,
            timeout_mating_capability_provider=self._timeout_mating_capability,
        )
        try:
            snapshot = session.start(config)
        except Exception:
            self._engine_game_phase = "error"
            self._engine_game_error = (
                "Не вдалося розпочати гру проти Stockfish."
                if self.lang == "uk"
                else "The Stockfish game could not start."
            )
            return self._error(self._engine_game_error)
        self._engine_session = session
        self._engine_game_phase = "active"
        self._engine_game_error = None
        self._engine_clock_history = [snapshot.clock]
        self._play_game_start_sound()

        human = "b" if snapshot.config.engine_side == "w" else "w"
        intro = (
            f"Нова гра проти Stockfish. Ви граєте за {self._engine_side_name(human)}. "
            f"Рівень {snapshot.config.level.level}."
            if self.lang == "uk"
            else f"New Stockfish game. You play {self._engine_side_name(human)}. "
            f"Level {snapshot.config.level.level}."
        )
        if snapshot.turn_state is EngineTurnState.ENGINE:
            self._suppress_next_engine_move_sound_for_start = True
            replied, message = self._request_engine_reply()
            # If no engine move reached _commit_engine_move(), do not let the
            # one-shot suppression leak into a later ordinary move.
            self._suppress_next_engine_move_sound_for_start = False
            if not replied:
                return self._error(f"{intro} {message}")
            return self._ok(f"{intro} {message}")
        return self._ok(
            f"{intro} " + ("Ваш хід." if self.lang == "uk" else "Your move.")
        )

    def stop_engine_game(self) -> dict[str, Any]:
        if self._engine_session is None or self._engine_game_phase == "idle":
            return self._concise_error(
                "Гру проти Stockfish не розпочато.",
                "No Stockfish game is running.",
            )
        if self._engine_game_phase == "active":
            try:
                self._engine_session.pause()
            except Exception:
                pass
        self._engine_game_phase = "stopped"
        if not self._engine_takeback_unsafe:
            self._engine_game_error = None
        return self._ok(
            "Гру проти Stockfish зупинено."
            if self.lang == "uk"
            else "The Stockfish game was stopped."
        )

    def retry_engine_move(self) -> dict[str, Any]:
        if self._engine_takeback_unsafe:
            return self._error(self._takeback_recovery_message())
        session = self._engine_session
        if session is None or self._engine_game_phase != "error":
            return self._concise_error(
                "Повторювати нічого.",
                "There is no engine move to retry.",
            )
        try:
            session.resume()
            snapshot = session.snapshot()
        except Exception:
            return self._error(self._pause_engine_after_failure())
        self._engine_game_phase = "active"
        self._engine_game_error = None
        if snapshot.turn_state is EngineTurnState.HUMAN:
            return self._ok("Ваш хід." if self.lang == "uk" else "Your move.")
        replied, message = self._request_engine_reply()
        return self._ok(message) if replied else self._error(message)

    def resign_engine_game(self) -> dict[str, Any]:
        session = self._engine_session
        human = self._engine_human_side()
        if session is None or human is None or self._engine_game_phase != "active":
            return self._concise_error(
                "Активної гри проти Stockfish немає.",
                "There is no active Stockfish game.",
            )
        try:
            snapshot = session.handle_handoff(
                EngineGameHandoff(EngineGameIntent.RESIGN, actor=human)
            )
        except Exception:
            return self._concise_error(
                "Не вдалося завершити партію.",
                "The game could not be finished.",
            )
        self._engine_game_phase = "finished"
        self._play_game_end_sound()
        return self._ok(self._outcome_text(snapshot))

    def offer_draw_engine_game(self) -> dict[str, Any]:
        session = self._engine_session
        human = self._engine_human_side()
        if session is None or human is None or self._engine_game_phase != "active":
            return self._concise_error(
                "Активної гри проти Stockfish немає.",
                "There is no active Stockfish game.",
            )
        try:
            snapshot = session.snapshot()
            if snapshot.turn_state is not EngineTurnState.HUMAN:
                return self._concise_error(
                    "Зараз хід Stockfish.",
                    "It is Stockfish's turn.",
                )
            session.handle_handoff(
                EngineGameHandoff(EngineGameIntent.OFFER_DRAW, actor=human)
            )
            session.handle_handoff(
                EngineGameHandoff(
                    EngineGameIntent.DECLINE_DRAW,
                    actor=snapshot.config.engine_side,
                )
            )
        except Exception:
            return self._concise_error(
                "Не вдалося запропонувати нічию.",
                "The draw offer could not be sent.",
            )
        return self._ok(
            "Stockfish відхилив пропозицію нічиєї. Ваш хід."
            if self.lang == "uk"
            else "Stockfish declined the draw offer. Your move."
        )

    def engine_takeback(self) -> dict[str, Any]:
        if self._engine_takeback_unsafe:
            return self._error(self._takeback_recovery_message())
        session = self._engine_session
        human = self._engine_human_side()
        if session is None or human is None or self._engine_game_phase not in {
            "active", "finished", "error"
        }:
            return self._concise_error(
                "Повернення ходу недоступне.",
                "Takeback is unavailable.",
            )
        if not any(side == human for side in self.move_sides):
            return self._concise_error(
                "Ще немає вашого ходу для повернення.",
                "There is no human move to take back yet.",
            )
        engine = "b" if human == "w" else "w"
        try:
            if self._engine_game_phase == "finished":
                board_checkpoint = self._capture_engine_takeback_state()
                previous_clock = session._clock.snapshot()
                previous_lifecycle = session._lifecycle.snapshot()
                try:
                    self._undo_engine_game_to_human_turn()
                    snapshot = session.reset(
                        clock_snapshot=self._engine_clock_restore_snapshot()
                    )
                    self._commit_engine_takeback_state()
                except Exception:
                    recovery_error = None
                    for restore in (
                        lambda: self._restore_engine_takeback_state(board_checkpoint),
                        lambda: session._clock.restore(previous_clock),
                        lambda: session._lifecycle.restore_checkpoint(previous_lifecycle),
                    ):
                        try:
                            restore()
                        except Exception as exc:
                            if recovery_error is None:
                                recovery_error = exc
                    if recovery_error is not None:
                        raise EngineContractError(
                            "takeback compensation failed; session requires recovery",
                            code=EngineContractErrorCode.INVALID_SESSION,
                        ) from recovery_error
                    raise
            else:
                # A failed compensated acceptance leaves the original request
                # pending so the user can retry without a duplicate request.
                pending = session.snapshot().lifecycle.takeback_requested_by
                if pending is None:
                    session.handle_handoff(
                        EngineGameHandoff(
                            EngineGameIntent.REQUEST_TAKEBACK,
                            actor=human,
                        )
                    )
                elif pending != human:
                    raise RuntimeError("takeback is pending for the other side")
                snapshot = session.handle_handoff(
                    EngineGameHandoff(
                        EngineGameIntent.ACCEPT_TAKEBACK,
                        actor=engine,
                    )
                )
        except Exception as exc:
            if (isinstance(exc, EngineContractError)
                    and exc.code is EngineContractErrorCode.INVALID_SESSION
                    and "takeback compensation failed" in str(exc)):
                return self._block_unrecoverable_takeback(exc)
            return self._error(self._pause_engine_after_failure())
        self._engine_game_phase = "active"
        self._engine_game_error = None
        self._resume_game_sound_after_takeback()
        if snapshot.turn_state is EngineTurnState.ENGINE:
            replied, message = self._request_engine_reply()
            if not replied:
                return self._error(message)
            return self._ok(
                (f"Ходи повернено. {message}" if self.lang == "uk"
                 else f"Moves taken back. {message}")
            )
        return self._ok(
            "Ходи повернено. Ваш хід."
            if self.lang == "uk"
            else "Moves taken back. Your move."
        )

    def new_game(self) -> dict[str, Any]:
        if self._engine_takeback_unsafe:
            # Keymap reset may reject while the analysis explorer is open.
            # An unsuccessful explicit reset must never clear the safety fence.
            blocked = self._temporary_exploration_error()
            if blocked is not None:
                return blocked
        result = super().new_game()
        if not result.get("ok"):
            return result
        message = str(result.get("announcement") or "")
        self._reset_engine_game_state()
        self._play_game_start_sound()
        return self._ok(message)

    def clear_board(self) -> dict[str, Any]:
        if self._engine_takeback_unsafe:
            # Keymap reset may reject while the analysis explorer is open.
            # An unsuccessful explicit reset must never clear the safety fence.
            blocked = self._temporary_exploration_error()
            if blocked is not None:
                return blocked
        result = super().clear_board()
        if not result.get("ok"):
            return result
        message = str(result.get("announcement") or "")
        self._reset_engine_game_state()
        return self._ok(message)

    def make_move(self, text: str) -> dict[str, Any]:
        if self._engine_takeback_unsafe:
            return self._error(self._takeback_recovery_message())
        if self._engine_game_phase == "stopped":
            self._reset_engine_game_state()
        guard = self._human_engine_move_guard()
        if guard is not None:
            return guard
        before = len(self.sans)
        moved_side = self.board.turn
        result = super().make_move(text)
        after = len(self.sans)
        if self._game_sounds is not None:
            if result.get("ok") and after > before:
                self._play_latest_move()
            elif not result.get("ok"):
                self._game_sounds.illegal()
        if (
            self._engine_game_phase == "active"
            and result.get("ok")
            and after == before + 1
        ):
            return self._after_human_engine_move(
                moved_side,
                _shared_spoken_san(self.sans[-1], self.lang),
            )
        return result

    def edit_position_piece(self, square: str, piece: str) -> dict[str, Any]:
        if self._engine_takeback_unsafe:
            return self._error(self._takeback_recovery_message())
        result = super().edit_position_piece(square, piece)
        if not result.get("ok"):
            return result
        message = str(result.get("announcement") or "")
        self._reset_engine_game_state()
        return self._ok(message)

    def edit_position_metadata(
        self,
        turn: str,
        castling: str,
        en_passant: str,
        halfmove_text: str,
        fullmove_text: str,
    ) -> dict[str, Any]:
        if self._engine_takeback_unsafe:
            return self._error(self._takeback_recovery_message())
        result = super().edit_position_metadata(
            turn,
            castling,
            en_passant,
            halfmove_text,
            fullmove_text,
        )
        if not result.get("ok"):
            return result
        message = str(result.get("announcement") or "")
        self._reset_engine_game_state()
        return self._ok(message)

    def set_fen(self, fen: str) -> dict[str, Any]:
        if self._engine_takeback_unsafe:
            return self._error(self._takeback_recovery_message())
        result = super().set_fen(fen)
        if result.get("ok"):
            message = str(result.get("announcement") or "")
            self._reset_engine_game_state()
            return self._ok(message)
        return self._concise_error("Некоректний FEN.", "Invalid FEN.")

    def set_position_text(self, text: str, turn: str | None = None) -> dict[str, Any]:
        if self._engine_takeback_unsafe:
            return self._error(self._takeback_recovery_message())
        result = super().set_position_text(text, turn)
        if result.get("ok"):
            message = str(result.get("announcement") or "")
            self._reset_engine_game_state()
            return self._ok(message)
        return self._concise_error("Некоректна позиція.", "Invalid position.")

    def set_turn(self, color: str) -> dict[str, Any]:
        if self._engine_takeback_unsafe:
            return self._error(self._takeback_recovery_message())
        result = super().set_turn(color)
        if result.get("ok"):
            message = str(result.get("announcement") or "")
            self._reset_engine_game_state()
            return self._ok(message)
        return result

    def insert_analysis_move(self) -> dict[str, Any]:
        if self._engine_takeback_unsafe:
            return self._error(self._takeback_recovery_message())
        return super().insert_analysis_move()

    def insert_analysis_line(self) -> dict[str, Any]:
        if self._engine_takeback_unsafe:
            return self._error(self._takeback_recovery_message())
        return super().insert_analysis_line()

    def undo(self) -> dict[str, Any]:
        if self._engine_takeback_unsafe:
            return self._error(self._takeback_recovery_message())
        if self._engine_game_phase == "active":
            return self.engine_takeback()
        if self._engine_game_phase in {"stopped", "finished"}:
            self._reset_engine_game_state()
        return super().undo()

    def redo(self) -> dict[str, Any]:
        if self._engine_takeback_unsafe:
            return self._error(self._takeback_recovery_message())
        if self._engine_game_phase in {"active", "error"}:
            return self._concise_error(
                "Повтор ходу недоступний під час гри проти Stockfish.",
                "Redo is unavailable during a Stockfish game.",
            )
        if self._engine_game_phase in {"stopped", "finished"}:
            self._reset_engine_game_state()
        return super().redo()

    def activate_square(self, square: str) -> dict[str, Any]:
        if self._engine_takeback_unsafe:
            return self._error(self._takeback_recovery_message())
        if self._engine_game_phase == "stopped":
            self._reset_engine_game_state()
        guard = self._human_engine_move_guard()
        if guard is not None:
            return guard
        before = len(self.sans)
        moved_side = self.board.turn
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
        if (
            self._engine_game_phase == "active"
            and result.get("ok")
            and after == before + 1
        ):
            return self._after_human_engine_move(
                moved_side,
                _shared_spoken_san(self.sans[-1], self.lang),
            )
        return result

    def dispatch_action(self, action_id: str) -> dict[str, Any]:
        actions = {
            "engine_play.start": self.start_engine_game,
            "engine_play.stop": self.stop_engine_game,
            "game.takeback": self.engine_takeback,
            "game.offer_draw": self.offer_draw_engine_game,
            "game.resign": self.resign_engine_game,
        }
        handler = actions.get(str(action_id or ""))
        return handler() if handler is not None else super().dispatch_action(action_id)

    def close_analysis(self) -> dict[str, Any]:
        service = self._engine_play_service
        self._engine_play_service = None
        self._reset_engine_game_state()
        try:
            return super().close_analysis()
        finally:
            if service is not None:
                service.close()


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
        checks["sound_settings_contract"] = (
            bool(sound.get("ok"))
            and isinstance(sound.get("enabled"), bool)
            and isinstance(sound.get("newGameAnimation"), bool)
            and 0 <= int(sound.get("volume", -1)) <= 100
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
