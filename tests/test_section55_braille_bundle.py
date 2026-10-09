from __future__ import annotations

"""Offline synthetic-only tests of Section 55 independent package verification."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from acs.bookdocument import BookDocument, Paragraph
from acs.chess_braille_brf import NABCC_DISPLAY_TABLE, pef_to_provisional_brf
from acs.chess_braille_factory import (
    BrailleFactoryError, BrailleProfile, prepare_chess_book_pef,
)
from acs.chess_braille_bundle import verify_provisional_bundle


class FakeSixDot:
    table_id = "fixture"
    table_version = "test"
    table_sha256 = "a" * 64

    def translate(self, text):
        return "".join("\u2800" if char == " " else "\u2801" for char in text)


def create_bundle(root: Path, *, brf: bool = True) -> tuple[Path, Path]:
    source = root / "original.json"
    source.write_text("Only synthetic fixture", encoding="utf-8")
    source_data = source.read_bytes()
    prepared = prepare_chess_book_pef(
        BookDocument(title="Chess", blocks=[Paragraph(text="King queen")]),
        BrailleProfile(
            language="en", table_id="fixture", table_version="test",
            table_sha256="a" * 64, device_model="SYNTHETIC",
            cells_per_line=20, lines_per_page=10,
        ), FakeSixDot(), rights_confirmed=True, rights_basis="Fixture only",
    )
    package = root / "package"
    package.mkdir()
    (package / "chess-book-unverified.pef").write_bytes(prepared.pef)
    manifest = {
        **prepared.manifest,
        "original_source_sha256": sha256(source_data).hexdigest(),
        "original_source_size_bytes": len(source_data),
    }
    if brf:
        result = pef_to_provisional_brf(
            prepared, display_table=NABCC_DISPLAY_TABLE,
        )
        (package / "chess-book-unverified.brf").write_bytes(result.data)
        manifest.update({
            "output_brf_sha256": result.sha256,
            "brf_display_table": NABCC_DISPLAY_TABLE,
            "brf_print_ready": False,
        })
    (package / "quality-report.json").write_text(json.dumps({
        "manifest": manifest,
        "warnings": list(prepared.warnings),
        "notice": "UNVERIFIED; NOT APPROVED FOR DIRECT EMBOSSING OR DISTRIBUTION",
    }, ensure_ascii=False), encoding="utf-8")
    return package, source


def update_report(folder: Path, modify):
    path = folder / "quality-report.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    modify(data)
    path.write_text(json.dumps(data), encoding="utf-8")


class Section55IndependentVerifier(unittest.TestCase):
    def test_roundtrip_both_formats_checks_bytes_and_stays_unqualified(self):
        with tempfile.TemporaryDirectory() as d:
            folder, source = create_bundle(Path(d))
            result = verify_provisional_bundle(folder, source)
            self.assertTrue(result.internal_consistency)
            self.assertIs(result.qualified_print_ready, False)
            self.assertEqual(result.status, "UNVERIFIED_REQUIRES_DECISION")
            self.assertEqual(result.source_sha256, sha256(source.read_bytes()).hexdigest())
            self.assertEqual(result.output_brf_sha256, sha256(
                (folder / "chess-book-unverified.brf").read_bytes()).hexdigest())

    def test_pef_only_package_still_validates_pef_structure(self):
        with tempfile.TemporaryDirectory() as d:
            folder, source = create_bundle(Path(d), brf=False)
            result = verify_provisional_bundle(folder, source)
            self.assertIsNone(result.output_brf_sha256)
            self.assertGreaterEqual(result.pages, 1)

    def test_source_substitution_fails(self):
        with tempfile.TemporaryDirectory() as d:
            folder, source = create_bundle(Path(d))
            source.write_text("CHANGED", encoding="utf-8")
            with self.assertRaises(BrailleFactoryError):
                verify_provisional_bundle(folder, source)

    def test_pef_substitution_fails(self):
        with tempfile.TemporaryDirectory() as d:
            folder, source = create_bundle(Path(d))
            path = folder / "chess-book-unverified.pef"
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaises(BrailleFactoryError):
                verify_provisional_bundle(folder, source)

    def test_brf_substitution_fails_even_if_manifest_hash_is_updated(self):
        with tempfile.TemporaryDirectory() as d:
            folder, source = create_bundle(Path(d))
            path = folder / "chess-book-unverified.brf"
            altered = path.read_bytes() + b"*"
            path.write_bytes(altered)
            update_report(folder, lambda d: d["manifest"].update({
                "output_brf_sha256": sha256(altered).hexdigest(),
            }))
            with self.assertRaises(BrailleFactoryError):
                verify_provisional_bundle(folder, source)

    def test_false_print_ready_fails(self):
        with tempfile.TemporaryDirectory() as d:
            folder, source = create_bundle(Path(d))
            update_report(folder, lambda d: d["manifest"].update({
                "print_ready": True,
            }))
            with self.assertRaises(BrailleFactoryError):
                verify_provisional_bundle(folder, source)

    def test_unexpected_file_and_missing_file_fail(self):
        with tempfile.TemporaryDirectory() as d:
            folder, source = create_bundle(Path(d))
            (folder / "unexpected.txt").write_text("foreign")
            with self.assertRaises(BrailleFactoryError):
                verify_provisional_bundle(folder, source)
            (folder / "unexpected.txt").unlink()
            (folder / "quality-report.json").unlink()
            with self.assertRaises(BrailleFactoryError):
                verify_provisional_bundle(folder, source)

    def test_public_cli_reports_pass_without_claiming_print_ready(self):
        with tempfile.TemporaryDirectory() as d:
            folder, source = create_bundle(Path(d))
            root = Path(__file__).resolve().parents[1]
            cli = root / "tools" / "section55_verify_bundle.py"
            process = subprocess.run([
                sys.executable, str(cli), "--folder", str(folder),
                "--original-source", str(source),
            ], capture_output=True, text=True, timeout=15, check=False)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertIn("UNVERIFIED_REQUIRES_DECISION", process.stdout)
            self.assertIn("readiness: false", process.stdout)

    def test_public_cli_hides_private_path_on_failure(self):
        with tempfile.TemporaryDirectory() as d:
            folder, source = create_bundle(Path(d))
            source.unlink()
            root = Path(__file__).resolve().parents[1]
            cli = root / "tools" / "section55_verify_bundle.py"
            process = subprocess.run([
                sys.executable, str(cli), "--folder", str(folder),
                "--original-source", str(source),
            ], capture_output=True, text=True, timeout=15, check=False)
            self.assertEqual(process.returncode, 2)
            self.assertNotIn(str(folder), process.stderr)
            self.assertNotIn(str(source), process.stderr)

if __name__ == "__main__":
    unittest.main()
