from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
from importlib import metadata
import json
from pathlib import Path
from types import SimpleNamespace
import traceback
import unittest

from acs.classroom_join_credentials import ClassroomJoinGrant
from acs.classroom_realtime_media import MAX_JOIN_TTL_SECONDS, MediaSource
from acs.livekit_join_token_issuer import (
    LIVEKIT_API_VERSION,
    LiveKitJoinTokenIssuer,
    LiveKitJoinTokenIssuerError,
    MAX_LIVEKIT_CREDENTIAL_CHARS,
)


NOW = datetime(2026, 10, 2, 21, 45, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]
ISSUER_WORKFLOW = ROOT / ".github" / "workflows" / "livekit-join-token-issuer.yml"
TWO_CLIENT_WORKFLOW = (
    ROOT / ".github" / "workflows" / "classroom-livekit-two-client-media-smoke.yml"
)


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
        self.token_now = NOW + timedelta(seconds=1)
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


def grant(*sources):
    return ClassroomJoinGrant(
        room_id="room-1",
        participant_id="student-1",
        publish_sources=tuple(sources),
    )


class LiveKitJoinTokenIssuerTests(unittest.TestCase):
    def issuer(self, *, now=NOW + timedelta(seconds=1), api=None, sdk_version=None):
        api = api or FakeApi()
        api.token_now = now
        return (
            LiveKitJoinTokenIssuer(
                api_key="server-key",
                api_secret="server-secret",
                api_module=api,
                sdk_version=sdk_version,
                now=lambda: now,
            ),
            api,
        )

    def issue(self, issuer, value=None, *, issued=NOW, expires=None):
        return asyncio.run(
            issuer.issue_join_token(
                grant=grant(MediaSource.MICROPHONE) if value is None else value,
                issued_at=issued,
                expires_at=expires or (issued + timedelta(seconds=60)),
            )
        )

    def test_maps_exact_room_identity_and_least_privilege_audio_grant(self):
        issuer, api = self.issuer()
        token = self.issue(issuer)

        self.assertEqual(len(token.split(".")), 3)
        self.assertEqual(api.access_credentials, ("server-key", "server-secret"))
        self.assertEqual(api.verify_credentials, ("server-key", "server-secret"))
        self.assertEqual(api.identity, "student-1")
        self.assertEqual(api.ttl, timedelta(seconds=58))
        self.assertEqual(api.leeway, timedelta(seconds=5))
        self.assertTrue(api.grant.room_join)
        self.assertEqual(api.grant.room, "room-1")
        self.assertTrue(api.grant.can_publish)
        self.assertTrue(api.grant.can_subscribe)
        self.assertTrue(api.grant.can_publish_data)
        self.assertEqual(api.grant.can_publish_sources, ["microphone"])

    def test_every_privileged_provider_grant_is_explicitly_disabled(self):
        issuer, api = self.issuer()
        self.issue(
            issuer,
            grant(
                MediaSource.CAMERA,
                MediaSource.SCREEN_SHARE,
                MediaSource.MICROPHONE,
            ),
        )

        self.assertEqual(
            api.grant.can_publish_sources,
            ["microphone", "camera", "screen_share"],
        )
        self.assertNotIn("screen_share_audio", api.grant.can_publish_sources)
        for name in (
            "room_create",
            "room_list",
            "room_record",
            "room_admin",
            "can_update_own_metadata",
            "ingress_admin",
            "hidden",
            "recorder",
            "agent",
            "can_manage_agent_session",
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(api.grant, name), False)
        self.assertIsNone(api.grant.destination_room)

    def test_zero_media_source_grant_retains_moderation_rpc_transport(self):
        issuer, api = self.issuer()
        self.issue(issuer, grant())
        self.assertFalse(api.grant.can_publish)
        self.assertEqual(api.grant.can_publish_sources, [])
        self.assertTrue(api.grant.can_subscribe)
        self.assertTrue(api.grant.can_publish_data)

    def test_mint_delay_reduces_provider_ttl_instead_of_extending_outer_expiry(self):
        issuer, api = self.issuer(now=NOW + timedelta(seconds=20))
        self.issue(issuer, expires=NOW + timedelta(seconds=60))

        self.assertEqual(api.ttl, timedelta(seconds=39))
        payload = json.loads(
            base64.urlsafe_b64decode(
                token_payload(self.issue(
                    self.issuer(now=NOW + timedelta(seconds=20))[0],
                    expires=NOW + timedelta(seconds=60),
                ))
            )
        )
        self.assertLessEqual(payload["exp"], int((NOW + timedelta(seconds=60)).timestamp()))

    def test_expired_or_too_close_grant_fails_before_provider(self):
        for current in (
            NOW + timedelta(seconds=60),
            NOW + timedelta(seconds=59, milliseconds=500),
        ):
            with self.subTest(current=current):
                issuer, api = self.issuer(now=current)
                with self.assertRaisesRegex(
                    LiveKitJoinTokenIssuerError,
                    "expires before safe token minting",
                ):
                    self.issue(issuer, expires=NOW + timedelta(seconds=60))
                self.assertIsNone(api.access_credentials)

    def test_outer_ttl_and_clock_are_fail_closed(self):
        issuer, api = self.issuer()
        with self.assertRaisesRegex(LiveKitJoinTokenIssuerError, "TTL is invalid"):
            self.issue(issuer, expires=NOW)
        with self.assertRaisesRegex(LiveKitJoinTokenIssuerError, "TTL is invalid"):
            self.issue(
                issuer,
                expires=NOW + timedelta(seconds=MAX_JOIN_TTL_SECONDS + 1),
            )
        future_issuer, future_api = self.issuer(now=NOW - timedelta(seconds=1))
        with self.assertRaisesRegex(
            LiveKitJoinTokenIssuerError,
            "precedes canonical issuance",
        ):
            self.issue(future_issuer)
        self.assertIsNone(future_api.access_credentials)

    def test_signature_verification_and_claim_drift_are_rejected(self):
        issuer, api = self.issuer()
        api.verify_error = RuntimeError("server-secret verifier details")
        with self.assertRaisesRegex(
            LiveKitJoinTokenIssuerError,
            "^LiveKit join token verification failed$",
        ) as caught:
            self.issue(issuer)
        self.assertIsNone(caught.exception.__cause__)
        self.assertNotIn(
            "server-secret",
            "".join(traceback.format_exception(caught.exception)),
        )

        issuer, api = self.issuer()
        self.issue(issuer)
        drift = SimpleNamespace(**vars(api.grant))
        drift.room_admin = True
        api.verified_override = SimpleNamespace(identity="student-1", video=drift)
        with self.assertRaisesRegex(LiveKitJoinTokenIssuerError, "room_admin"):
            self.issue(issuer)

        issuer, api = self.issuer()
        api.verified_override = SimpleNamespace(identity="other-student", video=api.grant)
        with self.assertRaisesRegex(LiveKitJoinTokenIssuerError, "identity"):
            self.issue(issuer)

    def test_temporal_claims_cannot_outlive_canonical_envelope(self):
        issuer, api = self.issuer()
        api.raw_override = {
            "iss": "server-key",
            "sub": "student-1",
            "nbf": int((NOW + timedelta(seconds=1)).timestamp()),
            "exp": int((NOW + timedelta(seconds=61)).timestamp()),
            "video": {},
        }
        with self.assertRaisesRegex(LiveKitJoinTokenIssuerError, "exceeds canonical expiry"):
            self.issue(issuer, expires=NOW + timedelta(seconds=60))

        issuer, api = self.issuer()
        api.raw_override = {
            "iss": "server-key",
            "sub": "student-1",
            "nbf": int((NOW - timedelta(seconds=1)).timestamp()),
            "exp": int((NOW + timedelta(seconds=30)).timestamp()),
            "video": {},
        }
        with self.assertRaisesRegex(LiveKitJoinTokenIssuerError, "predates canonical issuance"):
            self.issue(issuer)

    def test_bad_jwt_payload_and_provider_errors_are_sanitized(self):
        issuer, api = self.issuer()
        api.mint_error = RuntimeError("server-secret private provider trace")
        with self.assertRaisesRegex(
            LiveKitJoinTokenIssuerError,
            "^LiveKit join token issuance failed$",
        ) as caught:
            self.issue(issuer)
        self.assertIsNone(caught.exception.__cause__)
        self.assertNotIn(
            "server-secret",
            "".join(traceback.format_exception(caught.exception)),
        )

        issuer, api = self.issuer()
        api.raw_override = {"nbf": "bad", "exp": 1}
        with self.assertRaisesRegex(LiveKitJoinTokenIssuerError, "temporal claims"):
            self.issue(issuer)

    def test_credentials_version_and_sdk_surface_are_strict(self):
        api = FakeApi()
        with self.assertRaisesRegex(LiveKitJoinTokenIssuerError, "version is not approved"):
            LiveKitJoinTokenIssuer(
                api_key="key",
                api_secret="secret",
                api_module=api,
                sdk_version="9.9.9",
            )

        class MissingVerifier:
            AccessToken = api.AccessToken
            VideoGrants = api.VideoGrants

        with self.assertRaisesRegex(LiveKitJoinTokenIssuerError, "token API is unavailable"):
            LiveKitJoinTokenIssuer(
                api_key="key",
                api_secret="secret",
                api_module=MissingVerifier,
            )

        for key, secret in (
            ("", "secret"),
            (" key", "secret"),
            ("key", " secret"),
            ("key\n", "secret"),
            ("key", "secret\r"),
            ("k" * (MAX_LIVEKIT_CREDENTIAL_CHARS + 1), "secret"),
        ):
            with self.subTest(key=repr(key)[:20], secret=repr(secret)[:20]):
                with self.assertRaises(LiveKitJoinTokenIssuerError):
                    LiveKitJoinTokenIssuer(
                        api_key=key,
                        api_secret=secret,
                        api_module=api,
                    )

    def test_repr_redacts_credentials(self):
        issuer, _api = self.issuer()
        rendered = repr(issuer)
        self.assertNotIn("server-key", rendered)
        self.assertNotIn("server-secret", rendered)
        self.assertIn("api_key=<redacted>", rendered)
        self.assertIn("api_secret=<redacted>", rendered)

    def test_rejects_noncanonical_grant_and_naive_clock(self):
        issuer, api = self.issuer()
        with self.assertRaisesRegex(LiveKitJoinTokenIssuerError, "grant is invalid"):
            self.issue(issuer, object())
        with self.assertRaisesRegex(LiveKitJoinTokenIssuerError, "timezone-aware"):
            self.issue(issuer, issued=NOW.replace(tzinfo=None))
        self.assertIsNone(api.access_credentials)

    def test_qualification_workflows_bind_scope_to_immutable_event_base(self):
        issuer_workflow = ISSUER_WORKFLOW.read_text(encoding="utf-8")
        smoke_workflow = TWO_CLIENT_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn(
            "EVENT_BASE_SHA: ${{ github.event.pull_request.base.sha }}",
            issuer_workflow,
        )
        self.assertIn(
            'git diff --name-only "$EVENT_BASE_SHA...HEAD"',
            issuer_workflow,
        )
        self.assertNotIn("refs/remotes/origin/$EXPECTED_BASE_REF", issuer_workflow)
        for path in (
            ".github/workflows/classroom-livekit-two-client-media-smoke.yml",
            ".github/workflows/livekit-join-token-issuer.yml",
            "acs/livekit_join_token_issuer.py",
            "tests/js/livekit_two_client_media_smoke.js",
            "tests/livekit_two_client_token_fixture.py",
            "tests/test_livekit_join_token_issuer.py",
        ):
            with self.subTest(path=path):
                self.assertIn(path, issuer_workflow)

        self.assertIn(
            "EVENT_BASE_SHA: ${{ github.event.pull_request.base.sha }}",
            smoke_workflow,
        )
        self.assertIn(
            'git diff --name-only "$EVENT_BASE_SHA...HEAD"',
            smoke_workflow,
        )
        self.assertNotIn("refs/remotes/origin/$EXPECTED_BASE_REF", smoke_workflow)

    def test_real_pinned_sdk_emits_verified_source_scoped_jwt_when_installed(self):
        try:
            installed = metadata.version("livekit-api")
        except metadata.PackageNotFoundError:
            self.skipTest("livekit-api is installed by the dedicated provider gate")
        self.assertEqual(installed, LIVEKIT_API_VERSION)

        now = datetime.now(timezone.utc)
        issuer = LiveKitJoinTokenIssuer(
            api_key="ci-test-key",
            api_secret="ci-test-secret-material-long-enough-for-hmac",
        )
        token = asyncio.run(
            issuer.issue_join_token(
                grant=grant(MediaSource.MICROPHONE, MediaSource.CAMERA),
                issued_at=now - timedelta(seconds=1),
                expires_at=now + timedelta(seconds=30),
            )
        )
        from livekit import api

        claims = api.TokenVerifier(
            "ci-test-key",
            "ci-test-secret-material-long-enough-for-hmac",
            leeway=timedelta(seconds=5),
        ).verify(token)
        self.assertEqual(claims.identity, "student-1")
        self.assertEqual(claims.video.room, "room-1")
        self.assertEqual(claims.video.can_publish_sources, ["microphone", "camera"])
        self.assertFalse(claims.video.room_admin)
        self.assertTrue(claims.video.can_publish_data)


def token_payload(token):
    payload = token.split(".")[1]
    return payload + "=" * (-len(payload) % 4)


if __name__ == "__main__":
    unittest.main()
