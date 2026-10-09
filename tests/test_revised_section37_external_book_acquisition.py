"""Section 37 authentic Gutenberg checkout/source verification and adversarial boundaries."""
from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog
from tools.revised_section37_external_book_acquisition import (
    _git_blob, verify_external_books, verify_original_book, verify_original_cc0_pdf,
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


LICENSE_BYTES = b"THE FULL PROJECT GUTENBERG LICENSE\nSynthetic unit-test license fixture"


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
        "external_license_checkout_path": "original/LICENSE",
        "external_license_git_blob": _git_blob(LICENSE_BYTES),
        "external_license_sha256": hashlib.sha256(LICENSE_BYTES).hexdigest(),
        "external_license_indexed_bytes": len(LICENSE_BYTES),
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
                self.assertEqual(source["external_license_git_blob"], "8d062dda262bcdc42d45b861bd796117feb6d0fe")
                self.assertEqual(source["external_license_indexed_bytes"], 17504)
                self.assertEqual(source["external_license_sha256"], "1e301e03fb28addf6ad03d42b1429e87679013d1ee7e141c7c968fbef0ad961d")

    def test_section38_three_genuine_external_chess_books_semantic_readback(self):
        """Original checked-out books -> canonical semantic reader and restart.

        This runs in the existing source-only GitHub Actions job, which checks
        out the exact independent upstream Git object. Test-only source bytes
        and licenses are never copied into a distribution artifact.
        """
        import os

        from acs.book_text_import import import_text_book
        from acs.bookreader import BookReader
        from acs.lawful_corpus_registry import read_verified_source_snapshot

        source_root = os.environ.get("ACS_37_GITENBERG_ROOT")
        if not source_root:
            self.skipTest("genuine upstream books are not checked out on this host")
        root = Path(source_root)
        catalog = {entry["id"]: entry for entry in load_catalog()}

        for source_id in (
            "gutenberg_blue_book_chess_staunton",
            "gutenberg_chess_history_bird_original_txt",
            "gutenberg_checkmates_three_fishburne_original_txt",
        ):
            with self.subTest(source_id=source_id):
                record = catalog[source_id]
                self.assertEqual(record["format"], "txt")
                self.assertEqual(record["redistribution"], "NOT_CLEARED")
                verified = verify_original_book(record, root)
                self.assertEqual(verified["sha256"], record["sha256"])
                self.assertFalse(verified["original_bytes_packaged"])
                original = read_verified_source_snapshot(
                    root / record["external_checkout_path"], record
                )
                self.assertEqual(hashlib.sha256(original).hexdigest(), record["sha256"])
                book = import_text_book(
                    original,
                    source_name=Path(record["external_checkout_path"]).name,
                    source_format="txt",
                    title=record["title"],
                    author=record.get("author") or None,
                    language="en",
                )
                self.assertEqual(book.source_sha256, record["sha256"])
                self.assertGreater(len(book.document.blocks), 10)
                reader = BookReader(book.document)
                original_location = reader.location()
                destination = reader.next_block()
                self.assertEqual(destination.index, original_location.index + 1)
                reader.save_return_point("original-book-checkpoint")
                checkpoint = reader.snapshot()

                reopened = import_text_book(
                    original,
                    source_name=Path(record["external_checkout_path"]).name,
                    source_format="txt",
                    title=record["title"],
                    author=record.get("author") or None,
                    language="en",
                )
                self.assertEqual(reopened.book_key, book.book_key)
                restarted = BookReader.restore_snapshot(reopened.document, checkpoint)
                self.assertEqual(restarted.location(), destination)
                restarted.next_block()
                self.assertEqual(
                    restarted.restore_return_point("original-book-checkpoint"),
                    destination,
                )

    def test_original_source_readback_never_copies_or_promotes_rights(self):
        data = b"an authentic source of bounded bytes for negative test only"
        record = fake_record(data)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "original").mkdir()
            (root / record["external_checkout_path"]).write_bytes(data)
            (root / "original/LICENSE").write_bytes(LICENSE_BYTES)
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
            (root / "original/LICENSE").write_bytes(LICENSE_BYTES)
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
                {"external_license_git_blob": "0" * 40},
                {"external_license_sha256": "0" * 64},
                {"external_license_indexed_bytes": 1},
                {"external_license_checkout_path": "../outside"},
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

    def test_verification_never_uses_unbounded_read_bytes(self):
        from unittest.mock import patch

        data = b"original authorized source"
        record = fake_record(data)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "original").mkdir()
            (root / "original/original.txt").write_bytes(data)
            (root / "original/LICENSE").write_bytes(LICENSE_BYTES)
            # Both the book AND its legal-attribution fixture must be read
            # through the bounded same-descriptor path, never Path.read_bytes.
            with patch.object(Path, "read_bytes", side_effect=AssertionError("unbounded source read")):
                receipt = verify_original_book(record, root)
            self.assertEqual(receipt["original_bytes"], len(data))
            self.assertEqual(receipt["license_bytes"], len(LICENSE_BYTES))

    def test_post_verification_source_growth_is_denied(self):
        from unittest.mock import patch

        data = b"original verified source"
        record = fake_record(data)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "original").mkdir()
            source = root / "original/original.txt"
            source.write_bytes(data)
            (root / "original/LICENSE").write_bytes(LICENSE_BYTES)

            def grow_after_verifier(_path, _record):
                source.write_bytes(data * 100)
                return record["sha256"]

            with patch(
                "tools.revised_section37_external_book_acquisition.verified_local_source",
                side_effect=grow_after_verifier,
            ):
                with self.assertRaises(LawfulCorpusError):
                    verify_original_book(record, root)

    def test_license_snapshot_is_resource_bounded(self):
        from tools.revised_section37_external_book_acquisition import _bounded_direct_snapshot

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "LICENSE"
            path.write_bytes(b"THE FULL PROJECT GUTENBERG LICENSE" + b"A" * 5000)
            with self.assertRaises(LawfulCorpusError):
                _bounded_direct_snapshot(path, 64)
            with self.assertRaises(LawfulCorpusError):
                _bounded_direct_snapshot(path, True)
            with self.assertRaises(LawfulCorpusError):
                _bounded_direct_snapshot(path, 0)

    def test_missing_proprietary_fixtures_stay_missing_and_never_trigger_download(self):
        from unittest.mock import patch
        from acs.lawful_corpus_registry import acquire_cc0_source, _https_url

        records = {item["id"]: item for item in load_catalog()}
        for identity, family in (
            ("chessbase_official_cbf_cbi_format_external_gap", "cbf+cbi"),
            ("chessbase_official_cbone_format_external_gap", "cbone"),
            ("chessbase_official_2cbh_format_external_gap", "2cbh"),
        ):
            with self.subTest(source=identity):
                source = records[identity]
                self.assertEqual(source["format"], family)
                self.assertEqual(source["acquisition"], "BLOCKED_NO_LAWFUL_COMPLETE_SAMPLE")
                self.assertEqual(source["redistribution"], "NOT_CLEARED")
                self.assertIsNone(source["sha256"])
                self.assertEqual(source["max_bytes"], 0)
                self.assertIsNone(source["download_url"])
                self.assertEqual(
                    _https_url(source["source_page"], source_page=True),
                    source["source_page"],
                )
                with self.assertRaises(LawfulCorpusError):
                    _https_url(source["source_page"])
                with tempfile.TemporaryDirectory() as temp:
                    with patch("acs.lawful_corpus_registry._open_no_redirect") as network:
                        with self.assertRaises(LawfulCorpusError):
                            acquire_cc0_source(source, Path(temp))
                        network.assert_not_called()

    def test_original_gpl_markdown_source_is_exact_and_not_publicly_bundled(self):
        record = next(
            item for item in load_catalog()
            if item["id"] == "original_gpl_chastity_chess_chapters_markdown"
        )
        self.assertEqual(record["format"], "md")
        self.assertEqual(record["indexed_bytes"], 96821)
        self.assertEqual(record["sha256"], "a2642266dd0068739631de817732d999f213bf297c343a0206a4795068c33928")
        self.assertEqual(record["upstream_git_blob"], "67839e7768b2df1e54ce7136f010f93883bdf170")
        self.assertEqual(record["upstream_commit"], "69f3b151c8c6230ff1ebb252a24eb09a9e015f60")
        self.assertEqual(record["external_license_git_blob"], "f288702d2fa16d3cdf0035b15a9fcbc552cd88e7")
        self.assertEqual(record["external_license_indexed_bytes"], 35149)
        self.assertEqual(record["external_license_sha256"], "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986")
        self.assertEqual(record["external_book_rights_notice_git_blob"], "1b729a364e62d58718b0fa5dde9f07c0ffe49242")
        self.assertIn("CC BY-NC-SA", record["license"])
        self.assertEqual(record["redistribution"], "NOT_CLEARED")
        self.assertEqual(record["public_release"], "EXCLUDED")

    def test_gpl_markdown_original_source_and_license_negative_readback(self):
        source = b"# Real chapter structure for isolated security fixture\\n## Introduction\\n"
        license_data = b"                    GNU GENERAL PUBLIC LICENSE\\nVersion 3\\n"
        rights_notice = b"Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International\\n"
        record = {
            **fake_record(source),
            "format": "md",
            "external_checkout_path": "markdown/book.md",
            "external_license_checkout_path": "markdown/LICENSE",
            "external_license_git_blob": _git_blob(license_data),
            "external_license_sha256": hashlib.sha256(license_data).hexdigest(),
            "external_license_indexed_bytes": len(license_data),
            "external_book_rights_notice_path": "markdown/README.md",
            "external_book_rights_notice_git_blob": _git_blob(rights_notice),
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "markdown").mkdir()
            book = root / "markdown/book.md"
            license_file = root / "markdown/LICENSE"
            book.write_bytes(source)
            license_file.write_bytes(license_data)
            rights_file = root / "markdown/README.md"
            rights_file.write_bytes(rights_notice)
            result = verify_original_book(record, root)
            self.assertEqual(result["source_format"], "md")
            self.assertEqual(result["book_rights_notice"]["source_declared_book_license"], "CC-BY-NC-SA-4.0")
            self.assertEqual(result["sha256"], hashlib.sha256(source).hexdigest())
            self.assertEqual(result["public_release"], "EXCLUDED")
            self.assertFalse(result["original_bytes_packaged"])
            license_file.write_bytes(b"THE FULL PROJECT GUTENBERG LICENSE\\nother rights")
            with self.assertRaises(LawfulCorpusError):
                verify_original_book(record, root)
            license_file.write_bytes(license_data)
            rights_file.write_bytes(b"Creative Commons BY License unrelated")
            with self.assertRaises(LawfulCorpusError):
                verify_original_book(record, root)
            rights_file.write_bytes(rights_notice)
            book.write_bytes(source + b"tampered")
            with self.assertRaises(LawfulCorpusError):
                verify_original_book(record, root)

    def test_real_cc0_pdf_record_is_pinned_but_not_falsely_qualified(self):
        record = next(
            item for item in load_catalog()
            if item["id"] == "cc0_capablanca_open_pdf_original_source"
        )
        self.assertEqual(record["upstream_git_blob"], "eab7c13bdd5a21a33fa2bef863781e4c40794c2c")
        self.assertEqual(record["external_license_git_blob"], "0e259d42c996742e9e3cba14c677129b2c1b6311")
        self.assertEqual(record["acquisition"], "DISCOVERED_NOT_HASH_VERIFIED")
        self.assertIsNone(record["sha256"])
        self.assertEqual(record["public_release"], "EXCLUDED_PENDING_QUALIFICATION")

    def test_ephemeral_pdf_binary_and_cc0_license_readback_fail_closed(self):
        original = b"%PDF-1.4\\nsource-only fixture\\n%%EOF\\n"
        license_data = b"Creative Commons Legal Code\\nCC0 1.0 Universal\\n"
        record = {
            "id": "cc0_capablanca_open_pdf_original_source",
            "format": "pdf",
            "acquisition": "DISCOVERED_NOT_HASH_VERIFIED",
            "sha256": None,
            "test_access": "EXTERNAL_CC0_PDF_SOURCE_ONLY",
            "public_release": "EXCLUDED_PENDING_QUALIFICATION",
            "license": "CC0-1.0",
            "redistribution": "permitted under source CC0",
            "max_bytes": len(original),
            "upstream_git_blob": _git_blob(original),
            "external_license_git_blob": _git_blob(license_data),
            "external_checkout_path": "pdf/book.pdf",
            "external_license_checkout_path": "pdf/LICENSE",
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "pdf").mkdir()
            source = root / "pdf/book.pdf"
            licence = root / "pdf/LICENSE"
            source.write_bytes(original)
            licence.write_bytes(license_data)
            before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
            actual = verify_original_cc0_pdf(record, root)
            self.assertEqual(actual["source_format"], "pdf")
            self.assertEqual(actual["sha256"], hashlib.sha256(original).hexdigest())
            self.assertEqual(actual["license_sha256"], hashlib.sha256(license_data).hexdigest())
            self.assertFalse(actual["original_bytes_packaged"])
            self.assertEqual(actual["public_release"], "EXCLUDED_PENDING_QUALIFICATION")
            self.assertEqual(
                sorted(p.relative_to(root).as_posix() for p in root.rglob("*")), before,
            )
            self.assertEqual(verify_external_books((record,), root)[0]["source_format"], "pdf")
            for changed in (
                {"upstream_git_blob": "0" * 40},
                {"external_license_git_blob": "0" * 40},
                {"public_release": "INCLUDED"},
                {"redistribution": "NOT_CLEARED"},
                {"test_access": "PUBLIC_RELEASE"},
                {"max_bytes": True},
                {"max_bytes": 1},
                {"external_checkout_path": "../outside"},
            ):
                with self.subTest(changed=changed):
                    with self.assertRaises(LawfulCorpusError):
                        verify_original_cc0_pdf({**record, **changed}, root)
            source.write_bytes(b"not a PDF at all")
            with self.assertRaises(LawfulCorpusError):
                verify_original_cc0_pdf(record, root)
            source.write_bytes(original)
            licence.write_bytes(b"an unrelated license")
            with self.assertRaises(LawfulCorpusError):
                verify_original_cc0_pdf(record, root)

    def test_malformed_batch_or_symlinked_checkout_is_denied(self):
        data = b"safe test source"
        original = fake_record(data)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "original").mkdir()
            (root / "original/original.txt").write_bytes(data)
            (root / "original/LICENSE").write_bytes(LICENSE_BYTES)
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



