from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from importlib import metadata
import json
from types import SimpleNamespace
import traceback
import unittest

from acs.classroom_realtime_media import MAX_JOIN_TTL_SECONDS
from acs.livekit_join_token_issuer import (
    LIVEKIT_API_VERSION,
    MAX_LIVEKIT_CREDENTIAL_CHARS,
)
from acs.livekit_moderation_service_token import (
    LiveKitModerationServiceTokenError,
    LiveKitModerationServiceTokenIssuer,
    MIN_MODERATION_SERVICE_TTL_SECONDS,
)


NOW = datetime(2026, 10, 2, 22, 0, tzinfo=timezone.utc)
ROOM = "room-1"
SERVICE_ID = "moderation-service"


def _b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _raw_token(payload):
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode("utf-8"))
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{header}.{body}.signature"


class FakeApi:
    def __init__(self):
        self.access_credentials = None
        self.verify_credentials = None
        self.identity = None
        self.grant = None
        self.ttl = None
        self.leeway = None
        self.token_now = NOW
        self.mint_error = None
        self.verify_error = None
        self.verified_override = None
        self.raw_override = None

        module = self

        class VideoGrants:
            def __init__(self, **kwargs):
                for name, value in kwargs.items():
                    setattr(self, name, value)

        class AccessToken:
            def __init__(self, api_key, api_secret):
                module.access_credentials = (api_key, api_secret)

            def with_identity(self, value):
                module.identity = value
                return self

            def with_grants(self, value):
                module.grant = value
                return self

            def with_ttl(self, value):
                module.ttl = value
                return self

            def to_jwt(self):
                if module.mint_error is not None:
                    raise module.mint_error
                payload = module.raw_override or {
                    "iss": "server-key",
                    "sub": module.identity,
                    "nbf": int(module.token_now.timestamp()),
                    "exp": int((module.token_now + module.ttl).timestamp()),
                    "video": {},
                }
                return _raw_token(payload)

        class TokenVerifier:
            def __init__(self, api_key, api_secret, *, leeway):
                module.verify_credentials = (api_key, api_secret)
                module.leeway = leeway

            def verify(self, token):
                if module.verify_error is not None:
                    raise module.verify_error
                if module.verified_override is not None:
                    return module.verified_override
                return SimpleNamespace(identity=module.identity, video=module.grant)

        self.VideoGrants = VideoGrants
        self.AccessToken = AccessToken
        self.TokenVerifier = TokenVerifier


