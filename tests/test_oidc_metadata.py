from __future__ import annotations

import unittest

from acs.oauth_pkce import OAuthContractError
from acs.oidc_metadata import OidcProviderMetadata


class OidcProviderMetadataTests(unittest.TestCase):
    def document(self, **overrides):
        value = {
            "issuer": "https://accounts.example.test/tenant",
            "authorization_endpoint": "https://accounts.example.test/oauth/authorize",
            "token_endpoint": "https://accounts.example.test/oauth/token",
            "response_types_supported": ["code"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "grant_types_supported": ["authorization_code"],
            "scopes_supported": ["openid", "profile", "email"],
        }
        value.update(overrides)
        return value

    def test_valid_public_client_metadata_builds_pkce_request(self):
        metadata = OidcProviderMetadata.from_mapping(self.document())
        request = metadata.create_authorization_request(
            client_id="accessible-chess-desktop",
            redirect_uri="http://127.0.0.1:43127/callback",
            scopes=("openid", "profile"),
        )
        self.assertEqual(request.authorization_endpoint, self.document()["authorization_endpoint"])
        self.assertEqual(request.token_endpoint, self.document()["token_endpoint"])
        self.assertEqual(request.scopes, ("openid", "profile"))
        self.assertEqual(len(request.code_challenge), 43)

    def test_metadata_must_be_plain_json_object(self):
        class CustomDict(dict):
            pass

        with self.assertRaises(OAuthContractError):
            OidcProviderMetadata.from_mapping(CustomDict(self.document()))

    def test_issuer_and_endpoints_require_https(self):
        cases = (
            {"issuer": "http://accounts.example.test"},
            {"authorization_endpoint": "http://accounts.example.test/authorize"},
            {"token_endpoint": "http://accounts.example.test/token"},
            {"issuer": "https://accounts.example.test/tenant?shadow=1"},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides), self.assertRaises(OAuthContractError):
                OidcProviderMetadata.from_mapping(self.document(**overrides))

    def test_authorization_code_response_type_is_required(self):
        with self.assertRaisesRegex(OAuthContractError, "authorization code flow"):
            OidcProviderMetadata.from_mapping(
                self.document(response_types_supported=["id_token"])
            )

    def test_s256_is_required_and_plain_pkce_is_not_enough(self):
        for methods in ([], ["plain"]):
            with self.subTest(methods=methods), self.assertRaises(OAuthContractError):
                OidcProviderMetadata.from_mapping(
                    self.document(code_challenge_methods_supported=methods)
                )

    def test_public_client_none_token_auth_is_required(self):
        for methods in (None, ["client_secret_basic"], ["private_key_jwt"]):
            with self.subTest(methods=methods), self.assertRaises(OAuthContractError):
                document = self.document()
                if methods is None:
                    document.pop("token_endpoint_auth_methods_supported")
                else:
                    document["token_endpoint_auth_methods_supported"] = methods
                OidcProviderMetadata.from_mapping(document)

    def test_authorization_code_grant_is_required_when_advertised(self):
        with self.assertRaisesRegex(OAuthContractError, "authorization_code grant"):
            OidcProviderMetadata.from_mapping(
                self.document(grant_types_supported=["refresh_token"])
            )

    def test_openid_scope_is_required_when_scope_catalog_is_advertised(self):
        with self.assertRaisesRegex(OAuthContractError, "openid scope"):
            OidcProviderMetadata.from_mapping(
                self.document(scopes_supported=["profile", "email"])
            )

    def test_requested_scopes_are_checked_against_provider_catalog(self):
        metadata = OidcProviderMetadata.from_mapping(self.document())
        with self.assertRaisesRegex(OAuthContractError, "unsupported scope"):
            metadata.create_authorization_request(
                client_id="accessible-chess-desktop",
                redirect_uri="http://127.0.0.1:43127/callback",
                scopes=("openid", "offline_access"),
            )

    def test_oidc_request_cannot_drop_openid_scope(self):
        metadata = OidcProviderMetadata.from_mapping(self.document())
        with self.assertRaisesRegex(OAuthContractError, "requires openid"):
            metadata.create_authorization_request(
                client_id="accessible-chess-desktop",
                redirect_uri="http://127.0.0.1:43127/callback",
                scopes=("profile",),
            )

    def test_capability_arrays_reject_duplicates_and_non_text_values(self):
        cases = (
            {"response_types_supported": ["code", "code"]},
            {"code_challenge_methods_supported": ["S256", 7]},
            {"token_endpoint_auth_methods_supported": "none"},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides), self.assertRaises(OAuthContractError):
                OidcProviderMetadata.from_mapping(self.document(**overrides))


if __name__ == "__main__":
    unittest.main()
