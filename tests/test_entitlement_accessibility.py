from __future__ import annotations

import unittest

from acs.entitlement_accessibility import EntitlementAccessibilityPresenter
from acs.full_product_actions import FullProductActionRouter, build_full_product_action_registry
from acs.full_product_ui_shell import AccessibleShellState, UILanguage


class EntitlementAccessibilityPresenterTests(unittest.TestCase):
    def test_expired_state_is_semantic_blocking_and_login_is_keyboard_target(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []
        presenter = EntitlementAccessibilityPresenter(
            lambda: {"state": "expired"},
            lambda action_id, payload: calls.append((action_id, dict(payload))) or "sent",
            language="en",
        )
        snapshot = presenter.snapshot()
        data = snapshot.as_dict()
        self.assertTrue(data["blocking"])
        self.assertFalse(data["active"])
        self.assertTrue(data["preserveUserData"])
        self.assertEqual("heading", data["headingRole"])
        self.assertEqual("status", data["statusRole"])
        self.assertEqual("polite", data["statusLive"])
        self.assertEqual("button", data["actionControl"])
        self.assertEqual("account.login", data["actionId"])
        self.assertEqual("entitlement-action", data["focusTarget"])
        self.assertEqual("sent", presenter.activate("account.login"))
        self.assertEqual([("account.login", {})], calls)

    def test_provider_failure_fails_closed_without_leaking_exception(self) -> None:
        def failing_provider():
            raise RuntimeError(r"provider secret at C:\\private\\license.json")

        presenter = EntitlementAccessibilityPresenter(failing_provider, lambda *_: None, language="en")
        data = presenter.snapshot().as_dict()
        self.assertEqual("unknown", data["state"])
        self.assertTrue(data["blocking"])
        self.assertEqual("entitlement.refresh", data["actionId"])
        rendered = f"{data['heading']} {data['summary']}"
        self.assertNotIn("provider", rendered.lower())
        self.assertNotIn("private", rendered.lower())
        self.assertNotIn("license.json", rendered)

    def test_malformed_state_projection_fails_closed_to_recovery(self) -> None:
        class ExplosiveState:
            def __str__(self) -> str:
                raise RuntimeError("projection must not escape")

        presenter = EntitlementAccessibilityPresenter(
            lambda: {"state": ExplosiveState()},
            lambda *_: None,
            language="en",
        )
        data = presenter.snapshot().as_dict()
        self.assertEqual("unknown", data["state"])
        self.assertTrue(data["blocking"])
        self.assertFalse(data["active"])
        self.assertTrue(data["preserveUserData"])
        self.assertEqual("entitlement.refresh", data["actionId"])
        self.assertEqual("entitlement-action", data["focusTarget"])

    def test_stale_browser_action_is_rejected_after_live_state_changes(self) -> None:
        state = {"state": "expired"}
        calls: list[str] = []
        presenter = EntitlementAccessibilityPresenter(
            lambda: dict(state),
            lambda action_id, payload: calls.append(action_id),
            language="en",
        )
        self.assertEqual("account.login", presenter.snapshot().view.action_id)
        state["state"] = "paid_monthly"
        with self.assertRaisesRegex(ValueError, "stale or unavailable"):
            presenter.activate("account.login")
        self.assertEqual([], calls)
        self.assertEqual("account.status", presenter.snapshot().view.action_id)

    def test_unknown_and_malformed_provider_data_never_unlocks_protected_access(self) -> None:
        for payload in ({}, {"state": "future_paid"}, "not-a-mapping"):
            with self.subTest(payload=payload):
                presenter = EntitlementAccessibilityPresenter(
                    lambda payload=payload: payload,  # type: ignore[return-value]
                    lambda *_: None,
                    language="uk",
                )
                view = presenter.snapshot().view
                self.assertFalse(view.active)
                self.assertTrue(view.blocking)
                self.assertTrue(view.preserve_user_data)

    def test_language_switch_keeps_action_identity(self) -> None:
        presenter = EntitlementAccessibilityPresenter(
            lambda: {"state": "grace_period"}, lambda *_: None, language="uk"
        )
        ua = presenter.snapshot()
        presenter.set_language("en")
        en = presenter.snapshot()
        self.assertEqual(ua.view.action_id, en.view.action_id)
        self.assertEqual(ua.view.state, en.view.state)
        self.assertNotEqual(ua.view.heading, en.view.heading)


class EntitlementReachabilityIntegrationTests(unittest.TestCase):
    def test_access_screen_is_central_registry_route_and_recovery_intents_delegate(self) -> None:
        registry = build_full_product_action_registry()
        for action_id in (
            "screen.access",
            "account.status",
            "account.login",
            "entitlement.refresh",
            "app.update",
        ):
            self.assertEqual(action_id, registry.definition(action_id).action_id)

        calls: list[tuple[str, dict[str, object]]] = []
        shell = AccessibleShellState(language=UILanguage.EN)
        router = FullProductActionRouter(
            shell,
            lambda action_id, payload: calls.append((action_id, dict(payload))) or "delegated",
        )
        opened = router.dispatch("screen.access", current_focus_id="board-square-e4")
        self.assertTrue(opened.handled_by_shell)
        self.assertEqual("access", opened.route_id)
        self.assertEqual("entitlement-status", opened.focus_target)
        self.assertEqual([], calls)

        delegated = router.dispatch("entitlement.refresh")
        self.assertFalse(delegated.handled_by_shell)
        self.assertEqual("delegated", delegated.value)
        self.assertEqual([("entitlement.refresh", {})], calls)


if __name__ == "__main__":
    unittest.main()
