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
            self.assertEqual(test_report["real_import_readback"]["game_count"], 32)
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
                self.assertEqual(catalog["real_import_readback"]["game_count"], 32)
                self.assertIn("library/real-stockfish-first-32.acsdb", trial_names)
                self.assertIn("library/real-stockfish-first-32.pgn", trial_names)
                self.assertIn("books/accessible-chess-starter-course.json", trial_names)
                self.assertIn("training/starter-exercises.json", trial_names)
                self.assertEqual(
                    len([n for n in trial_names if n.startswith("books/booklet-")]), 24)
                self.assertTrue(any("stockfish_2moves" in n for n in trial_names))
                self.assertFalse(any("gitenberg_capablanca" in n for n in trial_names))
                self.assertEqual(len(catalog["materials"]), 35)
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
                self.assertEqual(len(catalog["materials"]), 31)
                self.assertFalse(any(p.startswith("library/") for p in names))
                self.assertFalse(any("stockfish_" in p for p in names))
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
        self.assertEqual(len(test_sources), 9)
        self.assertEqual(len(public), 5)
        self.assertTrue(all(s["source_id"].startswith("lichess_openings_original_")
                            for s in public))


if __name__ == "__main__":
    unittest.main()
