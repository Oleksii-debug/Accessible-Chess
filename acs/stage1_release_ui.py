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
from .clock_service import ClockSnapshot, TimeControl
from .engine_game_session import (
    EngineGameSessionCoordinator,
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
from .game_lifecycle import EndReason, GameStatus
from .sound_events import MoveSoundFacts, SoundEvent
from .ui_native_menu import install_windows_native_menu
from .webapp_keymap import (
    KeymapAwareAccessibleChessAPI,
    _asset_root,
    _shared_spoken_san,
)


class Stage1ReleaseAccessibleChessAPI(KeymapAwareAccessibleChessAPI):
    """One release API for chess state, analysis, sounds and accessible UI."""

    def __init__(
        self,
        *args: Any,
        game_sounds: Any | None = None,
        sound_runtime: Any | None = None,
        settings: Any | None = None,
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
        self._engine_play_service = engine_play_service
        self._engine_session: EngineGameSessionCoordinator | None = None
        self._engine_game_phase = "idle"
        self._engine_game_error: str | None = None
        self._engine_thinking = False
        self._engine_clock_history: list[ClockSnapshot] = []

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
        self._engine_thinking = False
        self._engine_clock_history = []

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
        self.redo_meta.clear()
        self.board.redo_stack.clear()
        del self._engine_clock_history[len(self.sans) + 1:]

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
            "canRetry": self._engine_game_phase == "error" and session is not None,
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
            base["canRetry"] = True
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
        if self._engine_game_phase == "error":
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
        side = self.board.turn
        san = self.board.push_text(move)
        self.sans.append(san)
        self.move_sides.append(side)
        self.redo_meta.clear()
        self.selected_source = None
        self._record_position_after_move(san, side)
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

        self._reset_engine_game_state()
        super().new_game()
        if self._game_sounds is not None:
            self._game_sounds.start()
        session = EngineGameSessionCoordinator(
            self._engine_play_service,
            fen_provider=self.board.fen,
            side_to_move_provider=lambda: self.board.turn,
            commit_engine_move=self._commit_engine_move,
            history_node_provider=lambda: str(self.live_history_node),
            undo_committed_move=self._undo_engine_game_to_human_turn,
            clock_restore_provider=self._engine_clock_restore_snapshot,
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

        human = "b" if snapshot.config.engine_side == "w" else "w"
        intro = (
            f"Нова гра проти Stockfish. Ви граєте за {self._engine_side_name(human)}. "
            f"Рівень {snapshot.config.level.level}."
            if self.lang == "uk"
            else f"New Stockfish game. You play {self._engine_side_name(human)}. "
            f"Level {snapshot.config.level.level}."
        )
        if snapshot.turn_state is EngineTurnState.ENGINE:
            replied, message = self._request_engine_reply()
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
        self._engine_game_error = None
        return self._ok(
            "Гру проти Stockfish зупинено."
            if self.lang == "uk"
            else "The Stockfish game was stopped."
        )

    def retry_engine_move(self) -> dict[str, Any]:
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
                self._undo_engine_game_to_human_turn()
                snapshot = session.reset(
                    clock_snapshot=self._engine_clock_restore_snapshot()
                )
            else:
                session.handle_handoff(
                    EngineGameHandoff(
                        EngineGameIntent.REQUEST_TAKEBACK,
                        actor=human,
                    )
                )
                snapshot = session.handle_handoff(
                    EngineGameHandoff(
                        EngineGameIntent.ACCEPT_TAKEBACK,
                        actor=engine,
                    )
                )
        except Exception:
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
        self._reset_engine_game_state()
        result = super().new_game()
        if result.get("ok") and self._game_sounds is not None:
            self._game_sounds.start()
        return result

    def clear_board(self) -> dict[str, Any]:
        self._reset_engine_game_state()
        return super().clear_board()

    def make_move(self, text: str) -> dict[str, Any]:
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

    def set_fen(self, fen: str) -> dict[str, Any]:
        result = super().set_fen(fen)
        if result.get("ok"):
            message = str(result.get("announcement") or "")
            self._reset_engine_game_state()
            return self._ok(message)
        return self._concise_error("Некоректний FEN.", "Invalid FEN.")

    def set_position_text(self, text: str, turn: str | None = None) -> dict[str, Any]:
        result = super().set_position_text(text, turn)
        if result.get("ok"):
            message = str(result.get("announcement") or "")
            self._reset_engine_game_state()
            return self._ok(message)
        return self._concise_error("Некоректна позиція.", "Invalid position.")

    def set_turn(self, color: str) -> dict[str, Any]:
        result = super().set_turn(color)
        if result.get("ok"):
            message = str(result.get("announcement") or "")
            self._reset_engine_game_state()
            return self._ok(message)
        return result

    def undo(self) -> dict[str, Any]:
        if self._engine_game_phase == "active":
            return self.engine_takeback()
        if self._engine_game_phase in {"stopped", "finished"}:
            self._reset_engine_game_state()
        return super().undo()

    def redo(self) -> dict[str, Any]:
        if self._engine_game_phase in {"active", "error"}:
            return self._concise_error(
                "Повтор ходу недоступний під час гри проти Stockfish.",
                "Redo is unavailable during a Stockfish game.",
            )
        if self._engine_game_phase in {"stopped", "finished"}:
            self._reset_engine_game_state()
        return super().redo()

    def activate_square(self, square: str) -> dict[str, Any]:
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
