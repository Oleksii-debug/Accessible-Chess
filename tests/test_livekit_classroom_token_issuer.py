from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import unittest

from acs.classroom_join_credentials import ClassroomJoinGrant
from acs.classroom_realtime_media import MAX_JOIN_TTL_SECONDS, MediaSource
from acs.livekit_classroom_token_issuer import (
    LIVEKIT_API_VERSION,
    LiveKitClassroomJoinTokenIssuer,
    LiveKitClassroomTokenIssuerError,
)


NOW = datetime(2026, 10, 2, 22, 0, 10, 400000, tzinfo=timezone.utc)


class FakeVideoGrants:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeAccessToken:
    instances = []

    def __init__(self, *, api_key, api_secret):
        self.api_key = api_key
        self.api_secret = api_secret
        self.identity = None
        self.ttl = None
        self.grants = None
        FakeAccessToken.instances.append(self)

    def with_identity(self, identity):
        self.identity = identity
        return self

    def with_ttl(self, ttl):
        self.ttl = ttl
        return self

    def with_grants(self, grants):
        self.grants = grants
        return self

    def to_jwt(self):
        if FakeApi.next_error is not None:
            raise FakeApi.next_error
        return FakeApi.next_token


class FakeApi:
    VideoGrants = FakeVideoGrants
    AccessToken = FakeAccessToken
    next_token = "header.payload.signature"
    next_error = None


