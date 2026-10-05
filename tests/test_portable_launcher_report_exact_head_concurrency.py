from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "portable-launch-report-reparse-safety.yml"


class PortableLaunchReportExactHeadConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_exact_candidate_concurrency_preserves_same_sha_cancellation(self) -> None:
        self.assertIn(
            "group: portable-launch-report-reparse-"
            "${{ github.event.pull_request.number || github.ref }}-"
            "${{ github.event.pull_request.head.sha || github.sha }}",
            self.text,
        )
        self.assertIn("  cancel-in-progress: true\n", self.text)
        self.assertNotIn(
            "group: portable-launch-report-reparse-${{ github.ref }}\n",
            self.text,
        )

    def test_historical_launcher_authority_stays_pinned(self) -> None:
        self.assertIn(
            "  PRODUCT_BASE: f726f9a82073f10e47dc095a2a10c974be0c1873\n",
            self.text,
        )
        self.assertIn(
            "  LAUNCHER_AUTHORITY: 5a923abf9a32f6c943b9640313e4a1b7ff479825\n",
            self.text,
        )
        self.assertIn(
            "historical_actual=\"$(git diff --name-only "
            "\"$PRODUCT_BASE\" \"$LAUNCHER_AUTHORITY\" | LC_ALL=C sort)\"",
            self.text,
        )
        for path in (
            ".github/workflows/portable-launch-report-reparse-safety.yml",
            "packaging/portable_launcher.c",
            "tests/test_portable_launcher_contract.py",
            "tests/test_portable_launcher_core_guard.py",
        ):
            self.assertIn(f"            '{path}'", self.text)

    def test_current_product_successor_is_two_path_qualification_only(self) -> None:
        self.assertIn(
            "  CURRENT_PRODUCT_BASE: 59486e2c9eff903e416d59a0e7c349c22ee2111d\n",
            self.text,
        )
        self.assertIn(
            '          git merge-base --is-ancestor "$LAUNCHER_AUTHORITY" "$CURRENT_PRODUCT_BASE"\n',
            self.text,
        )
        self.assertIn(
            '          git merge-base --is-ancestor "$CURRENT_PRODUCT_BASE" HEAD\n',
            self.text,
        )
        self.assertIn(
            '          current_actual="$(git diff --name-only "$CURRENT_PRODUCT_BASE" HEAD | LC_ALL=C sort)"\n',
            self.text,
        )
        self.assertIn(
            "            'tests/test_portable_launcher_report_exact_head_concurrency.py'",
            self.text,
        )

    def test_runtime_and_launcher_contract_blobs_remain_immutable(self) -> None:
        self.assertIn(
            "  LAUNCHER_BLOB: 6f0ec228a8ae1ef1f4a831f45f3d89eff3713f0f\n",
            self.text,
        )
        self.assertIn(
            "  CONTRACT_TEST_BLOB: 4e8d23f24794d1167042a83f2983957a537a244f\n",
            self.text,
        )
        self.assertIn(
            "  CORE_GUARD_TEST_BLOB: 410fddf296caf40e273c9916c078cc22a193876f\n",
            self.text,
        )
        self.assertEqual(
            self.text.count(
                'test "$(git hash-object packaging/portable_launcher.c)" = "$LAUNCHER_BLOB"'
            ),
            2,
        )

    def test_both_jobs_reject_superseded_pr_heads_before_expensive_work(self) -> None:
        self.assertEqual(
            self.text.count("      - name: Reject superseded pull-request candidate\n"),
            2,
        )
        self.assertEqual(
            self.text.count(
                '          git fetch --no-tags origin "refs/pull/${PR_NUMBER}/head"\n'
            ),
            2,
        )
        contract = self.text.index("  contract:\n")
        windows = self.text.index("  windows-native-build:\n")
        contract_text = self.text[contract:windows]
        windows_text = self.text[windows:]
        self.assertLess(
            contract_text.index("      - name: Reject superseded pull-request candidate\n"),
            contract_text.index("      - name: Setup exact Python\n"),
        )
        self.assertLess(
            windows_text.index("      - name: Reject superseded pull-request candidate\n"),
            windows_text.index("      - name: Build native x64 launcher with warnings as errors\n"),
        )

    def test_workflow_runs_this_contract_and_retriggers_when_it_changes(self) -> None:
        self.assertGreaterEqual(
            self.text.count(
                "      - 'tests/test_portable_launcher_report_exact_head_concurrency.py'\n"
            ),
            2,
        )
        self.assertIn(
            "          tests.test_portable_launcher_report_exact_head_concurrency\n",
            self.text,
        )


if __name__ == "__main__":
    unittest.main()
