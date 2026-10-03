from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "v2-library-acsdb-search-v4.yml"
STALE_FIXTURE_SHA = "04b5afb6894bed2e65c359cb1ffccc91e89f581e"
PRODUCT_BRANCH = "work/full-product-teacher-education-reachability-20260911"


class LibraryAcsdbSearchV4WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_qualifies_exact_candidate_against_live_pull_request_base(self) -> None:
        text = self.workflow
        self.assertIn(f"PRODUCT_BRANCH: {PRODUCT_BRANCH}", text)
        self.assertIn("expected='${{ github.event.pull_request.head.sha || github.sha }}'", text)
        self.assertIn("PR_HEAD_REF: ${{ github.event.pull_request.head.ref }}", text)
        self.assertIn("PR_BASE_REF: ${{ github.event.pull_request.base.ref }}", text)
        self.assertIn(
            'git fetch --no-tags origin "+refs/heads/$PR_BASE_REF:refs/remotes/origin/$PR_BASE_REF"',
            text,
        )
        self.assertIn('live_base="$(git rev-parse "refs/remotes/origin/$PR_BASE_REF")"', text)
        self.assertIn('git merge-base --is-ancestor "$live_base" HEAD', text)
        self.assertIn('qualification_base="$live_base"', text)
        self.assertIn('git diff --check "$qualification_base" HEAD', text)

    def test_product_pr_uses_only_latest_serial_increment_after_live_head_check(self) -> None:
        text = self.workflow
        self.assertIn(
            'if test -n "${PR_HEAD_REF:-}" && test "$PR_HEAD_REF" = "$PRODUCT_BRANCH"; then',
            text,
        )
        self.assertIn(
            'git fetch --no-tags origin "+refs/heads/$PRODUCT_BRANCH:refs/remotes/origin/$PRODUCT_BRANCH"',
            text,
        )
        self.assertIn('live_product="$(git rev-parse "refs/remotes/origin/$PRODUCT_BRANCH")"', text)
        self.assertIn('test "$live_product" = "$actual"', text)
        self.assertIn('qualification_base="$(git rev-parse HEAD^)"', text)

    def test_manual_dispatch_falls_back_to_live_product_ancestry(self) -> None:
        text = self.workflow
        fallback = text.index("else\n            git fetch --no-tags origin")
        ancestry = text.index('git merge-base --is-ancestor "$live_product" HEAD', fallback)
        assignment = text.index('qualification_base="$live_product"', ancestry)
        self.assertLess(fallback, ancestry)
        self.assertLess(ancestry, assignment)

    def test_does_not_replace_candidate_acsdb_with_historical_fixture(self) -> None:
        text = self.workflow
        self.assertNotIn(STALE_FIXTURE_SHA, text)
        self.assertNotIn("CURRENT_PRODUCT_BASE", text)
        self.assertNotIn("Checkout immutable current-product ACSDB fixture", text)
        self.assertNotIn("git checkout", text)
        self.assertNotIn("git diff --exit-code", text)

    def test_benchmarks_candidate_and_guards_its_own_contract(self) -> None:
        text = self.workflow
        self.assertIn("python -m tools.v2_library_acsdb_search_v4_benchmark --games 100000", text)
        self.assertIn("acs/acsdb.py", text)
        self.assertIn("tools/v2_library_acsdb_search_v4_benchmark.py", text)
        self.assertIn("tests.test_v2_library_acsdb_search_v4_workflow", text)
        self.assertIn("tests/test_v2_library_acsdb_search_v4_workflow.py", text)

    def test_retains_superseded_run_cancellation(self) -> None:
        text = self.workflow
        self.assertIn(
            "group: v2-library-acsdb-search-v4-${{ github.event.pull_request.number || github.ref }}",
            text,
        )
        self.assertIn("cancel-in-progress: true", text)


if __name__ == "__main__":
    unittest.main()
