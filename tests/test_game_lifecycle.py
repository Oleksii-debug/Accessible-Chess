import unittest

from acs.game_lifecycle import (
    EndReason,
    GameLifecycle,
    GameStatus,
    LifecycleError,
)


class GameLifecycleTests(unittest.TestCase):
    def test_draw_offer_accept_finishes_as_draw_and_clears_pending(self):
        game = GameLifecycle()
        self.assertEqual(game.offer_draw("w").draw_offered_by, "w")
        snap = game.accept_draw("b")
        self.assertEqual(snap.status, GameStatus.FINISHED)
        self.assertEqual(snap.outcome.result, "1/2-1/2")
        self.assertEqual(snap.outcome.reason, EndReason.DRAW_AGREEMENT)
        self.assertIsNone(snap.draw_offered_by)

    def test_offer_must_be_answered_by_opponent(self):
        game = GameLifecycle()
        game.offer_draw("b")
        with self.assertRaisesRegex(LifecycleError, "own draw"):
            game.accept_draw("b")
        self.assertEqual(game.snapshot().draw_offered_by, "b")
        self.assertEqual(game.decline_draw("w").status, GameStatus.ACTIVE)
        self.assertIsNone(game.snapshot().draw_offered_by)

    def test_resignation_awards_win_to_opponent(self):
        game = GameLifecycle()
        snap = game.resign("w")
        self.assertEqual(snap.outcome.result, "0-1")
        self.assertEqual(snap.outcome.winner, "b")
        self.assertEqual(snap.outcome.reason, EndReason.RESIGNATION)

    def test_timeout_wins_unless_opponent_cannot_mate(self):
        game = GameLifecycle()
        win = game.record_timeout("b")
        self.assertEqual(win.outcome.result, "1-0")
        self.assertEqual(win.outcome.winner, "w")

        game.reset_for_new_game()
        draw = game.record_timeout("w", opponent_can_mate=False)
        self.assertEqual(draw.outcome.result, "1/2-1/2")
        self.assertIsNone(draw.outcome.winner)
        self.assertEqual(draw.outcome.reason, EndReason.TIMEOUT)

    def test_takeback_acceptance_is_neutral_and_does_not_mutate_board_itself(self):
        game = GameLifecycle()
        self.assertEqual(game.request_takeback("w").takeback_requested_by, "w")
        snap = game.accept_takeback("b")
        self.assertEqual(snap.status, GameStatus.ACTIVE)
        self.assertIsNone(snap.takeback_requested_by)
        self.assertIsNone(snap.outcome)

    def test_takeback_must_be_answered_by_opponent(self):
        game = GameLifecycle()
        game.request_takeback("b")
        with self.assertRaisesRegex(LifecycleError, "own takeback"):
            game.decline_takeback("b")
        self.assertEqual(game.decline_takeback("w").status, GameStatus.ACTIVE)

    def test_move_expires_pending_requests(self):
        game = GameLifecycle()
        game.offer_draw("w")
        game.request_takeback("b")
        snap = game.on_move_committed()
        self.assertIsNone(snap.draw_offered_by)
        self.assertIsNone(snap.takeback_requested_by)

    def test_position_result_can_be_invalidated_after_history_change(self):
        game = GameLifecycle()
        ended = game.record_position_outcome(
            "1-0", EndReason.CHECKMATE, winner="w"
        )
        self.assertEqual(ended.status, GameStatus.FINISHED)
        reopened = game.invalidate_position_outcome()
        self.assertEqual(reopened.status, GameStatus.ACTIVE)
        self.assertIsNone(reopened.outcome)

    def test_manual_terminal_result_survives_generic_history_invalidation(self):
        game = GameLifecycle()
        game.resign("b")
        snap = game.invalidate_position_outcome()
        self.assertEqual(snap.status, GameStatus.FINISHED)
        self.assertEqual(snap.outcome.reason, EndReason.RESIGNATION)

    def test_position_outcome_rejects_non_position_reason(self):
        game = GameLifecycle()
        with self.assertRaisesRegex(LifecycleError, "not position-derived"):
            game.record_position_outcome("1-0", EndReason.RESIGNATION, winner="w")

    def test_finished_game_rejects_new_interaction_until_reset(self):
        game = GameLifecycle()
        game.resign("w")
        for action in (
            lambda: game.offer_draw("w"),
            lambda: game.request_takeback("b"),
            lambda: game.on_move_committed(),
        ):
            with self.assertRaisesRegex(LifecycleError, "already finished"):
                action()
        reset = game.reset_for_new_game()
        self.assertEqual(reset.status, GameStatus.ACTIVE)
        self.assertIsNone(reset.outcome)

    def test_invalid_side_or_inconsistent_result_is_rejected_without_corruption(self):
        game = GameLifecycle()
        with self.assertRaisesRegex(LifecycleError, "side must"):
            game.resign("x")
        with self.assertRaisesRegex(LifecycleError, "winner does not match"):
            game.record_position_outcome(
                "1-0", EndReason.CHECKMATE, winner="b"
            )
        self.assertEqual(game.snapshot().status, GameStatus.ACTIVE)
        self.assertIsNone(game.snapshot().outcome)


if __name__ == "__main__":
    unittest.main()
