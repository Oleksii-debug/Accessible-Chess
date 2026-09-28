from __future__ import annotations

import unittest

from acs.oauth_pkce import AuthorizationRequest, OAuthContractError


class OAuthPkceExplicitInputTests(unittest.TestCase):
    def create(self, **overrides):
        values = {
            "authorization_endpoint": "https://accounts.example.test/oauth/authorize",
            "token_endpoint": "https://accounts.example.test/oauth/token",
            "client_id": "accessible-chess-desktop",
            "redirect_uri": "http://127.0.0.1:43127/callback",
            "scopes": ("openid",),
        }
        values.update(overrides)
        return AuthorizationRequest.create(**values)

    def test_none_generates_security_correlation_values(self):
        request = self.create(state=None, nonce=None, code_verifier=None)
        self.assertTrue(request.state)
        self.assertTrue(request.nonce)
        self.assertGreaterEqual(len(request.code_verifier), 43)

    def test_explicit_empty_state_is_rejected_instead_of_regenerated(self):
        with self.assertRaises(OAuthContractError):
            self.create(state="")

    def test_explicit_empty_nonce_is_rejected_instead_of_regenerated(self):
        with self.assertRaises(OAuthContractError):
            self.create(nonce="")

    def test_explicit_empty_verifier_is_rejected_instead_of_regenerated(self):
        with self.assertRaises(OAuthContractError):
            self.create(code_verifier="")

    def test_explicit_whitespace_values_are_rejected(self):
        for field in ("state", "nonce", "code_verifier"):
            with self.subTest(field=field), self.assertRaises(OAuthContractError):
                self.create(**{field: " "})

    def test_scope_iteration_is_count_bounded(self):
        yielded = 0

        def scopes():
            nonlocal yielded
            while True:
                yielded += 1
                yield f"scope-{yielded}"

        with self.assertRaisesRegex(OAuthContractError, "scope count"):
            self.create(scopes=scopes())
        self.assertEqual(yielded, 65)

    def test_extra_authorization_parameters_and_url_size_are_bounded(self):
        request = self.create()
        too_many = {f"x-{index}": "v" for index in range(65)}
        with self.assertRaisesRegex(OAuthContractError, "parameter count"):
            request.authorization_url(extra_parameters=too_many)

        oversized = {f"long-{index}": "x" * 2048 for index in range(8)}
        with self.assertRaisesRegex(OAuthContractError, "URL exceeds"):
            request.authorization_url(extra_parameters=oversized)

    def test_text_subclass_cannot_execute_during_validation(self):
        calls: list[str] = []

        class HostileText(str):
            def strip(self):
                calls.append("strip")
                raise AssertionError("OAuth validator must not call subclass strip")

            def __eq__(self, other):
                calls.append("eq")
                raise AssertionError("OAuth validator must not call subclass equality")

        with self.assertRaisesRegex(OAuthContractError, "must be text"):
            self.create(client_id=HostileText("accessible-chess-desktop"))
        self.assertEqual(calls, [])



if __name__ == "__main__":
    unittest.main()
