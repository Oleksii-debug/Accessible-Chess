import unittest

from acs.engine_game_session import EngineNoMoveHandoff
from acs.engine_ports import ENGINE_FEN_MAX_LENGTH, EngineContractError, EngineContractErrorCode


class EngineNoMoveFenBoundsTests(unittest.TestCase):
    def test_shared_engine_fen_boundary_is_used(self):
        handoff = EngineNoMoveHandoff(
            "  " + ("x" * ENGINE_FEN_MAX_LENGTH) + "  ",
            "w",
            " node-1 ",
        )
        self.assertEqual(handoff.fen, "x" * ENGINE_FEN_MAX_LENGTH)
        self.assertEqual(handoff.history_node_id, "node-1")

    def test_one_character_over_boundary_fails_closed(self):
        with self.assertRaises(EngineContractError) as caught:
            EngineNoMoveHandoff(
                "x" * (ENGINE_FEN_MAX_LENGTH + 1),
                "b",
                "node-2",
            )
        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_HANDOFF)
        self.assertEqual(
            str(caught.exception),
            "no-move handoff FEN must be bounded non-empty text",
        )

    def test_bound_applies_after_outer_whitespace_normalization(self):
        handoff = EngineNoMoveHandoff(
            " \t" + ("y" * ENGINE_FEN_MAX_LENGTH) + "\n ",
            "w",
            "node-3",
        )
        self.assertEqual(len(handoff.fen), ENGINE_FEN_MAX_LENGTH)

    def test_blank_and_non_text_payloads_keep_typed_handoff_failure(self):
        for invalid in ("   ", None, 1, True, [], {}):
            with self.subTest(fen=invalid):
                with self.assertRaises(EngineContractError) as caught:
                    EngineNoMoveHandoff(invalid, "w", "node-4")
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_HANDOFF,
                )


if __name__ == "__main__":
    unittest.main()
