"""Section 40: executable rights split and actual offline Library readback."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import revised_section40_offline_test_library as builder


class RevisedSection40CollectionTests(unittest.TestCase):
    def test_both_real_packages_are_distinct_and_readable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            trial = root / "test-library.zip"
            public = root / "public-library.zip"
            test_report = builder.build_collection("TEST_BUILD", trial)
            public_report = builder.build_collection("PUBLIC_RELEASE", public)
            self.assertFalse(test_report["section40_done"])
            self.assertFalse(public_report["section40_done"])
            self.assertEqual(test_report["real_import_readback"]["game_count"], 512)
            self.assertEqual(test_report["real_import_readback"]["advanced_annotated_game_count"], 4)
            self.assertEqual(test_report["real_import_readback"]["total_database_games"], 516)
            self.assertIsNone(public_report["real_import_readback"])
            self.assertEqual(test_report["archive_sha256"],
                             hashlib.sha256(trial.read_bytes()).hexdigest())
            self.assertEqual(public_report["archive_sha256"],
                             hashlib.sha256(public.read_bytes()).hexdigest())
            with zipfile.ZipFile(trial) as z:
                trial_names = set(z.namelist())
                catalog = json.loads(z.read("catalog/materials.json"))
                self.assertEqual(catalog["profile"], "TEST_BUILD")
                self.assertFalse(catalog["owner_accepted"])
                self.assertEqual(catalog["real_import_readback"]["game_count"], 512)
                self.assertIn("library/real-stockfish-first-512.acsdb", trial_names)
                self.assertIn("library/real-lichess-four-annotated-original-games.pgn", trial_names)
                self.assertIn("library/original-reti-1921-uk-en-study.pgn", trial_names)
                reti = z.read("library/original-reti-1921-uk-en-study.pgn")
                self.assertIn(b'[SetUp "1"]', reti)
                self.assertIn(b'7K/8/k1P5/7p/8/8/8/8 w - - 0 1', reti)
                self.assertIn(b'EN:', reti)
                self.assertIn(b'UK:', reti)
                reti_sources = [
                    row for row in catalog["materials"]
                    if row["id"] == "historical_reti_1921_original_bilingual_study_pgn"
                ]
                self.assertEqual(len(reti_sources), 1)
                self.assertEqual(reti_sources[0]["sha256"], hashlib.sha256(reti).hexdigest())
                self.assertGreaterEqual(z.read("library/real-lichess-four-annotated-original-games.pgn").count(b'[%eval '), 60)
                self.assertIn("library/real-stockfish-first-32.pgn", trial_names)
                self.assertIn("library/real-stockfish-first-128.pgn", trial_names)
                self.assertIn("library/real-stockfish-first-512.pgn", trial_names)
                self.assertEqual(catalog["real_import_readback"]["sample_sizes"], [32, 128, 512])
                self.assertIn("books/accessible-chess-starter-course.json", trial_names)
                qualified_workbooks = [
                    item for item in catalog["materials"]
                    if item["id"].startswith("section37_bilingual_original_workbook_")
                ]
                self.assertEqual(len(qualified_workbooks), 10)
                self.assertEqual(
                    {(r["language"], r["format"]) for r in qualified_workbooks},
                    {(lang, ext) for lang in ("uk", "en")
                     for ext in ("txt", "md", "html", "epub", "docx")},
                )
                for row in qualified_workbooks:
                    self.assertIn(row["source_path"], trial_names)
                    raw = z.read(row["source_path"])
                    self.assertEqual(row["sha256"], hashlib.sha256(raw).hexdigest())
                    self.assertEqual(row["size_bytes"], len(raw))
                    self.assertEqual(row["original_lesson_count"], 12)
                    self.assertEqual(row["import_status"],
                                     "ACTUAL_NATIVE_BOOK_IMPORT_RESTART_PASS_DERIVED_SOURCE")
                for english_book in (
                    "books/advanced-lichess-16-en.json",
                    "books/extreme-lichess-4-en.json",
                ):
                    self.assertIn(english_book, trial_names)
                    en_document = json.loads(z.read(english_book))
                    self.assertEqual(en_document["language"], "en")
                self.assertEqual(
                    len([x for x in catalog["materials"]
                         if x.get("language") == "en"
                         and x.get("import_status") == "CANONICAL_BOOKDOCUMENT_ENGLISH_ROUNDTRIP_PASS"]), 2)
                self.assertIn("training/starter-exercises.json", trial_names)
                self.assertIn("training/advanced-lichess-16-middlegame-endgame.json", trial_names)
                self.assertIn("training/extreme-lichess-4-original-puzzles.json", trial_names)
                extreme = json.loads(z.read("training/extreme-lichess-4-original-puzzles.json"))
                self.assertEqual(len(extreme["tasks"]), 4)
                self.assertTrue(all(x["puzzle_rating_lichess_not_fide"] >= 3000
                                    for x in extreme["tasks"]))
                self.assertIn("books/advanced-lichess-16-middlegame-endgame.json", trial_names)
                advanced = json.loads(z.read("training/advanced-lichess-16-middlegame-endgame.json"))
                self.assertEqual(len(advanced["tasks"]), 16)
                self.assertTrue(all(x["puzzle_rating_lichess_not_fide"] >= 2200
                                    for x in advanced["tasks"]))
                self.assertEqual(
                    len([n for n in trial_names if n.startswith("books/booklet-")]), 24)
                self.assertTrue(any("stockfish_2moves" in n for n in trial_names))
                self.assertFalse(any("gitenberg_capablanca" in n for n in trial_names))
                self.assertGreaterEqual(len(catalog["materials"]), 42)
                self.assertTrue(any(x["id"] == "lichess_cc0_advanced_16_original_derived"
                                    for x in catalog["materials"]))
                self.assertTrue(any(x["id"] == "lichess_cc0_high_level_4_original_annotated_games"
                                    for x in catalog["materials"]))
                self.assertEqual(len(json.loads(z.read("training/starter-exercises.json"))["tasks"]), 144)
                data = json.loads(z.read("catalog/checksums.json"))
                for receipt in data:
                    self.assertEqual(
                        hashlib.sha256(z.read(receipt["path"])).hexdigest(),
                        receipt["sha256"],
                    )
            with zipfile.ZipFile(public) as z:
                names = set(z.namelist())
                catalog = json.loads(z.read("catalog/materials.json"))
                self.assertEqual(catalog["profile"], "PUBLIC_RELEASE")
                self.assertGreaterEqual(len(catalog["materials"]), 50)
                self.assertFalse(any(p.startswith("library/") for p in names))
                self.assertNotIn("library/original-reti-1921-uk-en-study.pgn", names)
                self.assertFalse(any("stockfish_" in p for p in names))
                self.assertIn("books/advanced-lichess-16-middlegame-endgame.json", names)
                self.assertIn("training/advanced-lichess-16-middlegame-endgame.json", names)
                self.assertIn("training/extreme-lichess-4-original-puzzles.json", names)
                self.assertIn("books/original-reti-1921-en.json", names)
                self.assertIn("books/original-reti-1921-uk.json", names)
                self.assertIn("training/original-reti-1921-study.json", names)
                bilingual = [
                    item for item in catalog["materials"]
                    if item["id"].startswith("section37_bilingual_original_workbook_")
                ]
                self.assertEqual(len(bilingual), 10)
                for row in bilingual:
                    self.assertIn(row["source_path"], names)
                    self.assertEqual(row["sha256"],
                                     hashlib.sha256(z.read(row["source_path"])).hexdigest())
                    self.assertFalse("publisher" in row["source_kind"].lower())
                    self.assertEqual(row["redistribution"], "permitted")
                self.assertIn("books/advanced-lichess-16-en.json", names)
                self.assertIn("books/extreme-lichess-4-en.json", names)
                self.assertFalse(any("gitenberg_" in p for p in names))
                self.assertEqual(
                    len([n for n in names if n.startswith("books/booklet-")]), 24)
                sources = [p for p in catalog["materials"]
                           if p["id"].startswith("lichess_openings_original_")]
                self.assertEqual(len(sources), 5)
                self.assertTrue(all(p["redistribution"] == "permitted" for p in sources))
                links = json.loads(z.read("catalog/external-links.json"))
                self.assertTrue(any(x["id"] == "gitenberg_capablanca_33870_original_txt"
                                    for x in links))
                self.assertTrue(all(x["note"].startswith("External link only") for x in links))

    def test_refuses_existing_destination_and_invalid_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "already-exists.zip"
            path.write_bytes(b"OWNER DATA")
            with self.assertRaisesRegex(builder.OfflineCollectionError, "unsupported"):
                builder.build_collection("DEBUG_BYPASS", Path(temp) / "new.zip")
            with self.assertRaisesRegex(builder.OfflineCollectionError, "refusing overwrite"):
                builder.build_collection("PUBLIC_RELEASE", path)
            self.assertEqual(path.read_bytes(), b"OWNER DATA")

    def test_refuses_mutated_source_bytes_before_publishing(self):
        with tempfile.TemporaryDirectory() as temp:
            original = builder.read_verified_source_snapshot

            def corrupt_one(path, record):
                if path.name == "lichess_openings_a.tsv":
                    return b"unauthorized substitute"
                return original(path, record)

            out = Path(temp) / "no-output.zip"
            with patch.object(builder, "read_verified_source_snapshot", corrupt_one):
                with self.assertRaisesRegex(builder.OfflineCollectionError,
                                            "source identity changed"):
                    builder.build_collection("PUBLIC_RELEASE", out)
            self.assertFalse(out.exists())

    def test_public_rights_gate_is_not_bypassed_by_catalog_flag(self):
        records = builder.load_catalog()
        test_sources = builder.inventory_vendored_corpus(
            records, builder.ROOT, distribution="TEST_BUILD")
        public = builder.inventory_vendored_corpus(
            records, builder.ROOT, distribution="PUBLIC_RELEASE")
        self.assertGreaterEqual(len(test_sources), 11)
        self.assertIn("lichess_cc0_advanced_16_original_derived",
                      {s["source_id"] for s in test_sources})
        self.assertIn("lichess_cc0_high_level_4_original_annotated_games",
                      {s["source_id"] for s in test_sources})
        self.assertEqual(len(public), 5)
        self.assertTrue(all(s["source_id"].startswith("lichess_openings_original_")
                            for s in public))


if __name__ == "__main__":
    unittest.main()
