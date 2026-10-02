from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import unittest

from acs.classroom_join_credentials import ClassroomJoinGrant
from acs.classroom_realtime_media import MAX_JOIN_TTL_SECONDS, MediaSource
from acs.livekit_join_token_issuer import (
    LiveKitJoinTokenIssuer,
    LiveKitJoinTokenIssuerError,
    MAX_LIVEKIT_CREDENTIAL_CHARS,
)


NOW = datetime(2026, 10, 2, 21, 45, tzinfo=timezone.utc)


class FakeVideoGrants:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeAccessToken:
    instances = []

    def __init__(self, api_key, api_secret):
        self.api_key = api_key
        self.api_secret = api_secret
        self.identity = None
        self.grants = None
        self.ttl = None
        self.token = "header.payload.signature"
        type(self).instances.append(self)

    def with_identity(self, value):
        self.identity = value
        return self

    def with_grants(self, value):
        self.grants = value
        return self

    def with_ttl(self, value):
        self.ttl = value
        return self

    def to_jwt(self):
        return self.token


class FakeApi:
    AccessToken = FakeAccessToken
    VideoGrants = FakeVideoGrants


def grant(*sources):
    return ClassroomJoinGrant(
        room_id="room-1",
        participant_id="student-1",
        publish_sources=tuple(sources),
    )


