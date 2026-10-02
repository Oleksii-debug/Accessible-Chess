from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
OLD_STAGE1_CORE = "b8586a26b9ab20c3d3ec0b0a3dbbbd53e38e94e6"
CURRENT_STAGE1_CORE = "b579ca0f59ba20f6b69b3a4b7d89589256d54852"
KEYMAP_CORE = "0ba06f548d39dad7372e0339b3e121fd1717cc05"
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "d01-pgn-workspace-webview.yml",
    ROOT / ".github" / "workflows" / "v2-markdown-semantic-lists-convergence.yml",
    ROOT / ".github" / "workflows" / "w2-library-source-catalog-d07-current.yml",
)
COMPOSITION_WORKFLOW = ROOT / ".github" / "workflows" / "version2-windows-composition.yml"
W3_WORKFLOW = ROOT / ".github" / "workflows" / "w3-takeback-clock-oracle-determinism.yml"
CLOCK_WORKFLOW = ROOT / ".github" / "workflows" / "chess-clock-switch-boundary.yml"


class CurrentProductStage1CoreGateConvergenceTests(unittest.TestCase):
    def test_retained_gates_admit_only_reviewed_old_and_current_core_identities(self) -> None:
        for path in WORKFLOWS:
            with self.subTest(workflow=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIn(OLD_STAGE1_CORE, text)
                self.assertIn(CURRENT_STAGE1_CORE, text)
                self.assertNotIn(
                    'if [ "${{ github.event.pull_request.head.ref }}" = '
                    '"integration/clock-engine-serial-intake-20261002" ]; then',
                    text,
                )

    def test_windows_materialization_keeps_keymap_core_exact(self) -> None:
        for path in WORKFLOWS[1:]:
            with self.subTest(workflow=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIn(
                    'git hash-object --no-filters acs/stage1_release_ui_core.py',
                    text,
                )
                self.assertIn(
                    f'test "$(git hash-object --no-filters acs/webapp_keymap_core.py)" = "{KEYMAP_CORE}"',
                    text,
                )
                self.assertIn(
                    "Protected blob mismatch after Windows materialization",
                    text,
                )

    def test_windows_composition_uses_exact_successor_identity_not_branch_name(self) -> None:
        text = COMPOSITION_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(CURRENT_STAGE1_CORE, text)
        self.assertIn(
            'if [ "$actual_stage1_core_blob" != "$V2_ACCEPTED_TAKEBACK_STAGE1_CORE_BLOB" ]; then',
            text,
        )
        self.assertNotIn(
            'if [ "${{ github.event.pull_request.head.ref }}" != '
            '"integration/clock-engine-serial-intake-20261002" ]',
            text,
        )

    def test_w3_gate_is_product_aware_and_core_identity_bound(self) -> None:
        text = W3_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(OLD_STAGE1_CORE, text)
        self.assertIn(CURRENT_STAGE1_CORE, text)
        self.assertIn(
            'if [ "${{ github.event.pull_request.base.ref }}" = "$product_ref" ]; then',
            text,
        )
        self.assertIn(
            "W3 Product convergence must not mutate runtime source ownership",
            text,
        )
        self.assertIn(
            'elif [ "${{ github.event.pull_request.head.ref }}" = "$product_ref" ]; then',
            text,
        )
        self.assertIn(
            "integrated_product=3f30f0d093fc19afe60e8262a70ccfdb3702d614",
            text,
        )
        self.assertIn(
            "60df98fc2138baa1ece727bac3eef4f8379a8e64",
            text,
        )
        self.assertNotIn("core_expected=", text)

    def test_clock_boundary_retains_exact_current_product_authority(self) -> None:
        text = CLOCK_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            'elif [ "$GH_HEAD_REF" = "$product_ref" ]; then',
            text,
        )
        self.assertIn(
            "integrated_product=3f30f0d093fc19afe60e8262a70ccfdb3702d614",
            text,
        )
        for digest in (
            "ced200e24405bbe0f6c1282e99fdc9440b675477",
            "2b0029b6da4dc88494c0e3cd4e891b886df45eda",
            "02cc2238a0ee3582707f8c926fc8e089faaeccc7",
            CURRENT_STAGE1_CORE,
        ):
            self.assertIn(digest, text)
        self.assertIn(
            "Clock Product convergence crossed foreign runtime ownership",
            text,
        )

    def test_d01_core_lock_remains_fail_closed(self) -> None:
        text = WORKFLOWS[0].read_text(encoding="utf-8")
        self.assertIn(
            'stage1_core_actual="$(git rev-parse HEAD:acs/stage1_release_ui_core.py)"',
            text,
        )
        self.assertIn(
            "Protected blob mismatch: acs/stage1_release_ui_core.py",
            text,
        )
        self.assertIn('case "$stage1_core_actual" in', text)


if __name__ == "__main__":
    unittest.main()
