from __future__ import annotations

from pathlib import Path
import unittest

from acs import version2_upgrade_status_release as shipping_release


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "run_accessible_chess_v2.py"


class P0GFinalProductRuntimeReachabilityTests(unittest.TestCase):
    def test_launcher_routes_diagnostic_and_real_ui_through_shipping_release(self) -> None:
        source = LAUNCHER.read_text(encoding="utf-8")
        diagnostic_marker = 'if "--diagnostic" in sys.argv:'
        self.assertIn(diagnostic_marker, source)
        diagnostic, real = source.split(diagnostic_marker, 1)[1].split("\nelse:", 1)
        self.assertIn(
            "from acs.version2_upgrade_status_release import (",
            diagnostic,
        )
        self.assertIn("create_version2_release_application", diagnostic)
        self.assertIn("final_product_resource_sources", diagnostic)
        self.assertIn(
            "from acs.version2_upgrade_status_release import main",
            real,
        )
        self.assertIn("main()", real)

    def test_event_aware_runtime_is_in_actual_shipping_resource_order(self) -> None:
        sources = shipping_release.final_product_resource_sources()
        labels = [label for label, _source in sources]
        runtime_label = "P0 accessibility runtime"
        teacher_label = "V2 Teacher surface"
        education_label = "V2 Education surface"
        bootstrap_label = "V2 final-product bootstrap"

        self.assertEqual(labels.count(runtime_label), 1)
        self.assertLess(labels.index(teacher_label), labels.index(runtime_label))
        self.assertLess(labels.index(education_label), labels.index(runtime_label))
        self.assertLess(labels.index(bootstrap_label), labels.index(runtime_label))

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
