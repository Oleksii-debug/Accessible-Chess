from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "current-product-shipping-integration-20261005.yml"
PORTABLE_GATE = ROOT / ".github" / "workflows" / "current-product-portable-integration-convergence.yml"
ACCESSIBILITY_GATE = ROOT / ".github" / "workflows" / "current-product-accessibility-formats-convergence.yml"


class CurrentProductShippingIntegration20261005Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.portable_text = PORTABLE_GATE.read_text(encoding="utf-8")
        cls.accessibility_text = ACCESSIBILITY_GATE.read_text(encoding="utf-8")

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
            'test "$product_count" -eq 64',
            'test "$candidate_count" -eq 66',
            "CURRENT_PRODUCT_SHIPPING_GEOMETRY=PASS",
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.text)

    def test_only_four_qualification_files_may_differ_from_product(self) -> None:
        required = (
            "ACCESSIBILITY_GATE: .github/workflows/current-product-accessibility-formats-convergence.yml",
            "PORTABLE_GATE: .github/workflows/current-product-portable-integration-convergence.yml",
            "INTEGRATION_WORKFLOW: .github/workflows/current-product-shipping-integration-20261005.yml",
            "INTEGRATION_TEST: tests/test_current_product_shipping_integration_20261005.py",
            'extra_paths="$(git diff --name-only "$live_product"...HEAD | sort)"',
            'test "$extra_paths" = "$expected_extra"',
            "QUALIFICATION_DELTA_PATHS=4",
            'test "$candidate_paths" = "$expected_candidate"',
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.text)

    def test_inherited_package_gate_retains_legacy_mode_and_exact_shipping_mode(self) -> None:
        required = (
            "CURRENT_PRODUCT_SHA: 59486e2c9eff903e416d59a0e7c349c22ee2111d",
            'if git merge-base --is-ancestor "$CURRENT_PRODUCT_SHA" HEAD; then',
            'test "$live_current_product" = "$CURRENT_PRODUCT_SHA"',
            'test "$product_count" -eq 64',
            "PACKAGE_MANIFEST_TOPOLOGY=CURRENT_SHIPPING_INTEGRATION",
            "PACKAGE_MANIFEST_TOPOLOGY=LEGACY_FOCUSED_INTEGRATION",
            'test "$extra" = "$expected_extra"',
            'test "$candidate_count" -eq 66',
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.portable_text)

    def test_inherited_accessibility_gate_retains_focused_mode_and_exact_shipping_mode(self) -> None:
        required = (
            "SHIPPING_BRANCH: integration/current-product-main-candidate-20261004-c2mbezb",
            "CURRENT_PRODUCT_SHA: 59486e2c9eff903e416d59a0e7c349c22ee2111d",
            'if [ "${EVENT_BASE_REF:-}" = "$SHIPPING_BRANCH" ]; then',
            'test "$live_current_product" = "$CURRENT_PRODUCT_SHA"',
            'test "$product_scope" = "$expected_paths"',
            'test "$extra" = "$expected_extra"',
            "ACCESSIBILITY_FORMATS_TOPOLOGY=CURRENT_SHIPPING_INTEGRATION",
            "ACCESSIBILITY_FORMATS_TOPOLOGY=FOCUSED_PRODUCT",
        )
        for fragment in required:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.accessibility_text)

    def test_gate_runs_on_both_release_relevant_operating_systems(self) -> None:
        for text in (self.text, self.portable_text, self.accessibility_text):
            self.assertIn("os: [ubuntu-22.04, windows-2025]", text)
            self.assertIn("fail-fast: false", text)
            self.assertNotIn("continue-on-error:", text)

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
