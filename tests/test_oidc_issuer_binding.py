from __future__ import annotations

import unittest

from acs.oauth_pkce import OAuthContractError
from acs.oidc_metadata import OidcProviderMetadata


class OidcIssuerBindingTests(unittest.TestCase):
    def document(self, *, issuer: str = "https://accounts.example.test/tenant"):
        return {
            "issuer": issuer,
            "authorization_endpoint": "https://accounts.example.test/oauth/authorize",
            "token_endpoint": "https://accounts.example.test/oauth/token",
            "response_types_supported": ["code"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "grant_types_supported": ["authorization_code"],
            "scopes_supported": ["openid", "profile"],
        }

    def test_exact_configured_issuer_is_accepted(self):
        metadata = OidcProviderMetadata.from_mapping_for_issuer(
            self.document(), expected_issuer="https://accounts.example.test/tenant"
        )
        self.assertEqual(metadata.issuer, "https://accounts.example.test/tenant")

    def test_different_https_issuer_is_rejected(self):
        with self.assertRaisesRegex(OAuthContractError, "does not match"):
            OidcProviderMetadata.from_mapping_for_issuer(
                self.document(issuer="https://evil.example.test/tenant"),
                expected_issuer="https://accounts.example.test/tenant",
            )

    def test_issuer_path_and_trailing_slash_are_exact(self):
        mismatches = (
            "https://accounts.example.test/tenant/",
            "https://accounts.example.test/TENANT",
            "https://accounts.example.test/other",
        )
        for actual in mismatches:
            with self.subTest(actual=actual), self.assertRaises(OAuthContractError):
                OidcProviderMetadata.from_mapping_for_issuer(
                    self.document(issuer=actual),
                    expected_issuer="https://accounts.example.test/tenant",
                )

    def test_invalid_expected_issuer_fails_before_trust(self):
        for expected in (
            "http://accounts.example.test/tenant",
            "https://accounts.example.test/tenant?shadow=1",
            "",
        ):
            with self.subTest(expected=expected), self.assertRaises(OAuthContractError):
                OidcProviderMetadata.from_mapping_for_issuer(
                    self.document(), expected_issuer=expected
                )


if __name__ == "__main__":
    unittest.main()
