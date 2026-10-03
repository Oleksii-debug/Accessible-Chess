from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import traceback
import unittest

from acs.classroom_join_credentials import (
    ClassroomJoinCredentialError,
    ClassroomJoinCredentialService,
    ClassroomJoinGrant,
    JOIN_REQUEST_VERSION,
    MAX_JOIN_REQUEST_BYTES,
    parse_join_request,
)
from acs.classroom_realtime_media import (
    JoinCredential,
    MAX_JOIN_TTL_SECONDS,
    MediaSource,
)


NOW = datetime(2026, 10, 2, 20, 0, tzinfo=timezone.utc)


def request(**overrides):
    value = {
        "version": JOIN_REQUEST_VERSION,
        "room_id": "room-1",
        "participant_id": "student-1",
    }
    value.update(overrides)
    return json.dumps(value, separators=(",", ":"))


class FakeAuthorization:
    def __init__(self):
        self.calls = []
        self.error = None
        self.grant = ClassroomJoinGrant(
            room_id="room-1",
            participant_id="student-1",
            publish_sources=(MediaSource.MICROPHONE, MediaSource.CAMERA),
        )

    def authorize_join(
        self,
        *,
        room_id,
        trusted_caller_identity,
        requested_participant_id,
    ):
        self.calls.append((room_id, trusted_caller_identity, requested_participant_id))
        if self.error is not None:
            raise self.error
        return self.grant


class FakeIssuer:
    def __init__(self):
        self.calls = []
        self.error = None
        self.token = "provider-short-lived-token"
        self.after_issue = None

    async def issue_join_token(self, *, grant, issued_at, expires_at):
        self.calls.append((grant, issued_at, expires_at))
        if self.error is not None:
            raise self.error
        if self.after_issue is not None:
            self.after_issue()
        return self.token


