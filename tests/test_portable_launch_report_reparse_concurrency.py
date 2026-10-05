from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "portable-launch-report-reparse-safety.yml"
CURRENT_PRODUCT = "59486e2c9eff903e416d59a0e7c349c22ee2111d"


class PortableLaunchReportReparseConcurrencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_concurrency_is_scoped_to_exact_candidate_identity(self) -> None:
        self.assertIn(
            "group: portable-launch-report-reparse-"
            "${{ github.event.pull_request.number || github.ref }}-"
            "${{ github.event.pull_request.head.sha || github.sha }}",
            self.text,
        )
        self.assertNotIn(
            "group: portable-launch-report-reparse-${{ github.ref }}\n",
            self.text,
        )
        self.assertIn("  cancel-in-progress: true\n", self.text)

    def test_current_product_is_the_qualification_base(self) -> None:
        self.assertIn(f"  PRODUCT_BASE: {CURRENT_PRODUCT}\n", self.text)
        self.assertNotIn("  PRODUCT_BASE: f726f9a82073f10e47dc095a2a10c974be0c1873\n", self.text)

    def test_focused_contract_is_part_of_trigger_and_owned_scope(self) -> None:
        path = "tests/test_portable_launch_report_reparse_concurrency.py"
        self.assertEqual(self.text.count(f"      - '{path}'\n"), 2)
        self.assertEqual(
            self.text.count(f"            '{path}' | LC_ALL=C sort)\"\n"),
            2,
        )

    def test_each_expensive_job_rejects_superseded_pull_request_head_first(self) -> None:
        self.assertEqual(
            self.text.count("      - name: Reject superseded pull-request candidate\n"),
            2,
        )
        self.assertEqual(
            self.text.count(
                '          git fetch --no-tags origin "refs/pull/${{ github.event.pull_request.number }}/head"\n'
            ),
            2,
        )
        self.assertEqual(
            self.text.count('          event_sha="${{ github.event.pull_request.head.sha }}"\n'),
            2,
        )
        self.assertEqual(
            self.text.count('          live_sha="$(git rev-parse FETCH_HEAD)"\n'),
            2,
        )
        self.assertEqual(
            self.text.count('          test "$live_sha" = "$event_sha" || {\n'),
            2,
        )
        self.assertEqual(
            self.text.count("          echo 'PORTABLE_LAUNCH_REPORT_EXACT_HEAD=PASS'\n"),
            2,
        )
        for job in ("  contract:\n", "  windows-native-build:\n"):
            section = self.text.split(job, 1)[1]
            self.assertLess(
                section.index("      - name: Reject superseded pull-request candidate\n"),
                section.index("      - name: Prove exact serial candidate and owned scope\n"),
            )

    def test_launcher_authority_bytes_and_regressions_remain_pinned(self) -> None:
        self.assertIn("  LAUNCHER_BLOB: 6f0ec228a8ae1ef1f4a831f45f3d89eff3713f0f\n", self.text)
        self.assertIn("  CONTRACT_TEST_BLOB: 4e8d23f24794d1167042a83f2983957a537a244f\n", self.text)
        self.assertIn("  CORE_GUARD_TEST_BLOB: 410fddf296caf40e273c9916c078cc22a193876f\n", self.text)
        self.assertIn("          tests.test_portable_launcher_contract\n", self.text)
        self.assertIn("          tests.test_portable_launcher_core_guard\n", self.text)
        self.assertIn("          tests.test_portable_launch_report_reparse_concurrency\n", self.text)


if __name__ == "__main__":
    unittest.main()
