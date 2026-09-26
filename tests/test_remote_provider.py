from __future__ import annotations

import unittest

from acs.remote_connectivity import (
    AuthenticatedPrincipal,
    RemoteConnectivityError,
    RemoteEndpointProfile,
    RemoteEnvelope,
    RemoteMessageKind,
    RemoteRetryPolicy,
    RemoteRole,
)
from acs.remote_provider import InProcessRemoteProvider, RemoteConnector


class _SecretProvider:
    def __init__(self, secret: str | None) -> None:
        self.secret = secret
        self.calls: list[str] = []

    def get_secret(self, credential_key: str) -> str | None:
        self.calls.append(credential_key)
        return self.secret


class RemoteProviderTests(unittest.TestCase):
    def profile(self) -> RemoteEndpointProfile:
        return RemoteEndpointProfile(
            "profile-1",
            "relay.example.test",
            443,
            "relay.example.test",
            "remote-profile-1",
        )

    def principal(self) -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            "class-1",
            "session-1",
            "student-1",
            RemoteRole.STUDENT,
        )

    def ack(self) -> RemoteEnvelope:
        return RemoteEnvelope(
            1,
            RemoteMessageKind.ACK,
            "ack-1",
            "session-1",
            "student-1",
            RemoteRole.STUDENT,
            1,
            {"accepted": True},
        )

    def test_in_process_provider_uses_real_protocol_contract_without_network(self) -> None:
        principal = self.principal()
        received: list[str] = []

        def authenticate(candidate: AuthenticatedPrincipal, secret: str) -> AuthenticatedPrincipal:
            self.assertEqual(candidate, principal)
            self.assertEqual(secret, "runtime-secret")
            received.append(candidate.person_id)
            return candidate

        provider = InProcessRemoteProvider(authenticate, lambda envelope: envelope)
        context = provider.connect(principal, "runtime-secret")
        self.assertEqual(context.principal, principal)
        self.assertTrue(provider.connected)
        self.assertEqual(provider.exchange(self.ack()), self.ack())
        self.assertEqual(received, ["student-1"])
        self.assertNotIn("secret", provider.__dict__)
        provider.close()
        self.assertFalse(provider.connected)
        with self.assertRaises(RemoteConnectivityError):
            provider.exchange(self.ack())

    def test_in_process_auth_identity_mismatch_fails_closed(self) -> None:
        principal = self.principal()
        wrong = AuthenticatedPrincipal(
            "class-1",
            "session-1",
            "student-2",
            RemoteRole.STUDENT,
        )
        provider = InProcessRemoteProvider(lambda _principal, _secret: wrong, lambda env: env)
        with self.assertRaises(RemoteConnectivityError):
            provider.connect(principal, "runtime-secret")
        self.assertFalse(provider.connected)

    def test_connector_retries_with_bounded_exponential_backoff(self) -> None:
        principal = self.principal()
        secret_provider = _SecretProvider("runtime-secret")
        attempts: list[int] = []
        sleeps: list[float] = []
        providers: list[InProcessRemoteProvider] = []

        def factory(_profile: RemoteEndpointProfile, _policy: RemoteRetryPolicy) -> InProcessRemoteProvider:
            attempt_number = len(attempts) + 1
            attempts.append(attempt_number)

            def authenticate(candidate: AuthenticatedPrincipal, secret: str) -> AuthenticatedPrincipal:
                self.assertEqual(secret, "runtime-secret")
                if attempt_number < 3:
                    raise RemoteConnectivityError("simulated provider outage")
                return candidate

            provider = InProcessRemoteProvider(authenticate, lambda envelope: envelope)
            providers.append(provider)
            return provider

        connector = RemoteConnector(
            self.profile(),
            secret_provider,
            factory,
            RemoteRetryPolicy(
                max_attempts=3,
                initial_backoff_seconds=0.25,
                max_backoff_seconds=1.0,
            ),
            sleep=sleeps.append,
        )
        connected = connector.connect(principal)
        self.assertEqual(connected.attempts, 3)
        self.assertEqual(connected.context.principal, principal)
        self.assertEqual(attempts, [1, 2, 3])
        self.assertEqual(sleeps, [0.25, 0.5])
        self.assertEqual(secret_provider.calls, ["remote-profile-1"] * 3)
        self.assertFalse(providers[0].connected)
        self.assertFalse(providers[1].connected)
        self.assertTrue(providers[2].connected)

    def test_connector_stops_after_budget_and_closes_every_failed_provider(self) -> None:
        secret_provider = _SecretProvider("runtime-secret")
        providers: list[InProcessRemoteProvider] = []
        sleeps: list[float] = []

        def factory(_profile: RemoteEndpointProfile, _policy: RemoteRetryPolicy) -> InProcessRemoteProvider:
            provider = InProcessRemoteProvider(
                lambda _principal, _secret: (_ for _ in ()).throw(
                    RemoteConnectivityError("simulated outage")
                ),
                lambda envelope: envelope,
            )
            providers.append(provider)
            return provider

        connector = RemoteConnector(
            self.profile(),
            secret_provider,
            factory,
            RemoteRetryPolicy(
                max_attempts=3,
                initial_backoff_seconds=0.5,
                max_backoff_seconds=0.75,
            ),
            sleep=sleeps.append,
        )
        with self.assertRaisesRegex(RemoteConnectivityError, "remote endpoint is unavailable"):
            connector.connect(self.principal())
        self.assertEqual(len(providers), 3)
        self.assertTrue(all(not provider.connected for provider in providers))
        self.assertEqual(sleeps, [0.5, 0.75])

    def test_missing_secret_fails_before_provider_creation_and_without_retry(self) -> None:
        factory_calls: list[int] = []

        def factory(_profile: RemoteEndpointProfile, _policy: RemoteRetryPolicy) -> InProcessRemoteProvider:
            factory_calls.append(1)
            return InProcessRemoteProvider(lambda principal, _secret: principal, lambda env: env)

        connector = RemoteConnector(
            self.profile(),
            _SecretProvider(None),
            factory,
            RemoteRetryPolicy(max_attempts=3),
            sleep=lambda _delay: self.fail("missing credentials must not sleep/retry"),
        )
        with self.assertRaisesRegex(RemoteConnectivityError, "remote credentials are unavailable"):
            connector.connect(self.principal())
        self.assertEqual(factory_calls, [])

    def test_provider_exchange_rejects_non_envelope_response(self) -> None:
        provider = InProcessRemoteProvider(
            lambda principal, _secret: principal,
            lambda _envelope: None,  # type: ignore[return-value]
        )
        provider.connect(self.principal(), "runtime-secret")
        with self.assertRaises(RemoteConnectivityError):
            provider.exchange(self.ack())


if __name__ == "__main__":
    unittest.main()
