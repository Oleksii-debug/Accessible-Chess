from __future__ import annotations

import unittest

from acs.oidc_id_token import (
    IdTokenError,
    TrustedOidcIdentity,
    VerifiedIdTokenEnvelope,
    validate_id_token,
)


NOW = 1_800_000_000
ISSUER = "https://identity.example.invalid"
CLIENT = "accessible-chess-public-client"
NONCE = "nonce-123"
TOKEN = "header.payload.signature"


def _claims(**updates):
    value = {
        "iss": ISSUER,
        "sub": "user-42",
        "aud": CLIENT,
        "nonce": NONCE,
        "iat": NOW - 10,
        "exp": NOW + 300,
    }
    value.update(updates)
    return value


class _Verifier:
    def __init__(self, envelope=None, failure=None):
        self.envelope = envelope or VerifiedIdTokenEnvelope("RS256", _claims())
        self.failure = failure
        self.seen = []

    def verify(self, compact_token: str):
        self.seen.append(compact_token)
        if self.failure is not None:
            raise self.failure
        return self.envelope


class OidcIdTokenTests(unittest.TestCase):
    def validate(self, *, envelope=None, verifier=None, **kwargs):
        verifier = verifier or _Verifier(envelope=envelope)
        return validate_id_token(
            TOKEN,
            verifier=verifier,
            expected_issuer=ISSUER,
            client_id=CLIENT,
            expected_nonce=NONCE,
            now=lambda: NOW,
            **kwargs,
        )

    def test_valid_verified_token_projects_minimal_identity(self) -> None:
        verifier = _Verifier()
        identity = self.validate(verifier=verifier)
        self.assertEqual(
            identity,
            TrustedOidcIdentity(
                issuer=ISSUER,
                subject="user-42",
                audiences=(CLIENT,),
                issued_at=NOW - 10,
                expires_at=NOW + 300,
            ),
        )
        self.assertEqual(verifier.seen, [TOKEN])
        self.assertNotIn(TOKEN, repr(identity))
        self.assertNotIn(NONCE, repr(identity))

    def test_signature_verifier_exception_is_bounded_and_unlinked(self) -> None:
        verifier = _Verifier(failure=RuntimeError("private key/provider detail"))
        with self.assertRaisesRegex(IdTokenError, "signature verification failed") as caught:
            self.validate(verifier=verifier)
        self.assertIsNone(caught.exception.__cause__)
        self.assertNotIn("private", str(caught.exception))

    def test_requires_verified_envelope_and_secure_algorithm(self) -> None:
        class BadVerifier:
            def __init__(self, value):
                self.value = value

            def verify(self, token):
                return self.value

        cases = [
            (object(), "invalid verified token envelope"),
            (VerifiedIdTokenEnvelope("", _claims()), "invalid algorithm"),
            (VerifiedIdTokenEnvelope("none", _claims()), "unsecured token algorithm rejected"),
            (VerifiedIdTokenEnvelope("NoNe", _claims()), "unsecured token algorithm rejected"),
            (VerifiedIdTokenEnvelope("RS256", None), "invalid verified claims"),
        ]
        for envelope, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(IdTokenError, message):
                    self.validate(verifier=BadVerifier(envelope))

    def test_issuer_subject_and_nonce_fail_closed(self) -> None:
        cases = [
            (_claims(iss="https://other.invalid"), "issuer mismatch"),
            (_claims(sub=""), "invalid sub claim"),
            (_claims(nonce="wrong"), "nonce mismatch"),
            (_claims(nonce=""), "invalid nonce claim"),
        ]
        for claims, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(IdTokenError, message):
                    self.validate(envelope=VerifiedIdTokenEnvelope("ES256", claims))

    def test_audience_and_authorized_party_rules(self) -> None:
        accepted = [
            _claims(aud=CLIENT),
            _claims(aud=CLIENT, azp=CLIENT),
            _claims(aud=[CLIENT, "secondary"], azp=CLIENT),
        ]
        for claims in accepted:
            with self.subTest(claims=claims):
                self.validate(envelope=VerifiedIdTokenEnvelope("RS256", claims))

        rejected = [
            (_claims(aud="other"), "audience mismatch"),
            (_claims(aud=[CLIENT, "secondary"]), "authorized party required"),
            (_claims(aud=[CLIENT, "secondary"], azp="other"), "authorized party mismatch"),
            (_claims(aud=CLIENT, azp="other"), "authorized party mismatch"),
            (_claims(aud=[]), "invalid aud claim"),
            (_claims(aud=[CLIENT, CLIENT]), "invalid aud claim"),
            (_claims(aud=[CLIENT, 7]), "invalid aud claim"),
        ]
        for claims, message in rejected:
            with self.subTest(message=message):
                with self.assertRaisesRegex(IdTokenError, message):
                    self.validate(envelope=VerifiedIdTokenEnvelope("RS256", claims))

    def test_expiry_issued_at_not_before_and_lifetime_rules(self) -> None:
        rejected = [
            (_claims(exp=NOW - 61), "token expired"),
            (_claims(iat=NOW + 61), "token issued in future"),
            (_claims(nbf=NOW + 61), "token not yet valid"),
            (_claims(iat=NOW, exp=NOW), "invalid token lifetime"),
            (_claims(exp="tomorrow"), "invalid exp claim"),
            (_claims(iat=True), "invalid iat claim"),
            (_claims(nbf=-1), "invalid nbf claim"),
        ]
        for claims, message in rejected:
            with self.subTest(message=message):
                with self.assertRaisesRegex(IdTokenError, message):
                    self.validate(envelope=VerifiedIdTokenEnvelope("RS256", claims))

        # Boundaries are accepted inside the explicitly configured skew.
        self.validate(
            envelope=VerifiedIdTokenEnvelope(
                "RS256", _claims(iat=NOW + 60, nbf=NOW + 60, exp=NOW + 61)
            )
        )

    def test_required_claims_cannot_be_omitted(self) -> None:
        for name in ("iss", "sub", "aud", "nonce", "iat", "exp"):
            claims = _claims()
            claims.pop(name)
            with self.subTest(name=name):
                with self.assertRaises(IdTokenError):
                    self.validate(envelope=VerifiedIdTokenEnvelope("RS256", claims))

    def test_clock_skew_is_bounded_and_clock_failures_are_secret_safe(self) -> None:
        for skew in (-1, 301, 1.5, True):
            with self.subTest(skew=skew):
                with self.assertRaisesRegex(IdTokenError, "invalid clock skew"):
                    self.validate(clock_skew_seconds=skew)

        with self.assertRaisesRegex(IdTokenError, "clock unavailable") as caught:
            validate_id_token(
                TOKEN,
                verifier=_Verifier(),
                expected_issuer=ISSUER,
                client_id=CLIENT,
                expected_nonce=NONCE,
                now=lambda: (_ for _ in ()).throw(RuntimeError("private clock detail")),
            )
        self.assertIsNone(caught.exception.__cause__)

    def test_untrusted_input_dimensions_are_bounded(self) -> None:
        for kwargs in [
            {"compact_token": ""},
            {"expected_issuer": ""},
            {"client_id": ""},
            {"expected_nonce": ""},
            {"expected_nonce": "bad\nnonce"},
        ]:
            arguments = {
                "compact_token": TOKEN,
                "verifier": _Verifier(),
                "expected_issuer": ISSUER,
                "client_id": CLIENT,
                "expected_nonce": NONCE,
                "now": lambda: NOW,
            }
            arguments.update(kwargs)
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(IdTokenError):
                    validate_id_token(**arguments)


if __name__ == "__main__":
    unittest.main()
