import unittest

from acs.security_redaction import REDACTED, assert_redacted, is_sensitive_key, redact_payload, redact_text


class SecurityRedactionTests(unittest.TestCase):
    def test_sensitive_mapping_keys_are_redacted_recursively_without_mutating_input(self):
        payload = {
            "account_id": "user-42",
            "access_token": "secret-access-token",
            "nested": {
                "client-secret": "secret-client-value",
                "message": "engine ready",
            },
            "items": [{"refreshToken": "secret-refresh-token"}],
        }

        sanitized = redact_payload(payload)

        self.assertEqual(sanitized["account_id"], "user-42")
        self.assertEqual(sanitized["access_token"], REDACTED)
        self.assertEqual(sanitized["nested"]["client-secret"], REDACTED)
        self.assertEqual(sanitized["items"][0]["refreshToken"], REDACTED)
        self.assertEqual(sanitized["nested"]["message"], "engine ready")
        self.assertEqual(payload["access_token"], "secret-access-token")

    def test_bearer_basic_jwt_and_url_credentials_are_removed_from_text(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyLTEifQ.c2lnbmF0dXJlMTIz"
        source = (
            "Authorization: Bearer abcdefghijklmnop "
            "proxy=Basic dXNlcjpwYXNzd29yZA== "
            f"jwt={jwt} "
            "https://example.invalid/callback?access_token=url-secret-value&x=1"
        )

        sanitized = redact_text(source)

        self.assertNotIn("abcdefghijklmnop", sanitized)
        self.assertNotIn("dXNlcjpwYXNzd29yZA==", sanitized)
        self.assertNotIn(jwt, sanitized)
        self.assertNotIn("url-secret-value", sanitized)
        self.assertIn("Bearer " + REDACTED, sanitized)
        self.assertIn("access_token=" + REDACTED, sanitized)

    def test_assignment_style_secrets_are_removed_but_normal_diagnostics_survive(self):
        source = "status=ok api_key=abc123456789 password: hunter2 depth=18"
        sanitized = redact_text(source)
        self.assertIn("status=ok", sanitized)
        self.assertIn("depth=18", sanitized)
        self.assertNotIn("abc123456789", sanitized)
        self.assertNotIn("hunter2", sanitized)

    def test_sensitive_key_policy_handles_common_variants(self):
        for key in ("Authorization", "refresh-token", "refreshToken", "license_key", "mySecret"):
            self.assertTrue(is_sensitive_key(key), key)
        self.assertFalse(is_sensitive_key("account_id"))
        self.assertFalse(is_sensitive_key("engine_depth"))

    def test_assert_redacted_accepts_sanitized_payload_and_detects_policy_regression(self):
        secret = "known-secret-123"
        payload = {"token": secret, "message": "Bearer " + secret}
        assert_redacted(payload, [secret])

        with self.assertRaises(ValueError):
            # The helper sanitizes first, so use a form intentionally outside the
            # policy to prove tests can pin any newly discovered secret format.
            assert_redacted({"message": "opaque:" + secret}, [secret])


if __name__ == "__main__":
    unittest.main()
