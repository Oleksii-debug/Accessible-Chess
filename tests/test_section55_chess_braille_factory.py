from __future__ import annotations

"""Synthetic boundary tests only; not physical embossing or table certification."""

import unittest
from xml.etree import ElementTree as ET

from acs.bookdocument import BookDocument, Heading, Paragraph, Position
from acs.chess_braille_factory import (
    BrailleFactoryError,
    BrailleProfile,
    LiblouisTranslator,
    prepare_chess_book_pef,
)

TABLE_SHA = "a" * 64


class SyntheticSixDotTranslator:
    """Test double; deliberately NOT an actual language/Braille translator."""
    table_id = "fixture-only"
    table_version = "fixture-1"
    table_sha256 = TABLE_SHA

    def translate(self, source: str) -> str:
        return "".join("\u2800" if char == " " else "\u2801" for char in source)


def profile(**overrides: object) -> BrailleProfile:
    params = dict(
        language="en", table_id="fixture-only", table_version="fixture-1",
        table_sha256=TABLE_SHA, device_model="SYNTHETIC-NOT-QUALIFIED",
        cells_per_line=24, lines_per_page=10,
    )
    params.update(overrides)
    return BrailleProfile(**params)


def book() -> BookDocument:
    return BookDocument(title="Chess",
                        blocks=[Heading(text="First"), Paragraph(text="Chess book text")])


def prepare(document=None, translator=None, **profile_overrides):
    return prepare_chess_book_pef(
        document if document is not None else book(), profile(**profile_overrides),
        translator if translator is not None else SyntheticSixDotTranslator(),
        rights_confirmed=True, rights_basis="Synthetic author-owned test book",
    )


