from __future__ import annotations

import re
import unittest
from urllib.parse import parse_qs, urlsplit

from acs.oauth_pkce import (
    AuthorizationRequest,
    OAuthAuthorizationError,
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

    def direct_request(self, **overrides):
        values = {
            "authorization_endpoint": "https://accounts.example.test/oauth/authorize",
            "token_endpoint": "https://accounts.example.test/oauth/token",
            "client_id": "accessible-chess-desktop",
            "redirect_uri": "http://127.0.0.1:43127/callback",
            "scopes": ("openid", "profile"),
            "state": "state-123",
            "nonce": "nonce-456",
            "code_verifier": "A" * 64,
        }
        values.update(overrides)
        return AuthorizationRequest(**values)

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

    def test_literal_ipv6_loopback_redirect_is_allowed(self):
        request = self.make_request(redirect_uri="http://[::1]:43127/callback")
        self.assertEqual(request.redirect_uri, "http://[::1]:43127/callback")

    def test_non_loopback_or_hostname_http_redirect_is_rejected(self):
        for redirect_uri in (
            "http://app.example.test/oauth/callback",
            "http://localhost:43127/callback",
        ):
            with self.subTest(redirect_uri=redirect_uri), self.assertRaises(OAuthContractError):
                self.make_request(redirect_uri=redirect_uri)

    def test_non_https_provider_endpoints_are_rejected(self):
        with self.assertRaises(OAuthContractError):
            self.make_request(authorization_endpoint="http://accounts.example.test/authorize")
        with self.assertRaises(OAuthContractError):
            self.make_request(token_endpoint="http://accounts.example.test/token")

    def test_malformed_provider_and_redirect_urls_fail_as_contract_errors(self):
        cases = (
            {"authorization_endpoint": "https://[::1/authorize"},
            {"token_endpoint": "https://accounts.example.test:99999/token"},
            {"redirect_uri": "http://[::1/callback"},
            {"redirect_uri": "http://127.0.0.1:99999/callback"},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides), self.assertRaises(OAuthContractError):
                self.make_request(**overrides)

    def test_url_backslashes_are_rejected_before_consumer_specific_parsing(self):
        cases = (
            {"authorization_endpoint": "https://accounts.example.test\\evil.test/authorize"},
            {"token_endpoint": "https://accounts.example.test\\evil.test/token"},
            {"redirect_uri": "https://app.example.test\\evil.test/callback"},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides), self.assertRaisesRegex(
                OAuthContractError, "ambiguous backslash"
            ):
                self.make_request(**overrides)

        request = self.make_request()
        with self.assertRaisesRegex(OAuthContractError, "ambiguous backslash"):
            request.authorization_code_from_callback(
                "http://127.0.0.1:43127\\evil.test/callback?code=abc&state=state-123"
            )

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

    def test_redirect_query_cannot_predefine_callback_parameters(self):
        for key in ("code", "error", "state"):
            with self.subTest(key=key), self.assertRaises(OAuthContractError):
                self.make_request(
                    redirect_uri=f"http://127.0.0.1:43127/callback?{key}=shadow"
                )

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
            redirect_uri="http://127.0.0.1:43127/callback",
            scopes=("openid",),
        )
        self.assertGreaterEqual(len(request.state), 32)
        self.assertGreaterEqual(len(request.nonce), 32)
        self.assertNotEqual(request.state, request.nonce)
        self.assertTrue(re.fullmatch(r"[A-Za-z0-9_-]+", request.state))
        self.assertTrue(re.fullmatch(r"[A-Za-z0-9_-]+", request.nonce))

    def test_direct_dataclass_construction_cannot_bypass_validation(self):
        invalid = (
            {"authorization_endpoint": "http://accounts.example.test/authorize"},
            {"redirect_uri": "http://localhost:43127/callback"},
            {"scopes": ("openid", "openid")},
            {"state": " state-with-leading-space"},
            {"nonce": ""},
            {"code_verifier": "short"},
        )
        for overrides in invalid:
            request = self.direct_request(**overrides)
            with self.subTest(overrides=overrides), self.assertRaises(OAuthContractError):
                request.authorization_url()
            with self.subTest(overrides=overrides), self.assertRaises(OAuthContractError):
                request.token_exchange_form("authorization-code")

    def test_callback_accepts_exact_redirect_and_matching_state(self):
        request = self.make_request()
        code = request.authorization_code_from_callback(
            "http://127.0.0.1:43127/callback?code=abc123&state=state-123&session_state=x"
        )
        self.assertEqual(code, "abc123")

    def test_callback_preserves_registered_redirect_query_contract(self):
        request = self.make_request(
            redirect_uri="http://127.0.0.1:43127/callback?channel=desktop"
        )
        self.assertEqual(
            request.authorization_code_from_callback(
                "http://127.0.0.1:43127/callback?state=state-123&channel=desktop&code=abc"
            ),
            "abc",
        )
        with self.assertRaises(OAuthContractError):
            request.authorization_code_from_callback(
                "http://127.0.0.1:43127/callback?state=state-123&code=abc"
            )

    def test_callback_rejects_missing_wrong_or_duplicate_state(self):
        callbacks = (
            "http://127.0.0.1:43127/callback?code=abc",
            "http://127.0.0.1:43127/callback?code=abc&state=wrong",
            "http://127.0.0.1:43127/callback?code=abc&state=state-123&state=state-123",
        )
        request = self.make_request()
        for callback in callbacks:
            with self.subTest(callback=callback), self.assertRaises(OAuthContractError):
                request.authorization_code_from_callback(callback)

    def test_callback_rejects_wrong_origin_path_fragment_and_duplicate_code(self):
        callbacks = (
            "http://127.0.0.1:43128/callback?code=abc&state=state-123",
            "http://127.0.0.1:43127/other?code=abc&state=state-123",
            "https://127.0.0.1:43127/callback?code=abc&state=state-123",
            "http://127.0.0.1:43127/callback?code=abc&state=state-123#frag",
            "http://127.0.0.1:43127/callback?code=abc&code=def&state=state-123",
        )
        request = self.make_request()
        for callback in callbacks:
            with self.subTest(callback=callback), self.assertRaises(OAuthContractError):
                request.authorization_code_from_callback(callback)

    def test_callback_requires_exactly_one_code_or_error(self):
        request = self.make_request()
        for callback in (
            "http://127.0.0.1:43127/callback?state=state-123",
            "http://127.0.0.1:43127/callback?code=abc&error=denied&state=state-123",
        ):
            with self.subTest(callback=callback), self.assertRaises(OAuthContractError):
                request.authorization_code_from_callback(callback)

    def test_validated_oauth_error_is_generic_but_preserves_bounded_code(self):
        request = self.make_request()
        with self.assertRaises(OAuthAuthorizationError) as raised:
            request.authorization_code_from_callback(
                "http://127.0.0.1:43127/callback?error=access_denied&state=state-123"
            )
        self.assertEqual(str(raised.exception), "authorization server returned an OAuth error")
        self.assertEqual(raised.exception.error_code, "access_denied")


if __name__ == "__main__":
    unittest.main()
