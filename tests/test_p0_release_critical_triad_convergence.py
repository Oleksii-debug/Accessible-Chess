from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_QA_PATHS = (
    "scripts/p0_packaged_document_copy_probe.ps1",
    "tests/test_p0_packaged_document_copy_probe.py",
    "scripts/verify_p0_packaged_document_copy_evidence.py",
    "tests/test_verify_p0_packaged_document_copy_evidence.py",
    "scripts/p0g_packaged_hotkey_result_probe.ps1",
    "tests/test_p0g_packaged_hotkey_result_probe.py",
)

P0F_MARKER = "P0-F PACKAGED W2 LIBRARY DIAGNOSTIC PASS"
P0F_PACKAGE_PATH = "release-content/w2-starter"


def _production_text_files() -> list[Path]:
    paths: list[Path] = []
    candidates = [ROOT / "acs", ROOT / "web", ROOT / "run_accessible_chess_v2.py"]
    for candidate in candidates:
        if candidate.is_file():
            paths.append(candidate)
            continue
        if candidate.is_dir():
            paths.extend(candidate.rglob("*.py"))
            paths.extend(candidate.rglob("*.js"))
    return sorted(set(paths))


class P0ReleaseCriticalTriadConvergenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (
            ROOT / ".github" / "workflows" / "p0-release-critical-triad-convergence.yml"
        ).read_text(encoding="utf-8")

    def test_pull_request_identity_authenticates_exact_event_merge(self) -> None:
        workflow = self.workflow
        self.assertIn("EVENT_BASE_REF:", workflow)
        self.assertIn("EVENT_BASE_SHA:", workflow)
        self.assertIn("EVENT_HEAD_REF:", workflow)
        self.assertIn("EVENT_HEAD_SHA:", workflow)
        self.assertIn("CHECKED_SHA:", workflow)
        self.assertIn(
            "PRODUCT_BRANCH: work/full-product-teacher-education-reachability-20260911",
            workflow,
        )
        self.assertIn('test "$(git rev-parse HEAD)" = "$CHECKED_SHA"', workflow)
        self.assertIn(
            'git fetch --no-tags origin "+refs/heads/$PRODUCT_BRANCH:refs/remotes/origin/$PRODUCT_BRANCH"',
            workflow,
        )
        self.assertIn(
            'live_product="$(git rev-parse "refs/remotes/origin/$PRODUCT_BRANCH")"',
            workflow,
        )
        self.assertIn(
            'git fetch --no-tags origin "+refs/heads/$EVENT_BASE_REF:refs/remotes/origin/$EVENT_BASE_REF"',
            workflow,
        )
        self.assertIn(
            'live_target="$(git rev-parse "refs/remotes/origin/$EVENT_BASE_REF")"',
            workflow,
        )
        self.assertIn('test "$EVENT_BASE_SHA" = "$live_target"', workflow)
        self.assertIn(
            'git merge-base --is-ancestor "$EVENT_BASE_SHA" "$EVENT_HEAD_SHA"',
            workflow,
        )
        self.assertIn(
            'test "$(git merge-base "$EVENT_BASE_SHA" "$EVENT_HEAD_SHA")" = "$EVENT_BASE_SHA"',
            workflow,
        )
        self.assertIn('git show -s --format=%P HEAD', workflow)
        self.assertIn('test "$parents" = "$EVENT_BASE_SHA $EVENT_HEAD_SHA"', workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertNotIn('case "$base" in', workflow)
        self.assertNotIn("release/w4-v2-current-p0-candidate-20260926", workflow)
        for path in REQUIRED_QA_PATHS:
            with self.subTest(trigger_path=path):
                self.assertIn("      - '" + path + "'", workflow)

    def test_long_lived_current_product_pr_uses_latest_product_increment(self) -> None:
        workflow = self.workflow
        self.assertIn('if test "$EVENT_HEAD_REF" = "$PRODUCT_BRANCH"; then', workflow)
        self.assertIn('test "$EVENT_HEAD_SHA" = "$live_product"', workflow)
        self.assertIn("Current Product PR head is stale", workflow)
        self.assertIn('diff_base="$(git rev-parse "$EVENT_HEAD_SHA^")"', workflow)
        self.assertIn('git cat-file -e "$diff_base^{commit}"', workflow)
        self.assertIn(
            'git merge-base --is-ancestor "$diff_base" "$EVENT_HEAD_SHA"', workflow
        )
        self.assertIn('git diff --check "$diff_base..$EVENT_HEAD_SHA"', workflow)
        self.assertNotIn('git diff --check "$EVENT_BASE_SHA..$EVENT_HEAD_SHA"', workflow)

    def test_non_product_pr_remains_live_product_rooted(self) -> None:
        workflow = self.workflow
        product_case = workflow.index('if test "$EVENT_HEAD_REF" = "$PRODUCT_BRANCH"; then')
        non_product_case = workflow.index("          else\n", product_case)
        self.assertLess(product_case, non_product_case)
        self.assertIn(
            'git merge-base --is-ancestor "$live_product" "$EVENT_BASE_SHA"', workflow
        )
        self.assertIn(
            'git merge-base --is-ancestor "$live_product" "$EVENT_HEAD_SHA"', workflow
        )
        self.assertIn('diff_base="$EVENT_BASE_SHA"', workflow)

    def test_packaged_copy_and_hotkey_qa_lineages_are_present(self) -> None:
        missing = [path for path in REQUIRED_QA_PATHS if not (ROOT / path).is_file()]
        self.assertFalse(missing, "missing P0 packaged QA paths: " + ", ".join(missing))

    def test_packaged_p0f_diagnostic_marker_is_in_production_code(self) -> None:
        hits: list[str] = []
        for path in _production_text_files():
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            if P0F_MARKER in text:
                hits.append(str(path.relative_to(ROOT)))
        self.assertTrue(hits, "P0-F packaged starter-content PASS marker is absent from production code")

    def test_packaged_w2_starter_path_is_in_production_code(self) -> None:
        hits: list[str] = []
        for path in _production_text_files():
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            if P0F_PACKAGE_PATH in text:
                hits.append(str(path.relative_to(ROOT)))
        self.assertTrue(hits, "packaged W2 starter-content discovery path is absent from production code")

    def test_p0f_pass_marker_is_not_fabricated_by_test_or_workflow(self) -> None:
        # The release predicate must live in Product/diagnostic code. Merely adding
        # the expected string to a test or workflow cannot satisfy the search above.
        self.assertNotIn(P0F_MARKER, " ".join(REQUIRED_QA_PATHS))


if __name__ == "__main__":
    unittest.main()
