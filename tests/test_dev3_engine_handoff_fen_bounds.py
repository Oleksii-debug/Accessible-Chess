import unittest

from acs.engine_play_service import EngineGameHandoff, EngineGameIntent
from acs.engine_ports import (
    ENGINE_FEN_MAX_LENGTH,
    EngineContractError,
    EngineContractErrorCode,
)


class EngineGameHandoffFenBoundsTests(unittest.TestCase):
    def test_accepts_exact_boundary_after_outer_whitespace_normalization(self):
        fen = "x" * ENGINE_FEN_MAX_LENGTH
        handoff = EngineGameHandoff(
            EngineGameIntent.ANALYZE_CURRENT_GAME,
            fen=f"  {fen}  ",
        )
        self.assertEqual(handoff.fen, fen)
        self.assertEqual(len(handoff.fen), ENGINE_FEN_MAX_LENGTH)

    def test_rejects_one_character_over_boundary_with_stable_contract(self):
        with self.assertRaises(EngineContractError) as caught:
            EngineGameHandoff(
                EngineGameIntent.ANALYZE_CURRENT_GAME,
                fen="y" * (ENGINE_FEN_MAX_LENGTH + 1),
            )
        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_HANDOFF)
        self.assertEqual(
            str(caught.exception),
            "analyze-current-game handoff requires fen text",
        )

    def test_rejects_oversized_normalized_payload(self):
        oversized = "z" * (ENGINE_FEN_MAX_LENGTH + 1)
        with self.assertRaises(EngineContractError) as caught:
            EngineGameHandoff(
                EngineGameIntent.ANALYZE_CURRENT_GAME,
                fen=f"  {oversized}  ",
            )
        self.assertEqual(caught.exception.code, EngineContractErrorCode.INVALID_HANDOFF)
        self.assertEqual(
            str(caught.exception),
            "analyze-current-game handoff requires fen text",
        )

    def test_missing_or_invalid_fen_preserves_legacy_error_contract(self):
        for fen in (None, "", "   ", 123):
            with self.subTest(fen=fen):
                with self.assertRaises(EngineContractError) as caught:
                    EngineGameHandoff(
                        EngineGameIntent.ANALYZE_CURRENT_GAME,
                        fen=fen,
                    )
                self.assertEqual(
                    caught.exception.code,
                    EngineContractErrorCode.INVALID_HANDOFF,
                )
                self.assertEqual(
                    str(caught.exception),
                    "analyze-current-game handoff requires fen text",
                )

    def test_shared_engine_bound_matches_direct_analysis_contract(self):
        from acs.analysis_service import ANALYSIS_MAX_FEN_LENGTH

        self.assertEqual(ENGINE_FEN_MAX_LENGTH, ANALYSIS_MAX_FEN_LENGTH)


if __name__ == "__main__":
    unittest.main()