class LiveKitClassroomJoinTokenIssuerTests(unittest.TestCase):
    def setUp(self):
        FakeAccessToken.instances.clear()
        FakeApi.next_token = "header.payload.signature"
        FakeApi.next_error = None

    def issuer(self, *, now=lambda: NOW):
        return LiveKitClassroomJoinTokenIssuer(
            api_key="api-key-123",
            api_secret="super-secret-456",
            now=now,
            api_module=FakeApi,
        )

    def grant(
        self,
        sources=(MediaSource.MICROPHONE, MediaSource.CAMERA),
    ):
        return ClassroomJoinGrant(
            room_id="room-17",
            participant_id="student-42",
            publish_sources=sources,
        )

    def issue(self, issuer, grant=None, *, issued=None, expires=None):
        grant = self.grant() if grant is None else grant
        issued = (
            NOW - timedelta(seconds=10, microseconds=400000)
            if issued is None
            else issued
        )
        expires = (
            NOW + timedelta(seconds=49, microseconds=600000)
            if expires is None
            else expires
        )
        return asyncio.run(
            issuer.issue_join_token(
                grant=grant,
                issued_at=issued,
                expires_at=expires,
            )
        )

    def test_maps_canonical_grant_to_exact_least_privilege_livekit_grants(self):
        token = self.issue(
            self.issuer(),
            self.grant(
                (
                    MediaSource.CAMERA,
                    MediaSource.MICROPHONE,
                    MediaSource.SCREEN_SHARE,
                )
            ),
        )
        self.assertEqual(token, "header.payload.signature")
        self.assertEqual(len(FakeAccessToken.instances), 1)
        access = FakeAccessToken.instances[0]
        self.assertEqual(access.api_key, "api-key-123")
        self.assertEqual(access.api_secret, "super-secret-456")
        self.assertEqual(access.identity, "student-42")
        self.assertEqual(access.ttl, timedelta(seconds=49))
        self.assertEqual(
            access.grants.kwargs,
            {
                "room_join": True,
                "room": "room-17",
                "room_admin": False,
                "can_publish": True,
                "can_subscribe": True,
                "can_publish_data": False,
                "can_publish_sources": ["camera", "microphone", "screen_share"],
                "can_update_own_metadata": False,
                "hidden": False,
            },
        )

    def test_no_source_grant_cannot_publish_tracks(self):
        self.issue(self.issuer(), self.grant(()))
        grants = FakeAccessToken.instances[0].grants.kwargs
        self.assertFalse(grants["can_publish"])
        self.assertEqual(grants["can_publish_sources"], [])

    def test_uses_remaining_whole_seconds_not_original_lifetime(self):
        issued = NOW - timedelta(seconds=40)
        expires = NOW + timedelta(seconds=19, microseconds=900000)
        self.issue(self.issuer(), issued=issued, expires=expires)
        self.assertEqual(
            FakeAccessToken.instances[0].ttl,
            timedelta(seconds=19),
        )

    def test_rejects_expired_future_and_overlong_grants_before_sdk(self):
        cases = (
            (NOW - timedelta(seconds=60), NOW, "expired"),
            (
                NOW + timedelta(seconds=1),
                NOW + timedelta(seconds=61),
                "not active",
            ),
            (
                NOW,
                NOW + timedelta(seconds=MAX_JOIN_TTL_SECONDS + 1),
                "TTL",
            ),
        )
        for issued, expires, fragment in cases:
            with self.subTest(fragment=fragment):
                with self.assertRaisesRegex(
                    LiveKitClassroomTokenIssuerError,
                    fragment,
                ):
                    self.issue(
                        self.issuer(),
                        issued=issued,
                        expires=expires,
                    )
        self.assertEqual(FakeAccessToken.instances, [])

    def test_clock_and_grant_inputs_fail_closed(self):
        with self.assertRaisesRegex(
            LiveKitClassroomTokenIssuerError,
            "canonical join grant",
        ):
            asyncio.run(
                self.issuer().issue_join_token(
                    grant=object(),
                    issued_at=NOW,
                    expires_at=NOW + timedelta(seconds=30),
                )
            )
        with self.assertRaisesRegex(
            LiveKitClassroomTokenIssuerError,
            "timezone-aware",
        ):
            self.issue(
                self.issuer(now=lambda: NOW.replace(tzinfo=None))
            )
        self.assertEqual(FakeAccessToken.instances, [])

    def test_provider_credentials_are_strict_and_never_represented(self):
        cases = (
            ("", "SAFESECRET123"),
            (" KEYVALUE123", "SAFESECRET123"),
            ("key", " TOPSECRET123"),
            ("key", "bad\nTOPSECRET123"),
        )
        for key, secret in cases:
            with self.subTest(key=key, secret=secret):
                with self.assertRaises(
                    LiveKitClassroomTokenIssuerError
                ) as caught:
                    LiveKitClassroomJoinTokenIssuer(
                        api_key=key,
                        api_secret=secret,
                        api_module=FakeApi,
                    )
                self.assertNotIn(secret, str(caught.exception))
        issuer = self.issuer()
        self.assertNotIn("api-key-123", repr(issuer))
        self.assertNotIn("super-secret-456", repr(issuer))

    def test_provider_error_and_bad_token_are_sanitized(self):
        FakeApi.next_error = RuntimeError(
            "provider leaked super-secret-456"
        )
        with self.assertRaisesRegex(
            LiveKitClassroomTokenIssuerError,
            "^LiveKit token issuance failed$",
        ) as caught:
            self.issue(self.issuer())
        self.assertNotIn(
            "super-secret-456",
            str(caught.exception),
        )

        for token in (
            None,
            "",
            "token with whitespace",
            "x\nsecret",
            "header.payload",
            "header.payload.signature.extra",
            "header.páyload.signature",
            "\ud800.payload.signature",
            "x" * 8193,
        ):
            with self.subTest(token=repr(token)[:40]):
                FakeApi.next_error = None
                FakeApi.next_token = token
                with self.assertRaisesRegex(
                    LiveKitClassroomTokenIssuerError,
                    "token output is invalid",
                ):
                    self.issue(self.issuer())

    def test_reviewed_sdk_version_is_explicit(self):
        self.assertEqual(LIVEKIT_API_VERSION, "1.2.1")


if __name__ == "__main__":
    unittest.main()
