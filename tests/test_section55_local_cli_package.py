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
    dotsIO = 2

    @staticmethod
    def translateString(tables, source, mode):
        if mode != (SyntheticLouis.ucBrl | SyntheticLouis.dotsIO) or not tables:
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
            self.assertEqual(sha256((root / "input.json").read_bytes()).hexdigest(), m["original_source_sha256"])
            self.assertEqual((root / "input.json").stat().st_size, m["original_source_size_bytes"])
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

    def test_mismatched_table_path_fails_before_translation(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.args(Path(tmp))
            args.table_id = str(Path(tmp) / "missing.ctb")
            with patch.dict("sys.modules", {"louis": SyntheticLouis("louis")}):
                with self.assertRaises(BrailleFactoryError):
                    run(args)
            self.assertFalse(args.output_folder.exists())

    def test_mid_run_table_drift_cannot_publish_output(self):
        class DriftLouis(SyntheticLouis):
            @staticmethod
            def translateString(tables, source, mode):
                Path(tables[0]).write_bytes(b"CHANGED DURING TRANSLATION")
                return "\u2801" * len(source)

        with tempfile.TemporaryDirectory() as tmp:
            args = self.args(Path(tmp))
            with patch.dict("sys.modules", {"louis": DriftLouis("louis")}):
                with self.assertRaises(BrailleFactoryError):
                    run(args)
            self.assertFalse(args.output_folder.exists())

    def test_direct_lawful_markdown_book_uses_canonical_source_ingress(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self.args(root)
            source = root / "chess.md"
            source.write_text("# Chess\n\nA move sequence.\n", encoding="utf-8")
            args.book_json = None
            args.source_file = source
            args.book_title = None
            with patch.dict("sys.modules", {"louis": SyntheticLouis("louis")}):
                self.assertEqual(run(args), 0)
            report = json.loads((args.output_folder / "quality-report.json").read_text("utf-8"))
            self.assertIs(report["manifest"]["print_ready"], False)
            self.assertEqual(report["manifest"]["status"], "UNVERIFIED_REQUIRES_DECISION")

    def test_ambiguous_markdown_image_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self.args(root)
            source = root / "chess.md"
            source.write_text("# Chess\n\n![unknown diagram](secret.png)\n", encoding="utf-8")
            args.book_json = None
            args.source_file = source
            args.book_title = None
            with patch.dict("sys.modules", {"louis": SyntheticLouis("louis")}):
                with self.assertRaises(BrailleFactoryError):
                    run(args)
            self.assertFalse(args.output_folder.exists())

    def test_unsupported_source_extension_is_never_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self.args(root)
            source = root / "unreadable.pdf"
            source.write_bytes(b"%PDF-1.7")
            args.book_json = None
            args.source_file = source
            args.book_title = None
            with self.assertRaises(BrailleFactoryError):
                run(args)
            self.assertFalse(args.output_folder.exists())

    def test_existing_empty_output_folder_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.args(Path(tmp))
            args.output_folder.mkdir()
            with patch.dict("sys.modules", {"louis": SyntheticLouis("louis")}):
                with self.assertRaises(BrailleFactoryError):
                    run(args)
            self.assertTrue(args.output_folder.is_dir())
            self.assertEqual(list(args.output_folder.iterdir()), [])

    def test_failed_independent_quality_gate_rolls_back_unpublished_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self.args(root)
            with patch.dict("sys.modules", {"louis": SyntheticLouis("louis")}):
                with patch("tools.section55_braille_pef.verify_provisional_bundle",
                           side_effect=BrailleFactoryError("Synthetic failed consistency")):
                    with self.assertRaises(BrailleFactoryError):
                        run(args)
            self.assertFalse(args.output_folder.exists())
            self.assertEqual(list(root.glob(".section55-unverified-*")), [])

if __name__ == "__main__":
    unittest.main()
