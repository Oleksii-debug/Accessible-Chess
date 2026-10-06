from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "p0-packaged-release-probe-convergence.yml"

REQUIRED_RELEASE_PROBE_PATHS = (
    "scripts/p0_packaged_document_copy_probe.ps1",
    "tests/test_p0_packaged_document_copy_probe.py",
    "scripts/verify_p0_packaged_document_copy_evidence.py",
    "tests/test_verify_p0_packaged_document_copy_evidence.py",
    "scripts/p0g_packaged_hotkey_result_probe.ps1",
    "tests/test_p0g_packaged_hotkey_result_probe.py",
)


class P0PackagedReleaseProbeConvergenceTests(unittest.TestCase):
    def test_pull_request_identity_is_proven_structurally_not_by_branch_allowlist(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("EVENT_BASE_SHA:", workflow)
        self.assertIn("EVENT_HEAD_SHA:", workflow)
        self.assertIn('git merge-base --is-ancestor "$EVENT_BASE_SHA" HEAD', workflow)
        self.assertIn('git merge-base --is-ancestor "$EVENT_HEAD_SHA" HEAD', workflow)
        self.assertIn('git show -s --format=%P HEAD', workflow)
        self.assertIn('git diff --check "$EVENT_BASE_SHA..HEAD"', workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertNotIn('case "$base" in', workflow)
        self.assertNotIn("release/w4-v2-current-p0-candidate-20260926", workflow)

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
