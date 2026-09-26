from __future__ import annotations

import unittest

from acs.oauth_pkce import AuthorizationRequest, OAuthContractError
from acs.oauth_token_response import OAuthTokenResponse


class OAuthTokenResponseTests(unittest.TestCase):
    def authorization_request(self, *, scopes=("openid", "profile")) -> AuthorizationRequest:
        return AuthorizationRequest.create(
            authorization_endpoint="https://accounts.example.test/oauth/authorize",
            token_endpoint="https://accounts.example.test/oauth/token",
            client_id="accessible-chess-desktop",
            redirect_uri="http://127.0.0.1:43127/callback",
            scopes=scopes,
            state="state-123",
            nonce="nonce-456",
            code_verifier="A" * 64,
        )

    def test_valid_success_response_is_bounded_and_secret_safe_in_repr(self):
        response = OAuthTokenResponse.from_mapping(
            {
                "access_token": "access-secret-value",
                "token_type": "bearer",
                "expires_in": 3600,
                "scope": "openid profile",
                "refresh_token": "refresh-secret-value",
                "id_token": "id-secret-value",
            }
        )
        self.assertEqual(response.token_type, "Bearer")
        self.assertEqual(response.expires_in, 3600)
        self.assertEqual(response.scope, ("openid", "profile"))
        self.assertEqual(response.access_token, "access-secret-value")
        rendered = repr(response)
        self.assertNotIn("access-secret-value", rendered)
        self.assertNotIn("refresh-secret-value", rendered)
        self.assertNotIn("id-secret-value", rendered)

    def test_access_token_and_bearer_type_are_required(self):
        cases = (
            {"token_type": "Bearer"},
            {"access_token": "token"},
            {"access_token": "token", "token_type": "MAC"},
            {"access_token": "", "token_type": "Bearer"},
        )
        for document in cases:
            with self.subTest(document=document), self.assertRaises(OAuthContractError):
                OAuthTokenResponse.from_mapping(document)

    def test_error_document_never_becomes_partial_success(self):
        with self.assertRaisesRegex(OAuthContractError, "reported an error") as raised:
            OAuthTokenResponse.from_mapping(
                {
                    "access_token": "must-not-leak",
                    "token_type": "Bearer",
                    "error": "invalid_grant",
                    "error_description": "also-must-not-leak",
                }
            )
        self.assertNotIn("must-not-leak", str(raised.exception))
        self.assertNotIn("invalid_grant", str(raised.exception))

    def test_expires_in_requires_plain_positive_bounded_integer(self):
        for value in (0, -1, True, "3600", 366 * 24 * 60 * 60 + 1):
            with self.subTest(value=value), self.assertRaises(OAuthContractError):
                OAuthTokenResponse.from_mapping(
                    {"access_token": "token", "token_type": "Bearer", "expires_in": value}
                )

    def test_scope_is_canonical_space_delimited_and_unique(self):
        response = OAuthTokenResponse.from_mapping(
            {"access_token": "token", "token_type": "Bearer", "scope": "openid profile"}
        )
        self.assertEqual(response.scope, ("openid", "profile"))
        for value in ("openid  profile", "openid\tprofile", "openid openid", ""):
            with self.subTest(value=value), self.assertRaises(OAuthContractError):
                OAuthTokenResponse.from_mapping(
                    {"access_token": "token", "token_type": "Bearer", "scope": value}
                )

    def test_optional_tokens_must_still_be_nonempty_when_present(self):
        for name in ("refresh_token", "id_token"):
            with self.subTest(name=name), self.assertRaises(OAuthContractError):
                OAuthTokenResponse.from_mapping(
                    {"access_token": "token", "token_type": "Bearer", name: ""}
                )

    def test_token_response_requires_plain_json_object(self):
        class MappingSubclass(dict):
            pass

        with self.assertRaises(OAuthContractError):
            OAuthTokenResponse.from_mapping(
                MappingSubclass({"access_token": "token", "token_type": "Bearer"})
            )

    def test_oidc_request_accepts_id_token_and_returned_scope_subset(self):
        request = self.authorization_request(scopes=("openid", "profile", "email"))
        response = OAuthTokenResponse.from_mapping(
            {
                "access_token": "access-token",
                "token_type": "Bearer",
                "scope": "openid profile",
                "id_token": "signed-token-placeholder",
            }
        )
        self.assertIs(response.validate_for_request(request), response)

    def test_oidc_request_requires_id_token(self):
        request = self.authorization_request(scopes=("openid", "profile"))
        response = OAuthTokenResponse.from_mapping(
            {
                "access_token": "access-token",
                "token_type": "Bearer",
                "scope": "openid profile",
            }
        )
        with self.assertRaisesRegex(OAuthContractError, "missing id_token"):
            response.validate_for_request(request)

    def test_response_scope_cannot_expand_beyond_requested_scope(self):
        request = self.authorization_request(scopes=("openid", "profile"))
        response = OAuthTokenResponse.from_mapping(
            {
                "access_token": "access-token",
                "token_type": "Bearer",
                "scope": "openid profile admin",
                "id_token": "signed-token-placeholder",
            }
        )
        with self.assertRaisesRegex(OAuthContractError, "unrequested scope"):
            response.validate_for_request(request)

    def test_plain_oauth_request_can_omit_id_token(self):
        request = self.authorization_request(scopes=("profile",))
        response = OAuthTokenResponse.from_mapping(
            {
                "access_token": "access-token",
                "token_type": "Bearer",
                "scope": "profile",
            }
        )
        self.assertIs(response.validate_for_request(request), response)

    def test_absent_response_scope_uses_request_contract_without_inventing_scope(self):
        request = self.authorization_request(scopes=("openid", "profile"))
        response = OAuthTokenResponse.from_mapping(
            {
                "access_token": "access-token",
                "token_type": "Bearer",
                "id_token": "signed-token-placeholder",
            }
        )
        self.assertIsNone(response.scope)
        self.assertIs(response.validate_for_request(request), response)

    def test_direct_dataclass_construction_cannot_bypass_token_validation(self):
        request = self.authorization_request(scopes=("profile",))
        defaults = {
            "access_token": "access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": ("profile",),
        }
        invalid = (
            {"access_token": ""},
            {"token_type": "MAC"},
            {"expires_in": -1},
            {"expires_in": True},
            {"scope": ()},
            {"scope": ("profile", "profile")},
            {"scope": ("profile admin",)},
            {"refresh_token": ""},
            {"id_token": ""},
        )
        for override in invalid:
            values = dict(defaults)
            values.update(override)
            response = OAuthTokenResponse(**values)
            with self.subTest(override=override), self.assertRaises(OAuthContractError):
                response.validate_for_request(request)

        valid = OAuthTokenResponse(**defaults)
        self.assertIs(valid.validate_for_request(request), valid)

    def test_request_binding_rejects_wrong_request_type(self):
        response = OAuthTokenResponse.from_mapping(
            {"access_token": "access-token", "token_type": "Bearer"}
        )
        with self.assertRaisesRegex(OAuthContractError, "AuthorizationRequest"):
            response.validate_for_request(object())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