class CatalogRecentSourceTruthTests(unittest.TestCase):
    """Regressions for source metadata added after the preserved test implementation."""

    def test_recent_sources_remain_explicitly_unacquired(self):
        sources = {record["id"]: record for record in load_catalog()}
        ids = (
            "capablanca_chess_fundamentals_epub3",
            "gutenberg_chess_strategy_lasker",
            "gutenberg_chess_and_checkers_lasker",
            "morphy_world_ch_2cbh_complete_source_candidate",
        )
        for identity in ids:
            with self.subTest(source=identity):
                source = sources[identity]
                self.assertIsNone(source["sha256"])
                self.assertEqual(source["redistribution"], "NOT_CLEARED")
                self.assertNotEqual(source.get("acquisition"), "VENDORED_SOURCE_VERIFIED")

    def test_incomplete_sources_cannot_claim_a_pinned_digest(self):
        import json

        from acs.lawful_corpus_registry import CATALOG_FILE

        catalog = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
        for identity in (
            "capablanca_chess_fundamentals_epub3",
            "morphy_world_ch_2cbh_complete_source_candidate",
        ):
            with self.subTest(source=identity):
                changed = json.loads(json.dumps(catalog))
                source = next(x for x in changed["sources"] if x["id"] == identity)
                source["sha256"] = "a" * 64
                with tempfile.TemporaryDirectory() as temp:
                    path = Path(temp) / "sources.json"
                    path.write_text(json.dumps(changed), encoding="utf-8")
                    with self.assertRaises(LawfulCorpusError):
                        load_catalog(path)

    def test_catalog_only_source_hosts_cannot_be_auto_downloaded(self):
        from acs.lawful_corpus_registry import _https_url

        catalog = {record["id"]: record for record in load_catalog()}
        for identity in (
            "lichess_openings_original_eco_a_tsv",
            "chessmail_tim_harding_macdonnell_wisker_1874_cbv",
        ):
            with self.subTest(source=identity):
                url = catalog[identity]["download_url"]
                self.assertEqual(_https_url(url, catalog_metadata=True), url)
                with self.assertRaises(LawfulCorpusError):
                    _https_url(url)


if __name__ == "__main__":
    unittest.main()
