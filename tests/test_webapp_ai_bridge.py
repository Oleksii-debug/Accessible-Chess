import unittest
from pathlib import Path
import tempfile

from acs.settings import Settings
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

    def test_ollama_and_no_ai_profiles_are_available(self):
        profiles = AccessibleChessAPI().ai_provider_profiles()
        ollama = next(item for item in profiles if item["name"] == "ollama")
        disabled = next(item for item in profiles if item["name"] == "none")
        self.assertEqual(ollama["protocol"], "ollama-chat")
        self.assertTrue(ollama["configured"])
        self.assertEqual(disabled["protocol"], "none")

    def test_profile_metadata_persists_without_secret_value(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            first = AccessibleChessAPI()
            first._settings = Settings(path)
            result = first.ai_update_profile("mistral", "https://example.test/v1", "demo", "ACS_DEMO_KEY")
            self.assertTrue(result["ok"])

            restarted = AccessibleChessAPI()
            restarted._settings = Settings(path)
            profile = next(item for item in restarted.ai_provider_profiles() if item["name"] == "mistral")
            self.assertEqual(profile["base_url"], "https://example.test/v1")
            self.assertEqual(profile["model"], "demo")
            self.assertEqual(profile["api_key_env"], "ACS_DEMO_KEY")
            self.assertNotIn("secret", path.read_text(encoding="utf-8").casefold())


if __name__ == "__main__":
    unittest.main()
