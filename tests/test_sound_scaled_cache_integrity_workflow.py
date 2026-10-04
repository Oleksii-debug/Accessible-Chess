from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "sound-scaled-cache-integrity.yml"


class SoundScaledCacheIntegrityWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_nested_product_candidate_reconciles_event_base_to_live_product(self) -> None:
        self.assertIn('BASE_SHA: ${{ github.event.pull_request.base.sha }}', self.text)
        self.assertIn(
            'git fetch --no-tags origin "+refs/heads/$product_ref:refs/remotes/origin/$product_ref"',
            self.text,
        )
        self.assertIn(
            'live_product="$(git rev-parse "refs/remotes/origin/$product_ref")"',
            self.text,
        )
        self.assertIn('git merge-base --is-ancestor "$BASE_SHA" "$live_product"', self.text)
        self.assertIn('git merge-base --is-ancestor "$live_product" HEAD', self.text)
        self.assertIn('test "$(git merge-base "$live_product" HEAD)" = "$live_product"', self.text)
        self.assertIn('scope_base="$live_product"', self.text)
        self.assertIn('git diff --check "$scope_base" HEAD', self.text)
        self.assertNotIn('git diff --check "$BASE_SHA" HEAD', self.text)

    def test_retained_product_mode_is_exact_blob_bound(self) -> None:
        self.assertIn('if [ "$HEAD_REF" = "$product_ref" ]; then', self.text)
        self.assertIn(
            "integrated_sound_product=3f30f0d093fc19afe60e8262a70ccfdb3702d614",
            self.text,
        )
        for digest in (
            "28559f05972ed46145e4c19d7f30973bbe7937be",
            "64c69688d01c19cb5ad411e46da6869d2a6ccd07",
            "e45bd14fa742e437c8580bf7f23796fe57bb5b3d",
            "b6dc29af150ec30de65691d90dcd6596b755662a",
        ):
            self.assertIn(digest, self.text)

    def test_nested_scope_stays_sound_owner_only(self) -> None:
        self.assertIn("Unexpected sound-cache scope:", self.text)
        self.assertIn('git diff --name-only "$scope_base" HEAD', self.text)
        self.assertNotIn('git diff --name-only "$BASE_SHA" HEAD', self.text)
        for approved in (
            "acs/sound_events.py",
            "acs/sound_runtime.py",
            "acs/sound_windows.py",
            "acs/settings.py",
            "acs/stage1_release_ui_core.py",
            "acs/version2_release_app.py",
            "tests/test_sound_runtime.py",
            "tests/test_sound_events.py",
            "tests/test_settings.py",
            "tests/test_stage1_engine_play_ui.py",
            "tests/test_sound_scaled_cache_integrity_workflow.py",
            "version2-windows-composition",
            "d01-pgn-workspace-webview",
            "w4-v2-p0-fresh-windows-candidate",
            "w6-v2-package-preflight-current-runtime",
            "w6-v2-package-assembler",
        ):
            self.assertIn(approved, self.text)

    def test_workflow_structure_is_not_duplicated_or_corrupted(self) -> None:
        self.assertEqual(self.text.count("- name: Compile sound authority"), 1)
        self.assertEqual(self.text.count("- name: Run sound regressions"), 1)
        self.assertEqual(self.text.count("jobs:"), 1)
        self.assertEqual(self.text.count("if __name__"), 0)
        self.assertIn("w4-v2-p0-fresh-windows-candidate", self.text)
        self.assertIn("|| true)", self.text)

    def test_dual_os_regressions_and_contract_run(self) -> None:
        self.assertIn("os: [ubuntu-22.04, windows-2025]", self.text)
        for module in (
            "tests.test_sound_runtime",
            "tests.test_settings",
            "tests.test_sound_events",
            "tests.test_stage1_release_composition_ui",
            "tests.test_stage1_engine_play_ui",
            "tests.test_dev3_sound_failure_isolation",
            "tests.test_sound_scaled_cache_integrity_workflow",
            "tests.test_version2_release_payload",
            "tests.test_w4_v2_p0_fresh_candidate_workflow",
        ):
            self.assertIn(module, self.text)

    def test_webview_and_keymap_syntax_checks_are_present(self) -> None:
        self.assertIn("node --check web/stage1_release_bootstrap.js", self.text)
        self.assertIn("python -m json.tool web/keybindings.json", self.text)

    def test_superseded_sound_runs_are_cancelled(self) -> None:
        self.assertIn("group: sound-scaled-cache-integrity-", self.text)
        self.assertIn("cancel-in-progress: true", self.text)


if __name__ == "__main__":
    unittest.main()
