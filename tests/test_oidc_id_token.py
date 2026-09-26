from __future__ import annotations

import base64
import hashlib
import json
import math
import random
import unittest

from acs.oidc_id_token import OidcIdTokenError, verify_id_token


_E = 65537
_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


def _is_probable_prime(value: int) -> bool:
    for prime in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if value % prime == 0:
            return value == prime
    remainder = value - 1
    power = 0
    while remainder % 2 == 0:
        power += 1
        remainder //= 2
    for base in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        candidate = pow(base, remainder, value)
        if candidate in (1, value - 1):
            continue
        for _ in range(power - 1):
            candidate = pow(candidate, 2, value)
            if candidate == value - 1:
                break
        else:
            return False
    return True


def _test_prime(bits: int, rng: random.Random) -> int:
    while True:
        candidate = rng.getrandbits(bits) | 1 | (1 << (bits - 1))
        if _is_probable_prime(candidate):
            return candidate


def _test_rsa_key() -> tuple[int, int]:
    # Generated at test time so the repository contains no private-key fixture.
    rng = random.Random(812827)
    while True:
        first = _test_prime(1024, rng)
        second = _test_prime(1024, rng)
        if first == second:
            continue
        phi = (first - 1) * (second - 1)
        if math.gcd(_E, phi) == 1:
            return first * second, pow(_E, -1, phi)


_N, _D = _test_rsa_key()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64_int(value: int) -> str:
    return _b64(value.to_bytes((value.bit_length() + 7) // 8, "big"))


def _json_segment(value: dict[str, object]) -> str:
    return _b64(json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def _sign(signing_input: bytes) -> bytes:
    width = (_N.bit_length() + 7) // 8
    digest = hashlib.sha256(signing_input).digest()
    tail = _DIGEST_INFO + digest
    encoded = b"\x00\x01" + b"\xff" * (width - len(tail) - 3) + b"\x00" + tail
    return pow(int.from_bytes(encoded, "big"), _D, _N).to_bytes(width, "big")


def _token(*, header: dict[str, object] | None = None, claims: dict[str, object] | None = None) -> str:
    effective_header = {"alg": "RS256", "kid": "test-key", "typ": "JWT"}
    if header:
        effective_header.update(header)
    effective_claims: dict[str, object] = {
        "iss": "https://identity.example.test",
        "sub": "user-123",
        "aud": "accessible-chess-client",
        "nonce": "request-nonce",
        "iat": 1_700_000_000,
        "exp": 1_700_000_600,
    }
    if claims:
        effective_claims.update(claims)
    encoded_header = _json_segment(effective_header)
    encoded_claims = _json_segment(effective_claims)
    signing_input = f"{encoded_header}.{encoded_claims}".encode("ascii")
    return f"{encoded_header}.{encoded_claims}.{_b64(_sign(signing_input))}"


def _jwks() -> dict[str, object]:
    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": "test-key",
                "alg": "RS256",
                "use": "sig",
                "key_ops": ["verify"],
                "n": _b64_int(_N),
                "e": _b64_int(_E),
            }
        ]
    }


