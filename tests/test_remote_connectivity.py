from __future__ import annotations

import unittest

from acs.classroom_domain import (
    ClassroomClass,
    ClassroomSnapshot,
    Cohort,
    ConsentState,
    Course,
    Group,
    Lesson,
    Student,
)
from acs.remote_connectivity import (
    MAX_REMOTE_PAYLOAD_BYTES,
    AuthenticatedPrincipal,
    CanonicalStudentAuthorizer,
    RemoteConnectionContext,
    RemoteConnectivityError,
    RemoteEndpointProfile,
    RemoteEnvelope,
    RemoteIngressDisposition,
    RemoteIngressGuard,
    RemoteMessageKind,
    RemoteRetryPolicy,
    RemoteRole,
    TlsRelayClient,
    event_envelope,
    require_runtime_secret,
)
from acs.remote_session import RemoteEventKind, RemoteSessionEvent, RemoteSessionLog
from acs.teaching_session import (
    LessonSession,
    PositionSourceKind,
    TeachingActivity,
    TeachingPositionSource,
    TeachingStep,
    default_policy,
)


class _SecretProvider:
    def __init__(self, secret: str | None) -> None:
        self.secret = secret
        self.keys: list[str] = []

    def get_secret(self, credential_key: str) -> str | None:
        self.keys.append(credential_key)
        return self.secret


class _Authorizer:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed
        self.calls: list[AuthenticatedPrincipal] = []

    def authorize(self, principal: AuthenticatedPrincipal) -> bool:
        self.calls.append(principal)
        return self.allowed


