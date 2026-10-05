from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "current-product-shipping-integration-20261005.yml"


class CurrentProductShippingIntegration20261005Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_gate_targets_only_canonical_shipping_branch(self) -> None:
        pull = self.text.index("  pull_request:\n")
        push = self.text.index("  push:\n", pull)
        block = self.text[pull:push]
        self.assertIn(
            "      - integration/current-product-main-candidate-20261004-c2mbezb\n",
            block,
        )
        self.assertNotIn("      - main\n", block)

    def test_gate_pins_and_late_binds_both_authorities(self) -> None:
        required = (
            "SHIPPING_BRANCH: integration/current-product-main-candidate-20261004-c2mbezb",
            "PRODUCT_BRANCH: converge/current-product-diagnostic-help-classroom-20261005-sol56m7k2",
            "PINNED_SHIPPING_SHA: 0a9e0db1663c04cf67fac2d249ba197fa22cde75",
            "PINNED_PRODUCT_SHA: 59486e2c9eff903e416d59a0e7c349c22ee2111d",
            'git fetch --no-tags origin "+refs/heads/$base_ref:refs/remotes/origin/$base_ref"',
            'test "$live_shipping" = "$PINNED_SHIPPING_SHA"',
            'git fetch --no-tags origin "+refs/heads/$PRODUCT_BRANCH:refs/remotes/origin/$PRODUCT_BRANCH"',
            'test "$live_product" = "$PINNED_PRODUCT_SHA"',
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.text)

    def test_gate_requires_ahead_only_product_geometry(self) -> None:
        required = (
            'git merge-base --is-ancestor "$live_shipping" "$live_product"',
            'test "$(git merge-base "$live_shipping" "$live_product")" = "$live_shipping"',
            'git merge-base --is-ancestor "$live_product" HEAD',
            'test "$(git merge-base "$live_shipping" HEAD)" = "$live_shipping"',
            'git diff --check "$live_shipping"...HEAD',
            "test \"$product_count\" -eq 64",
            "test \"$candidate_count\" -eq 66",
            "CURRENT_PRODUCT_SHIPPING_GEOMETRY=PASS",
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.text)

    def test_only_two_integration_files_may_exist_beyond_product(self) -> None:
        required = (
            "INTEGRATION_WORKFLOW: .github/workflows/current-product-shipping-integration-20261005.yml",
            "INTEGRATION_TEST: tests/test_current_product_shipping_integration_20261005.py",
            'extra_paths="$(git diff --name-only "$live_product"...HEAD | sort)"',
            'expected_extra="$(printf \'%s\\n\' "$INTEGRATION_WORKFLOW" "$INTEGRATION_TEST" | sort)"',
            'test "$extra_paths" = "$expected_extra"',
            'expected_candidate="$(printf \'%s\\n%s\\n\' "$product_paths" "$expected_extra" | sed \'/^$/d\' | sort -u)"',
            'test "$candidate_paths" = "$expected_candidate"',
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.text)

    def test_gate_runs_on_both_release_relevant_operating_systems(self) -> None:
        self.assertIn("os: [ubuntu-22.04, windows-2025]", self.text)
        self.assertIn("fail-fast: false", self.text)
        self.assertNotIn("continue-on-error:", self.text)

    def test_gate_executes_current_high_risk_product_contracts(self) -> None:
        required = (
            "tests.test_portable_manifest_json_prehash_bounds_current",
            "tests.test_bookdocument_total_text_budget_current",
            "tests.test_bookreader_revision_barriers_current",
            "tests.test_settings_corruption_security",
            "tests.test_training_progress_json_prehash_bounds_current",
            "tests.test_version2_package_preflight",
            "tests.test_version2_portable_package",
            "tests.test_w2_training_progress_crash_recovery",
            "tests.test_keybindings",
            "tests.test_dynamic_keymap_help_contract",
            "tests.test_stage1_unbound_shortcut_capture",
            "tests.test_pgn_tree_remaining_keybindings",
            "tests.test_book_html_pgn_loss_accounting",
            "tests.test_book_library_import_journey",
            "tests.test_book_training_variant_authority",
            "tests.test_pgn_board_start_authority",
            "tests.test_current_main_full_product_convergence_workflow",
            "tests.test_p0_release_critical_triad_convergence",
            "tests.test_version2_application",
            "node tests/js/dynamic_keymap_help_test.js",
            "node tests/js/classroom_surface_dom_test.js",
            "node tests/js/pgn_remaining_keybindings_test.js",
            "python run_accessible_chess_v2.py --diagnostic",
            "python -m acs.selftest",
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.text)


if __name__ == "__main__":
    unittest.main()
