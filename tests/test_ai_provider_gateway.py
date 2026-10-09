import json
import os
import unittest
from unittest.mock import patch

from acs.ai_provider_gateway import (
    AIProviderError,
    AIProviderGateway,
    ProviderProfile,
    ProviderRequest,
    default_profiles,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class GatewayTests(unittest.TestCase):
    def profile(self):
        return ProviderProfile("test", "https://provider.test/v1", "test-model", "TEST_PROVIDER_KEY")

    def test_editor_metadata_never_contains_secret_value(self):
        with patch.dict(os.environ, {"TEST_PROVIDER_KEY": "super-secret"}, clear=False):
            gateway = AIProviderGateway({"test": self.profile()})
            metadata = gateway.profiles_for_editor()[0]
            self.assertTrue(metadata["configured"])
            self.assertNotIn("super-secret", repr(metadata))

    def test_openai_compatible_response_is_normalized(self):
        seen = {}

        def opener(request, timeout):
            seen["url"] = request.full_url
            seen["auth"] = request.get_header("Authorization")
            seen["body"] = json.loads(request.data.decode("utf-8"))
            seen["timeout"] = timeout
            return FakeResponse({"choices": [{"message": {"content": "Use 1. e4"}}], "usage": {"total_tokens": 4}})

        with patch.dict(os.environ, {"TEST_PROVIDER_KEY": "secret"}, clear=False):
            result = AIProviderGateway({"test": self.profile()}, opener=opener).complete(
                "test", ProviderRequest(({"role": "user", "content": "Suggest a move"},))
            )
        self.assertEqual(result.text, "Use 1. e4")
        self.assertEqual(seen["url"], "https://provider.test/v1/chat/completions")
        self.assertEqual(seen["auth"], "Bearer secret")
        self.assertEqual(seen["body"]["model"], "test-model")

    def test_missing_credentials_fails_without_network(self):
        with patch.dict(os.environ, {}, clear=True):
            gateway = AIProviderGateway({"test": self.profile()}, opener=lambda *_: self.fail("network call"))
            with self.assertRaisesRegex(AIProviderError, "credentials"):
                gateway.complete("test", ProviderRequest(({"role": "user", "content": "x"},)))

    def test_retryable_failure_is_bounded(self):
        calls = []

        def opener(*_args, **_kwargs):
            calls.append(1)
            raise TimeoutError("timeout")

        with patch.dict(os.environ, {"TEST_PROVIDER_KEY": "secret"}, clear=False):
            gateway = AIProviderGateway({"test": self.profile()}, opener=opener, sleep=lambda _: None)
            with self.assertRaises(AIProviderError) as raised:
                gateway.complete("test", ProviderRequest(({"role": "user", "content": "x"},)))
        self.assertEqual(len(calls), 3)
        self.assertEqual(raised.exception.code, "network-error")

    def test_ollama_uses_loopback_without_secret_and_normalizes_response(self):
        seen = {}

        def opener(request, timeout):
            seen["url"] = request.full_url
            seen["auth"] = request.get_header("Authorization")
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse({"message": {"content": "Play e4"}, "prompt_eval_count": 9, "eval_count": 3})

        profile = ProviderProfile("ollama", "http://127.0.0.1:11434", "qwen3:8b", "", protocol="ollama-chat")
        gateway = AIProviderGateway({"ollama": profile}, opener=opener)
        result = gateway.complete("ollama", ProviderRequest(({"role": "user", "content": "move"},)))
        self.assertEqual(result.text, "Play e4")
        self.assertEqual(seen["url"], "http://127.0.0.1:11434/api/chat")
        self.assertIsNone(seen["auth"])
        self.assertFalse(seen["body"]["stream"])
        self.assertFalse(seen["body"]["think"])

    def test_default_ollama_profile_allows_slow_local_inference(self):
        profile = next(item for item in default_profiles().values() if item.name == "ollama")
        self.assertEqual(profile.timeout_seconds, 300.0)

    def test_profile_timeout_accepts_bounded_long_local_wait(self):
        gateway = AIProviderGateway()
        gateway.upsert_profile(ProviderProfile("slow", "http://127.0.0.1:11434", "local-9b", "", protocol="ollama-chat", timeout_seconds=600))
        with self.assertRaisesRegex(ValueError, "timeout"):
            gateway.upsert_profile(ProviderProfile("too-slow", "http://127.0.0.1:11434", "local", "", protocol="ollama-chat", timeout_seconds=601))

    def test_ollama_rejects_non_loopback_http_endpoint(self):
        gateway = AIProviderGateway()
        with self.assertRaisesRegex(ValueError, "loopback"):
            gateway.upsert_profile(ProviderProfile("bad", "http://example.test:11434", "qwen", "", protocol="ollama-chat"))

    def test_no_ai_mode_never_calls_network(self):
        profile = ProviderProfile("none", "", "", "", protocol="none")
        gateway = AIProviderGateway({"none": profile}, opener=lambda *_args, **_kwargs: self.fail("network call"))
        with self.assertRaises(AIProviderError) as raised:
            gateway.complete("none", ProviderRequest(({"role": "user", "content": "x"},)))
        self.assertEqual(raised.exception.code, "provider-disabled")


if __name__ == "__main__":
    unittest.main()