class OidcIdTokenTests(unittest.TestCase):
    def verify(self, token: str, *, jwks: dict[str, object] | None = None):
        return verify_id_token(
            token,
            jwks=_jwks() if jwks is None else jwks,
            expected_issuer="https://identity.example.test",
            client_id="accessible-chess-client",
            expected_nonce="request-nonce",
            now=1_700_000_100,
            clock_skew_seconds=30,
        )

    def test_valid_rs256_token_is_bound_to_request(self) -> None:
        verified = self.verify(_token())
        self.assertEqual(verified.subject, "user-123")
        self.assertEqual(verified.audience, ("accessible-chess-client",))
        self.assertEqual(verified.expires_at, 1_700_000_600)
        self.assertNotIn("user-123", repr(verified))
        self.assertNotIn("request-nonce", repr(verified))

    def test_signature_tampering_fails_closed(self) -> None:
        token = _token()
        header, payload, signature = token.split(".")
        raw = bytearray(base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)))
        raw[-1] ^= 1
        with self.assertRaisesRegex(OidcIdTokenError, "signature verification failed"):
            self.verify(f"{header}.{payload}.{_b64(bytes(raw))}")

    def test_algorithm_confusion_and_critical_extensions_are_rejected(self) -> None:
        with self.assertRaisesRegex(OidcIdTokenError, "must use RS256"):
            self.verify(_token(header={"alg": "none"}))
        with self.assertRaisesRegex(OidcIdTokenError, "critical extensions"):
            self.verify(_token(header={"crit": ["exp"]}))

    def test_wrong_issuer_audience_nonce_and_azp_fail(self) -> None:
        cases = (
            ({"iss": "https://evil.example.test"}, "issuer"),
            ({"aud": "different-client"}, "audience"),
            ({"nonce": "replayed-nonce"}, "nonce"),
            ({"aud": ["accessible-chess-client", "other"], "azp": "other"}, "azp"),
        )
        for claims, message in cases:
            with self.subTest(claims=claims):
                with self.assertRaisesRegex(OidcIdTokenError, message):
                    self.verify(_token(claims=claims))

    def test_time_claims_are_fail_closed(self) -> None:
        cases = (
            ({"exp": 1_700_000_070}, "expired"),
            ({"iat": 1_700_000_131}, "iat"),
            ({"nbf": 1_700_000_131}, "not yet valid"),
            ({"exp": True}, "exp"),
        )
        for claims, message in cases:
            with self.subTest(claims=claims):
                with self.assertRaisesRegex(OidcIdTokenError, message):
                    self.verify(_token(claims=claims))

    def test_expiry_allows_only_explicit_bounded_clock_skew(self) -> None:
        verified = self.verify(_token(claims={"exp": 1_700_000_120}))
        self.assertEqual(verified.expires_at, 1_700_000_120)
        with self.assertRaisesRegex(OidcIdTokenError, "clock skew"):
            verify_id_token(
                _token(), jwks=_jwks(), expected_issuer="https://identity.example.test",
                client_id="accessible-chess-client", expected_nonce="request-nonce",
                now=1_700_000_100, clock_skew_seconds=301,
            )

    def test_jwks_key_selection_is_exact_and_bounded(self) -> None:
        duplicate = _jwks()
        duplicate["keys"] = list(duplicate["keys"]) * 2
        with self.assertRaisesRegex(OidcIdTokenError, "exactly one"):
            self.verify(_token(), jwks=duplicate)
        wrong_kid = _jwks()
        wrong_kid["keys"][0]["kid"] = "different"
        with self.assertRaisesRegex(OidcIdTokenError, "exactly one"):
            self.verify(_token(), jwks=wrong_kid)
        with self.assertRaisesRegex(OidcIdTokenError, "bounded"):
            self.verify(_token(), jwks={"keys": list(_jwks()["keys"]) * 33})

    def test_standard_jwks_extensions_and_omitted_jwk_alg_are_accepted(self) -> None:
        jwks = _jwks()
        jwks["provider_extension"] = "ignored-by-key-selection"
        del jwks["keys"][0]["alg"]
        verified = self.verify(_token(), jwks=jwks)
        self.assertEqual(verified.subject, "user-123")

    def test_duplicate_json_claim_is_rejected_before_trust(self) -> None:
        header = _json_segment({"alg": "RS256", "kid": "test-key"})
        payload = _b64(
            b'{"iss":"https://identity.example.test","iss":"https://evil.example.test",'
            b'"sub":"u","aud":"accessible-chess-client","nonce":"request-nonce",'
            b'"iat":1700000000,"exp":1700000600}'
        )
        signing_input = f"{header}.{payload}".encode("ascii")
        with self.assertRaisesRegex(OidcIdTokenError, "duplicate"):
            self.verify(f"{header}.{payload}.{_b64(_sign(signing_input))}")

    def test_error_messages_do_not_echo_token_or_identity_values(self) -> None:
        secret_subject = "private-subject-marker"
        secret_nonce = "private-nonce-marker"
        token = _token(claims={"sub": secret_subject, "nonce": secret_nonce})
        try:
            self.verify(token)
        except OidcIdTokenError as exc:
            message = str(exc)
        else:
            self.fail("mismatched nonce must fail")
        self.assertNotIn(secret_subject, message)
        self.assertNotIn(secret_nonce, message)
        self.assertNotIn(token, message)


if __name__ == "__main__":
    unittest.main()
