from pathlib import Path
import tempfile
import unittest

from acs.game_lifecycle import (
    EndReason,
    GameLifecycle,
    GameOutcome,
    GameStatus,
    LifecycleError,
    LifecycleErrorCode,
    LifecycleSnapshot,
)
from acs.keybindings import ActionRegistry
from acs.stage1_release_ui import Stage1ReleaseAccessibleChessAPI
from acs.webapp import AccessibleChessAPI
from acs.webapp_keymap import KeymapAwareAccessibleChessAPI


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

    def test_outcome_reason_result_matrix_fails_closed(self):
        invalid = (
            ("1/2-1/2", EndReason.CHECKMATE, None),
            ("1/2-1/2", EndReason.RESIGNATION, None),
            ("1-0", EndReason.STALEMATE, "w"),
            ("1-0", EndReason.INSUFFICIENT_MATERIAL, "w"),
            ("0-1", EndReason.THREEFOLD_REPETITION, "b"),
            ("1-0", EndReason.FIFTY_MOVE_RULE, "w"),
            ("1-0", EndReason.DRAW_AGREEMENT, "w"),
            ("1-0", "checkmate", "w"),
            ("1-0", True, "w"),
            ("1-0", EndReason.CHECKMATE, []),
            ("1-0", EndReason.CHECKMATE, {}),
        )
        for result, reason, winner in invalid:
            with self.subTest(result=result, reason=reason, winner=winner):
                with self.assertRaises(LifecycleError) as caught:
                    GameOutcome(result, reason, winner)
                self.assertEqual(
                    caught.exception.code,
                    LifecycleErrorCode.INVALID_OUTCOME,
                )

    def test_timeout_is_the_only_reason_that_allows_draw_or_win(self):
        decisive = GameOutcome("1-0", EndReason.TIMEOUT, "w")
        drawn = GameOutcome("1/2-1/2", EndReason.TIMEOUT)
        checkmate = GameOutcome("0-1", EndReason.CHECKMATE, "b")

        self.assertEqual(decisive.winner, "w")
        self.assertIsNone(drawn.winner)
        self.assertEqual(checkmate.winner, "b")

    def test_position_outcome_validation_is_atomic_and_reason_is_exact(self):
        game = GameLifecycle()
        before = game.snapshot()
        invalid = (
            ("1-0", "checkmate", "w"),
            ("1/2-1/2", EndReason.CHECKMATE, None),
            ("1-0", EndReason.STALEMATE, "w"),
            ("1-0", EndReason.RESIGNATION, "w"),
        )
        for result, reason, winner in invalid:
            with self.subTest(result=result, reason=reason, winner=winner):
                with self.assertRaises(LifecycleError) as caught:
                    game.record_position_outcome(result, reason, winner=winner)
                self.assertEqual(
                    caught.exception.code,
                    LifecycleErrorCode.INVALID_OUTCOME,
                )
                self.assertEqual(game.snapshot(), before)

    def test_timeout_mating_capability_requires_boolean_without_mutation(self):
        game = GameLifecycle()
        before = game.snapshot()
        for invalid in (1, 0, "true", "false", None):
            with self.subTest(opponent_can_mate=invalid):
                with self.assertRaises(LifecycleError) as caught:
                    game.record_timeout("w", opponent_can_mate=invalid)
                self.assertEqual(
                    caught.exception.code,
                    LifecycleErrorCode.INVALID_COMMAND,
                )
                self.assertEqual(game.snapshot(), before)

    def test_side_inputs_reject_non_text_scalars_and_containers_atomically(self):
        game = GameLifecycle()
        before = game.snapshot()
        for invalid in (True, False, 1, None, [], {}):
            with self.subTest(side=invalid):
                with self.assertRaises(LifecycleError) as caught:
                    game.offer_draw(invalid)
                self.assertEqual(
                    caught.exception.code,
                    LifecycleErrorCode.INVALID_COMMAND,
                )
                self.assertEqual(game.snapshot(), before)

    def test_pending_interaction_owner_cannot_be_overwritten(self):
        game = GameLifecycle()
        game.offer_draw("w")
        draw_pending = game.snapshot()
        with self.assertRaises(LifecycleError) as draw_error:
            game.offer_draw("b")
        self.assertEqual(draw_error.exception.code, LifecycleErrorCode.ALREADY_PENDING)
        self.assertEqual(game.snapshot(), draw_pending)

        game.request_takeback("b")
        takeback_pending = game.snapshot()
        with self.assertRaises(LifecycleError) as takeback_error:
            game.request_takeback("w")
        self.assertEqual(
            takeback_error.exception.code,
            LifecycleErrorCode.ALREADY_PENDING,
        )
        self.assertEqual(game.snapshot(), takeback_pending)

    def test_pending_response_failures_have_stable_codes_and_are_atomic(self):
        game = GameLifecycle()
        before = game.snapshot()
        with self.assertRaises(LifecycleError) as missing:
            game.accept_draw("b")
        self.assertEqual(
            missing.exception.code,
            LifecycleErrorCode.NO_PENDING_INTERACTION,
        )
        self.assertEqual(game.snapshot(), before)

        game.offer_draw("w")
        pending = game.snapshot()
        with self.assertRaises(LifecycleError) as own:
            game.decline_draw("w")
        self.assertEqual(own.exception.code, LifecycleErrorCode.SELF_RESPONSE)
        self.assertEqual(game.snapshot(), pending)

    def test_lifecycle_snapshot_rejects_impossible_public_dto_states(self):
        outcome = GameOutcome("1-0", EndReason.RESIGNATION, "w")
        invalid = (
            ("active", None, None, None),
            (GameStatus.ACTIVE, outcome, None, None),
            (GameStatus.FINISHED, None, None, None),
            (GameStatus.FINISHED, outcome, "w", None),
            (GameStatus.ACTIVE, None, True, None),
            (GameStatus.ACTIVE, None, [], None),
            (GameStatus.ACTIVE, None, None, "white"),
        )
        for values in invalid:
            with self.subTest(values=values):
                with self.assertRaises(LifecycleError) as caught:
                    LifecycleSnapshot(*values)
                self.assertEqual(
                    caught.exception.code,
                    LifecycleErrorCode.INVALID_STATE,
                )

    def test_restore_checkpoint_round_trips_pending_interactions(self):
        game = GameLifecycle()
        game.offer_draw("w")
        game.request_takeback("b")
        checkpoint = game.snapshot()
        game.on_move_committed()
        self.assertNotEqual(game.snapshot(), checkpoint)

        self.assertEqual(game.restore_checkpoint(checkpoint), checkpoint)
        self.assertEqual(game.restore_checkpoint(checkpoint), checkpoint)
        self.assertEqual(game.snapshot().draw_offered_by, "w")
        self.assertEqual(game.snapshot().takeback_requested_by, "b")
        accepted = game.accept_takeback("w")
        self.assertIsNone(accepted.takeback_requested_by)
        self.assertEqual(accepted.draw_offered_by, "w")

    def test_restore_checkpoint_preserves_terminal_outcome(self):
        game = GameLifecycle()
        terminal = game.resign("b")
        game.reset_for_new_game()
        self.assertEqual(game.restore_checkpoint(terminal), terminal)
        self.assertEqual(game.snapshot().outcome, terminal.outcome)
        with self.assertRaises(LifecycleError):
            game.offer_draw("w")

    def test_restore_checkpoint_rejects_wrong_type_without_mutation(self):
        game = GameLifecycle()
        game.request_takeback("w")
        before = game.snapshot()
        for invalid in (None, {}, "active", True):
            with self.subTest(checkpoint=invalid):
                with self.assertRaises(LifecycleError) as caught:
                    game.restore_checkpoint(invalid)
                self.assertEqual(caught.exception.code, LifecycleErrorCode.INVALID_STATE)
                self.assertEqual(game.snapshot(), before)

    def test_restore_checkpoint_revalidates_corrupt_snapshot_before_mutation(self):
        game = GameLifecycle()
        game.offer_draw("b")
        before = game.snapshot()
        broken = LifecycleSnapshot(GameStatus.ACTIVE, None, None, None)
        object.__setattr__(broken, "status", "finished")
        with self.assertRaises(LifecycleError) as caught:
            game.restore_checkpoint(broken)
        self.assertEqual(caught.exception.code, LifecycleErrorCode.INVALID_STATE)
        self.assertEqual(game.snapshot(), before)

    def test_restore_checkpoint_revalidates_nested_outcome_atomically(self):
        game = GameLifecycle()
        game.request_takeback("w")
        before = game.snapshot()
        outcome = GameOutcome("1-0", EndReason.RESIGNATION, "w")
        checkpoint = LifecycleSnapshot(GameStatus.FINISHED, outcome, None, None)
        object.__setattr__(outcome, "reason", EndReason.STALEMATE)
        with self.assertRaises(LifecycleError) as caught:
            game.restore_checkpoint(checkpoint)
        self.assertEqual(caught.exception.code, LifecycleErrorCode.INVALID_OUTCOME)
        self.assertEqual(game.snapshot(), before)

    def test_finished_state_error_code_is_stable(self):
        game = GameLifecycle()
        game.resign("w")
        before = game.snapshot()

        with self.assertRaises(LifecycleError) as caught:
            game.offer_draw("b")

        self.assertEqual(caught.exception.code, LifecycleErrorCode.INVALID_STATE)
        self.assertEqual(game.snapshot(), before)

    def test_section12_local_draw_resign_and_new_game_transitions(self):
        api = AccessibleChessAPI("en")

        offered = api.offer_draw()
        self.assertTrue(offered["ok"])
        self.assertEqual(offered["localGame"]["drawOfferedBy"], "w")

        drawn = api.accept_draw()
        self.assertTrue(drawn["ok"])
        self.assertEqual(drawn["localGame"]["status"], "finished")
        self.assertEqual(drawn["localGame"]["result"], "1/2-1/2")
        self.assertEqual(drawn["localGame"]["reason"], "draw_agreement")
        self.assertFalse(api.make_move("e4")["ok"])

        reset = api.new_game()
        self.assertTrue(reset["ok"])
        self.assertEqual(reset["localGame"]["status"], "active")
        self.assertIsNone(reset["localGame"]["result"])

        resigned = api.resign()
        self.assertTrue(resigned["ok"])
        self.assertEqual(resigned["localGame"]["result"], "0-1")
        self.assertEqual(resigned["localGame"]["winner"], "b")
        self.assertEqual(resigned["localGame"]["reason"], "resignation")

    def test_section12_draw_offer_expires_on_committed_local_move(self):
        api = AccessibleChessAPI("en")
        self.assertTrue(api.offer_draw()["ok"])

        moved = api.make_move("e4")

        self.assertTrue(moved["ok"])
        self.assertEqual(moved["localGame"]["status"], "active")
        self.assertIsNone(moved["localGame"]["drawOfferedBy"])

    def test_section12_checkmate_result_blocks_play_and_undo_reopens(self):
        api = AccessibleChessAPI("en")
        for move in ("f3", "e5", "g4", "Qh4#"):
            result = api.make_move(move)
            self.assertTrue(result["ok"], move)

        terminal = api.get_state()
        self.assertEqual(terminal["localGame"]["status"], "finished")
        self.assertEqual(terminal["localGame"]["result"], "0-1")
        self.assertEqual(terminal["localGame"]["reason"], "checkmate")
        self.assertFalse(api.make_move("e4")["ok"])

        undone = api.undo()
        self.assertTrue(undone["ok"])
        self.assertEqual(undone["localGame"]["status"], "active")
        self.assertIsNone(undone["localGame"]["result"])

    def test_section12_commands_are_in_one_registry_and_keymap_dispatch(self):
        registry = ActionRegistry()
        action_ids = {item.action_id for item in registry.definitions()}
        self.assertTrue({
            "game.offer_draw",
            "game.accept_draw",
            "game.decline_draw",
            "game.resign",
        }.issubset(action_ids))

        with tempfile.TemporaryDirectory() as temp:
            api = KeymapAwareAccessibleChessAPI(
                "en",
                keymap_path=Path(temp) / "keymap.json",
            )
            self.assertTrue(api.dispatch_action("game.offer_draw")["ok"])
            accepted = api.dispatch_action("game.accept_draw")
            self.assertTrue(accepted["ok"])
            self.assertEqual(accepted["localGame"]["result"], "1/2-1/2")

    def test_section12_release_dispatch_uses_local_game_when_engine_does_not_own_board(self):
        with tempfile.TemporaryDirectory() as temp:
            api = Stage1ReleaseAccessibleChessAPI(
                "en",
                keymap_path=Path(temp) / "keymap.json",
            )
            result = api.dispatch_action("game.resign")

        self.assertTrue(result["ok"])
        self.assertEqual(result["localGame"]["status"], "finished")
        self.assertEqual(result["localGame"]["result"], "0-1")
        self.assertEqual(result["localGame"]["reason"], "resignation")


if __name__ == "__main__":
    unittest.main()
