from __future__ import annotations

import unittest
from pathlib import Path


class CompositionPublicationBoundaryWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "v2-composition-publication-boundary.yml"
        ).read_text(encoding="utf-8")

    def test_current_product_is_exact_candidate_ancestor(self) -> None:
        self.assertIn(
            'git merge-base --is-ancestor "$product" HEAD',
            self.workflow,
        )
        self.assertIn(
            'test "$(git merge-base "$product" HEAD)" = "$product"',
            self.workflow,
        )
        self.assertIn('git diff --check "$product" HEAD', self.workflow)

    def test_historical_composition_blob_fences_are_removed(self) -> None:
        for stale in (
            "OWNER_HEAD:",
            "BASE_PRODUCT_BLOB:",
            "CANDIDATE_PRODUCT_BLOB:",
            "fix/v2-composition-publication-recovery-20260926",
            "converge/p0-release-critical-to-full-product-20260926",
        ):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, self.workflow)

    def test_publication_semantic_oracle_is_locked_to_current_product(self) -> None:
        marker = "protected_paths=("
        start = self.workflow.index(marker)
        end = self.workflow.index("\n          )", start)
        protected = self.workflow[start:end]
        self.assertIn(
            "'tests/test_version2_composition_publication_boundary.py'",
            protected,
        )
        self.assertIn(
            'product_blob="$(git rev-parse "$product:$path")"',
            self.workflow,
        )
        self.assertIn(
            'candidate_blob="$(git rev-parse "HEAD:$path")"',
            self.workflow,
        )
        self.assertIn(
            "Publication-boundary oracle drift requires a dedicated successor",
            self.workflow,
        )

    def test_shared_release_composition_root_is_regressed_not_blob_frozen(self) -> None:
        marker = "protected_paths=("
        start = self.workflow.index(marker)
        end = self.workflow.index("\n          )", start)
        protected = self.workflow[start:end]
        self.assertNotIn("acs/version2_release_app.py", protected)
        self.assertIn("acs/version2_release_app.py", self.workflow)
        self.assertIn(
            "tests.test_version2_composition_publication_boundary",
            self.workflow,
        )
        self.assertIn("tests.test_version2_release_app", self.workflow)

    def test_contract_is_triggered_compiled_and_executed(self) -> None:
        path = "tests/test_composition_publication_boundary_workflow.py"
        self.assertGreaterEqual(self.workflow.count(path), 3)
        self.assertIn(
            "tests.test_composition_publication_boundary_workflow",
            self.workflow,
        )

    def test_broad_release_checks_are_retained(self) -> None:
        self.assertIn(
            "python -m unittest discover -s tests -p 'test_*.py'",
            self.workflow,
        )
        self.assertIn("python -m acs.selftest", self.workflow)
        self.assertIn(
            "python run_accessible_chess_v2.py --diagnostic",
            self.workflow,
        )

    def test_current_product_is_the_only_pull_request_base(self) -> None:
        branches = self.workflow.split("paths:", 1)[0]
        self.assertIn(
            "work/full-product-teacher-education-reachability-20260911",
            branches,
        )
        self.assertNotIn(
            "converge/p0-release-critical-to-full-product-20260926",
            branches,
        )


if __name__ == "__main__":
    unittest.main()
