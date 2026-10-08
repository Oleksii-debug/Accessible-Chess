"""Section 37 authentic Gutenberg checkout/source verification and adversarial boundaries."""
from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog
from tools.revised_section37_external_book_acquisition import (
    _git_blob, verify_external_books, verify_original_book,
)


BOOK_IDS = {
    "gutenberg_blue_book_chess_staunton": (
        "d946777f0eaee2b5f8f7a73afb9c1dd104eb4142",
        "aa35876c550a5c84d770a9daf2964a2a859c56cae9325ee6e9f261c307cd7b98",
        679686,
    ),
    "gutenberg_chess_history_bird_original_txt": (
        "fe18ddf36538952c95c62052b5d05464ca64abe7",
        "fb4b5ad969566c4ae9c974f7fa606ea7bbfb3aa2697142d05f8bf83d02365149",
        404528,
    ),
    "gutenberg_checkmates_three_fishburne_original_txt": (
        "ab6af427f4de27d8e98c0cc25e025b1984cc60cb",
        "f4d8c085d5450013876bfe6d214ba85107afebb37fe6e5fc2bf9c3b58b2c75fb",
        38389,
    ),
}


def fake_record(raw: bytes) -> dict:
    return {
        "id": "local_real_source",
        "title": "test-only bounded source",
        "author": "Test",
        "source_page": "https://www.gutenberg.org/ebooks/4902",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "indexed_bytes": len(raw), "max_bytes": len(raw),
        "upstream_git_blob": _git_blob(raw),
        "format": "txt",
        "redistribution": "NOT_CLEARED",
        "acquisition": "PINNED_NOT_DOWNLOADED_IN_THIS_PASS",
        "test_access": "EXTERNAL_EPHEMERAL_ONLY",
        "public_release": "EXCLUDED",
        "external_checkout_path": "original/original.txt",
    }


class ExternalOriginalBookTests(unittest.TestCase):
    def test_real_source_catalog_references_are_exact_not_false_downloads(self):
        originals = {r["id"]: r for r in load_catalog()}
        self.assertEqual(_git_blob(b"test"), hashlib.sha1(b"blob 4\0test").hexdigest())
        for identity, (git_sha, sha256, length) in BOOK_IDS.items():
            with self.subTest(source=identity):
                source = originals[identity]
                self.assertEqual(source["upstream_git_blob"], git_sha)
                self.assertEqual(source["sha256"], sha256)
                self.assertEqual(source["indexed_bytes"], length)
                self.assertEqual(source["format"], "txt")
                self.assertEqual(source["redistribution"], "NOT_CLEARED")
                self.assertEqual(source["public_release"], "EXCLUDED")
                self.assertEqual(source["test_access"], "EXTERNAL_EPHEMERAL_ONLY")
                self.assertEqual(source["acquisition"], "PINNED_NOT_DOWNLOADED_IN_THIS_PASS")
                self.assertIn("gutenberg.org/ebooks/", source["source_page"])

    def test_original_source_readback_never_copies_or_promotes_rights(self):
        data = b"an authentic source of bounded bytes for negative test only"
        record = fake_record(data)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "original").mkdir()
            (root / record["external_checkout_path"]).write_bytes(data)
            before = sorted(str(p.relative_to(root)) for p in root.rglob("*"))
            result = verify_original_book(record, root)
            self.assertEqual(result["sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(result["original_bytes"], len(data))
            self.assertEqual(result["redistribution"], "NOT_CLEARED")
            self.assertEqual(result["public_release"], "EXCLUDED")
            self.assertFalse(result["original_bytes_packaged"])
            self.assertFalse(result["imported_to_library"])
            self.assertEqual(
                sorted(str(p.relative_to(root)) for p in root.rglob("*")), before
            )
            self.assertEqual(
                verify_external_books((record,), root)[0]["source_id"], record["id"]
            )

    def test_identity_provenance_size_and_distribution_spoofs_are_denied(self):
        data = b"book source immutable"
        record = fake_record(data)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "original").mkdir()
            path = root / "original/original.txt"
            path.write_bytes(data)
            for bad in (
                {"sha256": "0" * 64},
                {"upstream_git_blob": "0" * 40},
                {"indexed_bytes": 1},
                {"indexed_bytes": True},
                {"test_access": "PUBLIC_RELEASE"},
                {"public_release": "INCLUDED"},
                {"redistribution": "permitted"},
                {"acquisition": "SOURCE_PAGE_ONLY"},
                {"format": "pdf"},
                {"id": "../other"},
                {"external_checkout_path": "../escape.txt"},
                {"external_checkout_path": "/absolute/path"},
                {"external_checkout_path": "other/absent.txt"},
                {"external_checkout_path": "original/../outside.txt"},
                {"external_checkout_path": "original\\original.txt"},
            ):
                with self.subTest(bad=bad):
                    with self.assertRaises(LawfulCorpusError):
                        verify_original_book({**record, **bad}, root)
            path.write_bytes(data[:-1] + b"X")
            with self.assertRaises(LawfulCorpusError):
                verify_original_book(record, root)

    def test_malformed_batch_or_symlinked_checkout_is_denied(self):
        data = b"safe test source"
        original = fake_record(data)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "original").mkdir()
            (root / "original/original.txt").write_bytes(data)
            with self.assertRaises(LawfulCorpusError):
                verify_external_books((original, original), root)
            with self.assertRaises(LawfulCorpusError):
                verify_external_books((), root)
            with self.assertRaises(LawfulCorpusError):
                verify_external_books(tuple([original] * 33), root)
            try:
                (root / "indirect").symlink_to(root / "original", target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable on test host")
            with self.assertRaises(LawfulCorpusError):
                verify_original_book(
                    {**original, "external_checkout_path": "indirect/original.txt"},
                    root,
                )


if __name__ == "__main__":
    unittest.main()
