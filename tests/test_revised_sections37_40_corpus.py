from __future__ import annotations

from copy import deepcopy
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from acs.lawful_corpus_registry import (
    LawfulCorpusError, acquire_cc0_source, load_catalog, verified_local_source,
)


class Response(io.BytesIO):
    def __init__(self, content: bytes, url: str):
        super().__init__(content)
        self.url = url

    def geturl(self) -> str:
        return self.url


class RevisedCorpusContractTests(unittest.TestCase):
    def test_actual_catalog_truth_and_unsupported_families(self):
        records = {entry["id"]: entry for entry in load_catalog()}
        self.assertIn("lichess_standard_rated_2013_01", records)
        lichess = records["lichess_standard_rated_2013_01"]
        self.assertEqual(lichess["sha256"], "aa40b3671fa3cf1072eb182892cd90b0e1e003a4a5943492f64b77e7f3fd1635")
        self.assertEqual(lichess["license"], "CC0")
        self.assertIn("NOT_DOWNLOADED", lichess["acquisition"])
        self.assertIsNone(records["capablanca_chess_fundamentals_txt"]["sha256"])
        cbh = records["chessbase_family_complete_real_samples"]
        self.assertEqual(cbh["acquisition"], "BLOCKED_NO_LAWFUL_COMPLETE_SAMPLE")
        self.assertEqual(cbh["redistribution"], "NOT_CLEARED")

    def _record(self, payload: bytes) -> dict:
        return {
            "id": "licensed_small_fixture", "license": "CC0",
            "redistribution": "permitted", "format": "pgn.zst",
            "acquisition": "PINNED_NOT_DOWNLOADED_IN_THIS_PASS",
            "download_url": "https://database.lichess.org/standard/test.pgn.zst",
            "sha256": hashlib.sha256(payload).hexdigest(), "max_bytes": 4096,
        }

    def test_verified_payload_publishes_once_no_overwrite(self):
        data = b"real-transport-fixture-not-represented-as-real-chess-games"
        record = self._record(data)
        hits = []
        def opener(request, timeout):
            hits.append(request.full_url)
            return Response(data, request.full_url)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = acquire_cc0_source(record, root, opener=opener)
            self.assertEqual(target.read_bytes(), data)
            self.assertEqual(verified_local_source(target, record), record["sha256"])
            self.assertEqual(acquire_cc0_source(record, root, opener=lambda *_a, **_kw: self.fail("unexpected network")), target)
        self.assertEqual(hits, [record["download_url"]])

    def test_unpinned_or_unlicensed_material_never_opens_network(self):
        base = self._record(b"sample")
        for bad in (
            {"license": "UNKNOWN"},
            {"redistribution": "NOT_CLEARED"},
            {"sha256": None},
            {"acquisition": "DISCOVERED_NOT_HASH_VERIFIED"},
            {"download_url": "http://database.lichess.org/a"},
            {"download_url": "https://example.com/a"},
            {"download_url": "https://database.lichess.org/a?token=secret"},
            {"id": "../escape"},
        ):
            with self.subTest(bad=bad):
                record = {**base, **bad}
                with tempfile.TemporaryDirectory() as tmp:
                    with self.assertRaises(LawfulCorpusError):
                        acquire_cc0_source(record, Path(tmp), opener=lambda *_a, **_kw: self.fail("network should not be called"))

    def test_redirect_overlong_and_digest_mismatch_never_publish(self):
        data = b"payload-with-changed-sha"
        record = self._record(data)
        variants = (
            (b"untrusted", record["download_url"]),
            (data * 600, record["download_url"]),
            (data, "https://example.com/malicious"),
        )
        for content, final_url in variants:
            with self.subTest(size=len(content), final_url=final_url):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    with self.assertRaises(LawfulCorpusError):
                        acquire_cc0_source(
                            record, root,
                            opener=lambda *_a, **_kw: Response(content, final_url),
                        )
                    self.assertEqual(list(root.iterdir()), [])

    def test_private_file_symlink_and_checksum_mutation_fail_closed(self):
        record = self._record(b"correct")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "data.pgn.zst"
            path.write_bytes(b"correct")
            self.assertEqual(verified_local_source(path, record), record["sha256"])
            path.write_bytes(b"changed")
            with self.assertRaises(LawfulCorpusError):
                verified_local_source(path, record)
            path.unlink()
            target = root / "target"
            target.write_bytes(b"correct")
            try:
                path.symlink_to(target)
            except (OSError, NotImplementedError):
                return
            with self.assertRaises(LawfulCorpusError):
                verified_local_source(path, record)


if __name__ == "__main__":
    unittest.main()