class ClassroomJoinCredentialServiceTests(unittest.TestCase):
    def make_service(self, *, ttl=60, now=lambda: NOW):
        authorization = FakeAuthorization()
        issuer = FakeIssuer()
        service = ClassroomJoinCredentialService(
            authorization=authorization,
            token_issuer=issuer,
            ttl_seconds=ttl,
            now=now,
        )
        return service, authorization, issuer

    def run_issue(self, service, payload=None, caller="account-17"):
        return asyncio.run(
            service.issue(
                trusted_caller_identity=caller,
                payload=request() if payload is None else payload,
            )
        )

    def test_valid_request_uses_trusted_authority_and_returns_canonical_credential(self):
        service, authorization, issuer = self.make_service()

        response = json.loads(self.run_issue(service))

        self.assertEqual(
            authorization.calls,
            [
                ("room-1", "account-17", "student-1"),
                ("room-1", "account-17", "student-1"),
            ],
        )
        self.assertEqual(len(issuer.calls), 1)
        grant, issued_at, expires_at = issuer.calls[0]
        self.assertEqual(
            grant.publish_sources,
            (MediaSource.MICROPHONE, MediaSource.CAMERA),
        )
        self.assertEqual(issued_at, NOW)
        self.assertEqual(expires_at, NOW + timedelta(seconds=60))
        self.assertEqual(
            set(response),
            {"version", "room_id", "participant_id", "token", "issued_at", "expires_at"},
        )
        self.assertEqual(response["room_id"], "room-1")
        self.assertEqual(response["participant_id"], "student-1")
        self.assertEqual(response["token"], "provider-short-lived-token")
        self.assertEqual(response["issued_at"], "2026-10-02T20:00:00Z")
        self.assertEqual(response["expires_at"], "2026-10-02T20:01:00Z")

        credential = JoinCredential(
            room_id=response["room_id"],
            participant_id=response["participant_id"],
            token=response["token"],
            issued_at=datetime.fromisoformat(response["issued_at"].replace("Z", "+00:00")),
            expires_at=datetime.fromisoformat(response["expires_at"].replace("Z", "+00:00")),
        )
        credential.assert_usable(NOW + timedelta(seconds=1))
        self.assertNotIn(response["token"], repr(credential))

    def test_client_cannot_choose_ttl_role_or_source_permissions(self):
        service, authorization, issuer = self.make_service()
        for extra in (
            {"ttl_seconds": 900},
            {"role": "teacher"},
            {"publish_sources": ["camera"]},
            {"api_secret": "never"},
        ):
            with self.subTest(extra=extra):
                with self.assertRaisesRegex(ClassroomJoinCredentialError, "fields are invalid"):
                    self.run_issue(service, request(**extra))
        self.assertEqual(authorization.calls, [])
        self.assertEqual(issuer.calls, [])

    def test_request_identity_is_exact_and_authority_sees_trusted_caller(self):
        service, authorization, issuer = self.make_service()
        with self.assertRaises(ClassroomJoinCredentialError):
            self.run_issue(service, request(room_id=" room-1"))
        with self.assertRaises(ClassroomJoinCredentialError):
            self.run_issue(service, caller=" account-17")
        self.assertEqual(authorization.calls, [])
        self.assertEqual(issuer.calls, [])

    def test_authorization_failure_happens_before_token_minting_and_is_sanitized(self):
        service, authorization, issuer = self.make_service()
        authorization.error = RuntimeError("private roster database detail")

        with self.assertRaisesRegex(
            ClassroomJoinCredentialError,
            "^join request is not authorized$",
        ) as caught:
            self.run_issue(service)

        self.assertNotIn("database", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)
        rendered = "".join(traceback.format_exception(caught.exception))
        self.assertNotIn("private roster database detail", rendered)
        self.assertEqual(issuer.calls, [])

    def test_authority_cannot_silently_rebind_room_or_participant(self):
        service, authorization, issuer = self.make_service()
        authorization.grant = ClassroomJoinGrant(
            room_id="other-room",
            participant_id="student-1",
            publish_sources=(MediaSource.MICROPHONE,),
        )
        with self.assertRaisesRegex(ClassroomJoinCredentialError, "identity does not match"):
            self.run_issue(service)
        self.assertEqual(issuer.calls, [])

        authorization.grant = ClassroomJoinGrant(
            room_id="room-1",
            participant_id="student-2",
            publish_sources=(MediaSource.MICROPHONE,),
        )
        with self.assertRaisesRegex(ClassroomJoinCredentialError, "identity does not match"):
            self.run_issue(service)
        self.assertEqual(issuer.calls, [])

    def test_revocation_during_provider_mint_discards_token_before_response(self):
        service, authorization, issuer = self.make_service()
        issuer.after_issue = lambda: setattr(
            authorization,
            "error",
            RuntimeError("private roster revocation detail"),
        )

        with self.assertRaisesRegex(
            ClassroomJoinCredentialError,
            "^join request is no longer authorized$",
        ) as caught:
            self.run_issue(service)

        self.assertEqual(len(issuer.calls), 1)
        self.assertEqual(len(authorization.calls), 2)
        self.assertIsNone(caught.exception.__cause__)
        rendered = "".join(traceback.format_exception(caught.exception))
        self.assertNotIn("private roster revocation detail", rendered)
        self.assertNotIn(issuer.token, rendered)

    def test_permission_change_during_provider_mint_discards_stale_grant(self):
        service, authorization, issuer = self.make_service()

        def change_grant():
            authorization.grant = ClassroomJoinGrant(
                room_id="room-1",
                participant_id="student-1",
                publish_sources=(MediaSource.MICROPHONE,),
            )

        issuer.after_issue = change_grant

        with self.assertRaisesRegex(
            ClassroomJoinCredentialError,
            "^join authorization changed during token issuance$",
        ) as caught:
            self.run_issue(service)

        self.assertEqual(len(issuer.calls), 1)
        self.assertEqual(len(authorization.calls), 2)
        self.assertIsNone(caught.exception.__cause__)
        self.assertNotIn(issuer.token, "".join(traceback.format_exception(caught.exception)))

    def test_authority_grant_canonicalizes_source_order_and_rejects_duplicates(self):
        grant = ClassroomJoinGrant(
            room_id="room-1",
            participant_id="student-1",
            publish_sources=(MediaSource.CAMERA, MediaSource.MICROPHONE),
        )
        self.assertEqual(grant.publish_sources, (MediaSource.MICROPHONE, MediaSource.CAMERA))
        with self.assertRaises(ClassroomJoinCredentialError):
            ClassroomJoinGrant(
                room_id="room-1",
                participant_id="student-1",
                publish_sources=(MediaSource.CAMERA, MediaSource.CAMERA),
            )

    def test_ttl_is_server_fixed_and_canonical_bound_is_enforced(self):
        with self.assertRaises(ValueError):
            ClassroomJoinCredentialService(
                authorization=FakeAuthorization(),
                token_issuer=FakeIssuer(),
                ttl_seconds=0,
                now=lambda: NOW,
            )
        with self.assertRaises(ValueError):
            ClassroomJoinCredentialService(
                authorization=FakeAuthorization(),
                token_issuer=FakeIssuer(),
                ttl_seconds=MAX_JOIN_TTL_SECONDS + 1,
                now=lambda: NOW,
            )
        with self.assertRaises(ValueError):
            ClassroomJoinCredentialService(
                authorization=FakeAuthorization(),
                token_issuer=FakeIssuer(),
                ttl_seconds=True,
                now=lambda: NOW,
            )

        service, _authorization, issuer = self.make_service(ttl=MAX_JOIN_TTL_SECONDS)
        self.run_issue(service)
        self.assertEqual(
            issuer.calls[0][2] - issuer.calls[0][1],
            timedelta(seconds=MAX_JOIN_TTL_SECONDS),
        )

    def test_clock_must_be_timezone_aware_before_authority_or_provider(self):
        service, authorization, issuer = self.make_service(now=lambda: NOW.replace(tzinfo=None))
        with self.assertRaisesRegex(ClassroomJoinCredentialError, "timezone-aware"):
            self.run_issue(service)
        self.assertEqual(authorization.calls, [])
        self.assertEqual(issuer.calls, [])

    def test_clock_provider_failure_is_sanitized_before_authority_or_provider(self):
        def broken_clock():
            raise RuntimeError("private clock backend detail")

        service, authorization, issuer = self.make_service(now=broken_clock)
        with self.assertRaisesRegex(
            ClassroomJoinCredentialError,
            "^join credential clock failed$",
        ) as caught:
            self.run_issue(service)

        self.assertIsNone(caught.exception.__cause__)
        rendered = "".join(traceback.format_exception(caught.exception))
        self.assertNotIn("private clock backend detail", rendered)
        self.assertEqual(authorization.calls, [])
        self.assertEqual(issuer.calls, [])

    def test_provider_failure_and_invalid_token_are_sanitized(self):
        service, _authorization, issuer = self.make_service()
        issuer.error = RuntimeError("provider api_secret leaked internally")
        with self.assertRaisesRegex(
            ClassroomJoinCredentialError,
            "^join token issuance failed$",
        ) as caught:
            self.run_issue(service)
        self.assertNotIn("api_secret", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)
        rendered = "".join(traceback.format_exception(caught.exception))
        self.assertNotIn("provider api_secret leaked internally", rendered)

        service, _authorization, issuer = self.make_service()
        issuer.token = "token with whitespace"
        with self.assertRaisesRegex(
            ClassroomJoinCredentialError,
            "^join token issuer returned invalid credential$",
        ) as caught:
            self.run_issue(service)
        self.assertNotIn(issuer.token, str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)
        rendered = "".join(traceback.format_exception(caught.exception))
        self.assertNotIn(issuer.token, rendered)

    def test_non_utf8_surrogate_text_fails_closed(self):
        with self.assertRaisesRegex(
            ClassroomJoinCredentialError,
            "valid UTF-8",
        ):
            parse_join_request(
                "\ud800",
                trusted_caller_identity="account-17",
            )

    def test_duplicate_json_object_fields_fail_closed(self):
        duplicate_payloads = (
            '{"version":1,"version":1,"room_id":"room-1","participant_id":"student-1"}',
            '{"version":1,"room_id":"room-1","room_id":"room-2","participant_id":"student-1"}',
            '{"version":1,"room_id":"room-1","participant_id":"student-1","participant_id":"student-2"}',
        )
        for payload_value in duplicate_payloads:
            with self.subTest(payload=payload_value):
                with self.assertRaisesRegex(
                    ClassroomJoinCredentialError,
                    "fields must be unique",
                ):
                    parse_join_request(
                        payload_value,
                        trusted_caller_identity="account-17",
                    )

    def test_request_parser_is_strict_and_bounded_before_authorization(self):
        for payload in (
            "",
            "[]",
            "{}",
            json.dumps({"version": True, "room_id": "room-1", "participant_id": "student-1"}),
            json.dumps({"version": 2, "room_id": "room-1", "participant_id": "student-1"}),
            "x" * (MAX_JOIN_REQUEST_BYTES + 1),
        ):
            with self.subTest(payload=payload[:40]):
                with self.assertRaises(ClassroomJoinCredentialError):
                    parse_join_request(payload, trusted_caller_identity="account-17")

    def test_expired_during_issuance_is_rejected_before_response(self):
        clock = iter((NOW, NOW + timedelta(seconds=61)))
        service, _authorization, issuer = self.make_service(now=lambda: next(clock))

        with self.assertRaisesRegex(
            ClassroomJoinCredentialError,
            "^join token issuer returned unusable credential$",
        ) as caught:
            self.run_issue(service)

        self.assertEqual(len(issuer.calls), 1)
        self.assertIsNone(caught.exception.__cause__)

    def test_each_reconnect_request_mints_a_fresh_credential(self):
        service, authorization, issuer = self.make_service()
        issuer.token = "fresh-token-one"
        first = json.loads(self.run_issue(service))
        issuer.token = "fresh-token-two"
        second = json.loads(self.run_issue(service))
        self.assertEqual(len(authorization.calls), 4)
        self.assertEqual(len(issuer.calls), 2)
        self.assertNotEqual(first["token"], second["token"])

    def test_join_credential_workflow_binds_current_product_base_fail_closed(self):
        source = (
            Path(__file__).parents[1]
            / ".github"
            / "workflows"
            / "classroom-join-credential-service.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("EVENT_BASE_SHA: ${{ github.event.pull_request.base.sha }}", source)
        self.assertIn('git merge-base --is-ancestor "$EVENT_BASE_SHA" HEAD', source)
        self.assertIn('git fetch --no-tags origin "$EXPECTED_BASE_REF"', source)
        self.assertIn('base="$(git rev-parse "refs/remotes/origin/$EXPECTED_BASE_REF")"', source)
        self.assertIn('git merge-base --is-ancestor "$base" HEAD', source)
        self.assertIn('git diff --name-only "$base...HEAD"', source)
        self.assertNotIn('git diff --name-only "$EXPECTED_BASE_SHA" HEAD', source)

    def test_bad_provider_return_never_escapes_join_credential_contract(self):
        service, _authorization, issuer = self.make_service()
        for bad in (None, "", "x\nsecret", "x" * 8193):
            with self.subTest(bad=repr(bad)[:30]):
                issuer.token = bad
                with self.assertRaises(ClassroomJoinCredentialError):
                    self.run_issue(service)


if __name__ == "__main__":
    unittest.main()