class TestSection55ProvisionalPEF(unittest.TestCase):
    def test_pef_structural_roundtrip_manifest_and_explicit_not_ready(self) -> None:
        produced = prepare()
        root = ET.fromstring(produced.pef)
        ns = {"pef": "http://www.daisy.org/ns/2008/pef"}
        pages = root.findall(".//pef:page", ns)
        self.assertTrue(pages)
        self.assertEqual(len(pages), produced.manifest["pages"])
        self.assertEqual(produced.manifest["status"], "UNVERIFIED_REQUIRES_DECISION")
        self.assertIs(produced.manifest["print_ready"], False)
        self.assertIs(produced.manifest["device_verified"], False)
        self.assertEqual(len(produced.manifest["output_pef_sha256"]), 64)
        self.assertTrue(produced.warnings)

    def test_reproducible_snapshot(self) -> None:
        first, second = prepare(), prepare()
        self.assertEqual(first.pef, second.pef)
        self.assertEqual(first.manifest, second.manifest)

    def test_source_must_be_rights_authorized(self) -> None:
        with self.assertRaises(BrailleFactoryError):
            prepare_chess_book_pef(
                book(), profile(), SyntheticSixDotTranslator(),
                rights_confirmed=False, rights_basis="unlicensed",
            )
        with self.assertRaises(BrailleFactoryError):
            prepare_chess_book_pef(
                book(), profile(), SyntheticSixDotTranslator(),
                rights_confirmed=True, rights_basis="",
            )

    def test_bad_table_pin_fails_before_translation(self) -> None:
        with self.assertRaises(BrailleFactoryError):
            prepare(table_sha256="b" * 64)
        with self.assertRaises(BrailleFactoryError):
            profile(table_sha256="not-a-digest")

    def test_unsupported_cell_width_is_rejected(self) -> None:
        for bad in (0, 8, True):
            with self.subTest(dots=bad), self.assertRaises(BrailleFactoryError):
                profile(dots=bad)
        with self.assertRaises(BrailleFactoryError):
            profile(cells_per_line=200)

    def test_translator_cannot_emit_plaintext_or_eight_dot(self) -> None:
        class Invalid(SyntheticSixDotTranslator):
            def translate(self, source: str) -> str:
                return "English"

        class EightDot(SyntheticSixDotTranslator):
            def translate(self, source: str) -> str:
                return "\u28ff"

        for fake in (Invalid(), EightDot()):
            with self.subTest(fake=type(fake).__name__):
                with self.assertRaises(BrailleFactoryError):
                    prepare(translator=fake)

    def test_overlong_unbreakable_word_fails_closed(self) -> None:
        with self.assertRaises(BrailleFactoryError):
            prepare(BookDocument(title="Chess", blocks=[Paragraph(text="X" * 100)]))

    def test_book_structural_warning_not_silently_published(self) -> None:
        with self.assertRaises(BrailleFactoryError):
            prepare(BookDocument(title="Chess", blocks=[Paragraph(text="Text")],
                                 warnings=["Unproven diagram"]))

    def test_position_uses_only_canonical_board_fen(self) -> None:
        document = BookDocument(
            title="Chess", blocks=[
                Position(fen="4k3/8/8/8/8/8/8/4K3 w - - 0 1")
            ])
        result = prepare(document)
        self.assertTrue(result.pef)
        self.assertIs(result.manifest["print_ready"], False)

    def test_piece_inventory_is_derived_from_canonical_board(self) -> None:
        from acs.chess_braille_factory import _canonical_lines
        example = BookDocument(
            title="Chess",
            blocks=[Position(fen="4k3/8/8/8/8/8/8/4K3 b - - 0 1")],
        )
        segments, source_digest = _canonical_lines(example)
        self.assertIn("Side to move: Black", segments)
        self.assertIn("Piece K on e1", segments)
        self.assertIn("Piece k on e8", segments)
        self.assertEqual(len(source_digest), 64)

    def test_xml_invalid_title_and_language_fail_closed(self) -> None:
        invalid_title = BookDocument(title="Chess\u0000",
                                     blocks=[Paragraph(text="Text")])
        with self.assertRaises(BrailleFactoryError):
            prepare(invalid_title)
        with self.assertRaises(BrailleFactoryError):
            prepare(language="en\u0000")

    def test_detached_game_and_unresolvable_pgn_cannot_pass(self) -> None:
        from acs.bookdocument import Game
        document = BookDocument(title="Chess", blocks=[Game(game_id=123)])
        with self.assertRaises(BrailleFactoryError):
            prepare(document)

    def test_optional_formal_adapter_does_not_claim_installed_support(self) -> None:
        with self.assertRaises(BrailleFactoryError):
            LiblouisTranslator(table_id="en-ueb-g1.ctb", table_version="",
                               table_bytes=b"data")
        adaptor = LiblouisTranslator(
            table_id="en-ueb-g1.ctb", table_version="test",
            table_bytes=b"not-the-real-table",
        )
        self.assertEqual(len(adaptor.table_sha256), 64)


    def test_lossy_leading_and_double_braille_blanks_fail_closed(self) -> None:
        class LeadingBlank(SyntheticSixDotTranslator):
            def translate(self, source: str) -> str:
                return "\u2800\u2801"

        class DoubleBlank(SyntheticSixDotTranslator):
            def translate(self, source: str) -> str:
                return "\u2801\u2800\u2800\u2801"

        for fake in (LeadingBlank(), DoubleBlank()):
            with self.subTest(fake=type(fake).__name__):
                with self.assertRaises(BrailleFactoryError):
                    prepare(translator=fake)

    def test_direct_cli_help_is_available_without_optional_liblouis(self) -> None:
        from pathlib import Path
        import subprocess
        import sys
        cli = Path(__file__).resolve().parents[1] / "tools" / "section55_braille_pef.py"
        response = subprocess.run(
            [sys.executable, str(cli), "--help"], capture_output=True,
            text=True, timeout=15, check=False,
        )
        self.assertEqual(response.returncode, 0, response.stderr)
        self.assertIn("--rights-confirmed", response.stdout)

if __name__ == "__main__":
    unittest.main()
