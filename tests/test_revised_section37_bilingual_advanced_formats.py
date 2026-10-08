"""Section 37: real CC0 chess sources -> two languages -> five native format importers.

This is a DERIVED legal interoperability workbook, not false evidence of five
unrelated foreign files, a complete PDF reader, or user-reviewed Windows NVDA.
Canonical chess/Book/Library adapters are reused exclusively.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest
import zipfile
from io import BytesIO
from unittest.mock import patch
import tempfile

from acs.pgn_roundtrip import parse_pgn_text

from acs.bookdocument import Heading, Position
from acs.book_text_import import import_text_book
from acs.book_html_import import import_html_book
from acs.book_epub_import import import_epub_book
from acs.book_docx_import import import_docx_book
from acs.bookreader import BookReader
from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog, verified_local_source
from tools.revised_section37_bilingual_workbook_pack import (
    LANGS, SOURCE, load_advanced_workbook, make_pack, source_receipt,
    render_markdown, render_text, render_html, render_epub3, render_docx,
)

ROOT = Path(__file__).resolve().parents[1]
PRACTICE_16 = ROOT / "tests/real_corpus/advanced_training/lichess_cc0_advanced_puzzles_100_sample.json"
EXTREME_4 = ROOT / "tests/real_corpus/advanced_training/lichess_cc0_extreme_3000_3166_original_puzzles.json"


class BilingualSourceGroundingTests(unittest.TestCase):
    def test_every_lesson_is_real_high_difficulty_CC0_source_and_two_actual_languages(self):
        work = load_advanced_workbook()
        catalog = {item["id"]: item for item in load_catalog()}
        for identity, location in (
            ("lichess_cc0_advanced_16_original_derived", PRACTICE_16),
            ("lichess_cc0_extreme_4_original_derived_puzzles", EXTREME_4),
        ):
            self.assertEqual(verified_local_source(location, catalog[identity]), catalog[identity]["sha256"])
        easy = json.loads(PRACTICE_16.read_text(encoding="utf-8"))["puzzles"]
        hard = json.loads(EXTREME_4.read_text(encoding="utf-8"))["puzzles"]
        positions = {
            row["puzzle_id"]: (
                row["fen_before_opponent_move"],
                row["uci_moves_with_opponent_first"].split(),
                row["rating"],
            )
            for row in easy
        }
        positions.update({
            row["puzzle_id"]: (
                row["fen_before_opponent_move"],
                row["uci_moves_opponent_first"].split(),
                row["puzzle_rating"],
            )
            for row in hard
        })
        self.assertEqual(len(work["lessons"]), 12)
        self.assertEqual(work["language_codes"], ["uk", "en"])
        self.assertEqual(work["level_floor_lichess_puzzle_rating"], 2200)
        self.assertEqual(len({x["lesson_id"] for x in work["lessons"]}), 12)
        self.assertEqual(
            {lesson["category"] for lesson in work["lessons"]},
            {"calculation", "combination", "opening", "middlegame", "endgame", "extreme"},
        )
        for lesson in work["lessons"]:
            with self.subTest(lesson=lesson["lesson_id"]):
                self.assertIn(lesson["original_puzzle_id"], positions)
                fen, moves, rating = positions[lesson["original_puzzle_id"]]
                self.assertEqual(lesson["fen_before_opponent_move"], fen)
                self.assertEqual(lesson["opponent_previous_move_uci"], moves[0])
                self.assertEqual(lesson["solution_after_opponent_uci"], moves[1:])
                self.assertEqual(lesson["rating_lichess_puzzle"], rating)
                self.assertGreaterEqual(rating, 2200)
                self.assertFalse(lesson["composer_study"])
                for lang in LANGS:
                    self.assertGreater(len(lesson[lang]["prompt"]), 45)

    def test_generated_assets_are_distinct_real_uk_en_text_not_dummy_identical_files(self):
        work = load_advanced_workbook()
        package = make_pack(work)
        self.assertEqual(len(package), 10)
        for extension in ("md", "txt", "html", "docx", "epub"):
            uk = package[f"section37-advanced-workbook-uk.{extension}"]
            en = package[f"section37-advanced-workbook-en.{extension}"]
            self.assertGreater(len(uk), 250)
            self.assertGreater(len(en), 250)
            self.assertNotEqual(hashlib.sha256(uk).digest(), hashlib.sha256(en).digest())
        receipt = source_receipt(work, package)
        self.assertEqual(receipt["lesson_count_per_language"], 12)
        self.assertEqual(receipt["format_family_count"], 5)
        self.assertFalse(receipt["external_unlicensed_material_included"])
        self.assertFalse(receipt["section37_terminal_done"])
        self.assertEqual(len(receipt["generated_files"]), 10)

    def test_canonical_txt_and_markdown_book_readback_are_bilingual_and_chess_semantic(self):
        work = load_advanced_workbook()
        for lang in LANGS:
            with self.subTest(language=lang):
                result = import_text_book(
                    render_markdown(work, lang),
                    source_name="Section37 bilingual hard lessons " + lang,
                    source_format="markdown",
                    language=lang,
                )
                doc = result.document
                self.assertGreaterEqual(len(doc.blocks), 30)
                self.assertGreaterEqual(result.positions, 10)
                self.assertTrue(any(isinstance(b, Position) for b in doc.blocks))
                self.assertTrue(any(isinstance(b, Heading) for b in doc.blocks))
                reader = BookReader(doc)
                self.assertIsNotNone(reader.next_heading())
                self.assertIsNotNone(reader.next_position())
                self.assertIsNotNone(reader.location().position_fen)
                textonly = import_text_book(
                    render_text(work, lang),
                    source_name="Section37 readable plain text " + lang,
                    source_format="txt",
                    language=lang,
                )
                self.assertGreater(len(textonly.document.blocks), 20)
                self.assertEqual(textonly.positions, 0)  # TXT prose is not a secret chess parser.
                self.assertIn(work["title"][lang], render_text(work, lang).decode("utf-8"))

    def test_canonical_html_and_epub3_readback_share_semantic_positions(self):
        work = load_advanced_workbook()
        for lang in LANGS:
            with self.subTest(language=lang):
                html = render_html(work, lang)
                result = import_html_book(
                    html, source_name="Section37 original HTML " + lang, language=lang,
                )
                self.assertGreater(len(result.document.blocks), 20)
                self.assertTrue(any(isinstance(b, Position) for b in result.document.blocks))
                self.assertIsNotNone(BookReader(result.document).next_position())
                epub = render_epub3(work, lang)
                with zipfile.ZipFile(BytesIO(epub)) as z:
                    self.assertEqual(z.namelist()[0], "mimetype")
                    self.assertEqual(z.read("mimetype"), b"application/epub+zip")
                    self.assertIn(lang.encode("utf-8"), z.read("OEBPS/book.opf"))
                epub_read = import_epub_book(
                    epub, source_name="Section37 original EPUB3 " + lang, language=lang,
                )
                self.assertGreater(len(epub_read.document.blocks), 20)
                self.assertTrue(any(isinstance(b, Position) for b in epub_read.document.blocks))
                self.assertIsNotNone(BookReader(epub_read.document).next_position())

    def test_canonical_docx_readback_preserves_bilingual_chess_text_without_fen_inference(self):
        work = load_advanced_workbook()
        for lang in LANGS:
            with self.subTest(language=lang):
                docx = render_docx(work, lang)
                with zipfile.ZipFile(BytesIO(docx)) as z:
                    self.assertIn("word/document.xml", z.namelist())
                    self.assertIn(work["title"][lang], z.read("word/document.xml").decode("utf-8"))
                imported = import_docx_book(
                    docx, source_name="Section37 original advanced DOCX " + lang,
                )
                self.assertGreater(len(imported.document.blocks), 20)
                self.assertTrue(any(isinstance(b, Heading) for b in imported.document.blocks))
                self.assertFalse(any(isinstance(b, Position) for b in imported.document.blocks))
                self.assertIsNotNone(BookReader(imported.document).next_heading())

    def test_actual_user_pack_contains_two_original_licensed_pgn_sources_and_real_fen_file(self):
        from tools.revised_section37_bilingual_workbook_pack import main
        with tempfile.TemporaryDirectory(prefix="section37-real-user-book-pack-") as tmp:
            out = Path(tmp) / "share-to-testers"
            with patch("sys.argv", ["section37_bilingual_pack", "--output-dir", str(out)]):
                main()
            items = sorted(p for p in out.iterdir() if p.is_file())
            self.assertEqual(len(items), 14)  # ten native books + two real PGNs + FEN + receipt
            report = json.loads((out / "section37-bilingual-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(report["generated_files"]), 13)
            self.assertEqual(report["format_family_count"], 5)
            self.assertFalse(report["section37_terminal_done"])
            for stem, expected in (
                ("original-reti-1921-uk-en-study.pgn", 1),
                ("original-lichess-2200-plus-annotated-games.pgn", 4),
            ):
                with self.subTest(real_original=stem):
                    content = (out / stem).read_bytes()
                    self.assertEqual(hashlib.sha256(content).hexdigest(),
                                     report["generated_files"][stem]["sha256"])
                    self.assertEqual(len(parse_pgn_text(content.decode("utf-8"), strict=False)), expected)
            raw_fens = (out / "original-advanced-before-opponent-move.fen").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(raw_fens), 12)
            from acs.chesscore import Board
            for fen in raw_fens:
                self.assertEqual(Board(fen).fen(), fen)

    def test_corrupted_fen_beginner_rating_lost_language_and_unrelated_study_are_denied(self):
        work = load_advanced_workbook()
        cases = [
            lambda d: d["lessons"][0].update(rating_lichess_puzzle=800),
            lambda d: d["lessons"][0].update(fen_before_opponent_move="invalid"),
            lambda d: d["lessons"][0].update(composer_study=True),
            lambda d: d.update(language_codes=["en"]),
            lambda d: d["lessons"][0]["uk"].update(prompt=""),
        ]
        for index, mutate in enumerate(cases):
            with self.subTest(tamper=index):
                data = json.loads(json.dumps(work))
                mutate(data)
                # Validate through the same actual loader on a temporary local file.
                import tempfile
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "invalid_workbook.json"
                    path.write_text(json.dumps(data), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        load_advanced_workbook(path)


if __name__ == "__main__":
    unittest.main()
