from __future__ import annotations

import re
import unittest
from urllib.parse import parse_qs, urlsplit

from acs.oauth_pkce import (
    AuthorizationRequest,
    OAuthContractError,
    code_challenge_s256,
    generate_code_verifier,
)


class OAuthPkceTests(unittest.TestCase):
    def make_request(self, **overrides):
        values = {
            "authorization_endpoint": "https://accounts.example.test/oauth/authorize",
            "token_endpoint": "https://accounts.example.test/oauth/token",
            "client_id": "accessible-chess-desktop",
            "redirect_uri": "http://127.0.0.1:43127/callback",
            "scopes": ("openid", "profile", "email"),
            "state": "state-123",
            "nonce": "nonce-456",
            "code_verifier": "A" * 64,
        }
        values.update(overrides)
        return AuthorizationRequest.create(**values)

    def test_rfc7636_reference_vector(self):
        verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        self.assertEqual(
            code_challenge_s256(verifier),
            "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        )

    def test_generated_verifier_is_rfc7636_safe(self):
        values = {generate_code_verifier() for _ in range(32)}
        self.assertEqual(len(values), 32)
        for value in values:
            self.assertGreaterEqual(len(value), 43)
            self.assertLessEqual(len(value), 128)
            self.assertRegex(value, r"^[A-Za-z0-9._~-]+$")

    def test_authorization_url_is_code_flow_with_s256_state_and_nonce(self):
        request = self.make_request()
        parsed = urlsplit(request.authorization_url())
        query = parse_qs(parsed.query, keep_blank_values=True)

        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["client_id"], ["accessible-chess-desktop"])
        self.assertEqual(query["redirect_uri"], ["http://127.0.0.1:43127/callback"])
        self.assertEqual(query["scope"], ["openid profile email"])
        self.assertEqual(query["state"], ["state-123"])
        self.assertEqual(query["nonce"], ["nonce-456"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["code_challenge"], [code_challenge_s256("A" * 64)])
        self.assertNotIn("code_verifier", query)

    def test_token_exchange_keeps_verifier_out_of_authorization_url(self):
        request = self.make_request()
        self.assertNotIn("A" * 64, request.authorization_url())
        self.assertEqual(
            dict(request.token_exchange_form("authorization-code")),
            {
                "grant_type": "authorization_code",
                "code": "authorization-code",
                "redirect_uri": "http://127.0.0.1:43127/callback",
                "client_id": "accessible-chess-desktop",
                "code_verifier": "A" * 64,
            },
        )

    def test_scopes_are_deduplicated_in_stable_order(self):
        request = self.make_request(scopes=("openid", "profile", "openid", "email"))
        self.assertEqual(request.scopes, ("openid", "profile", "email"))

    def test_https_redirect_is_allowed(self):
        request = self.make_request(redirect_uri="https://app.example.test/oauth/callback")
        self.assertEqual(request.redirect_uri, "https://app.example.test/oauth/callback")

    def test_non_loopback_http_redirect_is_rejected(self):
        with self.assertRaises(OAuthContractError):
            self.make_request(redirect_uri="http://app.example.test/oauth/callback")

    def test_non_https_provider_endpoints_are_rejected(self):
        with self.assertRaises(OAuthContractError):
            self.make_request(authorization_endpoint="http://accounts.example.test/authorize")
        with self.assertRaises(OAuthContractError):
            self.make_request(token_endpoint="http://accounts.example.test/token")

    def test_userinfo_and_fragments_are_rejected(self):
        with self.assertRaises(OAuthContractError):
            self.make_request(
                authorization_endpoint="https://user:pass@accounts.example.test/authorize"
            )
        with self.assertRaises(OAuthContractError):
            self.make_request(token_endpoint="https://accounts.example.test/token#fragment")
        with self.assertRaises(OAuthContractError):
            self.make_request(redirect_uri="https://app.example.test/callback#fragment")

    def test_reserved_endpoint_query_collision_is_rejected(self):
        request = self.make_request(
            authorization_endpoint="https://accounts.example.test/authorize?client_id=shadow"
        )
        with self.assertRaises(OAuthContractError):
            request.authorization_url()

    def test_reserved_extra_parameter_collision_is_rejected(self):
        request = self.make_request()
        for name in (
            "client_id",
            "redirect_uri",
            "scope",
            "state",
            "nonce",
            "code_challenge",
            "code_challenge_method",
            "response_type",
        ):
            with self.subTest(name=name), self.assertRaises(OAuthContractError):
                request.authorization_url(extra_parameters={name: "shadow"})

    def test_provider_specific_extra_parameters_remain_explicit_and_encoded(self):
        request = self.make_request()
        query = parse_qs(
            urlsplit(
                request.authorization_url(
                    extra_parameters={"prompt": "login", "audience": "chess users"}
                )
            ).query
        )
        self.assertEqual(query["prompt"], ["login"])
        self.assertEqual(query["audience"], ["chess users"])

    def test_bad_verifiers_fail_closed(self):
        for verifier in ("short", "A" * 129, "A" * 63 + "!", " A" * 32):
            with self.subTest(verifier=verifier[:12]), self.assertRaises(OAuthContractError):
                self.make_request(code_verifier=verifier)

    def test_bad_scope_shapes_fail_closed(self):
        for scopes in ((), "openid profile", ("openid profile",), ("openid", "")):
            with self.subTest(scopes=scopes), self.assertRaises(OAuthContractError):
                self.make_request(scopes=scopes)

    def test_generated_state_and_nonce_are_nonempty_high_entropy_tokens(self):
        request = AuthorizationRequest.create(
            authorization_endpoint="https://accounts.example.test/oauth/authorize",
            token_endpoint="https://accounts.example.test/oauth/token",
            client_id="accessible-chess-desktop",
            redirect_uri="http://localhost:43127/callback",
            scopes=("openid",),
        )
        self.assertGreaterEqual(len(request.state), 32)
        self.assertGreaterEqual(len(request.nonce), 32)
        self.assertNotEqual(request.state, request.nonce)
        self.assertTrue(re.fullmatch(r"[A-Za-z0-9_-]+", request.state))
        self.assertTrue(re.fullmatch(r"[A-Za-z0-9_-]+", request.nonce))


if __name__ == "__main__":
    unittest.main()
