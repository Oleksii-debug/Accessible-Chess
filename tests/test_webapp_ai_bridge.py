import unittest

from acs.webapp import AccessibleChessAPI


class WebappAIBridgeTests(unittest.TestCase):
    def test_profiles_are_editor_safe(self):
        api = AccessibleChessAPI()
        profiles = api.ai_provider_profiles()
        self.assertTrue(any(item["name"] == "mistral" for item in profiles))
        self.assertTrue(all("api_key" not in item for item in profiles))

    def test_profile_update_is_session_scoped(self):
        api = AccessibleChessAPI()
        result = api.ai_update_profile("mistral", "https://example.test/v1", "demo-model", "ACS_DEMO_KEY")
        self.assertTrue(result["ok"])
        updated = next(item for item in result["profiles"] if item["name"] == "mistral")
        self.assertEqual(updated["base_url"], "https://example.test/v1")
        self.assertEqual(updated["model"], "demo-model")
        self.assertEqual(updated["api_key_env"], "ACS_DEMO_KEY")

    def test_completion_without_key_is_safe(self):
        api = AccessibleChessAPI()
        api.ai_update_profile("mistral", "https://example.test/v1", "demo-model", "ACS_MISSING_KEY_FOR_TEST")
        result = api.ai_complete("mistral", [{"role": "user", "content": "Explain"}])
        self.assertFalse(result["ok"])
        self.assertNotIn("ACS_MISSING_KEY_FOR_TEST", result.get("announcement", ""))


if __name__ == "__main__":
    unittest.main()
