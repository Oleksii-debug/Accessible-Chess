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
        self.assertIn("base_branch='${{ github.event.pull_request.base.ref }}'", text)
        self.assertIn('if [ -z "$base_branch" ]; then', text)
        self.assertIn('base_branch="$PRODUCT_BRANCH"', text)
        self.assertIn('git fetch --no-tags origin "$base_branch"', text)
        self.assertIn('live_base="$(git rev-parse "origin/$base_branch")"', text)
        self.assertIn('git merge-base --is-ancestor "$live_base" HEAD', text)
        self.assertIn('test "$(git merge-base "$live_base" HEAD)" = "$live_base"', text)
        self.assertIn('git diff --check "$live_base" HEAD', text)

    def test_shared_gate_does_not_require_direct_product_ancestry_for_every_pr(self) -> None:
        text = self.workflow
        self.assertNotIn('live_product=', text)
        self.assertNotIn('git fetch --no-tags origin "$PRODUCT_BRANCH"', text)
        self.assertNotIn('git merge-base --is-ancestor "$PRODUCT_BRANCH" HEAD', text)
        self.assertLess(
            text.index("base_branch='${{ github.event.pull_request.base.ref }}'"),
            text.index('base_branch="$PRODUCT_BRANCH"'),
        )

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
