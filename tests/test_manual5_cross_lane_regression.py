from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.release_app import create_release_api
from acs.sound_events import SoundEvent


class _Line:
    def __init__(self, multipv: int) -> None:
        self.multipv = multipv
        self.depth = 12
        self.score_kind = "cp"
        self.score_value = 10 * multipv
        self.pv = ("e2e4", "e7e5")


class _Engine:
    def __init__(self) -> None:
        self.closed = False

    def analyze(self, fen: str, multipv: int = 5, depth: int = 16):
        return tuple(_Line(index) for index in range(1, multipv + 1))

    def best_move(self, fen: str, skill_level: int = 10, movetime_ms: int = 500):
        # The regressions use a human-as-White game and ask for one Black reply.
        return "e7e5"

    def close(self) -> None:
        self.closed = True


class _Runtime:
    def __init__(self, config) -> None:
        self.config = config
        self.engine = _Engine()
        self.closed = False

    def provider(self):
        return self.engine

    def close(self) -> None:
        self.closed = True
        self.engine.close()


class _FailingPlayback:
    def __init__(self) -> None:
        self.calls: list[tuple[SoundEvent, int]] = []

    def play(self, event: SoundEvent, *, volume: int) -> None:
        self.calls.append((event, volume))
        raise RuntimeError(r"C:\private\audio-device\driver failed")


class Manual5CrossLaneRegressionTests(unittest.TestCase):
    def make_composed(self, root: str, playback: _FailingPlayback):
        return create_release_api(
            application_dir=root,
            runtime_factory=_Runtime,
            sound_playback=playback,
            settings_path=Path(root) / "settings.json",
        )

    def test_sound_adapter_failure_cannot_corrupt_move_history_or_invalid_move_atomicity(self) -> None:
        playback = _FailingPlayback()
        with tempfile.TemporaryDirectory() as td:
            api, runtime = self.make_composed(td, playback)
            try:
                start_fen = api.board.fen()
                legal = api.make_move("e4")
                self.assertTrue(legal["ok"], legal)
                self.assertNotEqual(api.board.fen(), start_fen)
                self.assertEqual(tuple(api.sans), ("e4",))
                self.assertEqual(api.review_history.node_count, 2)
                after_legal = (
                    api.board.fen(),
                    tuple(api.sans),
                    api.review_history.node_count,
                    api.live_history_node,
                )

                illegal = api.make_move("e9")
                self.assertFalse(illegal["ok"], illegal)
                self.assertEqual(
                    (
                        api.board.fen(),
                        tuple(api.sans),
                        api.review_history.node_count,
                        api.live_history_node,
                    ),
                    after_legal,
                )
                self.assertIn((SoundEvent.MOVE, 80), playback.calls)
                self.assertIn((SoundEvent.ILLEGAL, 80), playback.calls)
                self.assertNotIn("RuntimeError", str(illegal.get("announcement", "")))
                self.assertNotIn("C:\\private", str(illegal.get("announcement", "")))
            finally:
                api.close_analysis()
                runtime.close()

    def test_sound_adapter_failure_cannot_interrupt_engine_reply_or_game_lifecycle(self) -> None:
        playback = _FailingPlayback()
        with tempfile.TemporaryDirectory() as td:
            api, runtime = self.make_composed(td, playback)
            try:
                started = api.start_engine_game("white", 5, 0, 0)
                self.assertTrue(started["ok"], started)
                self.assertIn((SoundEvent.START, 80), playback.calls)

                turn = api.make_move("e4")
                self.assertTrue(turn["ok"], turn)
                self.assertEqual(tuple(api.sans), ("e4", "e5"))
                state = api.get_state()["engineGame"]
                self.assertTrue(state["configured"])
                self.assertTrue(state["active"])
                self.assertEqual(state["phase"], "active")
                self.assertEqual(state["humanSide"], "w")
                self.assertEqual(api.board.turn, "w")

                resigned = api.resign_engine_game()
                self.assertTrue(resigned["ok"], resigned)
                finished = api.get_state()["engineGame"]
                self.assertEqual(finished["phase"], "finished")
                self.assertFalse(finished["active"])
                self.assertIn((SoundEvent.END, 80), playback.calls)
            finally:
                api.close_analysis()
                runtime.close()

    def test_invalid_fen_and_editor_preserve_active_engine_game_and_history(self) -> None:
        playback = _FailingPlayback()
        with tempfile.TemporaryDirectory() as td:
            api, runtime = self.make_composed(td, playback)
            try:
                started = api.start_engine_game("white", 5, 0, 0)
                self.assertTrue(started["ok"], started)
                turn = api.make_move("e4")
                self.assertTrue(turn["ok"], turn)
                self.assertEqual(tuple(api.sans), ("e4", "e5"))

                before = (
                    api.board.fen(),
                    tuple(api.sans),
                    tuple(api.move_sides),
                    api.review_history.node_count,
                    api.live_history_node,
                    api.get_state()["engineGame"].copy(),
                )

                bad_fen = api.set_fen("not a fen")
                self.assertFalse(bad_fen["ok"], bad_fen)
                self.assertEqual(
                    (
                        api.board.fen(),
                        tuple(api.sans),
                        tuple(api.move_sides),
                        api.review_history.node_count,
                        api.live_history_node,
                        api.get_state()["engineGame"],
                    ),
                    before,
                )

                bad_editor = api.set_position_text("broken position", "w")
                self.assertFalse(bad_editor["ok"], bad_editor)
                self.assertEqual(
                    (
                        api.board.fen(),
                        tuple(api.sans),
                        tuple(api.move_sides),
                        api.review_history.node_count,
                        api.live_history_node,
                        api.get_state()["engineGame"],
                    ),
                    before,
                )
                for result in (bad_fen, bad_editor):
                    announcement = str(result.get("announcement", ""))
                    self.assertNotIn("Traceback", announcement)
                    self.assertNotIn("C:\\private", announcement)
            finally:
                api.close_analysis()
                runtime.close()


if __name__ == "__main__":
    unittest.main()
