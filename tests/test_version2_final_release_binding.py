from __future__ import annotations

import importlib
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from acs.version2_final_product_application import Version2FinalProductApplication
from acs.version2_final_product_profile import (
    FINAL_PRODUCT_ACTION_IDS,
    FinalProductNativeMenuController,
)


class Version2FinalReleaseBindingTests(unittest.TestCase):
    @staticmethod
    def _snapshot_release_globals():
        from acs import version2_release_app, version2_release_ui

        api_type = version2_release_ui.Version2ReleaseAccessibleChessAPI
        return (
            version2_release_app.Version2Application,
            version2_release_ui.VERSION2_FULL_PRODUCT_ACTION_IDS,
            version2_release_ui.Version2NativeMenuController,
            api_type.__dict__["_sync_version2_language"],
            version2_release_ui._resource_sources,
        )

    @staticmethod
    def _write_resource_fixture(root: Path) -> Path:
        web = root / "web"
        web.mkdir(parents=True, exist_ok=True)
        resources = (
            "stage1_release_bootstrap.js",
            "stage1_board_actions.js",
            "full_product_pgn.js",
            "full_product_library.js",
            "full_product_books_training.js",
            "full_product_teacher.js",
            "full_product_education.js",
            "full_product_classroom_media.js",
            "classroom_media_host_executor.js",
            "classroom_media_provider_runtime.js",
            "version2_final_product_bootstrap.js",
            "p0_accessibility_runtime.js",
            "livekit_classroom_media.js",
        )
        for name in resources:
            (web / name).write_text("// test resource\n", encoding="utf-8")
        return web

    def test_import_preserves_exact_prior_release_owners(self) -> None:
        from acs import version2_final_release

        before = self._snapshot_release_globals()
        importlib.reload(version2_final_release)
        after = self._snapshot_release_globals()

        self.assertEqual(after, before)

    def test_eager_factory_binds_final_product_only_during_composition(self) -> None:
        from acs import version2_final_release as final_release
        from acs import version2_release_app, version2_release_ui

        before = self._snapshot_release_globals()
        observed: list[tuple[object, object, object, object]] = []
        api = SimpleNamespace()

        def fake_factory(*args: object, **kwargs: object):
            observed.append(
                (
                    version2_release_app.Version2Application,
                    version2_release_ui.VERSION2_FULL_PRODUCT_ACTION_IDS,
                    version2_release_ui.Version2NativeMenuController,
                    version2_release_ui._resource_sources,
                )
            )
            return (api, "application", "runtime", "native")

        with mock.patch.object(
            final_release._release_app,
            "create_version2_release_application",
            side_effect=fake_factory,
        ):
            result = final_release.create_version2_release_application()

        self.assertEqual(result, (api, "application", "runtime", "native"))
        self.assertEqual(len(observed), 1)
        application, action_ids, controller, resources = observed[0]
        self.assertIs(application, Version2FinalProductApplication)
        self.assertEqual(action_ids, FINAL_PRODUCT_ACTION_IDS)
        self.assertIs(controller, FinalProductNativeMenuController)
        self.assertIs(resources, final_release._final_product_resource_sources)
        self.assertTrue(callable(api._sync_version2_language))
        self.assertEqual(self._snapshot_release_globals(), before)

    def test_eager_factory_failure_restores_exact_prior_release_owners(self) -> None:
        from acs import version2_final_release as final_release
        from acs import version2_release_app, version2_release_ui

        before = self._snapshot_release_globals()
        observed: list[tuple[object, object, object, object]] = []

        def fail_factory(*args: object, **kwargs: object):
            observed.append(
                (
                    version2_release_app.Version2Application,
                    version2_release_ui.VERSION2_FULL_PRODUCT_ACTION_IDS,
                    version2_release_ui.Version2NativeMenuController,
                    version2_release_ui._resource_sources,
                )
            )
            raise RuntimeError("composition failed")

        with mock.patch.object(
            final_release._release_app,
            "create_version2_release_application",
            side_effect=fail_factory,
        ):
            with self.assertRaisesRegex(RuntimeError, "composition failed"):
                final_release.create_version2_release_application()

        self.assertEqual(len(observed), 1)
        application, action_ids, controller, resources = observed[0]
        self.assertIs(application, Version2FinalProductApplication)
        self.assertEqual(action_ids, FINAL_PRODUCT_ACTION_IDS)
        self.assertIs(controller, FinalProductNativeMenuController)
        self.assertIs(resources, final_release._final_product_resource_sources)
        self.assertEqual(self._snapshot_release_globals(), before)

    def test_deferred_factory_rebinds_final_product_on_ui_construction(self) -> None:
        from acs import version2_final_release as final_release
        from acs import version2_release_app, version2_release_ui

        before = self._snapshot_release_globals()
        observed: list[tuple[object, object]] = []
        api = SimpleNamespace()

        def fake_factory(*args: object, **kwargs: object):
            self.assertTrue(kwargs.get("defer_ui"))

            def build_application():
                observed.append(
                    (
                        version2_release_app.Version2Application,
                        version2_release_ui.Version2NativeMenuController,
                    )
                )
                return "application"

            return (api, build_application, "runtime", "native")

        with mock.patch.object(
            final_release._release_app,
            "create_version2_release_application",
            side_effect=fake_factory,
        ):
            returned_api, application_factory, runtime, native = (
                final_release.create_version2_release_application(defer_ui=True)
            )
            self.assertEqual(self._snapshot_release_globals(), before)
            application = application_factory()

        self.assertEqual(
            (returned_api, application, runtime, native),
            (api, "application", "runtime", "native"),
        )
        self.assertEqual(
            observed,
            [(Version2FinalProductApplication, FinalProductNativeMenuController)],
        )
        self.assertEqual(self._snapshot_release_globals(), before)

    def test_deferred_factory_failure_restores_exact_prior_release_owners(self) -> None:
        from acs import version2_final_release as final_release
        from acs import version2_release_app, version2_release_ui

        before = self._snapshot_release_globals()
        observed: list[tuple[object, object, object, object]] = []
        api = SimpleNamespace()

        def fake_factory(*args: object, **kwargs: object):
            self.assertTrue(kwargs.get("defer_ui"))

            def fail_application():
                observed.append(
                    (
                        version2_release_app.Version2Application,
                        version2_release_ui.VERSION2_FULL_PRODUCT_ACTION_IDS,
                        version2_release_ui.Version2NativeMenuController,
                        version2_release_ui._resource_sources,
                    )
                )
                raise RuntimeError("deferred composition failed")

            return (api, fail_application, "runtime", "native")

        with mock.patch.object(
            final_release._release_app,
            "create_version2_release_application",
            side_effect=fake_factory,
        ):
            _, application_factory, _, _ = final_release.create_version2_release_application(
                defer_ui=True
            )
            self.assertEqual(self._snapshot_release_globals(), before)
            with self.assertRaisesRegex(RuntimeError, "deferred composition failed"):
                application_factory()

        self.assertEqual(len(observed), 1)
        application, action_ids, controller, resources = observed[0]
        self.assertIs(application, Version2FinalProductApplication)
        self.assertEqual(action_ids, FINAL_PRODUCT_ACTION_IDS)
        self.assertIs(controller, FinalProductNativeMenuController)
        self.assertIs(resources, final_release._final_product_resource_sources)
        self.assertEqual(self._snapshot_release_globals(), before)

    def test_final_accessibility_resource_rejects_pathname_replacement(self) -> None:
        from acs import version2_final_release as final_release

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            web = self._write_resource_fixture(root)
            target = web / "p0_accessibility_runtime.js"
            replacement = root / "replacement-p0.js"
            replacement.write_bytes(target.read_bytes())
            original_open = Path.open
            swapped = False

            def replacing_open(path_self, *args, **kwargs):
                nonlocal swapped
                if path_self == target and not swapped:
                    swapped = True
                    os.replace(replacement, target)
                return original_open(path_self, *args, **kwargs)

            with (
                mock.patch.object(
                    final_release._release_ui,
                    "_asset_root",
                    return_value=root,
                ),
                mock.patch.object(Path, "open", new=replacing_open),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "P0 event-aware accessibility runtime changed while being opened",
                ):
                    final_release._final_product_resource_sources()
            self.assertTrue(swapped)

    def test_final_resource_rejects_non_utf8_bytes(self) -> None:
        from acs import version2_final_release as final_release

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            web = self._write_resource_fixture(root)
            (web / "full_product_pgn.js").write_bytes(b"\xff\xfe\x00")

            with mock.patch.object(
                final_release._release_ui,
                "_asset_root",
                return_value=root,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "V2 PGN surface resource is not UTF-8",
                ):
                    final_release._final_product_resource_sources()

    def test_staged_livekit_sdk_precedes_adapter_and_teacher_surface(self) -> None:
        from acs import version2_final_release as final_release

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            web = self._write_resource_fixture(root)
            vendor = web / "vendor" / "livekit"
            vendor.mkdir(parents=True)
            (vendor / "livekit-client.umd.js").write_text(
                "globalThis.LivekitClient={Room:function Room(){}};\n",
                encoding="utf-8",
            )
            (vendor / "LICENSE").write_text("Apache License Version 2.0\n", encoding="utf-8")
            (vendor / "NOTICE").write_text("LiveKit Apache License\n", encoding="utf-8")
            (vendor / "provenance.json").write_text("{}\n", encoding="utf-8")

            with mock.patch.object(
                final_release._release_ui,
                "_asset_root",
                return_value=root,
            ):
                sources = final_release._final_product_resource_sources()

        labels = [label for label, _source in sources]
        sdk_label = "LiveKit browser SDK"
        adapter_label = "Classroom LiveKit media adapter"
        teacher_label = "V2 Teacher surface"
        media_label = "V2 Classroom media surface"
        executor_label = "Classroom media host executor"
        runtime_label = "Classroom media provider runtime"
        bootstrap_label = "V2 final-product bootstrap"
        self.assertEqual(labels.count(sdk_label), 1)
        self.assertEqual(labels.count(adapter_label), 1)
        self.assertEqual(labels.count(executor_label), 1)
        self.assertEqual(labels.count(runtime_label), 1)
        self.assertEqual(labels.count(media_label), 1)
        self.assertLess(labels.index(sdk_label), labels.index(adapter_label))
        self.assertLess(labels.index(adapter_label), labels.index(executor_label))
        self.assertLess(labels.index(executor_label), labels.index(runtime_label))
        self.assertLess(labels.index(runtime_label), labels.index(teacher_label))
        self.assertLess(labels.index(runtime_label), labels.index(media_label))
        self.assertLess(labels.index(media_label), labels.index(bootstrap_label))
        self.assertIn("LivekitClient", dict(sources)[sdk_label])

    def test_unstaged_livekit_sdk_does_not_load_adapter_by_itself(self) -> None:
        from acs import version2_final_release as final_release

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._write_resource_fixture(root)

            with mock.patch.object(
                final_release._release_ui,
                "_asset_root",
                return_value=root,
            ):
                sources = final_release._final_product_resource_sources()

        labels = [label for label, _source in sources]
        self.assertNotIn("LiveKit browser SDK", labels)
        self.assertNotIn("Classroom LiveKit media adapter", labels)
        self.assertEqual(labels.count("V2 Classroom media surface"), 1)

    def test_partial_livekit_vendor_root_fails_closed(self) -> None:
        from acs import version2_final_release as final_release

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            web = self._write_resource_fixture(root)
            (web / "vendor" / "livekit").mkdir(parents=True)

            with mock.patch.object(
                final_release._release_ui,
                "_asset_root",
                return_value=root,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "LiveKit browser SDK not found in packaged resources",
                ):
                    final_release._final_product_resource_sources()

    def test_incomplete_livekit_vendor_evidence_fails_closed(self) -> None:
        from acs import version2_final_release as final_release

        for missing in ("LICENSE", "NOTICE", "provenance.json"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                web = self._write_resource_fixture(root)
                vendor = web / "vendor" / "livekit"
                vendor.mkdir(parents=True)
                (vendor / "livekit-client.umd.js").write_text(
                    "globalThis.LivekitClient={Room:function Room(){}};\n",
                    encoding="utf-8",
                )
                (vendor / "LICENSE").write_text(
                    "Apache License Version 2.0\n",
                    encoding="utf-8",
                )
                (vendor / "NOTICE").write_text(
                    "LiveKit Apache License\n",
                    encoding="utf-8",
                )
                (vendor / "provenance.json").write_text("{}\n", encoding="utf-8")
                (vendor / missing).unlink()

                with mock.patch.object(
                    final_release._release_ui,
                    "_asset_root",
                    return_value=root,
                ):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "not found in packaged resources",
                    ):
                        final_release._final_product_resource_sources()

    def test_linked_livekit_vendor_evidence_fails_closed(self) -> None:
        from acs import version2_final_release as final_release

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            web = self._write_resource_fixture(root)
            vendor = web / "vendor" / "livekit"
            vendor.mkdir(parents=True)
            (vendor / "livekit-client.umd.js").write_text(
                "globalThis.LivekitClient={Room:function Room(){}};\n",
                encoding="utf-8",
            )
            (vendor / "LICENSE").write_text("Apache License Version 2.0\n", encoding="utf-8")
            (vendor / "NOTICE").write_text("LiveKit Apache License\n", encoding="utf-8")
            (vendor / "provenance.json").write_text("{}\n", encoding="utf-8")

            original_is_symlink = Path.is_symlink

            def fake_is_symlink(path: Path) -> bool:
                if path == vendor / "provenance.json":
                    return True
                return original_is_symlink(path)

            with (
                mock.patch.object(final_release._release_ui, "_asset_root", return_value=root),
                mock.patch.object(Path, "is_symlink", new=fake_is_symlink),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "LiveKit browser SDK provenance resource is invalid",
                ):
                    final_release._final_product_resource_sources()

    def test_livekit_runtime_link_guard_detects_windows_reparse_attribute(self) -> None:
        from acs import version2_final_release as final_release

        reparse_flag = getattr(final_release.stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        with (
            mock.patch.object(Path, "is_symlink", return_value=False),
            mock.patch.object(
                Path,
                "lstat",
                return_value=SimpleNamespace(st_file_attributes=reparse_flag),
            ),
        ):
            self.assertTrue(final_release._is_link_like_resource(Path("livekit-resource")))

    def test_linked_livekit_media_adapter_fails_closed(self) -> None:
        from acs import version2_final_release as final_release

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            web = self._write_resource_fixture(root)
            vendor = web / "vendor" / "livekit"
            vendor.mkdir(parents=True)
            (vendor / "livekit-client.umd.js").write_text(
                "globalThis.LivekitClient={Room:function Room(){}};\n",
                encoding="utf-8",
            )
            (vendor / "LICENSE").write_text("Apache License Version 2.0\n", encoding="utf-8")
            (vendor / "NOTICE").write_text("LiveKit Apache License\n", encoding="utf-8")
            (vendor / "provenance.json").write_text("{}\n", encoding="utf-8")
            adapter = web / "livekit_classroom_media.js"

            original_is_symlink = Path.is_symlink

            def fake_is_symlink(candidate: Path) -> bool:
                if candidate == adapter:
                    return True
                return original_is_symlink(candidate)

            with (
                mock.patch.object(final_release._release_ui, "_asset_root", return_value=root),
                mock.patch.object(Path, "is_symlink", new=fake_is_symlink),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "Classroom LiveKit media adapter resource is invalid",
                ):
                    final_release._final_product_resource_sources()

    def test_non_directory_livekit_vendor_root_fails_closed(self) -> None:
        from acs import version2_final_release as final_release

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            web = self._write_resource_fixture(root)
            vendor = web / "vendor"
            vendor.mkdir(parents=True)
            (vendor / "livekit").write_text("not a directory\n", encoding="utf-8")

            with mock.patch.object(
                final_release._release_ui,
                "_asset_root",
                return_value=root,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "LiveKit browser SDK resource root is invalid",
                ):
                    final_release._final_product_resource_sources()

    def test_linked_livekit_vendor_root_fails_closed_before_following_target(self) -> None:
        from acs import version2_final_release as final_release

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._write_resource_fixture(root)
            with (
                mock.patch.object(final_release._release_ui, "_asset_root", return_value=root),
                mock.patch.object(final_release.os.path, "lexists", return_value=True),
                mock.patch.object(Path, "is_symlink", return_value=True),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "LiveKit browser SDK resource root is invalid",
                ):
                    final_release._final_product_resource_sources()

    def test_main_failure_restores_exact_prior_release_owners(self) -> None:
        from acs import version2_final_release as final_release
        from acs import version2_release_app, version2_release_ui

        before = self._snapshot_release_globals()
        observed: list[tuple[object, object, object, object]] = []

        def fail_main() -> None:
            observed.append(
                (
                    version2_release_app.Version2Application,
                    version2_release_ui.VERSION2_FULL_PRODUCT_ACTION_IDS,
                    version2_release_ui.Version2NativeMenuController,
                    version2_release_ui._resource_sources,
                )
            )
            raise RuntimeError("main failed")

        with mock.patch.object(final_release._release_app, "main", side_effect=fail_main):
            with self.assertRaisesRegex(RuntimeError, "main failed"):
                final_release.main()

        self.assertEqual(len(observed), 1)
        application, action_ids, controller, resources = observed[0]
        self.assertIs(application, Version2FinalProductApplication)
        self.assertEqual(action_ids, FINAL_PRODUCT_ACTION_IDS)
        self.assertIs(controller, FinalProductNativeMenuController)
        self.assertIs(resources, final_release._final_product_resource_sources)
        self.assertEqual(self._snapshot_release_globals(), before)


if __name__ == "__main__":
    unittest.main()
