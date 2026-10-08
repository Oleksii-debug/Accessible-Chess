import json
import os
import unittest
from unittest.mock import patch

from acs.ai_provider_gateway import (
    AIProviderError,
    AIProviderGateway,
    ProviderProfile,
    ProviderRequest,
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


if __name__ == "__main__":
    unittest.main()
