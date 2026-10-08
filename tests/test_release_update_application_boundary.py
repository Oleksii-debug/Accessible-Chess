from __future__ import annotations

import unittest

from acs.full_product_actions import (
    FULL_PRODUCT_ACTION_IDS,
    build_full_product_action_registry,
)
from acs.full_product_native_menu import build_full_product_menu_spec
from acs.full_product_ui_shell import UILanguage
from acs.release_update_center import ReleaseUpdateError, ReleaseUpdateSnapshot
from acs.version2_application import Version2Application
from acs.version2_profile import build_version2_action_registry, build_version2_shell


_RELEASE_IDS = {
    "release.status",
    "release.check_update",
    "release.apply_update",
}


class FakeCenter:
    def __init__(self):
        self.calls = []

    def snapshot(self, *, language):
        self.calls.append(("status", language))
        return ReleaseUpdateSnapshot(
            state="idle",
            current_version="2.0.0",
            target_version=None,
            announcement="Стан випуску готовий." if language == "uk" else "Release status is ready.",
        )

    def check(self, *, language):
        self.calls.append(("check", language))
        return ReleaseUpdateSnapshot(
            state="ready",
            current_version="2.0.0",
            target_version="2.1.0",
            announcement="Оновлення перевірено." if language == "uk" else "Update verified.",
        )

    def apply(self, *, language):
        self.calls.append(("apply", language))
        return ReleaseUpdateSnapshot(
            state="installed",
            current_version="2.0.0",
            target_version="2.1.0",
            announcement="Оновлення передано інсталятору." if language == "uk" else "Update handed to installer.",
        )


class ReleaseUpdateApplicationBoundaryTests(unittest.TestCase):
    def app(self, *, language=UILanguage.UA, center=None):
        app = object.__new__(Version2Application)
        app.shell = build_version2_shell(language=language)
        app.release_update_center = center
        app._events = []
        return app

    def test_release_actions_are_in_canonical_and_v2_registries(self):
        self.assertTrue(_RELEASE_IDS.issubset(FULL_PRODUCT_ACTION_IDS))
        full = {item.action_id for item in build_full_product_action_registry().definitions()}
        v2 = {item.action_id for item in build_version2_action_registry().definitions()}
        self.assertTrue(_RELEASE_IDS.issubset(full))
        self.assertTrue(_RELEASE_IDS.issubset(v2))

    def test_native_help_menu_exposes_all_release_actions_in_both_languages(self):
        registry = build_full_product_action_registry()
        for language in (UILanguage.UA, UILanguage.EN):
            spec = build_full_product_menu_spec(registry, language=language)
            help_menu = next(item for item in spec if item.menu_id == "help")
            ids = {item.action_id for item in help_menu.items if item.action_id}
            self.assertTrue(_RELEASE_IDS.issubset(ids))
            labels = " ".join(item.label for item in help_menu.items)
            if language is UILanguage.UA:
                self.assertIn("оновл", labels.lower())
            else:
                self.assertIn("update", labels.lower())

    def test_status_without_external_channel_is_accessible_and_nonfatal(self):
        app = self.app(center=None)
        result = app._delegate("release.status", {})
        self.assertEqual(result["state"], "channel-not-configured")
        self.assertIn("канал оновлень", result["announcement"].lower())
        self.assertEqual(app._events[-1]["kind"], "status")
        self.assertEqual(app._events[-1]["payload"]["announcement"], result["announcement"])

    def test_update_without_external_channel_fails_with_user_message(self):
        app = self.app(center=None)
        with self.assertRaisesRegex(ValueError, "Канал оновлень"):
            app._delegate("release.check_update", {})
        self.assertEqual(app._events, [])

    def test_check_and_apply_delegate_to_bound_center_and_announce(self):
        center = FakeCenter()
        app = self.app(center=center)
        checked = app._delegate("release.check_update", {})
        applied = app._delegate("release.apply_update", {})
        self.assertEqual(checked["state"], "ready")
        self.assertEqual(applied["state"], "installed")
        self.assertEqual(center.calls, [("check", "uk"), ("apply", "uk")])
        self.assertEqual([event["kind"] for event in app._events], ["status", "status"])
        self.assertIn("перевірено", app._events[0]["payload"]["announcement"].lower())

    def test_release_errors_are_projected_without_provider_details(self):
        class Broken(FakeCenter):
            def check(self, *, language):
                raise ReleaseUpdateError("Не вдалося перевірити наявність оновлень.")

        app = self.app(center=Broken())
        with self.assertRaisesRegex(ValueError, "Не вдалося перевірити"):
            app._delegate("release.check_update", {})

    def test_english_release_status_uses_english_accessible_text(self):
        center = FakeCenter()
        app = self.app(language=UILanguage.EN, center=center)
        result = app._delegate("release.status", {})
        self.assertIn("Release", result["announcement"])
        self.assertEqual(center.calls, [("status", "en")])

    def test_payload_is_rejected_before_release_provider(self):
        center = FakeCenter()
        app = self.app(center=center)
        with self.assertRaisesRegex(ValueError, "accept no payload"):
            app._delegate("release.check_update", {"path": "secret"})
        self.assertEqual(center.calls, [])


if __name__ == "__main__":
    unittest.main()
