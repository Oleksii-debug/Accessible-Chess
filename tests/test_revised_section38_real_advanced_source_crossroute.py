"""Section 38: real Section37 chess files across canonical Library and Books.

This is executable source/readback coverage, not a synthetic ChessBase PASS.
Generated EPUB/DOCX is marked *derived*; independently authored original
third-party EPUB3/DOCX and native PDF are distinct, pending qualifications.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from acs.acsdb import AcsDatabase
from acs.bookdocument import Heading, Position
from acs.chesscore import Board
from acs.library_import_service import LibraryImportService
from acs.library_source_service import LibrarySourceCatalogService
from acs.pgn_roundtrip import parse_pgn_text
from acs.version2_application import BookOpenCancelled, Version2Application
from acs.lawful_corpus_registry import load_catalog
from tools.revised_section37_bilingual_workbook_pack import main as build_user_pack
from tools.revised_section37_release_exclusion import audit_public_archive

ROOT = Path(__file__).resolve().parents[1]


class HighLevelRealMaterial38(unittest.TestCase):
    def test_exact_real_uk_en_zip_byte_lineage_native_books_and_real_pgn_import(self):
        with tempfile.TemporaryDirectory(prefix="section38-real-owner-") as directory:
            root = Path(directory)
            source_dir = root / "shareable"
            distribution = root / "genuine-bilingual-readable.zip"
            with patch("sys.argv", ["mk", "--output-dir", str(source_dir),
                                    "--zip-output", str(distribution)]):
                build_user_pack()
            independent = audit_public_archive(distribution)
            self.assertEqual(independent["result"], "PASS_ONLY_FOR_TESTED_ZIP_BYTES")
            with ZipFile(distribution) as zipfile:
                self.assertIsNone(zipfile.testzip())
                names = set(zipfile.namelist())
                self.assertEqual(len(names), 14)
                self.assertFalse(any(name.endswith(".pdf") for name in names))
                manifest = json.loads(zipfile.read("section37-bilingual-manifest.json"))
                self.assertEqual(len(manifest["generated_files"]), 13)
                self.assertTrue(manifest["original_foreign_EPUB_DOCX_claim"] is False)
                native_books = 0
                for name, row in manifest["generated_files"].items():
                    original = zipfile.read(name)
                    self.assertEqual(hashlib.sha256(original).hexdigest(), row["sha256"])
                    self.assertEqual(len(original), row["bytes"])
                    path = root / name
                    path.write_bytes(original)
                    if path.suffix.lower() in (".epub", ".docx", ".md", ".html", ".txt"):
                        prepared = Version2Application.prepare_book_open(path)
                        self.assertGreater(len(prepared.document.blocks), 20)
                        self.assertTrue(any(isinstance(b, Heading) for b in prepared.document.blocks)
                                        or path.suffix == ".txt")
                        if path.suffix in (".epub", ".md", ".html"):
                            self.assertTrue(any(isinstance(b, Position) for b in prepared.document.blocks))
                        native_books += 1
                    elif path.suffix == ".fen":
                        for original_fen in path.read_text(encoding="utf-8").splitlines():
                            self.assertEqual(Board(original_fen).fen(), original_fen)
                    elif path.suffix == ".pgn":
                        self.assertIn(len(parse_pgn_text(path.read_text(encoding="utf-8"), strict=False)),
                                      (1, 4))
                    else:
                        self.fail("unqualified source type entered owner archive")
                self.assertEqual(native_books, 10)
            sources = {r["id"]: r for r in load_catalog()}
            study = sources["historical_reti_1921_original_bilingual_study_pgn"]
            games = sources["lichess_cc0_high_level_4_original_annotated_games"]
            self.assertEqual(study["acquisition"], "VENDORED_SOURCE_VERIFIED")
            self.assertEqual(games["acquisition"], "VENDORED_SOURCE_VERIFIED")
            with AcsDatabase(root / "cross-38.acsdb") as db:
                service = LibraryImportService(db)
                handles = []
                for item, original in (
                    (study, root / "original-reti-1921-uk-en-study.pgn"),
                    (games, root / "original-lichess-2200-plus-annotated-games.pgn"),
                ):
                    parsed = parse_pgn_text(original.read_text(encoding="utf-8"), strict=False)
                    for position, part in enumerate(parsed):
                        part.source_index = position
                    out = service.import_games(
                        parsed, source_name=original.name,
                        source_format="pgn", source_sha256=item["sha256"])
                    self.assertFalse(out.reused)
                    self.assertEqual(out.game_count, len(parsed))
                    handles.append((out.source_id, out.game_count))
                self.assertEqual(sum(c for _, c in handles), 5)
                db.verify_integrity()
            with AcsDatabase(root / "cross-38.acsdb") as db:
                query = LibrarySourceCatalogService(db)
                self.assertEqual(sum(query.get_source(n).game_count for n, _ in handles), 5)
                db.verify_integrity()

    def test_cancelled_native_book_open_has_no_partial_readable_document(self):
        from tools.revised_section37_bilingual_workbook_pack import (
            make_pack, load_advanced_workbook,
        )
        pack = make_pack(load_advanced_workbook())
        with tempfile.TemporaryDirectory(prefix="section38-cancel-") as directory:
            source = Path(directory) / "actual-uk.epub"
            source.write_bytes(pack["section37-advanced-workbook-uk.epub"])
            times = 0
            def cancel():
                nonlocal times
                times += 1
                return times >= 2
            with self.assertRaises(BookOpenCancelled):
                Version2Application.prepare_book_open(source, cancel_check=cancel)
            accepted = Version2Application.prepare_book_open(source)
            self.assertGreater(len(accepted.document.blocks), 20)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),
                             hashlib.sha256(pack["section37-advanced-workbook-uk.epub"]).hexdigest())


if __name__ == "__main__":
    unittest.main()
