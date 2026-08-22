import unittest

from acs.engine_play_service import (
    ENGINE_HISTORY_NODE_ID_MAX_LENGTH,
    EngineGameHandoff,
    EngineGameIntent,
)
from acs.engine_ports import EngineContractError, EngineContractErrorCode


class EngineHistoryNodeIdBoundsTests(unittest.TestCase):
    def test_exact_boundary_is_accepted_after_outer_whitespace_normalization(self):
        node_id = "n" * ENGINE_HISTORY_NODE_ID_MAX_LENGTH
        handoff = EngineGameHandoff(
            EngineGameIntent.OPEN_FINAL_REVIEW,
            history_node_id=f"  {node_id}  ",
        )
        self.assertEqual(handoff.history_node_id, node_id)

    def test_one_character_over_boundary_fails_closed(self):
        with self.assertRaises(EngineContractError) as caught:
            EngineGameHandoff(
                EngineGameIntent.OPEN_FINAL_REVIEW,
                history_node_id="n" * (ENGINE_HISTORY_NODE_ID_MAX_LENGTH + 1),
            )
        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_HANDOFF)
        self.assertEqual(
            str(caught.exception),
            "final-review handoff requires history_node_id text",
        )

    def test_normalization_happens_before_bound(self):
        node_id = "x" * ENGINE_HISTORY_NODE_ID_MAX_LENGTH
        handoff = EngineGameHandoff(
            "open_final_review",
            history_node_id=f"\n {node_id} \t",
        )
        self.assertEqual(handoff.history_node_id, node_id)

    def test_blank_and_non_text_inputs_preserve_legacy_contract(self):
        for invalid in (None, "   ", True, 42, [], {}):
            with self.subTest(invalid=invalid):
                with self.assertRaises(EngineContractError) as caught:
                    EngineGameHandoff(
                        EngineGameIntent.OPEN_FINAL_REVIEW,
                        history_node_id=invalid,
                    )
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_HANDOFF,
                )
                self.assertEqual(
                    str(caught.exception),
                    "final-review handoff requires history_node_id text",
                )

    def test_bound_is_a_small_explicit_public_contract(self):
        self.assertEqual(ENGINE_HISTORY_NODE_ID_MAX_LENGTH, 256)


if __name__ == "__main__":
    unittest.main()
