from __future__ import annotations

import unittest

from acs import version2_final_release as final_release


class P0GFinalProductRuntimeReachabilityTests(unittest.TestCase):
    def test_event_aware_runtime_is_in_shipping_resource_order(self) -> None:
        sources = final_release._final_product_resource_sources()
        labels = [label for label, _source in sources]
        runtime_label = "P0 event-aware accessibility runtime"
        teacher_label = "V2 Teacher surface"
        education_label = "V2 Education surface"
        bootstrap_label = "V2 final-product bootstrap"

        self.assertEqual(labels.count(runtime_label), 1)
        self.assertLess(labels.index(teacher_label), labels.index(runtime_label))
        self.assertLess(labels.index(education_label), labels.index(runtime_label))
        self.assertLess(labels.index(bootstrap_label), labels.index(runtime_label))
        previous_resources = final_release._release_ui._resource_sources
        with final_release._final_product_bindings():
            self.assertIs(
                final_release._release_ui._resource_sources,
                final_release._final_product_resource_sources,
            )
        self.assertIs(final_release._release_ui._resource_sources, previous_resources)

        runtime_source = dict(sources)[runtime_label]
        for surface in (
            "AccessibleChessPgnSurface",
            "AccessibleChessLibrarySurface",
            "AccessibleChessBookSurface",
            "AccessibleChessTrainingSurface",
            "AccessibleChessEducationSurface",
            "AccessibleChessTeacherSurface",
        ):
            self.assertIn(f'"{surface}"', runtime_source)
        self.assertIn("wrapSurfaceRenderAnnouncement", runtime_source)
        self.assertIn("global.announce = function", runtime_source)


if __name__ == "__main__":
    unittest.main()
