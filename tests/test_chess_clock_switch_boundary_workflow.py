from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "chess-clock-switch-boundary.yml"
SOURCE_BRANCH = "fix/clock-switch-exact-charge-20261002"
INTEGRATION_BRANCH = "integration/clock-engine-serial-intake-20261002"
CURRENT_PRODUCT_BRANCH = "work/full-product-teacher-education-reachability-20260911"
CLOCK_OWNER = "77bfa596c7bbb6d2cdb06856584d5bf0ce7de2bf"
CLOCK_BLOB = "ced200e24405bbe0f6c1282e99fdc9440b675477"
CLOCK_TEST_BLOB = "2b0029b6da4dc88494c0e3cd4e891b886df45eda"


class ChessClockSwitchBoundaryWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_pull_request_trigger_tracks_contract_regression_test(self) -> None:
        pull_start = self.workflow.index("  pull_request:\n")
        permissions_start = self.workflow.index("\npermissions:", pull_start)
        pull = self.workflow[pull_start:permissions_start]
        self.assertIn(".github/workflows/chess-clock-switch-boundary.yml", pull)
        self.assertIn("acs/clock_service.py", pull)
        self.assertIn("tests/test_clock_service.py", pull)
        self.assertIn("tests/test_chess_clock_switch_boundary_workflow.py", pull)

    def test_lane_identity_works_for_pull_requests_and_pushes(self) -> None:
        self.assertIn(
            "LANE_REF: ${{ github.head_ref || github.ref_name }}",
            self.workflow,
        )
        self.assertIn(f'if [ "$LANE_REF" = "{SOURCE_BRANCH}" ]; then', self.workflow)
        self.assertIn(
            f'elif [ "$LANE_REF" = "{INTEGRATION_BRANCH}" ]; then',
            self.workflow,
        )

    def test_retained_product_proves_owner_ancestry_and_exact_blobs(self) -> None:
        self.assertIn(f"clock_owner={CLOCK_OWNER}", self.workflow)
        self.assertIn(f"clock_blob={CLOCK_BLOB}", self.workflow)
        self.assertIn(f"clock_test_blob={CLOCK_TEST_BLOB}", self.workflow)
        self.assertIn('git merge-base --is-ancestor "$clock_owner" HEAD', self.workflow)
        self.assertIn(
            'test "$(git rev-parse HEAD:acs/clock_service.py)" = "$clock_blob"',
            self.workflow,
        )
        self.assertIn(
            'test "$(git rev-parse HEAD:tests/test_clock_service.py)" = "$clock_test_blob"',
            self.workflow,
        )
        self.assertIn("Retained clock authority PASS", self.workflow)

    def test_original_source_lane_keeps_exact_three_path_scope(self) -> None:
        source_start = self.workflow.index(
            f'if [ "$LANE_REF" = "{SOURCE_BRANCH}" ]; then'
        )
        integration_start = self.workflow.index(
            f'elif [ "$LANE_REF" = "{INTEGRATION_BRANCH}" ]; then', source_start
        )
        source = self.workflow[source_start:integration_start]
        for path in (
            ".github/workflows/chess-clock-switch-boundary.yml",
            "acs/clock_service.py",
            "tests/test_clock_service.py",
        ):
            with self.subTest(path=path):
                self.assertIn(path, source)
        self.assertIn('test "$actual" = "$expected"', source)
        self.assertIn(
            'git diff --quiet "$source_base" HEAD -- acs/chesscore.py acs/gametree.py',
            source,
        )
        self.assertNotIn("tests/test_chess_clock_switch_boundary_workflow.py", source)

    def test_serial_intake_keeps_exact_multi_owner_fence(self) -> None:
        integration_start = self.workflow.index(
            f'elif [ "$LANE_REF" = "{INTEGRATION_BRANCH}" ]; then'
        )
        retained_start = self.workflow.index("\n          else\n", integration_start)
        integration = self.workflow[integration_start:retained_start]
        self.assertIn(CURRENT_PRODUCT_BRANCH, integration)
        self.assertIn("Unexpected clock/engine intake scope", integration)
        self.assertIn("acs/engine_game_session.py", integration)
        self.assertIn("tests/test_clock_engine_serial_acceptance.py", integration)
        self.assertIn("tests/test_engine_takeback_atomic_acceptance.py", integration)
        self.assertIn(
            'git diff --quiet "$scope_base" HEAD -- acs/chesscore.py acs/gametree.py',
            integration,
        )

    def test_retained_product_does_not_reapply_source_scope_to_cumulative_diff(self) -> None:
        integration_start = self.workflow.index(
            f'elif [ "$LANE_REF" = "{INTEGRATION_BRANCH}" ]; then'
        )
        retained_start = self.workflow.index("\n          else\n", integration_start)
        retained_end = self.workflow.index("\n          fi\n", retained_start)
        retained = self.workflow[retained_start:retained_end]
        self.assertIn("Retained clock authority PASS", retained)
        self.assertNotIn("Unexpected standalone clock source scope", retained)
        self.assertNotIn("Unexpected clock/engine intake scope", retained)
        self.assertNotIn('git diff --name-only "$scope_base" HEAD', retained)
        self.assertNotIn("acs/chesscore.py acs/gametree.py", retained)

    def test_dual_os_focused_and_full_regressions_remain(self) -> None:
        self.assertIn("os: [ubuntu-22.04, windows-2025]", self.workflow)
        self.assertIn("tests.test_clock_service", self.workflow)
        self.assertIn("tests.test_engine_game_session", self.workflow)
        self.assertIn("tests.test_engine_takeback_atomic_acceptance", self.workflow)
        self.assertIn("python -m unittest discover -s tests -v", self.workflow)
        self.assertIn("python -m pytest -q tests", self.workflow)


if __name__ == "__main__":
    unittest.main()
