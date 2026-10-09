"""Section 37 original legal-source EPD/FEN provenance plus source-only negatives."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog
from tools.revised_section37_external_position_acquisition import (
    EXPECTED, verify_record_line_structure, verify_original_positions,
    verify_real_position_sources,
)


class OriginalPositionSources(unittest.TestCase):
    def test_both_real_position_origins_are_exactly_pinned(self):
        records = {item["id"]: item for item in load_catalog()}
        self.assertEqual(
            EXPECTED,
            {
                "original_epd2doc_7men_human_epd": ("epd", 1110),
                "original_epd2doc_opening_fen": ("fen", 4),
            },
        )
        source_info = {
            "original_epd2doc_7men_human_epd": (
                "121f3e632d86ea754f961f9e2f1bb67262be4846ed6aeabda204008ec0eb3395",
                "28b416e56d2aadf65681e9a0b81413bf05e19209",
                79537,
            ),
            "original_epd2doc_opening_fen": (
                "3d97f9801f01cbc42f3aba66b18cca0114e504eac7e1b839da4e1ba0b3894a72",
                "25044ea22bfc28b41ec46c5d23e090602a9ba662",
                255,
            ),
        }
        for key, (digest, git_blob, total) in source_info.items():
            with self.subTest(source=key):
                record = records[key]
                self.assertEqual(record["sha256"], digest)
                self.assertEqual(record["upstream_git_blob"], git_blob)
                self.assertEqual(record["indexed_bytes"], total)
                self.assertEqual(record["expected_line_count"], EXPECTED[key][1])
                self.assertEqual(record["external_license_git_blob"], "f288702d2fa16d3cdf0035b15a9fcbc552cd88e7")
                self.assertEqual(record["external_license_sha256"], "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986")
                self.assertEqual(record["redistribution"], "NOT_CLEARED")
                self.assertEqual(record["public_release"], "EXCLUDED")
                self.assertEqual(record["acquisition"], "PINNED_NOT_DOWNLOADED_IN_THIS_PASS")

    def test_source_line_family_positive_and_negative(self):
        valid_epd = '8/8/2k3K1/8/7P/R5P1/p4r2/8 b - - bm Rg2; id "7menhuman_1"; c0 "draw";'
        valid_fen = "8/8/8/8/8/8/8/8 w - - 0 1"
        self.assertEqual(verify_record_line_structure(valid_epd, "epd", 1), 1)
        self.assertEqual(verify_record_line_structure(valid_fen + "\n" + valid_fen, "fen", 2), 2)
        for raw, fmt, expected in (
            (valid_epd, "epd", 2),
            (valid_epd.replace(" bm ", " BAD "), "epd", 1),
            (valid_epd.replace("; id ", "; blah "), "epd", 1),
            (valid_fen + "\x00", "fen", 1),
            ("not a FEN", "fen", 1),
            ("X" * 2049 + " bm A; id B;", "epd", 1),
            (valid_fen, "txt", 1),
            (valid_fen, "fen", True),
        ):
            with self.subTest(fmt=fmt, raw=raw[:20], count=expected):
                with self.assertRaises(LawfulCorpusError):
                    verify_record_line_structure(raw, fmt, expected)

    def test_missing_originals_and_unsafe_rights_are_denied_without_network(self):
        catalog = {x["id"]: x for x in load_catalog()}
        valid = [catalog[key] for key in EXPECTED]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(LawfulCorpusError):
                verify_real_position_sources((), root)
            for original in valid:
                with self.subTest(source=original["id"]):
                    for bad in (
                        {"public_release": "INCLUDED"},
                        {"test_access": "ANY"},
                        {"redistribution": "permitted"},
                        {"acquisition": "VENDORED_SOURCE_VERIFIED"},
                        {"expected_line_count": -1},
                        {"format": "not_chess"},
                        {"external_license_sha256": "0" * 64},
                    ):
                        with self.assertRaises(LawfulCorpusError):
                            verify_original_positions({**original, **bad}, root)
                    with self.assertRaises(LawfulCorpusError):
                        verify_original_positions(original, root)
            with patch("tools.revised_section37_external_position_acquisition.verified_local_source") as provenance:
                with self.assertRaises(LawfulCorpusError):
                    verify_real_position_sources(tuple(valid), root)
                provenance.assert_not_called()


if __name__ == "__main__":
    unittest.main()
