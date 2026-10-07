import asyncio
import unittest
from pathlib import Path

from acs.subscription_plans import (
    BillingCadence,
    DEFAULT_PLAN_CATALOG,
    PlanId,
    SubscriptionActionIntent,
    SubscriptionActionKind,
    SubscriptionBillingProvider,
    data_safety_features,
    public_plan_catalog,
)
from acs.subscription_web import (
    AccessibleChessSubscriptionAsgi,
    SubscriptionWebError,
    SubscriptionWebGateway,
)
from acs.web_client_gateway import WebPrincipal


ROOT = Path(__file__).resolve().parents[1]


class FakeBillingProvider:
    def begin_checkout(self, account_id, plan_id, cadence):
        return "https://billing.example.test/checkout"

    def customer_portal_url(self, account_id):
        return "https://billing.example.test/manage"

    def request_cancellation(self, account_id):
        return None


class Section35SubscriptionTests(unittest.TestCase):
    def test_required_plan_models_are_present_and_provider_neutral(self):
        self.assertEqual(
            set(DEFAULT_PLAN_CATALOG),
            {
                PlanId.FREE,
                PlanId.BASIC,
                PlanId.PRO,
                PlanId.TEACHER,
                PlanId.ORGANIZATION,
                PlanId.SOCIAL_LICENSE,
            },
        )
        self.assertTrue(DEFAULT_PLAN_CATALOG[PlanId.ORGANIZATION].organization)
        self.assertTrue(DEFAULT_PLAN_CATALOG[PlanId.SOCIAL_LICENSE].sponsored)
        for definition in DEFAULT_PLAN_CATALOG.values():
            self.assertFalse(hasattr(definition, "price"))
            self.assertFalse(hasattr(definition, "provider"))
            self.assertFalse(
                any(value.startswith("accessibility.") for value in definition.feature_ids)
            )

    def test_free_has_no_checkout_and_commercial_plans_are_cadence_explicit(self):
        self.assertFalse(DEFAULT_PLAN_CATALOG[PlanId.FREE].requires_billing)
        self.assertEqual(
            DEFAULT_PLAN_CATALOG[PlanId.FREE].cadences,
            (BillingCadence.NONE,),
        )
        self.assertIn(
            BillingCadence.MONTHLY,
            DEFAULT_PLAN_CATALOG[PlanId.PRO].cadences,
        )
        self.assertIn(
            BillingCadence.YEARLY,
            DEFAULT_PLAN_CATALOG[PlanId.TEACHER].cadences,
        )
        self.assertEqual(
            DEFAULT_PLAN_CATALOG[PlanId.ORGANIZATION].cadences,
            (BillingCadence.ORGANIZATION,),
        )

    def test_subscription_actions_are_typed_and_checkout_cannot_target_free(self):
        select = SubscriptionActionIntent(
            SubscriptionActionKind.SELECT_PLAN,
            PlanId.PRO,
        )
        self.assertEqual(select.to_payload(), {"action": "select_plan", "plan_id": "pro"})
        checkout = SubscriptionActionIntent(
            SubscriptionActionKind.BEGIN_CHECKOUT,
            PlanId.PRO,
            BillingCadence.MONTHLY,
        )
        self.assertEqual(checkout.to_payload()["cadence"], "monthly")
        with self.assertRaises(ValueError):
            SubscriptionActionIntent(
                SubscriptionActionKind.BEGIN_CHECKOUT,
                PlanId.FREE,
                BillingCadence.NONE,
            )

    def test_billing_provider_protocol_contains_no_payment_vendor_contract(self):
        self.assertIsInstance(FakeBillingProvider(), SubscriptionBillingProvider)
        source = (ROOT / "acs" / "subscription_plans.py").read_text(encoding="utf-8").lower()
        for vendor in ("stripe", "paypal", "adyen", "braintree", "paddle"):
            self.assertNotIn(vendor, source)

    def test_catalog_exposes_data_safety_without_accessibility_entitlement(self):
        catalog = public_plan_catalog()
        self.assertEqual(len(catalog), 6)
        self.assertEqual(
            set(data_safety_features()),
            {"data.export", "data.recovery"},
        )
        self.assertFalse(
            any(
                feature.startswith("accessibility.")
                for item in catalog
                for feature in item["feature_ids"]
            )
        )

    def gateway(self):
        def snapshot(principal):
            return {
                "plans": list(public_plan_catalog()),
                "current_plan": "pro" if principal else None,
                "entitlement_state": "trial" if principal else "expired",
                "status_message": "Ready",
                "data_safety_features": list(data_safety_features()),
            }

        def command(principal, action, payload):
            if action is SubscriptionActionKind.REGISTER:
                return {
                    "message": "Continue to registration.",
                    "navigation_url": "/register",
                    "navigation_label": "Register",
                }
            if action is SubscriptionActionKind.BEGIN_CHECKOUT:
                return {
                    "message": "Continue to checkout.",
                    "navigation_url": "https://billing.example.test/checkout",
                }
            if action is SubscriptionActionKind.OPEN_MANAGE:
                return {"navigation_url": "https://billing.example.test/manage"}
            return {"message": action.value, "payload": dict(payload)}

        return SubscriptionWebGateway(snapshot=snapshot, command=command)

    def test_public_registration_is_available_but_billing_actions_require_auth(self):
        gateway = self.gateway()
        public = gateway.snapshot(None)
        self.assertFalse(public["signed_in"])
        self.assertEqual(len(public["subscription"]["plans"]), 6)
        registration = gateway.command(None, action="register", payload={})
        self.assertEqual(registration["result"]["navigation_url"], "/register")
        with self.assertRaises(SubscriptionWebError) as caught:
            gateway.command(
                None,
                action="begin_checkout",
                payload={"plan_id": "pro", "cadence": "monthly"},
            )
        self.assertEqual(caught.exception.status, 401)

    def test_navigation_targets_fail_closed(self):
        gateway = SubscriptionWebGateway(
            snapshot=lambda _principal: {},
            command=lambda _principal, _action, _payload: {
                "navigation_url": "javascript:alert(1)"
            },
        )
        with self.assertRaises(SubscriptionWebError):
            gateway.command(None, action="register", payload={})

        fragment = SubscriptionWebGateway(
            snapshot=lambda _principal: {},
            command=lambda _principal, _action, _payload: {
                "navigation_url": "https://example.test/pay#token"
            },
        )
        with self.assertRaises(SubscriptionWebError):
            fragment.command(None, action="register", payload={})

    def test_authenticated_checkout_navigation_is_https_and_non_secret(self):
        principal = WebPrincipal("user-1", "workspace-1", "session-1", ("member",))
        result = self.gateway().command(
            principal,
            action="begin_checkout",
            payload={"plan_id": "pro", "cadence": "monthly"},
        )
        self.assertEqual(
            result["result"]["navigation_url"],
            "https://billing.example.test/checkout",
        )
        text = repr(result).lower()
        self.assertNotIn("card_number", text)
        self.assertNotIn("cvv", text)
        self.assertNotIn("client_secret", text)

    def test_subscription_html_is_semantic_keyboard_native_and_data_safe(self):
        html = (ROOT / "web" / "accessible_chess_subscription.html").read_text(
            encoding="utf-8"
        )
        lowered = html.lower()
        for token in (
            "<main",
            "<section",
            "<form",
            "<fieldset",
            "<legend",
            "<label",
            "<select",
            'role="status"',
            'role="alert"',
        ):
            self.assertIn(token, lowered)
        self.assertIn("Експорт і відновлення", html)
        self.assertNotIn("onclick=", lowered)
        self.assertNotIn('tabindex="-1" role="button"', lowered)

    def test_subscription_javascript_uses_native_events_and_no_popup_checkout(self):
        script = (ROOT / "web" / "accessible_chess_subscription.js").read_text(
            encoding="utf-8"
        )
        lowered = script.lower()
        self.assertIn("addeventlistener", lowered)
        self.assertIn('credentials: "same-origin"', lowered)
        self.assertNotIn("window.open", lowered)
        self.assertNotIn("onclick", lowered)
        for vendor in ("stripe", "paypal", "adyen", "braintree", "paddle"):
            self.assertNotIn(vendor, lowered)

    def test_asgi_serves_public_semantic_page_and_public_snapshot(self):
        app = AccessibleChessSubscriptionAsgi(self.gateway())

        async def run():
            sent = []
            events = [{"type": "http.request", "body": b"", "more_body": False}]

            async def receive():
                return events.pop(0)

            async def send(message):
                sent.append(message)

            await app(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/v1/subscription/snapshot",
                    "query_string": b"",
                    "headers": [],
                    "state": {},
                },
                receive,
                send,
            )
            return sent

        sent = asyncio.run(run())
        self.assertEqual(sent[0]["status"], 200)
        body = sent[1]["body"].decode("utf-8")
        self.assertIn('"signed_in":false', body)
        self.assertIn('"social_license"', body)


if __name__ == "__main__":
    unittest.main()
