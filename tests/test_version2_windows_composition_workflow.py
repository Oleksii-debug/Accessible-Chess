from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "version2-windows-composition.yml"
CURRENT_PRODUCT_BRANCH = "work/full-product-teacher-education-reachability-20260911"


class Version2WindowsCompositionWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def _trigger_blocks(self) -> tuple[str, str]:
        push_start = self.workflow.index("  push:\n")
        pull_start = self.workflow.index("  pull_request:\n")
        permissions = self.workflow.index("\npermissions:", pull_start)
        return (
            self.workflow[push_start:pull_start],
            self.workflow[pull_start:permissions],
        )

    def test_integrated_push_uses_live_full_product_authority(self) -> None:
        push, _ = self._trigger_blocks()
        self.assertIn(CURRENT_PRODUCT_BRANCH, push)
        self.assertNotIn("work/version2-windows-composition-20260828", self.workflow)

    def test_pull_requests_remain_available_to_stacked_product_candidates(self) -> None:
        _, pull = self._trigger_blocks()
        self.assertIn("paths:", pull)
        self.assertNotIn("branches:", pull)
        self.assertIn("tests/test_version2_*.py", pull)
        self.assertIn("tests/test_v2_windows_*.py", pull)
        self.assertIn(".github/workflows/version2-windows-composition.yml", pull)

    def test_geometry_uses_live_product_only_for_product_based_prs(self) -> None:
        self.assertIn("fetch-depth: 0", self.workflow)
        self.assertIn(
            "ref: ${{ github.event.pull_request.head.sha || github.sha }}",
            self.workflow,
        )
        self.assertIn(
            "PR_HEAD_SHA: ${{ github.event.pull_request.head.sha }}",
            self.workflow,
        )
        self.assertIn(
            "PR_BASE_SHA: ${{ github.event.pull_request.base.sha }}",
            self.workflow,
        )
        self.assertIn(
            "PR_BASE_REF: ${{ github.event.pull_request.base.ref }}",
            self.workflow,
        )
        self.assertIn(
            f"PRODUCT_BRANCH: {CURRENT_PRODUCT_BRANCH}",
            self.workflow,
        )
        self.assertIn(
            "PUSH_BASE_SHA: ${{ github.event.before }}",
            self.workflow,
        )
        self.assertNotIn("refs/remotes/origin/$PR_BASE_REF", self.workflow)
        self.assertIn('test "$(git rev-parse HEAD)" = "$expected_head"', self.workflow)
        self.assertIn('event_base="${PR_BASE_SHA:-}"', self.workflow)
        self.assertIn('base_ref="${PR_BASE_REF:-}"', self.workflow)
        self.assertIn('if [ "$base_ref" = "$PRODUCT_BRANCH" ]; then', self.workflow)
        self.assertIn(
            'git fetch --no-tags origin "+refs/heads/$PRODUCT_BRANCH:refs/remotes/origin/$PRODUCT_BRANCH"',
            self.workflow,
        )
        self.assertIn(
            'live_product="$(git rev-parse "refs/remotes/origin/$PRODUCT_BRANCH")"',
            self.workflow,
        )
        self.assertIn(
            'git merge-base --is-ancestor "$event_base" "$live_product"',
            self.workflow,
        )
        self.assertIn(
            'git merge-base --is-ancestor "$live_product" HEAD',
            self.workflow,
        )
        self.assertIn(
            'test "$(git merge-base "$live_product" HEAD)" = "$live_product"',
            self.workflow,
        )
        self.assertIn('scope_base="$live_product"', self.workflow)
        self.assertIn('scope_base="$event_base"', self.workflow)
        self.assertIn('git merge-base --is-ancestor "$scope_base" HEAD', self.workflow)
        self.assertIn('test "$(git merge-base "$scope_base" HEAD)" = "$scope_base"', self.workflow)
        self.assertIn('git diff --check "$scope_base" HEAD', self.workflow)

    def test_push_geometry_keeps_immutable_batch_boundary(self) -> None:
        self.assertIn('push_base="${PUSH_BASE_SHA:-}"', self.workflow)
        self.assertIn("zero_sha='0000000000000000000000000000000000000000'", self.workflow)
        self.assertIn('scope_base="$push_base"', self.workflow)
        self.assertIn('scope_base="$(git rev-parse HEAD^)"', self.workflow)

    def test_upstream_and_protected_release_authorities_remain_fail_closed(self) -> None:
        for token in (
            "V2_FORMATS_UPSTREAM",
            "V2_ACCEPTED_STAGE1_BOOTSTRAP_BLOB",
            "V2_ACCEPTED_STAGE1_UI_BLOB",
            "V2_ACCEPTED_P0G_STAGE1_UI_BLOB",
            "V2_ACCEPTED_ENGINE_TIMEOUT_STAGE1_UI_BLOB",
            "V2_ACCEPTED_TAKEBACK_STAGE1_CORE_BLOB",
            "V2_ACCEPTED_SOUND_RELEASE_APP_BLOB",
            "V2_ACCEPTED_PGN_WORKSPACE_BLOB",
            "V2_ACCEPTED_RELEASE_PREFLIGHT_BLOB",
        ):
            with self.subTest(token=token):
                self.assertIn(token, self.workflow)
        self.assertIn(
            'git merge-base --is-ancestor "$V2_FORMATS_UPSTREAM" HEAD',
            self.workflow,
        )
        self.assertIn(
            "V2_ACCEPTED_SOUND_RELEASE_APP_BLOB: dbbcaabd4f6df0ab615095949d464d1371b0ffef",
            self.workflow,
        )
        self.assertIn(
            'if [ "$actual_release_app_blob" != "$V2_ACCEPTED_SOUND_RELEASE_APP_BLOB" ]; then',
            self.workflow,
        )
        self.assertIn(
            'git diff --quiet "$scope_base" HEAD --',
            self.workflow,
        )
        self.assertIn("tools/qa", self.workflow)

    def test_reviewed_stage1_core_successor_is_not_branch_name_coupled(self) -> None:
        self.assertIn(
            "V2_ACCEPTED_TAKEBACK_STAGE1_CORE_BLOB: b579ca0f59ba20f6b69b3a4b7d89589256d54852",
            self.workflow,
        )
        self.assertIn(
            'if [ "$actual_stage1_core_blob" != "$V2_ACCEPTED_TAKEBACK_STAGE1_CORE_BLOB" ]; then',
            self.workflow,
        )
        self.assertNotIn(
            "integration/clock-engine-serial-intake-20261002",
            self.workflow,
        )
        self.assertNotIn(
            "github.event.pull_request.head.ref",
            self.workflow,
        )
        self.assertNotIn(
            "b8586a26b9ab20c3d3ec0b0a3dbbbd53e38e94e6|",
            self.workflow,
        )

    def test_dual_os_broad_qualification_and_diagnostics_remain_required(self) -> None:
        self.assertIn("os: [ubuntu-22.04, windows-2025]", self.workflow)
        self.assertIn("pytest==8.4.2", self.workflow)
        self.assertIn("tests.test_version2_windows_composition_workflow", self.workflow)
        self.assertIn("python -m unittest discover -s tests -v", self.workflow)
        self.assertIn("actions/upload-artifact@v4", self.workflow)
        self.assertIn("python -m pytest -q tests", self.workflow)
        self.assertIn("python -m acs.selftest", self.workflow)
        self.assertIn("python run_accessible_chess.py --diagnostic", self.workflow)
        self.assertIn("python run_accessible_chess_v2.py --diagnostic", self.workflow)


if __name__ == "__main__":
    unittest.main()
