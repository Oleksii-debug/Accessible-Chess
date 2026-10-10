from __future__ import annotations

"""All synthetic only: BRF is unverified until real professional/device gates pass."""
import unittest
from dataclasses import replace
from hashlib import sha256
from xml.etree import ElementTree as ET

from acs.bookdocument import BookDocument, Paragraph
from acs.chess_braille_factory import (
    BrailleFactoryError, BrailleProfile, BraillePreparation, prepare_chess_book_pef,
)
from acs.chess_braille_brf import (
    _BRAILLE_ASCII, NABCC_DISPLAY_TABLE, pef_to_provisional_brf,
)

class SyntheticOnly:
    table_id = "fixture"
    table_version = "1"
    table_sha256 = "a" * 64

    def translate(self, source: str) -> str:
        return "\u2801" * len(source.replace(" ", ""))

def make_pef() -> BraillePreparation:
    return prepare_chess_book_pef(
        BookDocument(title="Chess", blocks=[Paragraph(text="Tests")]),
        BrailleProfile(language="en", table_id="fixture", table_version="1",
            table_sha256="a" * 64, device_model="MOCK-DEVICE",
            cells_per_line=16, lines_per_page=10),
        SyntheticOnly(), rights_confirmed=True, rights_basis="Fixture, authored here",
    )

def changed_pef(sample: BraillePreparation, transform) -> BraillePreparation:
    root = ET.fromstring(sample.pef)
    transform(root)
    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return replace(sample, pef=data, manifest={
        **sample.manifest, "output_pef_sha256": sha256(data).hexdigest(),
    })

class TestSection55BRF(unittest.TestCase):
    def test_full_64_cell_map_and_known_characters(self):
        self.assertEqual(len(_BRAILLE_ASCII), 64)
        self.assertEqual(len(set(_BRAILLE_ASCII)), 64)
        self.assertEqual(_BRAILLE_ASCII[0], " ")
        self.assertEqual(_BRAILLE_ASCII[1], "A")
        self.assertEqual(_BRAILLE_ASCII[63], "=")
        self.assertEqual(_BRAILLE_ASCII[0x2e], "!")
        self.assertEqual(_BRAILLE_ASCII[0x3f], "=")

    def test_all_64_nabcc_characters_match_formal_display_rule_assignments(self):
        # Independent expected pairs from liblouis/tables/en-us-brf.dis.
        # The two columns are display ASCII character, dot indices 1-6.
        pairs = [
            (" ", ""), ("A", "1"), ("B", "12"), ("C", "14"),
            ("D", "145"), ("E", "15"), ("F", "124"), ("G", "1245"),
            ("H", "125"), ("I", "24"), ("J", "245"), ("K", "13"),
            ("L", "123"), ("M", "134"), ("N", "1345"), ("O", "135"),
            ("P", "1234"), ("Q", "12345"), ("R", "1235"),
            ("S", "234"), ("T", "2345"), ("U", "136"), ("V", "1236"),
            ("W", "2456"), ("X", "1346"), ("Y", "13456"), ("Z", "1356"),
            ("0", "356"), ("1", "2"), ("2", "23"), ("3", "25"),
            ("4", "256"), ("5", "26"), ("6", "235"), ("7", "2356"),
            ("8", "236"), ("9", "35"), ("'", "3"), ("@", "4"),
            ('"', "5"), (",", "6"), ("*", "16"), ("/", "34"),
            ("-", "36"), ("^", "45"), (".", "46"), (";", "56"),
            ("<", "126"), ("%", "146"), (":", "156"), ("[", "246"),
            (">", "345"), ("+", "346"), ("_", "456"), ("$", "1246"),
            ("\\", "1256"), ("?", "1456"), ("!", "2346"),
            ("#", "3456"), ("&", "12346"), ("(", "12356"),
            ("]", "12456"), (")", "23456"), ("=", "123456"),
        ]
        self.assertEqual(len(pairs), 64)
        for ascii_character, dots in pairs:
            mask = sum(1 << (int(dot) - 1) for dot in dots)
            with self.subTest(mask=mask, symbol=ascii_character):
                self.assertEqual(_BRAILLE_ASCII[mask], ascii_character)

    def test_provisional_pef_to_brf_is_deterministic_not_print_ready(self):
        sample = make_pef()
        first = pef_to_provisional_brf(sample, display_table=NABCC_DISPLAY_TABLE)
        second = pef_to_provisional_brf(sample, display_table=NABCC_DISPLAY_TABLE)
        self.assertTrue(first.data)
        self.assertEqual(first, second)
        self.assertEqual(first.sha256, sha256(first.data).hexdigest())
        self.assertEqual(first.pages, sample.manifest["pages"])
        self.assertEqual(first.status, "UNVERIFIED_REQUIRES_DECISION")
        self.assertIs(first.print_ready, False)

    def test_other_display_map_fails_closed(self):
        with self.assertRaises(BrailleFactoryError):
            pef_to_provisional_brf(make_pef(), display_table="unverified-table.dis")

    def test_changed_file_hash_fails_closed(self):
        source = make_pef()
        with self.assertRaises(BrailleFactoryError):
            pef_to_provisional_brf(replace(source, pef=source.pef + b" "),
                display_table=NABCC_DISPLAY_TABLE)

    def test_wrong_production_claim_rejected(self):
        source = make_pef()
        with self.assertRaises(BrailleFactoryError):
            pef_to_provisional_brf(replace(source, manifest={
                **source.manifest, "print_ready": True,
            }), display_table=NABCC_DISPLAY_TABLE)

    def test_disallow_duplex_and_unknown_layout_nodes(self):
        source = make_pef()
        ns = "{http://www.daisy.org/ns/2008/pef}"
        for change in (
            lambda root: root.find(".//" + ns + "volume").set("duplex", "true"),
            lambda root: ET.SubElement(root.find(".//" + ns + "section"), ns + "page"),
            lambda root: root.find(".//" + ns + "volume").set("untrusted", "1"),
            lambda root: root.find(".//" + ns + "row").set("rowgap", "1"),
            lambda root: root.find(".//" + ns + "row").__setattr__("text", "unsafe"),
        ):
            with self.subTest(change=change), self.assertRaises(BrailleFactoryError):
                pef_to_provisional_brf(changed_pef(source, change), display_table=NABCC_DISPLAY_TABLE)

    def test_cannot_fake_extra_volume_even_with_updated_digest(self):
        source = make_pef()
        ns = "{http://www.daisy.org/ns/2008/pef}"
        altered = changed_pef(source, lambda root: ET.SubElement(root.find(ns + "body"), ns + "volume"))
        with self.assertRaises(BrailleFactoryError):
            pef_to_provisional_brf(altered, display_table=NABCC_DISPLAY_TABLE)

if __name__ == "__main__":
    unittest.main()
