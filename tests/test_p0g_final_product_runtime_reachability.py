from __future__ import annotations

from pathlib import Path
import tempfile
import traceback
import unittest
from unittest.mock import patch

from acs import version2_education_mutation_release as education_release
from acs import version2_upgrade_status_release as shipping_release


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "run_accessible_chess_v2.py"
P0G_WORKFLOW = ROOT / ".github" / "workflows" / "p0g-final-product-runtime-reachability.yml"


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
        adapter_label = "V2 Classroom LiveKit adapter"
        media_label = "V2 Classroom media surface"
        bootstrap_label = "V2 final-product bootstrap"

        self.assertEqual(labels.count(runtime_label), 1)
        self.assertEqual(labels.count(adapter_label), 1)
        self.assertEqual(labels.count(media_label), 1)
        self.assertLess(labels.index(teacher_label), labels.index(runtime_label))
        self.assertLess(labels.index(education_label), labels.index(runtime_label))
        self.assertLess(labels.index(adapter_label), labels.index(media_label))
        self.assertLess(labels.index(adapter_label), labels.index(bootstrap_label))
        self.assertLess(labels.index(media_label), labels.index(bootstrap_label))
        self.assertLess(labels.index(media_label), labels.index(runtime_label))
        self.assertLess(labels.index(bootstrap_label), labels.index(runtime_label))

        adapter_source = dict(sources)[adapter_label]
        self.assertIn("AccessibleChessLiveKitMedia", adapter_source)
        self.assertIn("LiveKitClassroomMediaAdapter", adapter_source)
        self.assertNotIn("api_secret", adapter_source.casefold())
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

    def test_packaged_livekit_sdk_precedes_adapter_without_becoming_source_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            web = root / "web"
            resource_paths = (
                "stage1_release_bootstrap.js",
                "stage1_board_actions.js",
                "full_product_pgn.js",
                "full_product_library.js",
                "full_product_books_training.js",
                "full_product_teacher.js",
                "full_product_education.js",
                "livekit_classroom_media.js",
                "full_product_classroom_media.js",
                "version2_final_product_bootstrap.js",
                "p0_accessibility_runtime.js",
            )
            for relative in resource_paths:
                path = web / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"// {relative}\n", encoding="utf-8")

            with patch.object(
                education_release._release_ui,
                "_asset_root",
                return_value=root,
            ):
                source_sources = shipping_release.final_product_resource_sources()
            source_labels = [label for label, _source in source_sources]
            self.assertNotIn("LiveKit browser SDK", source_labels)
            self.assertIn("V2 Classroom LiveKit adapter", source_labels)

            sdk_path = web / "vendor" / "livekit" / "livekit-client.umd.js"
            sdk_path.parent.mkdir(parents=True, exist_ok=True)
            with patch.object(
                education_release._release_ui,
                "_asset_root",
                return_value=root,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "LiveKit browser SDK not found",
                ):
                    shipping_release.final_product_resource_sources()

            sdk_source = "globalThis.LivekitClient = { Room: function Room() {} };\n"
            sdk_path.write_text(sdk_source, encoding="utf-8")
            with patch.object(
                education_release._release_ui,
                "_asset_root",
                return_value=root,
            ):
                packaged_sources = shipping_release.final_product_resource_sources()

            packaged_labels = [label for label, _source in packaged_sources]
            sdk_index = packaged_labels.index("LiveKit browser SDK")
            adapter_index = packaged_labels.index("Classroom LiveKit media adapter")
            self.assertEqual(adapter_index, sdk_index + 1)
            self.assertLess(
                adapter_index,
                packaged_labels.index("V2 Teacher surface"),
            )
            self.assertNotIn("V2 Classroom LiveKit adapter", packaged_labels)
            self.assertEqual(
                dict(packaged_sources)["LiveKit browser SDK"],
                sdk_source,
            )

    def test_present_invalid_livekit_vendor_root_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            livekit_root = root / "web" / "vendor" / "livekit"
            livekit_root.parent.mkdir(parents=True, exist_ok=True)
            livekit_root.write_text("not a directory", encoding="utf-8")
            with patch.object(
                education_release._release_ui,
                "_asset_root",
                return_value=root,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "LiveKit browser SDK resource root is invalid",
                ):
                    shipping_release.final_product_resource_sources()


    def test_empty_packaged_livekit_sdk_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            web = root / "web"
            resource_paths = (
                "stage1_release_bootstrap.js",
                "stage1_board_actions.js",
                "full_product_pgn.js",
                "full_product_library.js",
                "full_product_books_training.js",
                "full_product_teacher.js",
                "full_product_education.js",
                "livekit_classroom_media.js",
                "full_product_classroom_media.js",
                "version2_final_product_bootstrap.js",
                "p0_accessibility_runtime.js",
            )
            for relative in resource_paths:
                path = web / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"// {relative}\n", encoding="utf-8")
            sdk_path = web / "vendor" / "livekit" / "livekit-client.umd.js"
            sdk_path.parent.mkdir(parents=True, exist_ok=True)
            sdk_path.write_text("", encoding="utf-8")

            with patch.object(
                education_release._release_ui,
                "_asset_root",
                return_value=root,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "LiveKit browser SDK is empty",
                ):
                    shipping_release.final_product_resource_sources()

    def test_packaged_resource_read_failure_redacts_filesystem_detail(self) -> None:
        secret_path = r"C:\Users\private-user\build\stage1_release_bootstrap.js"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            web = root / "web"
            resource_paths = (
                "stage1_release_bootstrap.js",
                "stage1_board_actions.js",
                "full_product_pgn.js",
                "full_product_library.js",
                "full_product_books_training.js",
                "full_product_teacher.js",
                "full_product_education.js",
                "livekit_classroom_media.js",
                "full_product_classroom_media.js",
                "version2_final_product_bootstrap.js",
                "p0_accessibility_runtime.js",
            )
            for relative in resource_paths:
                path = web / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"// {relative}\n", encoding="utf-8")

            original_read_text = Path.read_text

            def fail_selected(path: Path, *args, **kwargs):
                if path.name == "stage1_release_bootstrap.js":
                    raise OSError(secret_path)
                return original_read_text(path, *args, **kwargs)

            with (
                patch.object(
                    education_release._release_ui,
                    "_asset_root",
                    return_value=root,
                ),
                patch.object(Path, "read_text", fail_selected),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "Stage 1 WebView bootstrap could not be read",
                ) as caught:
                    shipping_release.final_product_resource_sources()

        rendered = "".join(traceback.format_exception(caught.exception))
        self.assertNotIn(secret_path, rendered)
        self.assertIsNone(caught.exception.__cause__)


    def test_retained_gate_accepts_exact_classroom_media_successor_identities(self) -> None:
        workflow = P0G_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("EDUCATION_RELEASE_MEDIA_BLOB:", workflow)
        self.assertIn("EDUCATION_RELEASE_MEDIA_SDK_BLOB:", workflow)
        self.assertIn("REACHABILITY_MEDIA_TEST_BLOB:", workflow)
        self.assertIn("REACHABILITY_MEDIA_SDK_TEST_BLOB:", workflow)
        self.assertIn('education_blob="$(git rev-parse HEAD:acs/version2_education_mutation_release.py)"', workflow)
        self.assertIn('reachability_test_blob="$(git rev-parse HEAD:tests/test_p0g_final_product_runtime_reachability.py)"', workflow)
        self.assertIn(
            '"$EDUCATION_RELEASE_BLOB"|"$EDUCATION_RELEASE_MEDIA_BLOB"|'
            '"$EDUCATION_RELEASE_MEDIA_SDK_BLOB"',
            workflow,
        )
        self.assertIn(
            '"$REACHABILITY_TEST_BLOB"|"$REACHABILITY_MEDIA_TEST_BLOB"|'
            '"$REACHABILITY_MEDIA_SDK_TEST_BLOB"',
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
