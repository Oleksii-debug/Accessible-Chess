"""Section 37 public release source-material exclusion (offline negative gates)."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from acs.lawful_corpus_registry import LawfulCorpusError, load_catalog
from tools.revised_section37_release_exclusion import (
    audit_public_archive, excluded_public_source_index,
)

RAW_EXCLUDED = b"authentic-original-source-only-in-test-fixture"
RECORD = {
    "id": "licensed_test_original",
    "format": "md",
    "external_checkout_path": "ephemeral/original-chess-book.md",
    "sha256": hashlib.sha256(RAW_EXCLUDED).hexdigest(),
    "public_release": "EXCLUDED",
    "redistribution": "NOT_CLEARED",
}


def build_zip(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, value in entries.items():
            zf.writestr(name, value)


class PublicReleaseExclusionTests(unittest.TestCase):
    def test_real_source_registry_has_explicit_excluded_identifiers_and_hashes(self):
        original = {x["id"]: x for x in load_catalog()}
        deny = excluded_public_source_index(load_catalog())
        self.assertIn(
            original["original_gpl_chastity_chess_chapters_markdown"]["sha256"],
            deny["sha256"],
        )
        self.assertIn(
            original["original_epd2doc_7men_human_epd"]["sha256"],
            deny["sha256"],
        )
        self.assertEqual(
            deny["basenames"]["chastitychesschapters-ebook.md"],
            "original_gpl_chastity_chess_chapters_markdown",
        )
        self.assertIn(
            original["libcbh_gpl_original_nested_variations_cbh_family"][
                "external_oracle_source_checksum"
            ]["sha256"],
            deny["sha256"],
        )
        self.assertNotIn(
            original["stockfish_2moves_v2_pgn_zip"]["sha256"],
            deny["sha256"],
        )
        self.assertEqual(deny["basenames"]["endgamestudiesgrigoriev.pgn"], "grigoriev_historical_original_studies_pgn_unlicensed")
        self.assertEqual(deny["basenames"]["kaspariandominationstudies.pgn"], "kasparian_domination_original_studies_pgn_unlicensed")

    def test_clean_release_passes_and_honestly_disclaims_public_authorization(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "safe-release.zip"
            build_zip(path, {"product/readme.txt": b"safe", "product/empty.txt": b""})
            result = audit_public_archive(path, (RECORD,))
            self.assertEqual(result["result"], "PASS_ONLY_FOR_TESTED_ZIP_BYTES")
            self.assertFalse(result["public_distribution_rights_granted"])
            self.assertEqual(result["archive_member_count"], 2)

    def test_same_original_bytes_denied_even_when_renamed_to_unrelated_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "renamed.zip"
            build_zip(path, {"safe-name.bin": RAW_EXCLUDED})
            with self.assertRaises(LawfulCorpusError):
                audit_public_archive(path, (RECORD,))

    def test_original_file_name_denied_even_if_bytes_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "filename.zip"
            build_zip(path, {"res/Original-Chess-Book.MD": b"something else"})
            with self.assertRaises(LawfulCorpusError):
                audit_public_archive(path, (RECORD,))

    def test_traversal_zip_bomb_metadata_and_symlink_denied(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for filename in ("../oops.bin", "/absolute.bin", "C:/file.bin", "a/./../evil.bin"):
                with self.subTest(filename=filename):
                    zip_path = directory / "bad.zip"
                    build_zip(zip_path, {filename: b"safe"})
                    with self.assertRaises(LawfulCorpusError):
                        audit_public_archive(zip_path, (RECORD,))
            zip_path = directory / "sym.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                entry = zipfile.ZipInfo("escape")
                entry.create_system = 3
                entry.external_attr = (0o120777 << 16)
                zf.writestr(entry, "out of tree")
            with self.assertRaises(LawfulCorpusError):
                audit_public_archive(zip_path, (RECORD,))

    def test_noncanonical_archive_paths_fail_before_windows_extraction_aliases(self):
        # A ZIP with normalized equivalents may overwrite a file when
        # extracted, evading source-name checks or duplicate detection.
        for filename in (
            "assets/./safe.txt",
            "assets//safe.txt",
            "assets/safe.txt.",
            "assets/safe.txt ",
            "assets/safe.txt:alternate-stream",
            "assets/../safe.txt",
        ):
            with self.subTest(filename=filename):
                with tempfile.TemporaryDirectory() as temp:
                    archive = Path(temp) / "alias.zip"
                    build_zip(archive, {filename: b"benign"})
                    with self.assertRaisesRegex(LawfulCorpusError, "unsafe member path"):
                        audit_public_archive(archive, (RECORD,))

    def test_duplicate_alias_cannot_hide_original_book(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "alias-original.zip"
            build_zip(
                archive,
                {
                    "product/original-chess-book.md.": b"disguised",
                    "product/readme.txt": b"safe",
                },
            )
            with self.assertRaises(LawfulCorpusError):
                audit_public_archive(archive, (RECORD,))

    def test_archive_replaced_between_lstat_and_open_is_refused(self):
        # Simulate an attacker exchanging the checked path before the ZIP opens.
        # os.replace works on Windows without symlink privileges.
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            archive = directory / "release.zip"
            replacement = directory / "replacement.zip"
            build_zip(archive, {"product/ok.txt": b"approved-content"})
            build_zip(replacement, {"unrelated.bin": b"swapped-content"})
            original_open = Path.open
            swaps = 0

            def replace_before_open(path, *args, **kwargs):
                nonlocal swaps
                if path == archive:
                    os.replace(replacement, archive)
                    swaps += 1
                return original_open(path, *args, **kwargs)

            with patch.object(Path, "open", replace_before_open):
                with self.assertRaisesRegex(LawfulCorpusError, "changed before safe open"):
                    audit_public_archive(archive, (RECORD,))
            self.assertEqual(swaps, 1)

    def test_real_owner_final_zip_upload_requires_exclusion_gate(self):
        workflow = Path(".github/workflows/owner-oneclick-from-w4.yml").read_text(encoding="utf-8")
        hook = "python -m tools.revised_section37_release_exclusion"
        upload = "- name: Upload exact owner one-click candidate and receipt"
        self.assertEqual(workflow.count(hook), 1)
        self.assertLess(workflow.index(hook), workflow.index(upload))
        self.assertIn("$env:ACS_37_PUBLIC_RELEASE_ZIP = $archive", workflow)
        self.assertIn("OWNER_FINAL_PUBLIC_CORPUS_EXCLUSION_FAILED", workflow)
        self.assertIn("OWNER_FINAL_ZIP_PRE_UPLOAD_BINDING=PASS", workflow)
        self.assertIn("OWNER_FINAL_POST_AUDIT_ZIP_DRIFT", workflow)
        self.assertLess(workflow.index("OWNER_FINAL_PUBLIC_CORPUS_EXCLUSION=PASS"), workflow.index("OWNER_FINAL_POST_AUDIT_ZIP_DRIFT"))

    def test_source_registry_empty_or_bad_hash_is_fail_closed(self):
        with self.assertRaises(LawfulCorpusError):
            excluded_public_source_index(())
        with self.assertRaises(LawfulCorpusError):
            excluded_public_source_index(({**RECORD, "sha256": "bad"},))
        with self.assertRaises(LawfulCorpusError):
            excluded_public_source_index(({**RECORD, "external_checkout_path": "unsafe\\a"},))


if __name__ == "__main__":
    unittest.main()
