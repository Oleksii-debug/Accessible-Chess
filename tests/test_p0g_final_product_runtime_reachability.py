from __future__ import annotations

from pathlib import Path
import unittest
from unittest import mock

from acs import version2_education_mutation_release as education_release
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

    def test_launcher_diagnoses_staged_livekit_shipping_resource_order(self) -> None:
        source = LAUNCHER.read_text(encoding="utf-8")
        diagnostic_marker = 'if "--diagnostic" in sys.argv:'
        diagnostic = source.split(diagnostic_marker, 1)[1].split("\nelse:", 1)[0]

        self.assertIn('livekit_sdk_label = "LiveKit browser SDK"', diagnostic)
        self.assertIn(
            'livekit_adapter_label = "Classroom LiveKit media adapter"',
            diagnostic,
        )
        self.assertIn("livekit_runtime_ready = (", diagnostic)
        self.assertIn("resource_names.count(livekit_sdk_label) == 1", diagnostic)
        self.assertIn("resource_names.count(livekit_adapter_label) == 1", diagnostic)
        self.assertIn(
            'resource_names.index("V2 Teacher surface")',
            diagnostic,
        )
        self.assertIn("or not livekit_runtime_ready", diagnostic)
        self.assertIn(
            '"livekitRuntimeReady": livekit_runtime_ready',
            diagnostic,
        )
        self.assertIn(
            "CLASSROOM LIVEKIT SHIPPING RUNTIME DIAGNOSTIC PASS",
            diagnostic,
        )

    def test_shipping_wrapper_reuses_canonical_final_resource_authority(self) -> None:
        canonical = (
            ("Stage 1 WebView bootstrap", "stage1"),
            ("LiveKit browser SDK", "sdk"),
            ("Classroom LiveKit media adapter", "adapter"),
            ("P0 event-aware accessibility runtime", "runtime"),
        )
        with mock.patch.object(
            education_release._final_release,
            "final_product_resource_sources",
            return_value=canonical,
        ) as resource_authority:
            sources = education_release.final_product_resource_sources()

        resource_authority.assert_called_once_with()
        self.assertEqual(
            sources,
            (
                ("Stage 1 WebView bootstrap", "stage1"),
                ("LiveKit browser SDK", "sdk"),
                ("Classroom LiveKit media adapter", "adapter"),
                ("P0 accessibility runtime", "runtime"),
            ),
        )

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
