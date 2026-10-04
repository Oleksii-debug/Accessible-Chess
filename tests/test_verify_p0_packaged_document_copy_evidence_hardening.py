from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from scripts.verify_p0_packaged_document_copy_evidence import (
    EvidenceError,
    MAX_CHECKSUM_BYTES,
    verify,
)


SHA = "a" * 40


class VerifyP0PackagedDocumentCopyEvidenceHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.product = self.root / "AccessibleChess"
        self.product.mkdir()
        self.exe = self.product / "AccessibleChess.exe"
        self.exe.write_bytes(b"fixture")
        digest = hashlib.sha256(b"fixture").hexdigest()
        (self.root / "SHA256SUMS.txt").write_text(
            f"{digest}  AccessibleChess/AccessibleChess.exe\n", encoding="utf-8"
        )
        (self.root / "RELEASE_MANIFEST.json").write_text(
            '{"integration_sha":"' + SHA + '","human_tested":false,"nvda_verified":false}', encoding="utf-8"
        )
        self.evidence = self.root / "evidence.json"
        self.evidence.write_text(
            "{"
            '"product_sha":"' + SHA + '",'
            '"static_document_text":"Game information",'
            '"static_document_outside_edit":true,'
            '"static_text_visible_rectangle":true,'
            '"native_copy_focus_verified":true,'
            '"foreground_product_verified":true,'
            '"manifest_product_sha_verified":true,'
            '"executable_checksum_verified":true,'
            '"textpattern_selection_supported":true,'
            '"textpattern_target_selected":true,'
            '"textpattern_selection_equality":"UIA exact range endpoints and case-sensitive text equality",'
            '"clipboard_equality":"case-sensitive exact string equality",'
            '"ctrl_c_exact_clipboard":true,'
            '"move_input_focus_verified":true,'
            '"move_input_native_ctrl_a_ctrl_c":true,'
            '"human_tested":false,'
            '"nvda_verified":false'
            "}",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_complete_bound_evidence_passes(self) -> None:
        verify(self.evidence, self.product, SHA)

    def test_evidence_product_sha_mismatch_fails(self) -> None:
        text = self.evidence.read_text(encoding="utf-8").replace(
            SHA, "b" * 40, 1
        )
        self.evidence.write_text(text, encoding="utf-8")
        with self.assertRaisesRegex(EvidenceError, "evidence product_sha"):
            verify(self.evidence, self.product, SHA)

    def test_move_input_native_copy_proof_is_required(self) -> None:
        text = self.evidence.read_text(encoding="utf-8").replace(
            '"move_input_native_ctrl_a_ctrl_c":true',
            '"move_input_native_ctrl_a_ctrl_c":false',
        )
        self.evidence.write_text(text, encoding="utf-8")
        with self.assertRaisesRegex(EvidenceError, "move_input_native_ctrl_a_ctrl_c"):
            verify(self.evidence, self.product, SHA)

    def test_duplicate_manifest_integration_sha_fails(self) -> None:
        (self.root / "RELEASE_MANIFEST.json").write_text(
            '{"integration_sha":"' + SHA + '","integration_sha":"' + SHA + '","human_tested":false,"nvda_verified":false}',
            encoding="utf-8",
        )
        with self.assertRaises(EvidenceError):
            verify(self.evidence, self.product, SHA)

    def test_manifest_human_overclaim_fails(self) -> None:
        (self.root / "RELEASE_MANIFEST.json").write_text(
            '{"integration_sha":"' + SHA + '","human_tested":true,"nvda_verified":false}',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(EvidenceError, "human_tested=false"):
            verify(self.evidence, self.product, SHA)

    def test_manifest_nvda_overclaim_fails(self) -> None:
        (self.root / "RELEASE_MANIFEST.json").write_text(
            '{"integration_sha":"' + SHA + '","human_tested":false,"nvda_verified":true}',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(EvidenceError, "nvda_verified=false"):
            verify(self.evidence, self.product, SHA)

    def test_malformed_checksum_digest_fails(self) -> None:
        (self.root / "SHA256SUMS.txt").write_text(
            "xyz  AccessibleChess/AccessibleChess.exe\n", encoding="utf-8"
        )
        with self.assertRaises(EvidenceError):
            verify(self.evidence, self.product, SHA)

    def test_checksum_inventory_rejects_malformed_unrelated_line(self) -> None:
        digest = hashlib.sha256(b"fixture").hexdigest()
        (self.root / "SHA256SUMS.txt").write_text(
            "malformed-line-without-delimiter\n"
            f"{digest}  AccessibleChess/AccessibleChess.exe\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(EvidenceError, "malformed line"):
            verify(self.evidence, self.product, SHA)

    def test_checksum_inventory_rejects_duplicate_unrelated_path(self) -> None:
        digest = hashlib.sha256(b"fixture").hexdigest()
        (self.root / "SHA256SUMS.txt").write_text(
            f"{digest}  AccessibleChess/AccessibleChess.exe\n"
            f"{digest}  AccessibleChess/web/index.html\n"
            f"{digest}  AccessibleChess/web/index.html\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(EvidenceError, "duplicate path"):
            verify(self.evidence, self.product, SHA)

    def test_oversized_checksum_inventory_fails_before_parse(self) -> None:
        (self.root / "SHA256SUMS.txt").write_text(
            "x" * (MAX_CHECKSUM_BYTES + 1),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(EvidenceError, "size is outside"):
            verify(self.evidence, self.product, SHA)

    def test_missing_manifest_fails(self) -> None:
        (self.root / "RELEASE_MANIFEST.json").unlink()
        with self.assertRaises(EvidenceError):
            verify(self.evidence, self.product, SHA)

    def test_oversized_evidence_fails(self) -> None:
        self.evidence.write_text("{" + (" " * (70 * 1024)) + "}", encoding="utf-8")
        with self.assertRaises(EvidenceError):
            verify(self.evidence, self.product, SHA)

    def test_wrong_clipboard_contract_text_fails(self) -> None:
        text = self.evidence.read_text(encoding="utf-8").replace(
            "case-sensitive exact string equality", "case-insensitive"
        )
        self.evidence.write_text(text, encoding="utf-8")
        with self.assertRaises(EvidenceError):
            verify(self.evidence, self.product, SHA)

    def test_noncanonical_sha_length_fails(self) -> None:
        with self.assertRaises(EvidenceError):
            verify(self.evidence, self.product, "a" * 39)


if __name__ == "__main__":
    unittest.main()