class LiveKitJoinTokenIssuerTests(unittest.TestCase):
    def setUp(self):
        FakeAccessToken.instances.clear()

    def issuer(self):
        return LiveKitJoinTokenIssuer(
            api_key="api-key",
            api_secret="api-secret",
            api_module=FakeApi,
        )

    def issue(self, issuer, value=None, *, ttl=60):
        return asyncio.run(
            issuer.issue_join_token(
                grant=grant(MediaSource.MICROPHONE) if value is None else value,
                issued_at=NOW,
                expires_at=NOW + timedelta(seconds=ttl),
            )
        )

    def test_maps_exact_room_identity_and_least_privilege_audio_grant(self):
        token = self.issue(self.issuer())
        self.assertEqual(token, "header.payload.signature")
        created = FakeAccessToken.instances[-1]
        self.assertEqual(created.api_key, "api-key")
        self.assertEqual(created.api_secret, "api-secret")
        self.assertEqual(created.identity, "student-1")
        self.assertEqual(created.ttl, timedelta(seconds=60))
        self.assertEqual(
            created.grants.kwargs,
            {
                "room_join": True,
                "room": "room-1",
                "can_publish": True,
                "can_subscribe": True,
                "can_publish_data": False,
                "can_publish_sources": ["microphone"],
            },
        )

    def test_maps_every_canonical_source_without_implicit_extra_permission(self):
        self.issue(
            self.issuer(),
            grant(
                MediaSource.CAMERA,
                MediaSource.SCREEN_SHARE,
                MediaSource.MICROPHONE,
            ),
        )
        kwargs = FakeAccessToken.instances[-1].grants.kwargs
        self.assertEqual(
            kwargs["can_publish_sources"],
            ["microphone", "camera", "screen_share"],
        )
        self.assertNotIn("screen_share_audio", kwargs["can_publish_sources"])
        self.assertNotIn("room_admin", kwargs)
        self.assertNotIn("room_create", kwargs)
        self.assertNotIn("room_record", kwargs)
        self.assertFalse(kwargs["can_publish_data"])

    def test_zero_source_grant_is_explicitly_non_publishing_but_can_subscribe(self):
        self.issue(self.issuer(), grant())
        kwargs = FakeAccessToken.instances[-1].grants.kwargs
        self.assertFalse(kwargs["can_publish"])
        self.assertEqual(kwargs["can_publish_sources"], [])
        self.assertTrue(kwargs["can_subscribe"])
        self.assertFalse(kwargs["can_publish_data"])

    def test_ttl_is_exactly_canonical_service_interval_and_bounded(self):
        self.issue(self.issuer(), ttl=MAX_JOIN_TTL_SECONDS)
        self.assertEqual(
            FakeAccessToken.instances[-1].ttl,
            timedelta(seconds=MAX_JOIN_TTL_SECONDS),
        )
        with self.assertRaisesRegex(LiveKitJoinTokenIssuerError, "TTL is invalid"):
            self.issue(self.issuer(), ttl=0)
        with self.assertRaisesRegex(LiveKitJoinTokenIssuerError, "TTL is invalid"):
            self.issue(self.issuer(), ttl=MAX_JOIN_TTL_SECONDS + 1)

    def test_reuses_canonical_token_validation(self):
        for bad in ("", "token with whitespace", "x\nsecret", "x" * 8193):
            class BadAccessToken(FakeAccessToken):
                def __init__(self, api_key, api_secret, bad=bad):
                    super().__init__(api_key, api_secret)
                    self.token = bad

            class BadApi:
                AccessToken = BadAccessToken
                VideoGrants = FakeVideoGrants

            with self.subTest(bad=repr(bad)[:30]):
                with self.assertRaisesRegex(
                    LiveKitJoinTokenIssuerError,
                    "^LiveKit join token issuance failed$",
                ):
                    self.issue(
                        LiveKitJoinTokenIssuer(
                            api_key="api-key",
                            api_secret="api-secret",
                            api_module=BadApi,
                        ),
                    )

    def test_provider_error_is_sanitized_and_secret_never_renders(self):
        secret = "super-private-provider-secret"

        class BrokenAccessToken(FakeAccessToken):
            def to_jwt(self):
                raise RuntimeError(secret)

        class BrokenApi:
            AccessToken = BrokenAccessToken
            VideoGrants = FakeVideoGrants

        issuer = LiveKitJoinTokenIssuer(
            api_key="private-key",
            api_secret=secret,
            api_module=BrokenApi,
        )
        self.assertNotIn(secret, repr(issuer))
        self.assertNotIn("private-key", repr(issuer))
        with self.assertRaisesRegex(
            LiveKitJoinTokenIssuerError,
            "^LiveKit join token issuance failed$",
        ) as caught:
            self.issue(issuer)
        self.assertNotIn(secret, str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    def test_credentials_are_explicit_strict_and_bounded(self):
        for key, secret in (
            ("", "secret"),
            (" key", "secret"),
            ("key", " secret"),
            ("key\n", "secret"),
            ("key", "secret\r"),
            ("k" * (MAX_LIVEKIT_CREDENTIAL_CHARS + 1), "secret"),
            ("key", "s" * (MAX_LIVEKIT_CREDENTIAL_CHARS + 1)),
        ):
            with self.subTest(key=repr(key)[:20], secret=repr(secret)[:20]):
                with self.assertRaises(LiveKitJoinTokenIssuerError):
                    LiveKitJoinTokenIssuer(
                        api_key=key,
                        api_secret=secret,
                        api_module=FakeApi,
                    )

    def test_missing_or_incompatible_sdk_fails_closed(self):
        class MissingApi:
            pass

        with self.assertRaisesRegex(
            LiveKitJoinTokenIssuerError,
            "token API is unavailable",
        ):
            LiveKitJoinTokenIssuer(
                api_key="key",
                api_secret="secret",
                api_module=MissingApi,
            )

    def test_rejects_noncanonical_grant_and_naive_clock(self):
        issuer = self.issuer()
        with self.assertRaisesRegex(LiveKitJoinTokenIssuerError, "grant is invalid"):
            asyncio.run(
                issuer.issue_join_token(
                    grant=object(),
                    issued_at=NOW,
                    expires_at=NOW + timedelta(seconds=60),
                )
            )
        with self.assertRaisesRegex(LiveKitJoinTokenIssuerError, "timezone-aware"):
            asyncio.run(
                issuer.issue_join_token(
                    grant=grant(MediaSource.MICROPHONE),
                    issued_at=NOW.replace(tzinfo=None),
                    expires_at=NOW + timedelta(seconds=60),
                )
            )


if __name__ == "__main__":
    unittest.main()
