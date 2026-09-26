from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_RELEASE_PROBE_PATHS = (
    "scripts/p0_packaged_document_copy_probe.ps1",
    "tests/test_p0_packaged_document_copy_probe.py",
    "scripts/verify_p0_packaged_document_copy_evidence.py",
    "tests/test_verify_p0_packaged_document_copy_evidence.py",
    "scripts/p0g_packaged_hotkey_result_probe.ps1",
    "tests/test_p0g_packaged_hotkey_result_probe.py",
)


class P0PackagedReleaseProbeConvergenceTests(unittest.TestCase):
    def test_copy_and_hotkey_packaged_acceptance_probes_are_both_present(self) -> None:
        missing = [path for path in REQUIRED_RELEASE_PROBE_PATHS if not (ROOT / path).is_file()]
        self.assertFalse(
            missing,
            "P0 packaged release qualification is incomplete; missing: " + ", ".join(missing),
        )

    def test_packaged_probe_contracts_remain_independent(self) -> None:
        copy_probe = (ROOT / "scripts/p0_packaged_document_copy_probe.ps1").read_text(encoding="utf-8")
        hotkey_probe = (ROOT / "scripts/p0g_packaged_hotkey_result_probe.ps1").read_text(encoding="utf-8")
        self.assertIn("AccessibleChess.exe", copy_probe)
        self.assertIn("AccessibleChess.exe", hotkey_probe)
        self.assertIn("Ctrl+C", copy_probe)
        self.assertTrue("Alt+1" in hotkey_probe or "VK_1" in hotkey_probe or "0x31" in hotkey_probe)
        self.assertNotEqual(copy_probe, hotkey_probe, "distinct P0 acceptance probes must not collapse into one fake oracle")


if __name__ == "__main__":
    unittest.main()
