from __future__ import annotations

import unittest

from acs.version2_education_mutation_release import final_product_resource_sources


class P0FinalProductResourceOrderTests(unittest.TestCase):
    def test_p0_accessibility_runtime_loads_after_final_product_workspace_bootstrap(self) -> None:
        """The P0 runtime must discover the real V2 workspace/navigation at install time."""

        resources = final_product_resource_sources()
        labels = tuple(label for label, _source in resources)

        bootstrap_index = labels.index("V2 final-product bootstrap")
        runtime_index = labels.index("P0 accessibility runtime")

        self.assertLess(bootstrap_index, runtime_index)
        profile_index = labels.index("V2 local profile surface")
        self.assertLess(bootstrap_index, profile_index)
        self.assertLess(profile_index, runtime_index)
        self.assertEqual("V2 local profile surface", labels[runtime_index - 1])

        bootstrap_source = resources[bootstrap_index][1]
        runtime_source = resources[runtime_index][1]

        self.assertIn('workspace.id = "v2-workspace"', bootstrap_source)
        self.assertIn('nav.id = "v2-navigation"', bootstrap_source)
        self.assertIn('documentRef.getElementById("v2-workspace")', runtime_source)
        self.assertIn('documentRef.getElementById("v2-navigation")', runtime_source)
        self.assertIn("__accessibleChessP0AccessibilityRuntimeInstalled", runtime_source)


if __name__ == "__main__":
    unittest.main()
