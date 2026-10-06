from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.verify_p0_packaged_document_copy_evidence import EvidenceError
from scripts.verify_p0g_packaged_hotkey_result_evidence import verify


SHA = "c" * 40


def _evidence() -> dict[str, object]:
    return {
        "product_sha": SHA,
        "discovery": "connected provider-root ControlView",
        "hotkey_focus_path": "board-launcher outside role=application",
        "board_application_entered": False,
        "engine_enable_state": "already-enabled",
        "native_keyboard_dispatch": True,
        "foreground_product_verified": True,
        "manifest_product_sha_verified": True,
        "executable_checksum_verified": True,
        "alt_1_precondition_selected_state": "Variant 2. depth 12 eval +0.10",
        "alt_1_action_occurred": True,
        "alt_1_selected_state": "Variant 1. depth 12 eval +0.20",
        "alt_1_accessible_result_exposed": True,
        "alt_1_result": "Variant 1. depth 12, eval +0.20",
        "alt_2_precondition_selected_state": "Variant 1. depth 12 eval +0.20",
        "alt_2_action_occurred": True,
        "alt_2_selected_state": "Variant 2. depth 12 eval +0.10",
        "alt_2_accessible_result_exposed": True,
        "alt_2_result": "Variant 2. depth 12, eval +0.10",
        "raw_uci_or_debug_exposed": False,
        "human_tested": False,
        "nvda_verified": False,
    }


class VerifyP0GPackagedHotkeyResultEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.package = Path(self.temp.name)
        self.product = self.package / "AccessibleChess"
        self.product.mkdir()
        self.exe = self.product / "AccessibleChess.exe"
        self.exe.write_bytes(b"p0g-fixture")
        digest = hashlib.sha256(self.exe.read_bytes()).hexdigest()
        (self.package / "RELEASE_MANIFEST.json").write_text(
            json.dumps({"integration_sha": SHA, "human_tested": False, "nvda_verified": False}), encoding="utf-8"
        )
        (self.package / "SHA256SUMS.txt").write_text(
            f"{digest}  AccessibleChess/AccessibleChess.exe\n", encoding="utf-8"
        )
        self.path = self.package / "p0g.json"
        self._write(_evidence())

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write(self, value: dict[str, object]) -> None:
        self.path.write_text(json.dumps(value), encoding="utf-8")

    def test_complete_causal_evidence_passes(self) -> None:
        verify(self.path, self.product, SHA)

    def test_wrong_product_sha_fails(self) -> None:
        value = _evidence()
        value["product_sha"] = "d" * 40
        self._write(value)
        with self.assertRaises(EvidenceError):
            verify(self.path, self.product, SHA)

    def test_tampered_executable_fails(self) -> None:
        self.exe.write_bytes(b"tampered")
        with self.assertRaises(EvidenceError):
            verify(self.path, self.product, SHA)

    def test_required_true_flags_fail_closed(self) -> None:
        for key in (
            "native_keyboard_dispatch",
            "foreground_product_verified",
            "manifest_product_sha_verified",
            "executable_checksum_verified",
            "alt_1_action_occurred",
            "alt_1_accessible_result_exposed",
            "alt_2_action_occurred",
            "alt_2_accessible_result_exposed",
        ):
            with self.subTest(key=key):
                value = _evidence()
                value[key] = False
                self._write(value)
                with self.assertRaises(EvidenceError):
                    verify(self.path, self.product, SHA)

    def test_forbidden_true_flags_fail_closed(self) -> None:
        for key in (
            "board_application_entered",
            "raw_uci_or_debug_exposed",
            "human_tested",
            "nvda_verified",
        ):
            with self.subTest(key=key):
                value = _evidence()
                value[key] = True
                self._write(value)
                with self.assertRaises(EvidenceError):
                    verify(self.path, self.product, SHA)

    def test_noncausal_same_state_fails(self) -> None:
        value = _evidence()
        value["alt_1_precondition_selected_state"] = value["alt_1_selected_state"]
        self._write(value)
        with self.assertRaises(EvidenceError):
            verify(self.path, self.product, SHA)

    def test_identical_results_fail(self) -> None:
        value = _evidence()
        value["alt_2_result"] = value["alt_1_result"]
        self._write(value)
        with self.assertRaises(EvidenceError):
            verify(self.path, self.product, SHA)

    def test_missing_depth_eval_or_variation_identity_fails(self) -> None:
        for text in (
            "Variant 1. eval +0.20",
            "Variant 1. depth 12",
            "Depth 12, eval +0.20",
        ):
            with self.subTest(text=text):
                value = _evidence()
                value["alt_1_result"] = text
                self._write(value)
                with self.assertRaises(EvidenceError):
                    verify(self.path, self.product, SHA)

    def test_raw_debug_result_fails(self) -> None:
        value = _evidence()
        value["alt_1_result"] = "Variant 1. depth 12, eval +0.20 debug"
        self._write(value)
        with self.assertRaises(EvidenceError):
            verify(self.path, self.product, SHA)

    def test_duplicate_json_key_fails(self) -> None:
        self.path.write_text('{"product_sha":"' + SHA + '","product_sha":"' + SHA + '"}', encoding="utf-8")
        with self.assertRaises(EvidenceError):
            verify(self.path, self.product, SHA)


if __name__ == "__main__":
    unittest.main()
