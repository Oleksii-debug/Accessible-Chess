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
MAIN_INTEGRATION_NARROW_WORKFLOWS = (
    ".github/workflows/current-indexed-book-training-source.yml",
    ".github/workflows/current-library-browser-passive-ingress.yml",
    ".github/workflows/current-library-presenter-passive-root.yml",
    ".github/workflows/current-pgn-presenter-passive-root.yml",
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
    def test_pull_request_identity_is_proven_against_live_base_with_product_ancestry(self) -> None:
        workflow = (
            ROOT / ".github" / "workflows" / "p0-release-critical-triad-convergence.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("EVENT_BASE_SHA:", workflow)
        self.assertIn("EVENT_BASE_REF:", workflow)
        self.assertIn("EVENT_HEAD_SHA:", workflow)
        self.assertIn("CHECKED_SHA:", workflow)
        self.assertIn("DEFAULT_BRANCH:", workflow)
        self.assertIn(
            "PRODUCT_BRANCH: work/full-product-teacher-education-reachability-20260911",
            workflow,
        )
        self.assertIn(
            "INTEGRATION_PRODUCT_BRANCH: converge/current-product-pgn-graph-safety-20261004-sol60a1",
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
            'live_event_base="$(git rev-parse "refs/remotes/origin/$EVENT_BASE_REF")"',
            workflow,
        )
        self.assertIn(
            'git merge-base --is-ancestor "$EVENT_BASE_SHA" "$live_event_base"',
            workflow,
        )
        self.assertIn('if [ "$EVENT_BASE_REF" = "$DEFAULT_BRANCH" ]; then', workflow)
        self.assertIn(
            'git merge-base --is-ancestor "$live_product" "$EVENT_HEAD_SHA"',
            workflow,
        )
        self.assertIn(
            'git fetch --no-tags origin "+refs/heads/$INTEGRATION_PRODUCT_BRANCH:refs/remotes/origin/$INTEGRATION_PRODUCT_BRANCH"',
            workflow,
        )
        self.assertIn(
            'live_integration_product="$(git rev-parse "refs/remotes/origin/$INTEGRATION_PRODUCT_BRANCH")"',
            workflow,
        )
        self.assertIn(
            'git merge-base --is-ancestor "$live_product" "$live_integration_product"',
            workflow,
        )
        self.assertIn(
            'git merge-base --is-ancestor "$live_integration_product" "$EVENT_HEAD_SHA"',
            workflow,
        )
        self.assertIn("P0_TRIAD_CURRENT_PRODUCT_ANCESTOR=", workflow)
        self.assertIn("P0_TRIAD_MODE=DEFAULT_BRANCH_INTEGRATION", workflow)
        self.assertIn(
            'git merge-base --is-ancestor "$live_product" "$live_event_base"',
            workflow,
        )
        self.assertIn("P0_TRIAD_MODE=STACKED_PRODUCT", workflow)
        self.assertIn(
            'git merge-base --is-ancestor "$live_event_base" "$EVENT_HEAD_SHA"',
            workflow,
        )
        self.assertIn(
            'git merge-base --is-ancestor "$live_event_base" HEAD',
            workflow,
        )
        self.assertIn('git merge-base --is-ancestor "$EVENT_HEAD_SHA" HEAD', workflow)
        self.assertIn('git show -s --format=%P HEAD', workflow)
        self.assertIn(
            'test "$parents" = "$live_event_base $EVENT_HEAD_SHA"',
            workflow,
        )
        self.assertIn('git diff --check "$live_event_base..HEAD"', workflow)
        self.assertNotIn('git diff --check "$EVENT_BASE_SHA..HEAD"', workflow)
        self.assertIn("P0_TRIAD_PRODUCT_ANCESTOR=", workflow)
        self.assertIn("P0_TRIAD_LIVE_EVENT_BASE=", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertNotIn('case "$base" in', workflow)
        self.assertNotIn("release/w4-v2-current-p0-candidate-20260926", workflow)
        self.assertIn('test -n "$DEFAULT_BRANCH"', workflow)
        for path in REQUIRED_QA_PATHS:
            with self.subTest(trigger_path=path):
                self.assertIn("      - '" + path + "'", workflow)

    def test_narrow_integration_gates_are_reachable_from_main_pull_request(self) -> None:
        for workflow_path in MAIN_INTEGRATION_NARROW_WORKFLOWS:
            with self.subTest(workflow_path=workflow_path):
                workflow = (ROOT / workflow_path).read_text(encoding="utf-8")
                self.assertIn("  pull_request:\n    branches:\n", workflow)
                self.assertIn("      - main\n", workflow)
                self.assertIn("NARROW_SCOPE_MODE=DEFAULT_BRANCH_INTEGRATION", workflow)

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
