"""Section 39 canonical EPD/FEN semantic readback, fail-closed source identity."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog
from tools.section39_external_position_semantic import (
    _qualify_pinned_source, qualify_external_position_sources, qualify_original_record,
)
from tools.revised_section37_external_position_acquisition import EXPECTED


class RealPositionFormatTests(unittest.TestCase):
    def test_canonical_epd_preserves_original_position_and_opaque_operations(self):
        original = '8/8/2k3K1/8/7P/R5P1/p4r2/8 b - - bm Rg2; id "7menhuman_1"; c0 "draw";'
        status, scope = qualify_original_record(original, "epd")
        self.assertEqual(status, "PASS")
        self.assertIn("ordered opaque operations", scope)

    def test_six_field_fen_semantics_stable(self):
        original = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        status, scope = qualify_original_record(original, "fen")
        self.assertEqual(status, "PASS")
        self.assertIn("six-field", scope)

    def test_four_field_fen_does_not_invent_fullmove_halfmove(self):
        original = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"
        status, scope = qualify_original_record(original, "fen")
        self.assertEqual(status, "PARTIAL")
        self.assertIn("no source counters", scope)

    def test_garbled_positions_are_rejected_not_published(self):
        for source, family in (
            ("garbage", "epd"),
            ("8/8/8/8/8/8/8/8 b - - 0 no", "fen"),
            ("8/8/8/8/8/8/8/8 b -", "txt"),
            ('8/8/2k3K1/8/7P/R5P1/p4r2/8 b - - bm Rg2; bm Nf6;', "epd"),
        ):
            with self.subTest(source=source[:20], family=family):
                with self.assertRaises((LawfulCorpusError, ValueError)):
                    qualify_original_record(source, family)

    def test_external_checker_requires_genuine_upstream_and_license(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(LawfulCorpusError):
                qualify_external_position_sources((), root)
            catalog = load_catalog()
            originals = tuple(x for x in catalog if x["id"] in EXPECTED)
            with self.assertRaises(LawfulCorpusError):
                qualify_external_position_sources(originals, root)

    def test_second_read_detects_changed_bytes_after_provenance_pass(self):
        record = next(x for x in load_catalog()
                      if x["id"] == "original_epd2doc_opening_fen")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "epd2doc").mkdir()
            path = root / "epd2doc" / "opening.fen"
            path.write_text("invalid fake bytes", encoding="ascii")
            forged = {
                "original_sha256": record["sha256"],
                "original_bytes": record["indexed_bytes"],
                "original_git_blob": record["upstream_git_blob"],
                "original_license_sha256": record["external_license_sha256"],
            }
            with self.assertRaisesRegex(LawfulCorpusError,
                                        "changed between acquisition and semantic read"):
                _qualify_pinned_source(record, root, forged)


if __name__ == "__main__":
    unittest.main()
