from __future__ import annotations

"""Offline synthetic Section-55 CLI/package journey; no real Liblouis certification."""
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
from hashlib import sha256

from acs.bookdocument import BookDocument, Paragraph, Position
from tools.section55_braille_pef import make_parser, run
from acs.chess_braille_factory import BrailleFactoryError
from acs.chess_braille_bundle import verify_provisional_bundle


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

    def test_transitive_liblouis_closure_is_in_package_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self.args(root)
            nested = root / "included.cti"
            nested.write_text("# dependent rule file\n", encoding="utf-8")
            args.table_file.write_text("include included.cti\n", encoding="utf-8")
            with patch.dict("sys.modules", {"louis": SyntheticLouis("louis")}):
                self.assertEqual(run(args), 0)
            report = json.loads((args.output_folder / "quality-report.json").read_text(encoding="utf-8"))
            provenance = report["manifest"]
            self.assertEqual(len(provenance["table_closure_files"]), 2)
            self.assertEqual(len(provenance["table_closure_sha256"]), 64)
            self.assertEqual(provenance["table_closure_status"],
                             "LOCAL_PIN_ONLY_NOT_LANGUAGE_CERTIFICATION")
            completed = verify_provisional_bundle(
                args.output_folder, args.book_json, table_file=args.table_file,
            )
            self.assertTrue(completed.table_inventory_verified)
            nested.write_text("# Modified after package\n", encoding="utf-8")
            with self.assertRaises(BrailleFactoryError):
                verify_provisional_bundle(
                    args.output_folder, args.book_json, table_file=args.table_file,
                )

    def test_modified_included_table_during_translation_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self.args(root)
            nested = root / "included.cti"
            nested.write_text("# Original\n", encoding="utf-8")
            args.table_file.write_text("include included.cti\n", encoding="utf-8")

            class DriftIncluded(SyntheticLouis):
                @staticmethod
                def translateString(tables, source, mode):
                    nested.write_text("# MODIFIED\n", encoding="utf-8")
                    return "\u2801" * len(source)

            with patch.dict("sys.modules", {"louis": DriftIncluded("louis")}):
                with self.assertRaises(BrailleFactoryError):
                    run(args)
            self.assertFalse(args.output_folder.exists())

    def test_optional_html_is_independently_rerendered_from_original_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self.args(root)
            args.emit_html = True
            with patch.dict("sys.modules", {"louis": SyntheticLouis("louis")}):
                self.assertEqual(run(args), 0)
            html_file = args.output_folder / "chess-book-unverified.html"
            content = html_file.read_bytes()
            self.assertIn(b"UNVERIFIED", content)
            report = json.loads((args.output_folder / "quality-report.json").read_text("utf-8"))
            self.assertEqual(sha256(content).hexdigest(), report["manifest"]["output_html_sha256"])
            self.assertIs(report["manifest"]["html_print_ready"], False)
            verified = verify_provisional_bundle(
                args.output_folder, args.book_json, table_file=args.table_file,
            )
            self.assertEqual(verified.output_html_sha256, sha256(content).hexdigest())
            html_file.write_bytes(content + b"<script>unsafe</script>")
            with self.assertRaises(BrailleFactoryError):
                verify_provisional_bundle(args.output_folder, args.book_json)

    def test_markdown_title_override_survives_html_source_revalidation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self.args(root)
            md = root / "owned.md"
            md.write_text("# Chapter\n\nA white king and a black king.\n", encoding="utf-8")
            args.book_json = None
            args.source_file = md
            args.book_title = "My Owned Chess Book"
            args.emit_html = True
            with patch.dict("sys.modules", {"louis": SyntheticLouis("louis")}):
                self.assertEqual(run(args), 0)
            verified = verify_provisional_bundle(
                args.output_folder, md, table_file=args.table_file,
            )
            self.assertIsNotNone(verified.output_html_sha256)
            self.assertIn(b"My Owned Chess Book",
                          (args.output_folder / "chess-book-unverified.html").read_bytes())

    def test_explicit_ukaaf2015_diagrams_are_source_bound_and_not_print_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self.args(root)
            args.emit_ukaaf_diagrams = True
            args.cells_per_line = 80
            args.book_json.write_text(json.dumps(BookDocument(
                title="Owned sample chess position",
                blocks=[Position(fen="4k3/8/8/8/8/8/8/4K3 w - - 0 1")],
            ).as_dict()), encoding="utf-8")
            with patch.dict("sys.modules", {"louis": SyntheticLouis("louis")}):
                self.assertEqual(run(args), 0)
            path = args.output_folder / "chess-diagrams-ukaaf2015-unverified.json"
            parsed = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(parsed["diagram_count"], 1)
            self.assertIs(parsed["layout_qualified"], False)
            report_path = args.output_folder / "quality-report.json"
            report = json.loads(report_path.read_text("utf-8"))
            self.assertIs(report["manifest"]["ukaaf_print_ready"], False)
            self.assertEqual(sha256(path.read_bytes()).hexdigest(),
                             report["manifest"]["ukaaf_diagram_catalog_sha256"])
            verified = verify_provisional_bundle(args.output_folder, args.book_json,
                                                  table_file=args.table_file)
            self.assertEqual(verified.output_ukaaf_sha256,
                             report["manifest"]["ukaaf_diagram_catalog_sha256"])
            # Updating the file AND its reported SHA is still detected by
            # independent re-rendering of the original canonical BookDocument.
            parsed["diagrams"][0]["braille_position_cells"] = "⠁"
            altered = (json.dumps(parsed, ensure_ascii=False) + "\n").encode("utf-8")
            path.write_bytes(altered)
            report["manifest"]["ukaaf_diagram_catalog_sha256"] = sha256(altered).hexdigest()
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaises(BrailleFactoryError):
                verify_provisional_bundle(args.output_folder, args.book_json)

    def test_ukaaf_catalog_refuses_wrong_language_and_missing_positions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self.args(root)
            args.emit_ukaaf_diagrams = True
            args.language = "sk"
            with patch.dict("sys.modules", {"louis": SyntheticLouis("louis")}):
                with self.assertRaises(BrailleFactoryError):
                    run(args)
            self.assertFalse(args.output_folder.exists())
            args.language = "en"
            with patch.dict("sys.modules", {"louis": SyntheticLouis("louis")}):
                with self.assertRaises(BrailleFactoryError):
                    run(args)
            self.assertFalse(args.output_folder.exists())

if __name__ == "__main__":
    unittest.main()