class LiveKitModerationServiceTokenTests(unittest.TestCase):
    def issuer(
        self,
        *,
        api=None,
        now=NOW,
        room_id=ROOM,
        identity=SERVICE_ID,
        ttl_seconds=60,
        sdk_version=LIVEKIT_API_VERSION,
        api_key="server-key",
        api_secret="server-secret",
    ):
        api = api or FakeApi()
        api.token_now = now
        return (
            LiveKitModerationServiceTokenIssuer(
                api_key=api_key,
                api_secret=api_secret,
                room_id=room_id,
                moderation_participant_identity=identity,
                ttl_seconds=ttl_seconds,
                api_module=api,
                sdk_version=sdk_version,
                now=lambda: now,
            ),
            api,
        )

    def test_mints_exact_non_media_rpc_service_grant(self):
        issuer, api = self.issuer()
        token = issuer.issue_token()

        self.assertEqual(len(token.split(".")), 3)
        self.assertEqual(api.access_credentials, ("server-key", "server-secret"))
        self.assertEqual(api.verify_credentials, ("server-key", "server-secret"))
        self.assertEqual(api.identity, SERVICE_ID)
        self.assertEqual(api.ttl, timedelta(seconds=59))
        self.assertEqual(api.leeway, timedelta(seconds=5))
        self.assertTrue(api.grant.room_join)
        self.assertEqual(api.grant.room, ROOM)
        self.assertFalse(api.grant.can_publish)
        self.assertFalse(api.grant.can_subscribe)
        self.assertTrue(api.grant.can_publish_data)
        self.assertEqual(api.grant.can_publish_sources, [])

    def test_every_non_rpc_provider_capability_is_explicitly_disabled(self):
        issuer, api = self.issuer()
        issuer.issue_token()

        for name in (
            "room_create",
            "room_list",
            "room_record",
            "room_admin",
            "can_publish",
            "can_subscribe",
            "can_update_own_metadata",
            "ingress_admin",
            "hidden",
            "recorder",
            "agent",
            "can_manage_agent_session",
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(api.grant, name), False)
        self.assertTrue(api.grant.can_publish_data)
        self.assertEqual(api.grant.can_publish_sources, [])
        self.assertIsNone(api.grant.destination_room)

    def test_room_and_service_identity_are_constructor_bound_not_issue_inputs(self):
        issuer, api = self.issuer(
            room_id="room-fixed",
            identity="moderation-service-fixed",
        )
        issuer.issue_token()
        self.assertEqual(api.grant.room, "room-fixed")
        self.assertEqual(api.identity, "moderation-service-fixed")
        self.assertEqual(issuer.issue_token.__code__.co_argcount, 1)

    def test_ttl_is_short_bounded_and_reduced_for_provider_clock_safety(self):
        issuer, api = self.issuer(ttl_seconds=MIN_MODERATION_SERVICE_TTL_SECONDS)
        issuer.issue_token()
        self.assertEqual(api.ttl, timedelta(seconds=1))

        for ttl in (
            MIN_MODERATION_SERVICE_TTL_SECONDS - 1,
            0,
            -1,
            MAX_JOIN_TTL_SECONDS + 1,
            True,
            1.5,
        ):
            with self.subTest(ttl=ttl):
                with self.assertRaisesRegex(
                    LiveKitModerationServiceTokenError,
                    "TTL is invalid",
                ):
                    self.issuer(ttl_seconds=ttl)

    def test_temporal_claim_cannot_predate_issue_or_exceed_configured_expiry(self):
        issuer, api = self.issuer()
        api.raw_override = {
            "iss": "server-key",
            "sub": SERVICE_ID,
            "nbf": int((NOW - timedelta(seconds=1)).timestamp()),
            "exp": int((NOW + timedelta(seconds=30)).timestamp()),
            "video": {},
        }
        with self.assertRaisesRegex(
            LiveKitModerationServiceTokenError,
            "predates issuance",
        ):
            issuer.issue_token()

        issuer, api = self.issuer()
        api.raw_override = {
            "iss": "server-key",
            "sub": SERVICE_ID,
            "nbf": int(NOW.timestamp()),
            "exp": int((NOW + timedelta(seconds=61)).timestamp()),
            "video": {},
        }
        with self.assertRaisesRegex(
            LiveKitModerationServiceTokenError,
            "exceeds configured expiry",
        ):
            issuer.issue_token()

    def test_claim_drift_is_rejected_after_signature_verification(self):
        issuer, api = self.issuer()
        issuer.issue_token()

        for field, value in (
            ("room_admin", True),
            ("can_publish", True),
            ("can_subscribe", True),
            ("can_publish_data", False),
            ("hidden", True),
        ):
            with self.subTest(field=field):
                drift = SimpleNamespace(**vars(api.grant))
                setattr(drift, field, value)
                api.verified_override = SimpleNamespace(
                    identity=SERVICE_ID,
                    video=drift,
                )
                with self.assertRaisesRegex(
                    LiveKitModerationServiceTokenError,
                    field,
                ):
                    issuer.issue_token()
                api.verified_override = None

        api.verified_override = SimpleNamespace(
            identity="student-1",
            video=api.grant,
        )
        with self.assertRaisesRegex(
            LiveKitModerationServiceTokenError,
            "identity is not canonical",
        ):
            issuer.issue_token()

    def test_provider_failures_are_sanitized_and_do_not_leak_credentials(self):
        issuer, api = self.issuer()
        api.mint_error = RuntimeError("server-secret private mint detail")
        with self.assertRaisesRegex(
            LiveKitModerationServiceTokenError,
            "^LiveKit moderation service token issuance failed$",
        ) as caught:
            issuer.issue_token()
        self.assertIsNone(caught.exception.__cause__)
        self.assertNotIn(
            "server-secret",
            "".join(traceback.format_exception(caught.exception)),
        )

        issuer, api = self.issuer()
        api.verify_error = RuntimeError("server-secret private verify detail")
        with self.assertRaisesRegex(
            LiveKitModerationServiceTokenError,
            "^LiveKit moderation service token verification failed$",
        ) as caught:
            issuer.issue_token()
        self.assertIsNone(caught.exception.__cause__)
        self.assertNotIn(
            "server-secret",
            "".join(traceback.format_exception(caught.exception)),
        )

    def test_bad_token_and_bad_clock_fail_closed(self):
        issuer, api = self.issuer()
        api.raw_override = {"nbf": "bad", "exp": 1}
        with self.assertRaisesRegex(
            LiveKitModerationServiceTokenError,
            "temporal claims",
        ):
            issuer.issue_token()

        bad_clock = LiveKitModerationServiceTokenIssuer(
            api_key="key",
            api_secret="secret",
            room_id=ROOM,
            moderation_participant_identity=SERVICE_ID,
            api_module=FakeApi(),
            sdk_version=LIVEKIT_API_VERSION,
            now=lambda: datetime(2026, 10, 2, 22, 0),
        )
        with self.assertRaisesRegex(
            LiveKitModerationServiceTokenError,
            "timezone-aware",
        ):
            bad_clock.issue_token()

    def test_credentials_identifiers_sdk_surface_and_version_are_strict(self):
        for key, secret in (
            ("", "secret"),
            (" key", "secret"),
            ("key", " secret"),
            ("key\n", "secret"),
            ("key", "secret\r"),
            ("k" * (MAX_LIVEKIT_CREDENTIAL_CHARS + 1), "secret"),
        ):
            with self.subTest(key=repr(key)[:20], secret=repr(secret)[:20]):
                with self.assertRaises(LiveKitModerationServiceTokenError):
                    self.issuer(api_key=key, api_secret=secret)

        for room, identity in (
            (" room", SERVICE_ID),
            ("room name", SERVICE_ID),
            ("", SERVICE_ID),
            (ROOM, " moderation-service"),
            (ROOM, "bad identity"),
            (ROOM, ""),
            ("x" * 129, SERVICE_ID),
        ):
            with self.subTest(room=room, identity=identity):
                with self.assertRaises(LiveKitModerationServiceTokenError):
                    self.issuer(room_id=room, identity=identity)

        with self.assertRaisesRegex(
            LiveKitModerationServiceTokenError,
            "version is not approved",
        ):
            self.issuer(sdk_version="1.2.0")

        api = FakeApi()

        class MissingVerifier:
            AccessToken = api.AccessToken
            VideoGrants = api.VideoGrants

        with self.assertRaisesRegex(
            LiveKitModerationServiceTokenError,
            "token API is unavailable",
        ):
            LiveKitModerationServiceTokenIssuer(
                api_key="key",
                api_secret="secret",
                room_id=ROOM,
                moderation_participant_identity=SERVICE_ID,
                api_module=MissingVerifier,
                sdk_version=LIVEKIT_API_VERSION,
            )

    def test_repr_redacts_credentials_room_and_service_identity(self):
        issuer, _api = self.issuer()
        rendered = repr(issuer)
        self.assertNotIn("server-key", rendered)
        self.assertNotIn("server-secret", rendered)
        self.assertNotIn(ROOM, rendered)
        self.assertNotIn(SERVICE_ID, rendered)
        for marker in (
            "room=<redacted>",
            "participant=<redacted>",
            "api_key=<redacted>",
            "api_secret=<redacted>",
        ):
            self.assertIn(marker, rendered)

    def test_real_pinned_sdk_emits_verified_rpc_only_service_jwt_when_installed(self):
        try:
            installed = metadata.version("livekit-api")
        except metadata.PackageNotFoundError:
            self.skipTest("livekit-api is installed by the dedicated provider gate")
        self.assertEqual(installed, LIVEKIT_API_VERSION)

        now = datetime.now(timezone.utc)
        issuer = LiveKitModerationServiceTokenIssuer(
            api_key="ci-test-key",
            api_secret="ci-test-secret-material-long-enough-for-hmac",
            room_id=ROOM,
            moderation_participant_identity=SERVICE_ID,
            now=lambda: now,
        )
        token = issuer.issue_token()

        from livekit import api

        claims = api.TokenVerifier(
            "ci-test-key",
            "ci-test-secret-material-long-enough-for-hmac",
            leeway=timedelta(seconds=5),
        ).verify(token)
        self.assertEqual(claims.identity, SERVICE_ID)
        self.assertEqual(claims.video.room, ROOM)
        self.assertTrue(claims.video.room_join)
        self.assertFalse(claims.video.can_publish)
        self.assertFalse(claims.video.can_subscribe)
        self.assertTrue(claims.video.can_publish_data)
        self.assertEqual(claims.video.can_publish_sources, [])
        self.assertFalse(claims.video.room_admin)


if __name__ == "__main__":
    unittest.main()
