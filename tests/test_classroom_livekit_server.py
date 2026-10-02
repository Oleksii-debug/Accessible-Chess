from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import traceback
import unittest
from unittest.mock import patch

from acs.classroom_join_credentials import ClassroomJoinGrant
from acs.classroom_livekit_server import (
    ClassroomLiveKitServerError,
    LiveKitJoinTokenIssuer,
)
from acs.classroom_realtime_media import MAX_JOIN_TTL_SECONDS, MediaSource


NOW = datetime(2026, 10, 2, 21, 0, tzinfo=timezone.utc)


class FakeVideoGrants:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeAccessToken:
    instances = []

    def __init__(self, *, api_key, api_secret):
        self.api_key = api_key
        self.api_secret = api_secret
        self.identity = None
        self.ttl = None
        self.grants = None
        type(self).instances.append(self)

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
        return "signed-provider-token"


class FakeApi:
    VideoGrants = FakeVideoGrants
    AccessToken = FakeAccessToken


class ExplodingAccessToken(FakeAccessToken):
    def to_jwt(self):
        raise RuntimeError(f"provider exploded with {self.api_secret}")


class ExplodingApi:
    VideoGrants = FakeVideoGrants
    AccessToken = ExplodingAccessToken


class LiveKitJoinTokenIssuerTests(unittest.TestCase):
    def setUp(self):
        FakeAccessToken.instances.clear()
        ExplodingAccessToken.instances.clear()

    def issuer(self, api_module=FakeApi, *, now=NOW):
        return LiveKitJoinTokenIssuer(
            api_key="api-key-17",
            api_secret="server-secret-17",
            api_module=api_module,
            now=lambda: now,
        )

    def issue(self, grant, *, issued=NOW, expires=None, issuer=None):
        selected = issuer or self.issuer()
        return asyncio.run(
            selected.issue_join_token(
                grant=grant,
                issued_at=issued,
                expires_at=expires or issued + timedelta(seconds=60),
            )
        )

    def test_exact_canonical_grant_maps_to_source_scoped_least_privilege_token(self):
        grant = ClassroomJoinGrant(
            room_id="room-1",
            participant_id="student-1",
            publish_sources=(MediaSource.MICROPHONE, MediaSource.CAMERA),
        )

        token = self.issue(grant)

        self.assertEqual(token, "signed-provider-token")
        self.assertEqual(len(FakeAccessToken.instances), 1)
        minted = FakeAccessToken.instances[0]
        self.assertEqual(minted.api_key, "api-key-17")
        self.assertEqual(minted.api_secret, "server-secret-17")
        self.assertEqual(minted.identity, "student-1")
        self.assertEqual(minted.ttl, timedelta(seconds=59))
        self.assertTrue(minted.grants.room_join)
        self.assertEqual(minted.grants.room, "room-1")
        self.assertFalse(minted.grants.room_admin)
        self.assertTrue(minted.grants.can_publish)
        self.assertTrue(minted.grants.can_subscribe)
        self.assertTrue(minted.grants.can_publish_data)
        self.assertFalse(minted.grants.can_update_own_metadata)
        self.assertEqual(
            minted.grants.can_publish_sources,
            ["microphone", "camera"],
        )

    def test_no_track_grant_cannot_silently_gain_track_publish_permission(self):
        grant = ClassroomJoinGrant(
            room_id="room-1",
            participant_id="observer-1",
            publish_sources=(),
        )

        self.issue(grant)

        minted = FakeAccessToken.instances[0]
        self.assertFalse(minted.grants.can_publish)
        self.assertEqual(minted.grants.can_publish_sources, [])
        self.assertTrue(minted.grants.can_subscribe)
        self.assertTrue(minted.grants.can_publish_data)

    def test_screen_share_uses_livekit_canonical_track_source_name(self):
        grant = ClassroomJoinGrant(
            room_id="room-1",
            participant_id="teacher-1",
            publish_sources=(MediaSource.SCREEN_SHARE,),
        )

        self.issue(grant)

        self.assertEqual(
            FakeAccessToken.instances[0].grants.can_publish_sources,
            ["screen_share"],
        )

    def test_provider_ttl_tracks_remaining_canonical_lifetime(self):
        grant = ClassroomJoinGrant(
            "room-1",
            "student-1",
            (MediaSource.MICROPHONE,),
        )
        delayed = self.issuer(now=NOW + timedelta(seconds=20))

        self.issue(
            grant,
            issued=NOW,
            expires=NOW + timedelta(seconds=60),
            issuer=delayed,
        )

        self.assertEqual(
            FakeAccessToken.instances[0].ttl,
            timedelta(seconds=39),
        )

    def test_expired_or_too_close_grant_fails_before_provider(self):
        grant = ClassroomJoinGrant(
            "room-1",
            "student-1",
            (MediaSource.MICROPHONE,),
        )
        for current, fragment in (
            (NOW - timedelta(seconds=1), "precedes canonical issuance"),
            (NOW + timedelta(seconds=59), "expires before safe token minting"),
            (NOW + timedelta(seconds=60), "expires before safe token minting"),
        ):
            with self.subTest(current=current):
                FakeAccessToken.instances.clear()
                issuer = self.issuer(now=current)
                with self.assertRaisesRegex(
                    ClassroomLiveKitServerError,
                    fragment,
                ):
                    self.issue(
                        grant,
                        issued=NOW,
                        expires=NOW + timedelta(seconds=60),
                        issuer=issuer,
                    )
                self.assertEqual(FakeAccessToken.instances, [])

    def test_runtime_sdk_version_pin_is_enforced_without_injected_provider(self):
        issuer = LiveKitJoinTokenIssuer(
            api_key="api-key-17",
            api_secret="server-secret-17",
            api_module=None,
            now=lambda: NOW,
        )
        grant = ClassroomJoinGrant("room-1", "student-1", ())
        with patch(
            "acs.classroom_livekit_server.metadata.version",
            return_value="9.9.9",
        ):
            with self.assertRaisesRegex(
                ClassroomLiveKitServerError,
                "version is not approved",
            ):
                self.issue(grant, issuer=issuer)
        self.assertEqual(FakeAccessToken.instances, [])

    def test_noncanonical_grant_and_invalid_ttl_fail_before_provider(self):
        with self.assertRaises(ClassroomLiveKitServerError):
            self.issue(object())
        self.assertEqual(FakeAccessToken.instances, [])

        grant = ClassroomJoinGrant("room-1", "student-1", ())
        for issued, expires in (
            (NOW.replace(tzinfo=None), NOW + timedelta(seconds=60)),
            (NOW, NOW),
            (NOW, NOW - timedelta(seconds=1)),
            (NOW, NOW + timedelta(seconds=MAX_JOIN_TTL_SECONDS + 1)),
        ):
            with self.subTest(issued=issued, expires=expires):
                with self.assertRaises(ClassroomLiveKitServerError):
                    self.issue(grant, issued=issued, expires=expires)
        self.assertEqual(FakeAccessToken.instances, [])

    def test_provider_credentials_are_explicit_bounded_and_redacted(self):
        for key, secret in (
            ("", "secret"),
            ("api key", "secret"),
            ("api-key", ""),
            ("api-key", "secret\nvalue"),
        ):
            with self.subTest(key=repr(key), secret=repr(secret)):
                with self.assertRaises(ClassroomLiveKitServerError):
                    LiveKitJoinTokenIssuer(api_key=key, api_secret=secret, api_module=FakeApi)

        issuer = self.issuer()
        rendered = repr(issuer)
        self.assertNotIn("api-key-17", rendered)
        self.assertNotIn("server-secret-17", rendered)
        self.assertIn("redacted", rendered)

    def test_provider_failure_does_not_chain_or_render_server_secret(self):
        issuer = self.issuer(ExplodingApi)
        grant = ClassroomJoinGrant("room-1", "student-1", (MediaSource.MICROPHONE,))

        with self.assertRaisesRegex(
            ClassroomLiveKitServerError,
            "^LiveKit join token issuance failed$",
        ) as caught:
            self.issue(grant, issuer=issuer)

        self.assertIsNone(caught.exception.__cause__)
        rendered = "".join(traceback.format_exception(caught.exception))
        self.assertNotIn("server-secret-17", rendered)

    def test_real_livekit_api_contract_when_dependency_is_installed(self):
        try:
            from livekit import api
        except ImportError:
            self.skipTest("livekit-api is not installed outside the dedicated server gate")

        api_key = "test-api-key"
        api_secret = "test-server-secret-with-enough-entropy"
        issued = datetime.now(timezone.utc)
        issuer = LiveKitJoinTokenIssuer(
            api_key=api_key,
            api_secret=api_secret,
            api_module=api,
            now=lambda: issued,
        )
        grant = ClassroomJoinGrant(
            "room-livekit-contract",
            "participant-livekit-contract",
            (MediaSource.MICROPHONE, MediaSource.CAMERA),
        )

        token = self.issue(
            grant,
            issued=issued,
            expires=issued + timedelta(seconds=60),
            issuer=issuer,
        )
        claims = api.TokenVerifier(api_key=api_key, api_secret=api_secret).verify(token)

        self.assertEqual(claims.identity, grant.participant_id)
        self.assertEqual(claims.video.room, grant.room_id)
        self.assertTrue(claims.video.room_join)
        self.assertFalse(claims.video.room_admin)
        self.assertTrue(claims.video.can_publish)
        self.assertTrue(claims.video.can_subscribe)
        self.assertTrue(claims.video.can_publish_data)
        self.assertFalse(claims.video.can_update_own_metadata)
        self.assertEqual(
            claims.video.can_publish_sources,
            ["microphone", "camera"],
        )
        self.assertNotIn(api_secret, token)


if __name__ == "__main__":
    unittest.main()
