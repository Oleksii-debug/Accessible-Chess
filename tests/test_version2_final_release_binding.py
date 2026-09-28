from __future__ import annotations

import importlib
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
