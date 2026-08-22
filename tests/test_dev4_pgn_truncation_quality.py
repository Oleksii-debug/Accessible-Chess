from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.import_contract import ImportQuality
from acs.pgn_service import PgnFileImporter


class Dev4PgnTruncationQualityTests(unittest.TestCase):
    """QA gate for false-green quality on abruptly terminated PGN sources."""

    def test_missing_game_termination_marker_is_not_counted_full(self) -> None:
        # The source ends immediately after a move. The parser currently fills
        # in Result='*' even though no movetext termination marker was present.
        # Import quality must distinguish that recovery from a genuinely full
        # record instead of incrementing the FULL aggregate count.
        text = (
            '[Event "Truncated"]\n'
            '[White "Alpha"]\n'
            '[Black "Beta"]\n\n'
            '1. e4 e5 2. Nf3'
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "truncated.pgn"
            source.write_text(text, encoding="utf-8")

            report = PgnFileImporter().inspect(source)

        self.assertEqual(report.total, 1)
        self.assertNotEqual(
            report.records[0].quality,
            ImportQuality.FULL,
            "A PGN recovered without an explicit game-termination marker must not be reported as FULL quality.",
        )
        self.assertEqual(
            report.counts[ImportQuality.FULL.value],
            0,
            "Aggregate quality counts must not false-green an abruptly terminated PGN as full.",
        )


if __name__ == "__main__":
    unittest.main()
