"""Real, upstream-identical Project Gutenberg chess-book TXT acceptance slice.

This is an actual authored book, not fabricated narrative text, generated
fixtures or proof that proprietary Books/PDF/DOCX/ChessBase formats work.
Source rights are deliberately NOT promoted to PUBLIC_RELEASE.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from acs.book_text_import import import_text_book
from acs.lawful_corpus_registry import (
    LawfulCorpusError, acquire_cc0_source, load_catalog,
    qualify_offline_collection, verified_local_source,
)


ROOT = Path(__file__).resolve().parents[1]
RECORD_ID = "gitenberg_capablanca_33870_original_txt"
EXPECTED_SOURCE_SHA256 = "dfbd48d5b513ea45f07a3701a9148b7aa2a473080a82f39728dbd62b5019c160"
EXPECTED_UPSTREAM_BLOB = "c9a674d3281ccd8a39de7ca673467b79902a103a"


class ActualBookTextSourceTests(unittest.TestCase):
    def _record_and_bytes(self):
        record = {item["id"]: item for item in load_catalog()}[RECORD_ID]
        path = ROOT / record["local_source"]
        raw = path.read_bytes()
        self.assertEqual(record["acquisition"], "VENDORED_SOURCE_VERIFIED")
        self.assertEqual(record["format"], "txt")
        self.assertEqual(record["indexed_bytes"], 262824)
        self.assertEqual(len(raw), record["indexed_bytes"])
        self.assertEqual(record["sha256"], EXPECTED_SOURCE_SHA256)
        self.assertEqual(record["upstream_git_blob"], EXPECTED_UPSTREAM_BLOB)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), EXPECTED_SOURCE_SHA256)
        self.assertEqual(
            hashlib.sha1(f"blob {len(raw)}\\0".encode("ascii") + raw).hexdigest(),
            EXPECTED_UPSTREAM_BLOB,
        )
        self.assertEqual(verified_local_source(path, record), EXPECTED_SOURCE_SHA256)
        self.assertIn(b"Project Gutenberg", raw)
        self.assertIn(b"Chess Fundamentals", raw)
        return record, raw

    def test_original_real_book_is_readable_via_existing_canonical_txt_adapter(self):
        record, original = self._record_and_bytes()
        results = [
            import_text_book(
                original,
                source_name="gitenberg-capablanca-33870.txt",
                source_format="txt",
                title="Chess Fundamentals",
                author="Jos\\u00e9 Ra\\u00fal Capablanca",
                language="en",
            )
            for _ in range(2)
        ]
        first, after_reopen = results
        self.assertEqual(first.source_sha256, EXPECTED_SOURCE_SHA256)
        self.assertEqual(first.book_key, after_reopen.book_key)
        self.assertEqual(first.document.title, "Chess Fundamentals")
        self.assertGreater(len(first.document.blocks), 20)
        self.assertEqual(first.pgn_games, 0)
        self.assertEqual(first.positions, 0)
        self.assertEqual(
            len(first.document.blocks), len(after_reopen.document.blocks),
            "reopening the same genuine file must not change reading structure",
        )
        self.assertEqual(record["redistribution"], "NOT_CLEARED")

    def test_corruption_and_implicit_network_or_release_refused(self):
        record, original = self._record_and_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            changed = cache / "damaged-original-book.txt"
            changed.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
            with self.assertRaises(LawfulCorpusError):
                verified_local_source(changed, record)
            with patch("acs.lawful_corpus_registry._open_no_redirect") as network:
                with self.assertRaises(LawfulCorpusError):
                    acquire_cc0_source(record, cache)
                network.assert_not_called()
            self.assertEqual(
                qualify_offline_collection((record,), cache, distribution="PUBLIC_RELEASE"),
                (),
                "Gutenberg rights conditions must not be silently treated as CC0",
            )


if __name__ == "__main__":
    unittest.main()
