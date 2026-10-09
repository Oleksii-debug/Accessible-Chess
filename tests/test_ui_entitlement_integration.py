import unittest

from acs.ui_entitlement import project_entitlement, semantic_contract


class AccessibleEntitlementIntegrationTests(unittest.TestCase):
    def test_free_beta_is_active_non_blocking_and_preserves_data(self):
        view = project_entitlement({"state": "free_beta"}, lang="uk")
        self.assertEqual(view.state, "free_beta")
        self.assertTrue(view.active)
        self.assertFalse(view.blocking)
        self.assertTrue(view.preserve_user_data)
        self.assertIsNone(view.action_id)

    def test_expired_and_revoked_preserve_local_data_and_offer_recovery(self):
        for state in ("expired", "revoked"):
            with self.subTest(state=state):
                view = project_entitlement({"state": state}, lang="en")
                self.assertFalse(view.active)
                self.assertTrue(view.blocking)
                self.assertTrue(view.preserve_user_data)
                self.assertEqual(view.action_id, "account.login")
                self.assertIn("preserved", view.summary)

    def test_grace_period_is_semantic_non_destructive_recovery_state(self):
        view = project_entitlement({"state": "grace_period"}, lang="uk")
        contract = semantic_contract(view)
        self.assertTrue(view.active)
        self.assertFalse(view.blocking)
        self.assertEqual(view.action_id, "entitlement.refresh")
        self.assertEqual(contract["statusRole"], "status")
        self.assertEqual(contract["statusLive"], "polite")
        self.assertEqual(contract["actionControl"], "button")
        self.assertFalse(contract["modalRequired"])
        self.assertFalse(contract["destructiveAction"])

    def test_update_required_blocks_protected_features_without_data_loss(self):
        view = project_entitlement({"state": "update_required"}, lang="en")
        contract = semantic_contract(view)
        self.assertTrue(view.blocking)
        self.assertEqual(view.action_id, "app.update")
        self.assertTrue(view.preserve_user_data)
        self.assertFalse(contract["destructiveAction"])

    def test_unknown_state_fails_closed_with_recovery_and_data_preservation(self):
        for payload in (None, {}, {"state": "provider-specific-value"}):
            with self.subTest(payload=payload):
                view = project_entitlement(payload, lang="uk")
                self.assertEqual(view.state, "unknown")
                self.assertFalse(view.active)
                self.assertTrue(view.blocking)
                self.assertTrue(view.preserve_user_data)
                self.assertEqual(view.action_id, "entitlement.refresh")
                self.assertIn("збережено", view.summary)

    def test_all_issue_11_states_have_semantic_projection(self):
        states = {
            "free_beta", "trial", "paid_monthly", "paid_yearly", "organization",
            "grace_period", "expired", "revoked", "update_required",
        }
        for state in states:
            with self.subTest(state=state):
                contract = semantic_contract(project_entitlement({"state": state}, lang="en"))
                self.assertEqual(contract["state"], state)
                self.assertTrue(contract["heading"])
                self.assertTrue(contract["summary"])
                self.assertEqual(contract["headingRole"], "heading")
                self.assertEqual(contract["statusRole"], "status")
                self.assertFalse(contract["modalRequired"])


if __name__ == "__main__":
    unittest.main()
