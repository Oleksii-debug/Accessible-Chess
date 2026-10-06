from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "v2-html-current-d06-recovery.yml"
CURRENT_PRODUCT_BRANCH = "work/full-product-teacher-education-reachability-20260911"


class V2HtmlCurrentD06RecoveryWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def _trigger_blocks(self) -> tuple[str, str]:
        push_start = self.workflow.index("  push:\n")
        pull_start = self.workflow.index("  pull_request:\n")
        dispatch_start = self.workflow.index("  workflow_dispatch:\n", pull_start)
        return (
            self.workflow[push_start:pull_start],
            self.workflow[pull_start:dispatch_start],
        )

    def test_current_product_push_and_stacked_prs_are_qualified(self) -> None:
        push, pull = self._trigger_blocks()
        self.assertIn(CURRENT_PRODUCT_BRANCH, push)
        self.assertNotIn("branches:", pull)
        required = (
            "acs/book_html_import.py",
            "tests/test_v2_book_html_import.py",
            "tests/test_v2_html_semantic_lists.py",
            "tests/test_v2_html_current_d06_recovery_workflow.py",
            ".github/workflows/v2-html-current-d06-recovery.yml",
        )
        for block in (push, pull):
            self.assertIn("paths:", block)
            for item in required:
                with self.subTest(item=item):
                    self.assertIn(item, block)

    def test_live_candidate_geometry_replaces_historical_parent_diff(self) -> None:
        self.assertNotIn("CURRENT_PARENT:", self.workflow)
        self.assertNotIn("fcfa2963a9bc71ab43f2e68b5118a7d4ec1aba9d", self.workflow)
        self.assertIn(
            "PR_BASE_REF: ${{ github.event.pull_request.base.ref }}",
            self.workflow,
        )
        self.assertIn(
            "PR_BASE_SHA: ${{ github.event.pull_request.base.sha }}",
            self.workflow,
        )
        self.assertIn("PUSH_BASE_SHA: ${{ github.event.before }}", self.workflow)
        self.assertIn(
            'git fetch --no-tags origin "+refs/heads/$PR_BASE_REF:refs/remotes/origin/$PR_BASE_REF"',
            self.workflow,
        )
        self.assertIn(
            'live_base="$(git rev-parse "refs/remotes/origin/$PR_BASE_REF")"',
            self.workflow,
        )
        self.assertIn('git merge-base --is-ancestor "$live_base" HEAD', self.workflow)
        self.assertIn('base="$live_base"', self.workflow)
        self.assertIn('base="$PR_BASE_SHA"', self.workflow)
        self.assertIn('base="${PUSH_BASE_SHA:-}"', self.workflow)
        self.assertIn('base="$(git rev-parse HEAD^)"', self.workflow)
        self.assertIn('git diff --check "$base" HEAD', self.workflow)
        self.assertIn("PR head is stale against live base", self.workflow)

    def test_candidate_scope_is_allowlisted_without_requiring_every_owned_path(self) -> None:
        self.assertIn('changed="$(git diff --name-only "$base" HEAD | sort)"', self.workflow)
        self.assertIn('case "$path" in', self.workflow)
        for item in (
            ".github/workflows/v2-html-current-d06-recovery.yml",
            "acs/book_html_import.py",
            "tests/test_v2_book_html_import.py",
            "tests/test_v2_html_semantic_lists.py",
            "tests/test_v2_html_current_d06_recovery_workflow.py",
        ):
            with self.subTest(item=item):
                self.assertIn(item, self.workflow)
        self.assertIn("Unexpected HTML/D06 candidate path", self.workflow)
        self.assertNotIn('test "$changed" = "$expected"', self.workflow)

    def test_mutable_html_surfaces_are_not_frozen_to_historical_blobs(self) -> None:
        self.assertNotIn("HTML_ADAPTER_BLOB:", self.workflow)
        self.assertNotIn("HTML_LIST_TEST_BLOB:", self.workflow)
        self.assertNotIn("ORIGINAL_HTML_TEST_BLOB:", self.workflow)
        self.assertNotIn(
            'test "$(git rev-parse HEAD:acs/book_html_import.py)"',
            self.workflow,
        )
        self.assertNotIn(
            'test "$(git rev-parse HEAD:tests/test_v2_book_html_import.py)"',
            self.workflow,
        )
        self.assertNotIn(
            'test "$(git rev-parse HEAD:tests/test_v2_html_semantic_lists.py)"',
            self.workflow,
        )

    def test_real_book_oracles_remain_byte_pinned_and_semantically_asserted(self) -> None:
        self.assertIn(
            "REAL_HTML_ORACLE_BLOB: e6bbbebc204b2ea2e34fff629e841c99aa13ef52",
            self.workflow,
        )
        self.assertIn(
            "D06_REAL_BOOK_ORACLE_BLOB: 34fbce8e5e6e5faa1cf76d62d2556e9d4c90e5a1",
            self.workflow,
        )
        self.assertIn(
            'test "$(git rev-parse HEAD:scripts/v2_real_html_book_oracle.py)" = "$REAL_HTML_ORACLE_BLOB"',
            self.workflow,
        )
        self.assertIn(
            'test "$(git rev-parse HEAD:scripts/v2_pgn_nested_comment_real_book_oracle.py)" = "$D06_REAL_BOOK_ORACLE_BLOB"',
            self.workflow,
        )
        self.assertIn("EXPECTED_GAME_COUNT = 85", self.workflow)
        self.assertIn("parse_pgn_text(candidate, strict=False)", self.workflow)
        self.assertIn("_PGN_MARKER_RE.fullmatch", self.workflow)
        self.assertIn("implicit PGN inference from ordinary text", self.workflow)

    def test_semantic_fences_dual_os_full_suites_and_diagnostics_remain(self) -> None:
        self.assertIn("os: [ubuntu-22.04, windows-2025]", self.workflow)
        self.assertIn('git diff --quiet "$base" HEAD --', self.workflow)
        for item in (
            "acs/gametree.py",
            "acs/pgn_roundtrip.py",
            "tests/test_v2_pgn_nested_comment_recovery.py",
            "scripts/v2_pgn_nested_comment_real_book_oracle.py",
            "scripts/v2_real_html_book_oracle.py",
            "acs/bookdocument.py",
            "acs/book_index.py",
            "acs/bookreader.py",
            "acs/chesscore.py",
            "web",
        ):
            with self.subTest(item=item):
                self.assertIn(item, self.workflow)
        self.assertIn("tests.test_v2_html_current_d06_recovery_workflow", self.workflow)
        self.assertIn("python -m unittest discover -s tests -v", self.workflow)
        self.assertIn("python -m pytest -q tests", self.workflow)
        self.assertIn("python -m acs.selftest", self.workflow)
        self.assertIn("python run_accessible_chess.py --diagnostic", self.workflow)
        self.assertIn("python run_accessible_chess_v2.py --diagnostic", self.workflow)


if __name__ == "__main__":
    unittest.main()
