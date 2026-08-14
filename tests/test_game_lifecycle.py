import unittest

from acs.game_lifecycle import EndReason, GameLifecycle, GameStatus, LifecycleError


class GameLifecycleTests(unittest.TestCase):
    def test_draw_and_resign_end_states(self):
        game = GameLifecycle()
        game.offer_draw("w")
        snap = game.accept_draw("b")
        self.assertEqual(snap.status, GameStatus.FINISHED)
        self.assertEqual(snap.outcome.result, "1/2-1/2")
        game.reset_for_new_game()
        snap = game.resign("w")
        self.assertEqual(snap.outcome.result, "0-1")
        self.assertEqual(snap.outcome.winner, "b")

    def test_takeback_handshake_does_not_mutate_board(self):
        game = GameLifecycle()
        game.request_takeback("w")
        snap = game.accept_takeback("b")
        self.assertEqual(snap.status, GameStatus.ACTIVE)
        self.assertIsNone(snap.takeback_requested_by)
        self.assertIsNone(snap.outcome)

    def test_timeout_handles_insufficient_mating_material(self):
        game = GameLifecycle()
        draw = game.record_timeout("w", opponent_can_mate=False)
        self.assertEqual(draw.outcome.result, "1/2-1/2")
        self.assertEqual(draw.outcome.reason, EndReason.TIMEOUT)

    def test_position_outcome_can_be_invalidated_after_history_change(self):
        game = GameLifecycle()
        game.record_position_outcome("1-0", EndReason.CHECKMATE, winner="w")
        reopened = game.invalidate_position_outcome()
        self.assertEqual(reopened.status, GameStatus.ACTIVE)
        self.assertIsNone(reopened.outcome)

    def test_manual_terminal_result_survives_position_invalidation(self):
        game = GameLifecycle()
        game.resign("b")
        snap = game.invalidate_position_outcome()
        self.assertEqual(snap.status, GameStatus.FINISHED)
        self.assertEqual(snap.outcome.reason, EndReason.RESIGNATION)

    def test_move_expires_pending_interactions(self):
        game = GameLifecycle()
        game.offer_draw("w")
        game.request_takeback("b")
        snap = game.on_move_committed()
        self.assertIsNone(snap.draw_offered_by)
        self.assertIsNone(snap.takeback_requested_by)

    def test_invalid_side_and_finished_game_are_rejected(self):
        game = GameLifecycle()
        with self.assertRaises(LifecycleError):
            game.resign("x")
        game.resign("w")
        with self.assertRaises(LifecycleError):
            game.offer_draw("b")


if __name__ == "__main__":
    unittest.main()
