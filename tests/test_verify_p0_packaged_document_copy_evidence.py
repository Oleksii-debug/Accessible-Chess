from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.verify_p0_packaged_document_copy_evidence import EvidenceError, verify


SHA = "1" * 40


def _base_evidence() -> dict[str, object]:
    return {
        "product_sha": SHA,
        "static_document_text": "Game information",
        "static_document_outside_edit": True,
        "static_text_visible_rectangle": True,
        "native_copy_focus_verified": True,
        "foreground_product_verified": True,
        "manifest_product_sha_verified": True,
        "executable_checksum_verified": True,
        "textpattern_selection_supported": True,
        "textpattern_target_selected": True,
        "textpattern_selection_equality": "UIA exact range endpoints and case-sensitive text equality",
        "clipboard_equality": "case-sensitive exact string equality",
        "ctrl_c_exact_clipboard": True,
        "move_input_focus_verified": True,
        "move_input_native_ctrl_a_ctrl_c": True,
        "human_tested": False,
        "nvda_verified": False,
    }


class VerifyP0PackagedDocumentCopyEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.product = self.root / "AccessibleChess"
        self.product.mkdir()
        self.exe = self.product / "AccessibleChess.exe"
        self.exe.write_bytes(b"accessible-chess-fixture")
        digest = hashlib.sha256(self.exe.read_bytes()).hexdigest()
        (self.root / "RELEASE_MANIFEST.json").write_text(
            json.dumps({"integration_sha": SHA, "human_tested": False, "nvda_verified": False}), encoding="utf-8"
        )
        (self.root / "SHA256SUMS.txt").write_text(
            f"{digest}  AccessibleChess/AccessibleChess.exe\n", encoding="utf-8"
        )
        self.evidence = self.root / "copy-evidence.json"
        self._write_evidence(_base_evidence())

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_evidence(self, value: dict[str, object]) -> None:
        self.evidence.write_text(json.dumps(value), encoding="utf-8")

    def test_complete_exact_evidence_passes(self) -> None:
        verify(self.evidence, self.product, SHA)

    def test_wrong_expected_product_sha_fails(self) -> None:
        with self.assertRaises(EvidenceError):
            verify(self.evidence, self.product, "2" * 40)

    def test_tampered_executable_fails(self) -> None:
        self.exe.write_bytes(b"tampered")
        with self.assertRaises(EvidenceError):
            verify(self.evidence, self.product, SHA)

    def test_duplicate_executable_checksum_entry_fails(self) -> None:
        digest = hashlib.sha256(self.exe.read_bytes()).hexdigest()
        (self.root / "SHA256SUMS.txt").write_text(
            f"{digest}  AccessibleChess/AccessibleChess.exe\n"
            f"{digest}  AccessibleChess/AccessibleChess.exe\n",
            encoding="utf-8",
        )
        with self.assertRaises(EvidenceError):
            verify(self.evidence, self.product, SHA)

    def test_false_foreground_product_proof_fails(self) -> None:
        value = _base_evidence()
        value["foreground_product_verified"] = False
        self._write_evidence(value)
        with self.assertRaises(EvidenceError):
            verify(self.evidence, self.product, SHA)

    def test_false_textpattern_selection_proof_fails(self) -> None:
        value = _base_evidence()
        value["textpattern_selection_supported"] = False
        self._write_evidence(value)
        with self.assertRaises(EvidenceError):
            verify(self.evidence, self.product, SHA)

    def test_false_visible_text_range_proof_fails(self) -> None:
        value = _base_evidence()
        value["static_text_visible_rectangle"] = False
        self._write_evidence(value)
        with self.assertRaisesRegex(EvidenceError, "static_text_visible_rectangle"):
            verify(self.evidence, self.product, SHA)

    def test_false_target_selection_proof_fails(self) -> None:
        value = _base_evidence()
        value["textpattern_target_selected"] = False
        self._write_evidence(value)
        with self.assertRaises(EvidenceError):
            verify(self.evidence, self.product, SHA)

    def test_wrong_selection_equality_contract_fails(self) -> None:
        value = _base_evidence()
        value["textpattern_selection_equality"] = "text only"
        self._write_evidence(value)
        with self.assertRaises(EvidenceError):
            verify(self.evidence, self.product, SHA)

    def test_false_clipboard_proof_fails(self) -> None:
        value = _base_evidence()
        value["ctrl_c_exact_clipboard"] = False
        self._write_evidence(value)
        with self.assertRaises(EvidenceError):
            verify(self.evidence, self.product, SHA)

    def test_empty_static_document_text_fails(self) -> None:
        value = _base_evidence()
        value["static_document_text"] = "   "
        self._write_evidence(value)
        with self.assertRaises(EvidenceError):
            verify(self.evidence, self.product, SHA)

    def test_machine_evidence_cannot_claim_human_or_nvda_verification(self) -> None:
        for key in ("human_tested", "nvda_verified"):
            with self.subTest(key=key):
                value = _base_evidence()
                value[key] = True
                self._write_evidence(value)
                with self.assertRaises(EvidenceError):
                    verify(self.evidence, self.product, SHA)

    def test_machine_acceptance_flags_are_required_exact_false_booleans(self) -> None:
        for key in ("human_tested", "nvda_verified"):
            for invalid in (None, "no", 0):
                with self.subTest(key=key, invalid=invalid):
                    value = _base_evidence()
                    if invalid is None:
                        del value[key]
                    else:
                        value[key] = invalid
                    self._write_evidence(value)
                    with self.assertRaisesRegex(EvidenceError, key):
                        verify(self.evidence, self.product, SHA)

    def test_duplicate_json_key_fails(self) -> None:
        self.evidence.write_text(
            '{"foreground_product_verified":true,"foreground_product_verified":true}',
            encoding="utf-8",
        )
        with self.assertRaises(EvidenceError):
            verify(self.evidence, self.product, SHA)

    def test_symlink_executable_fails_when_supported(self) -> None:
        target = self.root / "elsewhere.exe"
        target.write_bytes(self.exe.read_bytes())
        self.exe.unlink()
        try:
            self.exe.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlink unavailable on this runner")
        with self.assertRaises(EvidenceError):
            verify(self.evidence, self.product, SHA)


if __name__ == "__main__":
    unittest.main()
