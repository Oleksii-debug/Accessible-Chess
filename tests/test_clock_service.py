import unittest

from acs.clock_service import (
    ChessClock,
    ClockError,
    ClockErrorCode,
    ClockSnapshot,
    ClockState,
    TimeControl,
)


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

    def test_switch_charges_mover_through_exact_switch_instant(self):
        class SteppedTime:
            def __init__(self):
                self.value = 100.0
                self.step = 0.0

            def __call__(self):
                self.value += self.step
                return self.value

        now = SteppedTime()
        clock = ChessClock(TimeControl(10_000, 2_000), now=now)
        clock.start("w")
        now.step = 1.0
        switched = clock.switch_after_move("w")

        # Charge two seconds to White before the 2-second increment.
        # The returned snapshot may also charge Black after switching.
        self.assertEqual(switched.white_ms, 10_000)
        self.assertEqual(switched.black_ms, 9_000)
        self.assertEqual(switched.active, "b")
        self.assertEqual(switched.state, ClockState.RUNNING)

    def test_switch_flags_mover_before_increment_at_second_time_read(self):
        class SteppedTime:
            def __init__(self):
                self.value = 100.0
                self.step = 0.0

            def __call__(self):
                self.value += self.step
                return self.value

        now = SteppedTime()
        clock = ChessClock(TimeControl(1_500, 2_000), now=now)
        clock.start("w")
        now.step = 1.0
        rejected = clock.switch_after_move("w")

        self.assertEqual(rejected.white_ms, 0)
        self.assertEqual(rejected.black_ms, 1_500)
        self.assertEqual(rejected.flagged, "w")
        self.assertEqual(rejected.state, ClockState.FLAGGED)
        self.assertIsNone(rejected.active)

    def test_switch_does_not_undo_accepted_mover_when_next_side_flags(self):
        class SequenceTime:
            def __init__(self, values):
                self.values = list(values)

            def __call__(self):
                if not self.values:
                    raise AssertionError("unexpected clock sample")
                return self.values.pop(0)

        # Start, start snapshot, mover preflight, switch instant, and returned
        # snapshot are separate samples. Only the last sample flags Black.
        now = SequenceTime((100.0, 100.0, 101.0, 102.0, 102.002))
        clock = ChessClock(TimeControl(3_000, 1_000), now=now)
        clock.set_remaining("b", 1)
        clock.start("w")

        switched = clock.switch_after_move("w")

        self.assertEqual(switched.white_ms, 2_000)
        self.assertEqual(switched.black_ms, 0)
        self.assertEqual(switched.flagged, "b")
        self.assertEqual(switched.state, ClockState.FLAGGED)
        self.assertIsNone(switched.active)
        # The mover was accepted and earned its increment. Higher layers must
        # not roll back that move because the *opponent* then flagged.

    def test_switch_final_sample_failure_rolls_back_increment_and_active_side(self):
        class SequenceTime:
            def __init__(self, *values):
                self.values = list(values)
                self.last = float(values[0])

            def __call__(self):
                if not self.values:
                    return self.last
                sample = self.values.pop(0)
                if isinstance(sample, Exception):
                    raise sample
                self.last = sample
                return sample

        for invalid in (float("nan"), 99.0, RuntimeError("clock source unavailable")):
            with self.subTest(invalid=invalid):
                # start + its returned snapshot, pre-switch accounting,
                # exact switch instant, then the final opponent snapshot.
                now = SequenceTime(100.0, 100.0, 100.5, 101.0, invalid)
                clock = ChessClock(TimeControl(3_000, 1_000), now=now)
                clock.start("w")

                with self.assertRaises((ClockError, RuntimeError)) as caught:
                    clock.switch_after_move("w")
                if isinstance(caught.exception, ClockError):
                    self.assertEqual(
                        caught.exception.code, ClockErrorCode.INVALID_TIME_SOURCE
                    )

                # The mover's real elapsed second remains charged, but no
                # rejected-move increment, side switch, or flag survives.
                now.last = 101.0
                recovered = clock.snapshot()
                self.assertEqual(recovered.white_ms, 2_000)
                self.assertEqual(recovered.black_ms, 3_000)
                self.assertEqual(recovered.active, "w")
                self.assertEqual(recovered.state, ClockState.RUNNING)
                self.assertIsNone(recovered.flagged)

    def test_switch_invalid_second_sample_does_not_change_side_or_award_increment(self):
        class SequenceTime:
            def __init__(self, values):
                self.values = list(values)

            def __call__(self):
                return self.values.pop(0) if self.values else 100.0

        now = SequenceTime((100.0, 100.0, 100.0, float("nan")))
        clock = ChessClock(TimeControl(3_000, 1_000), now=now)
        clock.start("w")

        with self.assertRaises(ClockError) as caught:
            clock.switch_after_move("w")

        self.assertEqual(caught.exception.code, ClockErrorCode.INVALID_TIME_SOURCE)
        unchanged = clock.snapshot()
        self.assertEqual(unchanged.white_ms, 3_000)
        self.assertEqual(unchanged.black_ms, 3_000)
        self.assertEqual(unchanged.active, "w")
        self.assertEqual(unchanged.state, ClockState.RUNNING)

    def test_setting_running_mover_to_zero_flags_without_tick_or_increment(self):
        clock = ChessClock(TimeControl(1_000, 2_000), now=self.now)
        clock.start("w")

        zero = clock.set_remaining("w", 0)
        self.assertEqual(zero.white_ms, 0)
        self.assertEqual(zero.flagged, "w")
        self.assertEqual(zero.state, ClockState.FLAGGED)
        self.assertIsNone(zero.active)

        rejected = clock.switch_after_move("w")
        self.assertEqual(rejected, zero)
        self.assertEqual(rejected.black_ms, 1_000)

    def test_restored_running_zero_time_flags_before_move_increment(self):
        clock = ChessClock(TimeControl(1_000, 2_000), now=self.now)

        restored = clock.restore(
            ClockSnapshot(0, 1_000, "w", ClockState.RUNNING),
            resume_running=True,
        )
        self.assertEqual(restored.state, ClockState.FLAGGED)
        self.assertEqual(restored.flagged, "w")
        self.assertEqual(restored.white_ms, 0)
        self.assertEqual(clock.switch_after_move("w"), restored)

    def test_paused_zero_time_flags_on_resume_before_move_increment(self):
        clock = ChessClock(TimeControl(1_000, 2_000), now=self.now)
        paused = clock.restore(ClockSnapshot(0, 1_000, "w", ClockState.PAUSED))
        self.assertEqual(paused.state, ClockState.PAUSED)

        resumed = clock.resume()
        self.assertEqual(resumed.state, ClockState.FLAGGED)
        self.assertEqual(resumed.flagged, "w")
        self.assertEqual(resumed.white_ms, 0)
        self.assertEqual(clock.switch_after_move("w"), resumed)

    def test_zero_time_next_side_flags_only_after_movers_accepted_switch(self):
        clock = ChessClock(TimeControl(1_000, 100), now=self.now)
        clock.start("w")
        running = clock.set_remaining("b", 0)
        self.assertEqual(running.state, ClockState.RUNNING)
        self.assertEqual(running.active, "w")

        switched = clock.switch_after_move("w")
        self.assertEqual(switched.white_ms, 1_100)
        self.assertEqual(switched.black_ms, 0)
        self.assertEqual(switched.flagged, "b")
        self.assertEqual(switched.state, ClockState.FLAGGED)

    def test_failed_start_final_sample_keeps_clock_stopped(self):
        class Samples:
            def __init__(self):
                self.values = [100.0, float("nan")]
                self.fallback = 100.0

            def __call__(self):
                return self.values.pop(0) if self.values else self.fallback

        clock = ChessClock(TimeControl(3_000), now=Samples())
        before = clock.snapshot()
        with self.assertRaises(ClockError) as caught:
            clock.start("w")
        self.assertEqual(caught.exception.code, ClockErrorCode.INVALID_TIME_SOURCE)
        self.assertEqual(clock.snapshot(), before)
        self.assertEqual(clock.start("b").active, "b")

    def test_failed_resume_final_sample_preserves_pause(self):
        class Samples:
            def __init__(self):
                self.values = [100.0, float("nan")]
                self.fallback = 100.0

            def __call__(self):
                return self.values.pop(0) if self.values else self.fallback

        clock = ChessClock(TimeControl(3_000), now=Samples())
        before = clock.reset(side_to_move="w")
        with self.assertRaises(ClockError) as caught:
            clock.resume()
        self.assertEqual(caught.exception.code, ClockErrorCode.INVALID_TIME_SOURCE)
        self.assertEqual(clock.snapshot(), before)
        self.assertEqual(clock.resume().state, ClockState.RUNNING)

    def test_failed_resume_restore_final_sample_keeps_old_game(self):
        class Samples:
            def __init__(self):
                self.values = [100.0, float("nan")]
                self.fallback = 100.0

            def __call__(self):
                return self.values.pop(0) if self.values else self.fallback

        clock = ChessClock(TimeControl(3_000), now=Samples())
        before = clock.reset(side_to_move="b")
        incoming = ClockSnapshot(1_500, 2_000, "w", ClockState.RUNNING)
        with self.assertRaises(ClockError) as caught:
            clock.restore(incoming, resume_running=True)
        self.assertEqual(caught.exception.code, ClockErrorCode.INVALID_TIME_SOURCE)
        self.assertEqual(clock.snapshot(), before)
        accepted = clock.restore(incoming, resume_running=True)
        self.assertEqual(accepted.white_ms, 1_500)
        self.assertEqual(accepted.active, "w")
        self.assertEqual(accepted.state, ClockState.RUNNING)

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

    def test_failed_administrative_edit_preserves_preedit_balances(self):
        class Samples:
            def __init__(self):
                self.values = [100.0, 100.0, 100.5, float("nan")]
                self.fallback = 100.5

            def __call__(self):
                return self.values.pop(0) if self.values else self.fallback

        for edited_side in ("w", "b"):
            with self.subTest(side=edited_side):
                clock = ChessClock(TimeControl(3_000), now=Samples())
                clock.start("w")
                with self.assertRaises(ClockError) as caught:
                    clock.set_remaining(edited_side, 1_500)
                self.assertEqual(caught.exception.code, ClockErrorCode.INVALID_TIME_SOURCE)
                recovered = clock.snapshot()
                # Half a second actually elapsed before the rejected edit.
                self.assertEqual(recovered.white_ms, 2_500)
                self.assertEqual(recovered.black_ms, 3_000)
                self.assertEqual(recovered.active, "w")
                self.assertEqual(recovered.state, ClockState.RUNNING)
                self.assertEqual(
                    clock.set_remaining(edited_side, 1_500).remaining(edited_side),
                    1_500,
                )

    def test_untimed_administrative_balance_must_remain_canonical(self):
        clock = ChessClock(TimeControl(0), now=self.now)
        canonical = clock.start("b")
        self.assertEqual(canonical, ClockSnapshot(0, 0, None, ClockState.STOPPED))

        for side in ("w", "b"):
            with self.subTest(side=side):
                with self.assertRaises(ClockError) as caught:
                    clock.set_remaining(side, 1_000)
                self.assertEqual(caught.exception.code, ClockErrorCode.INVALID_COMMAND)
                self.assertEqual(clock.snapshot(), canonical)
                self.assertEqual(clock.set_remaining(side, 0), canonical)
                # A returned administrative snapshot must always be restorable.
                self.assertEqual(clock.restore(clock.snapshot()), canonical)

    def test_untimed_reset_discards_side_to_move_from_stopped_clock(self):
        clock = ChessClock(TimeControl(0, 0), now=self.now)

        snap = clock.reset(side_to_move="b")

        self.assertEqual(snap, ClockSnapshot(0, 0, None, ClockState.STOPPED))

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

    def test_restore_running_snapshot_is_paused_by_default(self):
        clock = ChessClock(TimeControl(60_000), now=self.now)
        restored = clock.restore(ClockSnapshot(41_000, 55_000, "b", ClockState.RUNNING))
        self.assertEqual(restored.white_ms, 41_000)
        self.assertEqual(restored.black_ms, 55_000)
        self.assertEqual(restored.active, "b")
        self.assertEqual(restored.state, ClockState.PAUSED)
        self.now.advance(20)
        self.assertEqual(clock.snapshot().black_ms, 55_000)

    def test_restore_can_resume_from_current_monotonic_instant(self):
        clock = ChessClock(TimeControl(60_000), now=self.now)
        clock.restore(ClockSnapshot(41_000, 55_000, "b", ClockState.RUNNING), resume_running=True)
        self.now.advance(2)
        restored = clock.snapshot()
        self.assertEqual(restored.black_ms, 53_000)
        self.assertEqual(restored.state, ClockState.RUNNING)

    def test_restore_flagged_snapshot_preserves_terminal_clock_state(self):
        clock = ChessClock(TimeControl(60_000), now=self.now)
        restored = clock.restore(ClockSnapshot(0, 17_000, None, ClockState.FLAGGED, "w"))
        self.assertEqual(restored.flagged, "w")
        self.assertEqual(restored.state, ClockState.FLAGGED)
        self.now.advance(30)
        self.assertEqual(clock.snapshot().black_ms, 17_000)

    def test_snapshot_constructor_rejects_inconsistent_or_negative_state(self):
        invalid = (
            (-1, 1_000, None, ClockState.STOPPED, None),
            (1_000, 1_000, None, ClockState.RUNNING, None),
            (1_000, 1_000, "w", ClockState.STOPPED, None),
            (1_000, 1_000, None, ClockState.FLAGGED, "w"),
            (1_000, 1_000, None, ClockState.STOPPED, "w"),
        )
        for values in invalid:
            with self.subTest(values=values):
                with self.assertRaises(ClockError) as caught:
                    ClockSnapshot(*values)
                self.assertEqual(
                    caught.exception.code,
                    ClockErrorCode.INVALID_SNAPSHOT,
                )

    def test_untimed_restore_rejects_timed_state_and_normalizes_zero_snapshot(self):
        clock = ChessClock(TimeControl(0), now=self.now)
        with self.assertRaises(ClockError):
            clock.restore(ClockSnapshot(1, 0, None, ClockState.STOPPED))
        restored = clock.restore(ClockSnapshot(0, 0, None, ClockState.STOPPED))
        self.assertEqual(restored, ClockSnapshot(0, 0, None, ClockState.STOPPED))

    def test_invalid_controls_and_sides_are_rejected(self):
        with self.assertRaises(ClockError):
            TimeControl(-1)
        with self.assertRaises(ClockError):
            TimeControl(1, -1)
        clock = ChessClock(TimeControl(1_000), now=self.now)
        with self.assertRaises(ClockError):
            clock.start("x")

    def test_time_control_requires_exact_non_negative_integer_fields(self):
        invalid = (
            (True, 0),
            (False, 0),
            (1.5, 0),
            ("1000", 0),
            (1_000, True),
            (1_000, 0.5),
            (0, 1_000),
        )
        for values in invalid:
            with self.subTest(values=values):
                with self.assertRaises(ClockError) as caught:
                    TimeControl(*values)
                self.assertEqual(
                    caught.exception.code,
                    ClockErrorCode.INVALID_CONTROL,
                )

        with self.assertRaises(ClockError) as caught:
            ChessClock(object(), now=self.now)
        self.assertEqual(caught.exception.code, ClockErrorCode.INVALID_CONTROL)

    def test_snapshot_fields_reject_scalar_and_container_coercion(self):
        invalid = (
            (True, 1_000, None, ClockState.STOPPED, None),
            (1_000, 1.0, None, ClockState.STOPPED, None),
            (1_000, 1_000, None, "stopped", None),
            (1_000, 1_000, [], ClockState.RUNNING, None),
            (0, 1_000, None, ClockState.FLAGGED, {}),
        )
        for values in invalid:
            with self.subTest(values=values):
                with self.assertRaises(ClockError) as caught:
                    ClockSnapshot(*values)
                self.assertEqual(
                    caught.exception.code,
                    ClockErrorCode.INVALID_SNAPSHOT,
                )

    def test_restore_revalidates_forged_snapshot_and_is_atomic(self):
        clock = ChessClock(TimeControl(60_000), now=self.now)
        before = clock.snapshot()
        forged = object.__new__(ClockSnapshot)
        object.__setattr__(forged, "white_ms", True)
        object.__setattr__(forged, "black_ms", 60_000)
        object.__setattr__(forged, "active", None)
        object.__setattr__(forged, "state", ClockState.STOPPED)
        object.__setattr__(forged, "flagged", None)

        with self.assertRaises(ClockError) as caught:
            clock.restore(forged)

        self.assertEqual(caught.exception.code, ClockErrorCode.INVALID_SNAPSHOT)
        self.assertEqual(clock.snapshot(), before)

    def test_restore_resume_flag_requires_boolean_and_is_atomic(self):
        clock = ChessClock(TimeControl(60_000), now=self.now)
        before = clock.snapshot()
        running = ClockSnapshot(41_000, 55_000, "b", ClockState.RUNNING)

        for invalid in (1, 0, "true", None):
            with self.subTest(resume_running=invalid):
                with self.assertRaises(ClockError) as caught:
                    clock.restore(running, resume_running=invalid)
                self.assertEqual(
                    caught.exception.code,
                    ClockErrorCode.INVALID_COMMAND,
                )
                self.assertEqual(clock.snapshot(), before)

    def test_set_remaining_requires_exact_integer_and_is_atomic(self):
        clock = ChessClock(TimeControl(60_000), now=self.now)
        before = clock.snapshot()
        for invalid in (True, False, 1.0, "1000", None):
            with self.subTest(milliseconds=invalid):
                with self.assertRaises(ClockError) as caught:
                    clock.set_remaining("w", invalid)
                self.assertEqual(
                    caught.exception.code,
                    ClockErrorCode.INVALID_COMMAND,
                )
                self.assertEqual(clock.snapshot(), before)

    def test_start_cannot_reassign_a_live_or_paused_clock(self):
        clock = ChessClock(TimeControl(60_000), now=self.now)
        clock.start("w")
        running = clock.snapshot()
        with self.assertRaises(ClockError) as caught:
            clock.start("b")
        self.assertEqual(caught.exception.code, ClockErrorCode.INVALID_STATE)
        self.assertEqual(clock.snapshot(), running)

        clock.pause()
        paused = clock.snapshot()
        with self.assertRaises(ClockError) as caught:
            clock.start("b")
        self.assertEqual(caught.exception.code, ClockErrorCode.INVALID_STATE)
        self.assertEqual(clock.snapshot(), paused)

    def test_fractional_milliseconds_accumulate_across_fast_snapshots(self):
        clock = ChessClock(TimeControl(1_000), now=self.now)
        clock.start("w")

        self.now.advance(0.0004)
        self.assertEqual(clock.snapshot().white_ms, 1_000)
        self.now.advance(0.0004)
        self.assertEqual(clock.snapshot().white_ms, 1_000)
        self.now.advance(0.0004)
        self.assertEqual(clock.snapshot().white_ms, 999)

    def test_monotonic_source_rejects_invalid_values_and_rollback(self):
        with self.assertRaises(ClockError) as not_callable:
            ChessClock(TimeControl(1_000), now=object())
        self.assertEqual(
            not_callable.exception.code,
            ClockErrorCode.INVALID_TIME_SOURCE,
        )

        for invalid in (True, "100", float("nan"), float("inf"), 10**400, -(10**400)):
            self.now.value = invalid
            clock = ChessClock(TimeControl(1_000), now=self.now)
            with self.subTest(value=invalid):
                with self.assertRaises(ClockError) as caught:
                    clock.start("w")
                self.assertEqual(
                    caught.exception.code,
                    ClockErrorCode.INVALID_TIME_SOURCE,
                )
                self.assertEqual(clock.state, ClockState.STOPPED)

        self.now.value = 100.0
        clock = ChessClock(TimeControl(2_000), now=self.now)
        clock.start("w")
        self.now.value = 99.0
        with self.assertRaises(ClockError) as rollback:
            clock.snapshot()
        self.assertEqual(
            rollback.exception.code,
            ClockErrorCode.INVALID_TIME_SOURCE,
        )
        self.now.value = 101.0
        self.assertEqual(clock.snapshot().white_ms, 1_000)

        self.now.value = float("nan")
        clock = ChessClock(TimeControl(2_000), now=self.now)
        before = clock.snapshot()
        running = ClockSnapshot(1_500, 2_000, "w", ClockState.RUNNING)
        with self.assertRaises(ClockError) as restore_time_error:
            clock.restore(running, resume_running=True)
        self.assertEqual(
            restore_time_error.exception.code,
            ClockErrorCode.INVALID_TIME_SOURCE,
        )
        self.now.value = 100.0
        self.assertEqual(clock.snapshot(), before)

    def test_extreme_finite_monotonic_delta_fails_with_domain_error_atomically(self):
        # The subtraction can overflow (opposite signs), or the subtraction
        # can be finite while conversion to milliseconds overflows.
        for starting, advanced in ((-1e308, 1e308), (1e308, 1.1e308)):
            with self.subTest(starting=starting, advanced=advanced):
                now = FakeTime()
                now.value = starting
                clock = ChessClock(TimeControl(2_000, 500), now=now)
                before = clock.start("w")
                now.value = advanced
                with self.assertRaises(ClockError) as caught:
                    clock.snapshot()
                self.assertEqual(caught.exception.code, ClockErrorCode.INVALID_TIME_SOURCE)
                # The invalid reading must not award an increment, flag a side,
                # or mutate the last accepted snapshot.
                now.value = starting
                self.assertEqual(clock.snapshot(), before)

    def test_untimed_restore_requires_canonical_stopped_zero_snapshot(self):
        clock = ChessClock(TimeControl(0), now=self.now)
        before = clock.snapshot()
        noncanonical = ClockSnapshot(0, 0, "w", ClockState.RUNNING)

        with self.assertRaises(ClockError) as caught:
            clock.restore(noncanonical)

        self.assertEqual(caught.exception.code, ClockErrorCode.INVALID_SNAPSHOT)
        self.assertEqual(clock.snapshot(), before)

    def test_side_inputs_reject_non_text_values_with_stable_code(self):
        clock = ChessClock(TimeControl(1_000), now=self.now)
        before = clock.snapshot()
        for invalid in (True, 1, None, [], {}):
            with self.subTest(side=invalid):
                with self.assertRaises(ClockError) as caught:
                    clock.start(invalid)
                self.assertEqual(
                    caught.exception.code,
                    ClockErrorCode.INVALID_COMMAND,
                )
                self.assertEqual(clock.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
