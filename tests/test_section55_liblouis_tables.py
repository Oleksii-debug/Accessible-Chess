from __future__ import annotations

"""Real filesystem tests for conservative Liblouis include closure, no Liblouis binary."""
from pathlib import Path
import tempfile
import unittest

from acs.chess_braille_factory import BrailleFactoryError
from acs.chess_braille_tables import scan_local_liblouis_table_closure


class TestSection55TableClosure(unittest.TestCase):
    def test_main_and_transitive_include_are_pinned_deterministically(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            main = base / "main.ctb"
            nested = base / "nested.cti"
            final = base / "final.cti"
            main.write_text("# Main\ninclude nested.cti\n", encoding="utf-8")
            nested.write_text("include final.cti\n", encoding="utf-8")
            final.write_text("# End\n", encoding="utf-8")
            first = scan_local_liblouis_table_closure(main)
            second = scan_local_liblouis_table_closure(main)
            self.assertEqual(first, second)
            self.assertEqual(len(first.files), 3)
            self.assertEqual(len(first.closure_sha256), 64)
            self.assertEqual(first.status, "LOCAL_PIN_ONLY_NOT_LANGUAGE_CERTIFICATION")
            final.write_text("# Altered\n", encoding="utf-8")
            changed = scan_local_liblouis_table_closure(main)
            self.assertNotEqual(first.closure_sha256, changed.closure_sha256)

    def test_unicode_whitespace_in_include_directive_fails_closed(self):
        # Python regex \s and str.strip() recognize these characters,
        # but the external Liblouis parser's lexical equivalence is unproven.
        # Do not silently certify a different include dependency graph.
        variants = (
            "include\u00a0child.cti",   # NO-BREAK SPACE
            "include\u2003child.cti",   # EM SPACE
            "include\u202fchild.cti",   # NARROW NO-BREAK SPACE
            "\u00a0include child.cti",  # leading NBSP
            "include child.cti\u2003",  # trailing EM SPACE
        )
        for directive in variants:
            with self.subTest(directive=repr(directive)), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                (base / "child.cti").write_text("# legitimate\n", encoding="utf-8")
                main = base / "main.ctb"
                main.write_text(directive + "\n", encoding="utf-8")
                with self.assertRaisesRegex(BrailleFactoryError, "Unicode whitespace"):
                    scan_local_liblouis_table_closure(main)

    def test_canonical_ascii_spaces_and_tabs_in_include_directive_work(self):
        for directive in ("include child.cti", "include\tchild.cti"):
            with self.subTest(directive=repr(directive)), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                (base / "child.cti").write_text("# legitimate\n", encoding="utf-8")
                main = base / "main.ctb"
                main.write_text(directive + "\n", encoding="utf-8")
                self.assertEqual(
                    len(scan_local_liblouis_table_closure(main).files), 2
                )

    def test_raw_include_path_aliases_fail_before_path_normalization(self):
        # pathlib.Path collapses './' and repeated separators, hiding distinct
        # input spellings that an external Liblouis resolver might interpret
        # differently. The local table inventory must reject them verbatim.
        invalid = (
            "./child.cti", "dir/./child.cti", "dir//child.cti",
            "dir/../child.cti", "dir/child.cti/",
        )
        for operand in invalid:
            with self.subTest(operand=operand), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                (base / "dir").mkdir()
                (base / "child.cti").write_text("# child\n", encoding="utf-8")
                (base / "dir" / "child.cti").write_text("# nested\n", encoding="utf-8")
                main = base / "main.ctb"
                main.write_text(f"include {operand}\n", encoding="utf-8")
                with self.assertRaises(BrailleFactoryError):
                    scan_local_liblouis_table_closure(main)

    def test_canonical_relative_nested_include_still_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "dir").mkdir()
            (base / "dir" / "child.cti").write_text("# nested\n", encoding="utf-8")
            main = base / "main.ctb"
            main.write_text("include dir/child.cti\n", encoding="utf-8")
            closure = scan_local_liblouis_table_closure(main)
            self.assertEqual(
                tuple(name for name, _ in closure.files),
                ("dir/child.cti", "main.ctb"),
            )

    def test_absolute_and_traversal_include_fail_closed(self):
        for operand in ("../unsafe.ctb", "/other/unsafe.ctb", "dir/../unsafe.ctb"):
            with self.subTest(operand=operand), tempfile.TemporaryDirectory() as tmp:
                main = Path(tmp) / "main.ctb"
                main.write_text("include " + operand + "\n", encoding="utf-8")
                with self.assertRaises(BrailleFactoryError):
                    scan_local_liblouis_table_closure(main)

    def test_include_cycles_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            main = base / "main.ctb"
            child = base / "child.cti"
            main.write_text("include child.cti\n", encoding="utf-8")
            child.write_text("include main.ctb\n", encoding="utf-8")
            with self.assertRaises(BrailleFactoryError):
                scan_local_liblouis_table_closure(main)

    def test_missing_include_and_ambiguous_directive_fail_closed(self):
        for text in ("include missing.cti", "include", "include child.cti ignored"):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp:
                main = Path(tmp) / "main.ctb"
                main.write_text(text + "\n", encoding="utf-8")
                with self.assertRaises(BrailleFactoryError):
                    scan_local_liblouis_table_closure(main)

    def test_utf16_and_binary_input_are_not_silently_guessed(self):
        with tempfile.TemporaryDirectory() as tmp:
            main = Path(tmp) / "main.ctb"
            main.write_bytes("\ufeffinclude child.cti\n".encode("utf-16"))
            with self.assertRaises(BrailleFactoryError):
                scan_local_liblouis_table_closure(main)

    def test_lf_and_crlf_table_lines_are_supported(self):
        for sep in (b"\n", b"\r\n"):
            with self.subTest(separator=sep), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                (base / "child.cti").write_bytes(b"# included" + sep)
                main = base / "main.ctb"
                main.write_bytes(b"include child.cti" + sep)
                closure = scan_local_liblouis_table_closure(main)
                self.assertEqual(len(closure.files), 2)

    def test_ambiguous_line_separators_and_nul_fail_closed(self):
        # splitlines() treats these as extra lines even where Liblouis
        # newline semantics may differ. They must not create hidden includes.
        for marker in ("\r", "\x00", "\v", "\f", "\x1c", "\x1d",
                       "\x1e", "\x85", "\u2028", "\u2029"):
            with self.subTest(marker=repr(marker)), tempfile.TemporaryDirectory() as tmp:
                main = Path(tmp) / "main.ctb"
                main.write_bytes(
                    ("include child.cti" + marker + "# hidden\n").encode("utf-8")
                )
                with self.assertRaisesRegex(BrailleFactoryError, "line separator"):
                    scan_local_liblouis_table_closure(main)

    def test_nonportable_include_path_aliases_fail_closed(self):
        for operand in (r"sub\child.cti", "C:child.cti", "sub:child.cti"):
            with self.subTest(operand=operand), tempfile.TemporaryDirectory() as tmp:
                main = Path(tmp) / "main.ctb"
                main.write_bytes(("include " + operand + "\n").encode("utf-8"))
                with self.assertRaisesRegex(BrailleFactoryError, "Unsafe Liblouis include target"):
                    scan_local_liblouis_table_closure(main)

    def test_symlinked_include_directory_within_root_is_rejected(self):
        # A symlink to another directory *inside* the root also creates an
        # ambiguous dependency name; checking only the target file misses it.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            real = base / "real"
            real.mkdir()
            (real / "child.cti").write_text("# pinned\n", encoding="utf-8")
            alias = base / "alias"
            try:
                alias.symlink_to(real, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("Directory symlinks need OS permissions")
            main = base / "main.ctb"
            main.write_text("include alias/child.cti\n", encoding="utf-8")
            with self.assertRaisesRegex(BrailleFactoryError, "Symlink"):
                scan_local_liblouis_table_closure(main)

    def test_symlink_inside_pinned_folder_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target = base / "real.cti"
            target.write_text("# data", encoding="utf-8")
            link = base / "link.cti"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks require elevated permissions on this OS")
            main = base / "main.ctb"
            main.write_text("include link.cti\n", encoding="utf-8")
            with self.assertRaises(BrailleFactoryError):
                scan_local_liblouis_table_closure(main)


if __name__ == "__main__":
    unittest.main()
