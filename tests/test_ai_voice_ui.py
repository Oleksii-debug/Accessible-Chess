from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AIVoiceUITests(unittest.TestCase):
    def test_accessible_conversation_and_voice_controls_are_exposed(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<script src="ai_voice.js"></script>', html)
        for control_id in (
            "ai-prompt",
            "ai-listen",
            "ai-stop-listening",
            "ai-send",
            "ai-speak-response",
            "ai-speech-rate",
            "ai-stop-speaking",
            "ai-voice-status",
            "ai-voice-privacy-hint",
            "ai-timeout",
        ):
            self.assertIn(f'id="{control_id}"', html)
        self.assertEqual(html.count('aria-live="polite"'), 1)
        self.assertIn('id="ai-voice-status" class="block" role="status" aria-live="off"', html)
        self.assertIn("requestMessages=[...aiConversation", html)
        self.assertIn("].slice(-12)", html)
        self.assertIn("agentVoiceController?.speak", html)

    def test_slow_local_model_wait_is_user_configurable(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        gateway = (ROOT / "acs" / "ai_provider_gateway.py").read_text(encoding="utf-8")
        self.assertIn('id="ai-timeout" type="number" min="1" max="600"', html)
        self.assertIn("timeout_seconds=300.0", gateway)
        self.assertIn("<= 600.0", gateway)


if __name__ == "__main__":
    unittest.main()
