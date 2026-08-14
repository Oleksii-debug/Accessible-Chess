import unittest

from acs.clock_service import ChessClock, ClockError, ClockState, TimeControl


class FakeTime:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class ChessClockTests(unittest.TestCase):
    def setUp(self):
        self.now = FakeTime()

    def test_start_charges_only_active_side(self):
        clock = ChessClock(TimeControl(300_000), now=self.now)
        clock.start("w")
        self.now.advance(2.5)
        snap = clock.snapshot()
        self.assertEqual(snap.white_ms, 297_500)
        self.assertEqual(snap.black_ms, 300_000)
        self.assertEqual(snap.active, "w")
        self.assertEqual(snap.state, ClockState.RUNNING)

    def test_switch_charges_mover_then_awards_increment(self):
        clock = ChessClock(TimeControl(60_000, 2_000), now=self.now)
        clock.start("w")
        self.now.advance(5)
        snap = clock.switch_after_move("w")
        self.assertEqual(snap.white_ms, 57_000)
        self.assertEqual(snap.black_ms, 60_000)
        self.assertEqual(snap.active, "b")
        self.now.advance(3)
        snap = clock.switch_after_move("b")
        self.assertEqual(snap.black_ms, 59_000)
        self.assertEqual(snap.active, "w")

    def test_pause_resume_does_not_charge_paused_time(self):
        clock = ChessClock(TimeControl(10_000), now=self.now)
        clock.start("b")
        self.now.advance(1)
        self.assertEqual(clock.pause().black_ms, 9_000)
        self.now.advance(100)
        self.assertEqual(clock.snapshot().black_ms, 9_000)
        clock.resume()
        self.now.advance(2)
        self.assertEqual(clock.snapshot().black_ms, 7_000)

    def test_timeout_flags_exact_side_and_clamps_to_zero(self):
        clock = ChessClock(TimeControl(1_000), now=self.now)
        clock.start("w")
        self.now.advance(1.5)
        snap = clock.snapshot()
        self.assertEqual(snap.white_ms, 0)
        self.assertEqual(snap.black_ms, 1_000)
        self.assertEqual(snap.flagged, "w")
        self.assertEqual(snap.state, ClockState.FLAGGED)
        self.assertIsNone(snap.active)

    def test_cannot_resume_flagged_clock_until_reset_or_restore(self):
        clock = ChessClock(TimeControl(1_000), now=self.now)
        clock.start("w")
        self.now.advance(2)
        self.assertEqual(clock.snapshot().state, ClockState.FLAGGED)
        with self.assertRaises(ClockError):
            clock.resume()
        restored = clock.set_remaining("w", 5_000)
        self.assertEqual(restored.state, ClockState.STOPPED)
        self.assertIsNone(restored.flagged)

    def test_wrong_side_switch_is_rejected_without_corrupting_state(self):
        clock = ChessClock(TimeControl(60_000, 1_000), now=self.now)
        clock.start("w")
        self.now.advance(2)
        with self.assertRaisesRegex(ClockError, "does not match"):
            clock.switch_after_move("b")
        snap = clock.snapshot()
        self.assertEqual(snap.white_ms, 58_000)
        self.assertEqual(snap.black_ms, 60_000)
        self.assertEqual(snap.active, "w")

    def test_untimed_control_is_noop_and_never_flags(self):
        clock = ChessClock(TimeControl(0, 0), now=self.now)
        snap = clock.start("w")
        self.assertEqual(snap.state, ClockState.STOPPED)
        self.assertIsNone(snap.active)
        self.now.advance(10_000)
        snap = clock.snapshot()
        self.assertEqual(snap.white_ms, 0)
        self.assertIsNone(snap.flagged)

    def test_reset_can_prepare_paused_clock_for_restored_side_to_move(self):
        clock = ChessClock(TimeControl(120_000, 5_000), now=self.now)
        clock.start("w")
        self.now.advance(4)
        snap = clock.reset(side_to_move="b")
        self.assertEqual(snap.white_ms, 120_000)
        self.assertEqual(snap.black_ms, 120_000)
        self.assertEqual(snap.active, "b")
        self.assertEqual(snap.state, ClockState.PAUSED)
        clock.resume()
        self.now.advance(1)
        self.assertEqual(clock.snapshot().black_ms, 119_000)

    def test_stop_freezes_both_clocks(self):
        clock = ChessClock(TimeControl(30_000), now=self.now)
        clock.start("w")
        self.now.advance(3)
        snap = clock.stop()
        self.assertEqual(snap.white_ms, 27_000)
        self.assertEqual(snap.state, ClockState.STOPPED)
        self.now.advance(50)
        self.assertEqual(clock.snapshot().white_ms, 27_000)

    def test_invalid_controls_and_sides_are_rejected(self):
        with self.assertRaises(ClockError):
            TimeControl(-1)
        with self.assertRaises(ClockError):
            TimeControl(1, -1)
        clock = ChessClock(TimeControl(1_000), now=self.now)
        with self.assertRaises(ClockError):
            clock.start("x")


if __name__ == "__main__":
    unittest.main()
