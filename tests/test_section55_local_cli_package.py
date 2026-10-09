from __future__ import annotations

"""Offline synthetic Section-55 CLI/package journey; no real Liblouis certification."""
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
from hashlib import sha256

from acs.bookdocument import BookDocument, Paragraph
from tools.section55_braille_pef import make_parser, run
from acs.chess_braille_factory import BrailleFactoryError


class SyntheticLouis(types.ModuleType):
    ucBrl = 1

    @staticmethod
    def translateString(tables, source, mode):
        if mode != SyntheticLouis.ucBrl or not tables:
            raise ValueError("Wrong synthetic mode/table")
        return "\u2801" * len(source)  # fixture only, never readable language Braille


class Section55LocalCLITests(unittest.TestCase):
    def args(self, root: Path, *, emit_brf: bool = True, rights: bool = True):
        book_path = root / "input.json"
        book_path.write_text(
            json.dumps(BookDocument(title="Chess", blocks=[
                Paragraph(text="Knight"),
            ]).as_dict()), encoding="utf-8",
        )
        table = root / "synthetic.ctb"
        table.write_bytes(b"SYNTHETIC ONLY")
        cli = [
            "--book-json", str(book_path), "--table-file", str(table),
            "--table-id", str(table), "--table-version", "fixture-v1",
            "--language", "en", "--device-model", "NOT-QUALIFIED",
            "--cells-per-line", "20", "--lines-per-page", "10",
            "--rights-basis", "Original synthetic fixture",
            "--output-folder", str(root / "package"),
        ]
        if rights:
            cli.append("--rights-confirmed")
        if emit_brf:
            cli.extend(["--emit-brf", "--display-table", "en-us-brf.dis"])
        return make_parser().parse_args(cli)

    def test_one_book_pef_and_brf_with_manifest_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self.args(root)
            with patch.dict("sys.modules", {"louis": SyntheticLouis("louis")}):
                self.assertEqual(run(args), 0)
            output = root / "package"
            report = json.loads((output / "quality-report.json").read_text(encoding="utf-8"))
            m = report["manifest"]
            pef = (output / "chess-book-unverified.pef").read_bytes()
            brf = (output / "chess-book-unverified.brf").read_bytes()
            self.assertEqual(sha256(pef).hexdigest(), m["output_pef_sha256"])
            self.assertEqual(sha256(brf).hexdigest(), m["output_brf_sha256"])
            self.assertIs(m["print_ready"], False)
            self.assertIs(m["brf_print_ready"], False)
            self.assertEqual(m["status"], "UNVERIFIED_REQUIRES_DECISION")
            self.assertIn("UNVERIFIED", report["notice"])
            self.assertNotIn("private", json.dumps(report).lower())
            # A second request never overwrites accepted output.
            with patch.dict("sys.modules", {"louis": SyntheticLouis("louis")}):
                with self.assertRaises(BrailleFactoryError):
                    run(args)
            self.assertEqual(pef, (output / "chess-book-unverified.pef").read_bytes())

    def test_absent_consent_produces_no_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.args(Path(tmp), rights=False)
            with self.assertRaises(BrailleFactoryError):
                run(args)
            self.assertFalse(args.output_folder.exists())

    def test_missing_explicit_brf_map_produces_no_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.args(Path(tmp))
            args.display_table = None
            with patch.dict("sys.modules", {"louis": SyntheticLouis("louis")}):
                with self.assertRaises(BrailleFactoryError):
                    run(args)
            self.assertFalse(args.output_folder.exists())

    def test_optional_brf_can_be_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.args(Path(tmp), emit_brf=False)
            with patch.dict("sys.modules", {"louis": SyntheticLouis("louis")}):
                self.assertEqual(run(args), 0)
            self.assertTrue((args.output_folder / "chess-book-unverified.pef").exists())
            self.assertFalse((args.output_folder / "chess-book-unverified.brf").exists())

if __name__ == "__main__":
    unittest.main()
