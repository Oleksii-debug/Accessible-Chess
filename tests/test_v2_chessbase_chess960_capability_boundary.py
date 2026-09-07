from __future__ import annotations

from pathlib import Path
import unittest


MATRIX = Path(__file__).resolve().parents[1] / "docs" / "automation" / "DEV4_CHESSBASE_CAPABILITY_MATRIX.md"


class V2ChessBaseChess960CapabilityBoundaryTests(unittest.TestCase):
    def test_public_matrix_explicitly_blocks_chess960_fischer_random(self) -> None:
        text = MATRIX.read_text(encoding="utf-8")
        lowered = text.casefold()
        self.assertIn("chess960", lowered)
        self.assertIn("fischer random", lowered)
        self.assertIn("chess960_fischer_random=unsupported", lowered)
        self.assertIn("must never be silently reinterpreted as standard", lowered)

    def test_cbh_and_cbv_rows_inherit_the_same_variant_boundary(self) -> None:
        text = MATRIX.read_text(encoding="utf-8")
        cbh_row = next(line for line in text.splitlines() if line.startswith("| `.cbh`"))
        cbv_row = next(line for line in text.splitlines() if line.startswith("| `.cbv`"))
        self.assertIn("Chess960 / Fischer Random", cbh_row)
        self.assertIn("UNSUPPORTED", cbh_row)
        self.assertIn("Chess960 / Fischer Random", cbv_row)
        self.assertIn("UNSUPPORTED", cbv_row)


if __name__ == "__main__":
    unittest.main()
