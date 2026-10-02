from __future__ import annotations

import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from acs import version2_livekit_release as release


class Version2LiveKitReleaseTests(unittest.TestCase):
    def staged_root(self, directory: str) -> Path:
        root = Path(directory)
        sdk = root / release.LIVEKIT_SDK_RELATIVE_PATH
        adapter = root / release.LIVEKIT_ADAPTER_RELATIVE_PATH
        sdk.parent.mkdir(parents=True, exist_ok=True)
        adapter.parent.mkdir(parents=True, exist_ok=True)
        sdk.write_text(
            "globalThis.LivekitClient = {Room: function Room(){}};\n",
            encoding="utf-8",
        )
        adapter.write_text(
            "globalThis.AccessibleChessLiveKitMedia = {"
            "LiveKitClassroomMediaAdapter: function Adapter(){}};\n",
            encoding="utf-8",
        )
        return root

    def test_livekit_resources_are_local_nonempty_and_sdk_precedes_adapter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.staged_root(directory)
            with patch.object(release._release_ui, "_asset_root", return_value=root):
                resources = release.livekit_resource_sources()

        self.assertEqual(
            tuple(label for label, _source in resources),
            (
                release.LIVEKIT_SDK_RESOURCE_LABEL,
                release.LIVEKIT_ADAPTER_RESOURCE_LABEL,
            ),
        )
        self.assertIn("LivekitClient", resources[0][1])
        self.assertIn("AccessibleChessLiveKitMedia", resources[1][1])

    def test_final_resources_preserve_inherited_order_then_append_livekit_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.staged_root(directory)
            with (
                patch.object(release._release_ui, "_asset_root", return_value=root),
                patch.object(
                    release,
                    "_BASE_RESOURCE_SOURCES",
                    return_value=(
                        ("Stage 1", "stage-one"),
                        ("Final bootstrap", "bootstrap"),
                    ),
                ),
            ):
                resources = release.final_product_resource_sources()

        self.assertEqual(
            tuple(label for label, _source in resources),
            (
                "Stage 1",
                "Final bootstrap",
                release.LIVEKIT_SDK_RESOURCE_LABEL,
                release.LIVEKIT_ADAPTER_RESOURCE_LABEL,
            ),
        )

    def test_missing_or_empty_runtime_asset_fails_closed(self):
        for missing in ("sdk", "adapter"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as directory:
                root = self.staged_root(directory)
                target = (
                    root / release.LIVEKIT_SDK_RELATIVE_PATH
                    if missing == "sdk"
                    else root / release.LIVEKIT_ADAPTER_RELATIVE_PATH
                )
                target.unlink()
                with patch.object(release._release_ui, "_asset_root", return_value=root):
                    with self.assertRaisesRegex(RuntimeError, "not found"):
                        release.livekit_resource_sources()

        with tempfile.TemporaryDirectory() as directory:
            root = self.staged_root(directory)
            (root / release.LIVEKIT_SDK_RELATIVE_PATH).write_text("", encoding="utf-8")
            with patch.object(release._release_ui, "_asset_root", return_value=root):
                with self.assertRaisesRegex(RuntimeError, "empty"):
                    release.livekit_resource_sources()

    def test_duplicate_registration_fails_instead_of_injecting_sdk_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.staged_root(directory)
            with (
                patch.object(release._release_ui, "_asset_root", return_value=root),
                patch.object(
                    release,
                    "_BASE_RESOURCE_SOURCES",
                    return_value=((release.LIVEKIT_SDK_RESOURCE_LABEL, "old"),),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "already registered"):
                    release.final_product_resource_sources()

    def test_binding_restores_exact_inherited_resource_authority(self):
        original = release._education_release.final_product_resource_sources
        with release._livekit_resource_bindings():
            self.assertIs(
                release._education_release.final_product_resource_sources,
                release.final_product_resource_sources,
            )
        self.assertIs(
            release._education_release.final_product_resource_sources,
            original,
        )

    def test_deferred_application_factory_reacquires_livekit_binding(self):
        observations = []

        def fake_create(*args, **kwargs):
            self.assertTrue(kwargs.get("defer_ui"))
            observations.append(
                release._education_release.final_product_resource_sources
                is release.final_product_resource_sources
            )

            def build():
                observations.append(
                    release._education_release.final_product_resource_sources
                    is release.final_product_resource_sources
                )
                return "application"

            return "api", build, "runtime", "native"

        with patch.object(
            release._status_release,
            "create_version2_release_application",
            side_effect=fake_create,
        ):
            api, build, runtime, native = release.create_version2_release_application(
                defer_ui=True
            )
            self.assertEqual((api, runtime, native), ("api", "runtime", "native"))
            self.assertEqual(build(), "application")

        self.assertEqual(observations, [True, True])


if __name__ == "__main__":
    unittest.main()