class RemoteConnectivityTests(unittest.TestCase):
    def principal(self) -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            "class-1",
            "session-1",
            "student-1",
            RemoteRole.STUDENT,
        )

    def classroom(self, *, include_student: bool = True) -> ClassroomSnapshot:
        students = (
            (Student("student-1", "Anna", ConsentState.GRANTED),)
            if include_student
            else ()
        )
        return ClassroomSnapshot(
            students=students,
            classes=(ClassroomClass("class-1", "Class", ("group-1",)),),
            groups=(Group("group-1", "class-1", "Group"),),
            courses=(Course("course-1", "Course", ("lesson-1",)),),
            cohorts=(
                Cohort(
                    "cohort-1",
                    "course-1",
                    ("student-1",) if include_student else (),
                    "group-1",
                ),
            ),
            lessons=(
                Lesson(
                    "lesson-1",
                    "course-1",
                    "Lesson",
                    (),
                    "2026-09-11T10:00:00Z",
                ),
            ),
        )

    def plan(self) -> LessonSession:
        activity = TeachingActivity.STUDENT_RESPONDS
        return LessonSession(
            "session-1",
            "lesson-1",
            TeachingPositionSource(PositionSourceKind.START),
            (
                TeachingStep(
                    "step-1",
                    activity,
                    "Prompt",
                    default_policy(activity),
                ),
            ),
            ("student-1",),
            "cohort-1",
        )

    def event(self, *, sequence: int = 1, square: str = "e4") -> RemoteSessionEvent:
        return RemoteSessionEvent(
            "session-1",
            sequence,
            RemoteEventKind.POINTER,
            {"square": square},
            "student-1",
        )

    def test_envelope_round_trip_is_closed_world_and_deterministic(self) -> None:
        principal = self.principal()
        envelope = event_envelope(self.event(), principal)
        encoded = envelope.to_json_bytes()
        restored = RemoteEnvelope.from_json_bytes(encoded)
        self.assertEqual(restored, envelope)
        self.assertEqual(restored.message_id, self.event().event_id)
        self.assertLess(len(encoded), 64 * 1024)

    def test_duplicate_keys_nonfinite_unknown_version_and_unknown_kind_fail_closed(self) -> None:
        for payload in (
            b'{"version":1,"version":1}',
            b'{"number":NaN}',
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(RemoteConnectivityError):
                    RemoteEnvelope.from_json_bytes(payload)

        record = event_envelope(self.event(), self.principal()).to_record()
        record["version"] = 2
        with self.assertRaises(RemoteConnectivityError):
            RemoteEnvelope.from_record(record)
        record["version"] = 1
        record["kind"] = "future-message"
        with self.assertRaises(RemoteConnectivityError):
            RemoteEnvelope.from_record(record)

    def test_payload_size_is_bounded_before_transport(self) -> None:
        with self.assertRaises(RemoteConnectivityError):
            RemoteEnvelope(
                1,
                RemoteMessageKind.ACK,
                "message-1",
                "session-1",
                "student-1",
                RemoteRole.STUDENT,
                None,
                {"blob": "x" * MAX_REMOTE_PAYLOAD_BYTES},
            )

    def test_endpoint_profile_serialization_contains_no_secret(self) -> None:
        profile = RemoteEndpointProfile(
            "profile-1",
            "relay.example.test",
            443,
            "relay.example.test",
            "remote-profile-1",
        )
        record = profile.to_record()
        self.assertEqual(RemoteEndpointProfile.from_record(record), profile)
        self.assertNotIn("secret", repr(record).lower())
        self.assertNotIn("token", repr(record).lower())
        self.assertEqual(record["credential_key"], "remote-profile-1")

    def test_runtime_secret_is_injected_and_missing_or_invalid_secret_fails_closed(self) -> None:
        provider = _SecretProvider("runtime-only-secret")
        self.assertEqual(
            require_runtime_secret(provider, "remote-profile-1"),
            "runtime-only-secret",
        )
        self.assertEqual(provider.keys, ["remote-profile-1"])
        for secret in (None, "", " padded "):
            with self.subTest(secret=secret):
                with self.assertRaises(RemoteConnectivityError):
                    require_runtime_secret(_SecretProvider(secret), "remote-profile-1")

    def test_canonical_student_authorizer_uses_existing_membership_and_session_scope(self) -> None:
        authorizer = CanonicalStudentAuthorizer(
            self.plan(),
            self.classroom(),
            "class-1",
        )
        self.assertTrue(authorizer.authorize(self.principal()))
        self.assertFalse(
            authorizer.authorize(
                AuthenticatedPrincipal(
                    "class-1",
                    "session-1",
                    "teacher-1",
                    RemoteRole.TEACHER,
                )
            )
        )
        revoked = CanonicalStudentAuthorizer(
            self.plan(),
            self.classroom(include_student=False),
            "class-1",
        )
        self.assertFalse(revoked.authorize(self.principal()))

    def test_ingress_authorizes_before_canonical_mutation_and_exact_replay_is_idempotent(self) -> None:
        principal = self.principal()
        context = RemoteConnectionContext(principal)
        log = RemoteSessionLog("session-1")
        authorizer = CanonicalStudentAuthorizer(
            self.plan(),
            self.classroom(),
            "class-1",
        )
        guard = RemoteIngressGuard(log, authorizer)
        envelope = event_envelope(self.event(), principal)

        self.assertIs(guard.apply(envelope, context), RemoteIngressDisposition.APPLIED)
        self.assertEqual(log.state.last_sequence, 1)
        self.assertEqual(log.state.pointer_square, "e4")
        self.assertIs(guard.apply(envelope, context), RemoteIngressDisposition.DUPLICATE)
        self.assertEqual(len(log.events), 1)

    def test_spoofed_actor_role_and_revoked_membership_cannot_mutate_log(self) -> None:
        principal = self.principal()
        context = RemoteConnectionContext(principal)
        base = event_envelope(self.event(), principal).to_record()

        for key, value in (("actor_id", "student-2"), ("role", "teacher")):
            with self.subTest(key=key):
                record = dict(base)
                record[key] = value
                log = RemoteSessionLog("session-1")
                guard = RemoteIngressGuard(log, _Authorizer(True))
                with self.assertRaises(RemoteConnectivityError):
                    guard.apply(RemoteEnvelope.from_record(record), context)
                self.assertEqual(log.state.last_sequence, 0)

        log = RemoteSessionLog("session-1")
        guard = RemoteIngressGuard(log, _Authorizer(False))
        with self.assertRaises(RemoteConnectivityError):
            guard.apply(event_envelope(self.event(), principal), context)
        self.assertEqual(log.state.last_sequence, 0)

    def test_event_content_tampering_and_sequence_gap_fail_before_state_change(self) -> None:
        principal = self.principal()
        context = RemoteConnectionContext(principal)
        envelope = event_envelope(self.event(), principal)
        record = envelope.to_record()
        tampered_payload = dict(record["payload"])
        tampered_payload["payload"] = {"square": "d4"}
        record["payload"] = tampered_payload
        guard = RemoteIngressGuard(RemoteSessionLog("session-1"), _Authorizer(True))
        with self.assertRaises(RemoteConnectivityError):
            guard.apply(RemoteEnvelope.from_record(record), context)

        gap_log = RemoteSessionLog("session-1")
        gap_guard = RemoteIngressGuard(gap_log, _Authorizer(True))
        with self.assertRaises(RemoteConnectivityError):
            gap_guard.apply(event_envelope(self.event(sequence=2), principal), context)
        self.assertEqual(gap_log.state.last_sequence, 0)

    def test_non_event_control_message_cannot_mutate_canonical_log(self) -> None:
        principal = self.principal()
        log = RemoteSessionLog("session-1")
        guard = RemoteIngressGuard(log, _Authorizer(True))
        envelope = RemoteEnvelope(
            1,
            RemoteMessageKind.RESUME,
            "resume-1",
            "session-1",
            "student-1",
            RemoteRole.STUDENT,
            0,
            {},
            "0" * 64,
        )
        with self.assertRaises(RemoteConnectivityError):
            guard.apply(envelope, RemoteConnectionContext(principal))
        self.assertEqual(log.state.last_sequence, 0)

    def test_retry_policy_is_bounded_and_tls_client_never_implicitly_connects(self) -> None:
        with self.assertRaises(RemoteConnectivityError):
            RemoteRetryPolicy(max_attempts=6)
        profile = RemoteEndpointProfile(
            "profile-1",
            "relay.example.test",
            443,
            "relay.example.test",
            "remote-profile-1",
        )
        client = TlsRelayClient(profile)
        with self.assertRaises(RemoteConnectivityError):
            client.exchange(event_envelope(self.event(), self.principal()))


if __name__ == "__main__":
    unittest.main()
