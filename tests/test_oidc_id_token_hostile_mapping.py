from __future__ import annotations

from collections.abc import Mapping
import unittest

from acs.oidc_id_token import IdTokenError, VerifiedIdTokenEnvelope, validate_id_token


NOW = 1_800_000_000


class _ExplodingMapping(Mapping):
    def __iter__(self):
        yield "iss"
        yield "sub"

    def __len__(self):
        return 2

    def __getitem__(self, key):
        raise RuntimeError("provider-private-claim-detail")


class _Verifier:
    def verify(self, compact_token: str):
        return VerifiedIdTokenEnvelope("RS256", _ExplodingMapping())


class OidcHostileMappingTests(unittest.TestCase):
    def test_verifier_owned_mapping_exceptions_are_bounded(self) -> None:
        with self.assertRaises(IdTokenError) as caught:
            validate_id_token(
                "header.payload.signature",
                verifier=_Verifier(),
                expected_issuer="https://identity.example.invalid",
                client_id="accessible-chess-public-client",
                expected_nonce="nonce-123",
                now=lambda: NOW,
            )
        self.assertEqual(str(caught.exception), "invalid verified claims")
        self.assertIsNone(caught.exception.__cause__)
        self.assertNotIn("provider-private", str(caught.exception))

    def test_infinite_mapping_iteration_is_bounded_without_len(self) -> None:
        class InfiniteMapping(Mapping):
            def __iter__(self):
                index = 0
                while True:
                    yield f"claim-{index}"
                    index += 1

            def __len__(self):
                raise RuntimeError("len must not be trusted")

            def __getitem__(self, key):
                return key

        class Verifier:
            def verify(self, compact_token: str):
                return VerifiedIdTokenEnvelope("RS256", InfiniteMapping())

        with self.assertRaisesRegex(IdTokenError, "invalid verified claims"):
            validate_id_token(
                "header.payload.signature",
                verifier=Verifier(),
                expected_issuer="https://identity.example.invalid",
                client_id="accessible-chess-public-client",
                expected_nonce="nonce-123",
                now=lambda: NOW,
            )


if __name__ == "__main__":
    unittest.main()
