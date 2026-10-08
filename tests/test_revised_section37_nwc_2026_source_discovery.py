"""Section 37: actual publisher links are not an acquired/redistributable corpus.

These checks are offline. They guard the source-discovery boundary; they are
not evidence that the remote CBV/PGN bytes were downloaded or parsed.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.lawful_corpus_registry import (
    LawfulCorpusError,
    acquire_cc0_source,
    load_catalog,
    qualify_offline_collection,
)


class NorthwestChess2026DiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sources = {record["id"]: record for record in load_catalog()}

    def test_two_original_publisher_pairs_remain_source_only(self) -> None:
        parent = "https://www.nwchess.com/articles/games/published/"
        expected_ids = set()
        for edition in ("2026_08", "2026_09"):
            month = edition.replace("_", "-")
            for extension in ("cbv", "pgn"):
                identifier = (
                    f"northwest_chess_{edition}_raw_{extension}_original_external"
                )
                expected_ids.add(identifier)
                with self.subTest(source=identifier):
                    record = self.sources[identifier]
                    self.assertEqual(record["format"], extension)
                    self.assertEqual(
                        record["source_page"], parent + "published_games.htm"
                    )
                    self.assertEqual(
                        record["download_url"],
                        parent + f"NWC%20{month}%20Published%20Raw.{extension}"
                    )
                    self.assertEqual(record["author"].split(";")[0], "Northwest Chess")
                    self.assertIsNone(record["sha256"])
                    self.assertEqual(record["acquisition"], "SOURCE_PAGE_ONLY")
                    self.assertEqual(record["redistribution"], "NOT_CLEARED")
                    self.assertEqual(record["test_access"], "EXTERNAL_EPHEMERAL_ONLY")
                    self.assertEqual(record["public_release"], "EXCLUDED")
                    self.assertGreater(record["max_bytes"], 0)
                    self.assertLessEqual(record["max_bytes"], 128 * 1024 * 1024)
        self.assertEqual(
            {key for key in self.sources if key.startswith("northwest_chess_2026_")},
            expected_ids,
        )

    def test_no_download_or_public_release_authority_from_discovery(self) -> None:
        with tempfile.TemporaryDirectory(prefix="acs-37-nwc2026-") as temporary:
            root = Path(temporary)
            selected = tuple(
                value for key, value in self.sources.items()
                if key.startswith("northwest_chess_2026_")
            )
            self.assertEqual(
                qualify_offline_collection(selected, root, distribution="PUBLIC_RELEASE"),
                (),
            )
            self.assertEqual(
                qualify_offline_collection(selected, root, distribution="TEST_BUILD"),
                (),
            )
            for record in selected:
                with self.subTest(source=record["id"]):
                    with self.assertRaises(LawfulCorpusError):
                        acquire_cc0_source(record, root)
                    self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
