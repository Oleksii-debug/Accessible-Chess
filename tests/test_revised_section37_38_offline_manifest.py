"""Real-byte provenance receipt regression: NEVER promote discovery to PASS."""
from __future__ import annotations

from pathlib import Path
import hashlib
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from acs.lawful_corpus_registry import LawfulCorpusError, read_verified_source_snapshot
from tools.revised_sections37_38_offline_manifest import build_manifest


ROOT = Path(__file__).resolve().parents[1]


class GenuineCorpusReceiptTests(unittest.TestCase):
    def test_semantic_source_snapshot_uses_bounded_verified_consumed_bytes(self):
        original = b"Verified original chess test source\\n"
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "real.txt"
            source.write_bytes(original)
            record = {
                "max_bytes": len(original),
                "indexed_bytes": len(original),
                "sha256": hashlib.sha256(original).hexdigest(),
            }
            with patch.object(
                Path, "read_bytes", side_effect=AssertionError("unbounded reread forbidden")
            ):
                self.assertEqual(read_verified_source_snapshot(source, record), original)
            source.write_bytes(original[:-1] + b"!")
            with self.assertRaises(LawfulCorpusError):
                read_verified_source_snapshot(source, record)
            source.write_bytes(original + b"too-large")
            with self.assertRaises(LawfulCorpusError):
                read_verified_source_snapshot(source, record)
            source.write_bytes(original)
            for invalid in (True, 0, len(original) - 1):
                with self.subTest(budget=invalid):
                    with self.assertRaises(LawfulCorpusError):
                        read_verified_source_snapshot(source, {**record, "max_bytes": invalid})
            with self.assertRaises(LawfulCorpusError):
                read_verified_source_snapshot(source, {**record, "indexed_bytes": True})

    def test_semantic_source_snapshot_rejects_swap_between_stat_and_open(self):
        original = b"genuine original source"
        changed = b"swapped hostile source!"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "real.txt"
            replacement = root / "replacement.txt"
            target.write_bytes(original)
            replacement.write_bytes(changed)
            record = {
                "max_bytes": 4096,
                "indexed_bytes": len(original),
                "sha256": hashlib.sha256(original).hexdigest(),
            }
            underlying_open = Path.open
            swapped = False

            def swap_once(path, *args, **kwargs):
                nonlocal swapped
                if path == target and not swapped:
                    swapped = True
                    os.replace(replacement, target)
                return underlying_open(path, *args, **kwargs)

            with patch.object(Path, "open", new=swap_once):
                with self.assertRaises(LawfulCorpusError):
                    read_verified_source_snapshot(target, record)
            self.assertTrue(swapped)

    def test_actual_original_file_bytes_and_semantic_status_are_distinct(self):
        report = build_manifest()
        self.assertGreaterEqual(report["source_count"], 25)
        self.assertEqual(report["vendored_cc0_byte_verified_count"], 9)
        self.assertEqual(report["genuine_test_book_read_count"], 1)
        self.assertFalse(report["revised_section_37_terminal_done"])
        self.assertFalse(report["revised_section_38_terminal_done"])
        sources = {item["source_id"]: item for item in report["sources"]}
        self.assertEqual(len(sources), report["source_count"])
        self.assertGreater(
            sources["stockfish_2moves_v2_pgn_zip"]["semantic_count"], 0
        )
        self.assertEqual(
            sources["stockfish_2moves_v2_pgn_zip"]["semantic_state"],
            "SEMANTIC_PGN_PARSED",
        )
        self.assertEqual(
            sources["stockfish_startpos_epd_zip"]["semantic_state"],
            "SEMANTIC_FEN_READ",
        )
        self.assertGreater(
            sources["gitenberg_capablanca_33870_original_txt"]["semantic_count"], 20
        )
        self.assertEqual(
            sources["gitenberg_capablanca_33870_original_txt"]["redistribution"],
            "NOT_CLEARED",
        )
        for identifier in (
            "chessbase_family_complete_real_samples",
            "chessbase_official_free_rossolimo_cbv_sample",
            "capablanca_chess_fundamentals_epub3",
            "lichess_official_puzzles_fen_csv",
        ):
            entry = sources[identifier]
            self.assertEqual(entry["semantic_state"], "NOT_QUALIFIED")
            self.assertIsNone(entry["actual_sha256"])
        self.assertFalse(any(item["public_release_published"] for item in sources.values()))
        for item in sources.values():
            if item["semantic_state"] != "NOT_QUALIFIED":
                self.assertIsNotNone(item["actual_sha256"])
                self.assertEqual(item["actual_sha256"], item["expected_sha256"])
                self.assertEqual(item["actual_bytes"], item["expected_bytes"])

    def test_authentic_cbh_source_families_are_cataloged_without_false_local_pass(self):
        report = build_manifest()
        records = {item["source_id"]: item for item in report["sources"]}
        for identifier in (
            "libcbh_gpl_original_annotation_cbh_family",
            "libcbh_gpl_original_nested_variations_cbh_family",
            "libcbh_gpl_original_unusual_start_cbh_family",
        ):
            with self.subTest(source=identifier):
                entry = records[identifier]
                self.assertEqual(entry["acquisition"], "SOURCE_PAGE_ONLY")
                self.assertEqual(entry["redistribution"], "NOT_CLEARED")
                self.assertEqual(entry["semantic_state"], "NOT_QUALIFIED")
                self.assertFalse(entry["public_release_published"])
                self.assertIsNone(entry["actual_sha256"])

    def test_tampered_original_cc0_source_is_not_reported_as_verified(self):
        # This is deliberately a temporary copy: never modify committed upstream
        # fixtures or overwrite any owner Library database.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "docs/corpus").mkdir(parents=True)
            shutil.copy2(
                ROOT / "docs/corpus/revised_sections37_40_sources.json",
                root / "docs/corpus/revised_sections37_40_sources.json",
            )
            shutil.copytree(ROOT / "tests/real_corpus", root / "tests/real_corpus")
            changed = root / "tests/real_corpus/lichess_openings_a.tsv"
            data = bytearray(changed.read_bytes())
            data[0] ^= 1
            changed.write_bytes(data)
            with self.assertRaises(LawfulCorpusError):
                build_manifest(root)


if __name__ == "__main__":
    unittest.main()
