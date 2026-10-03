from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest import mock

from acs.classroom_join_http_client import (
    ClassroomJoinHttpClient,
    ClassroomJoinHttpClientError,
)
from acs.classroom_media_webview_projection import ClassroomMediaWebViewEvent
from acs.classroom_realtime_media import ClassroomMediaError, JoinCredential
from acs.full_product_ui_shell import UILanguage
from acs.version2_final_product_application import Version2FinalProductApplication


NOW = datetime(2026, 10, 3, 4, 0, tzinfo=timezone.utc)
TOKEN = "provider-secret-token"


def credential(room_id: str = "room-1", participant_id: str = "student-1") -> JoinCredential:
    return JoinCredential(
        room_id=room_id,
        participant_id=participant_id,
        token=TOKEN,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=1),
    )


class FakeController:
    def __init__(self) -> None:
        self.state = SimpleNamespace(
            room_id=None,
            participant_id="student-1",
            connected=False,
        )
        self.removed = False
        self.blocked = False

    def participant_policy(self, participant_id: str):
        if participant_id != self.state.participant_id:
            raise AssertionError("composition changed canonical participant identity")
        return SimpleNamespace(removed=self.removed, blocked=self.blocked)


class FakeTransactions:
    def __init__(self) -> None:
        self.binder = SimpleNamespace(active_lease=None, recovery_status=None)
        self.join_calls = []
        self.reconnect_calls = []

    def prepare_join(self, value: JoinCredential, *, now: datetime):
        value.assert_usable(now)
        self.join_calls.append((value, now))
        return ClassroomMediaWebViewEvent(
            "provider-dispatch",
            {
                "transaction_id": "session-" + "1" * 32,
                "provider": {"operation": "connect"},
                "provider_boundary_crossed": False,
            },
        )

    def prepare_reconnect(self, value: JoinCredential, *, now: datetime):
        value.assert_usable(now)
        self.reconnect_calls.append((value, now))
        return ClassroomMediaWebViewEvent(
            "provider-dispatch",
            {
                "transaction_id": "session-" + "2" * 32,
                "provider": {"operation": "reconnect"},
                "provider_boundary_crossed": False,
            },
        )


class ClassroomMediaJoinHttpCompositionTests(unittest.TestCase):
    def application(self):
        controller = FakeController()
        transactions = FakeTransactions()
        application = object.__new__(Version2FinalProductApplication)
        application.shell = SimpleNamespace(language=UILanguage.EN)
        application.media = SimpleNamespace(
            projection=SimpleNamespace(controller=controller)
        )
        application.media_transactions = transactions
        application._media_join_http = None
        application._events = deque()
        application._assert_thread = lambda: None
        return application, controller, transactions

    def configure(self, application, bearer, now_provider=None):
        application.configure_classroom_media_join_http(
            endpoint_url="https://classroom.example/v1/classroom/join-credential",
            bearer_token_provider=bearer,
            now_provider=(
                (lambda: NOW + timedelta(seconds=1))
                if now_provider is None
                else now_provider
            ),
        )

    def test_configuration_is_lazy_and_requires_transactional_media(self):
        calls = []
        application, _controller, _transactions = self.application()
        self.configure(application, lambda: calls.append("bearer") or "account-token")
        self.assertEqual(calls, [])
        self.assertIsInstance(application._media_join_http, ClassroomJoinHttpClient)

        with self.assertRaisesRegex(RuntimeError, "already configured"):
            self.configure(application, lambda: "replacement")

        unbound, _controller, _transactions = self.application()
        unbound.media_transactions = None
        with self.assertRaisesRegex(RuntimeError, "must be bound"):
            self.configure(unbound, lambda: "never")
        self.assertIsNone(unbound._media_join_http)

    def test_invalid_clock_configuration_is_atomic(self):
        application, _controller, _transactions = self.application()
        with self.assertRaisesRegex(
            TypeError,
            "classroom media join clock must be callable",
        ):
            application.configure_classroom_media_join_http(
                endpoint_url="https://classroom.example/v1/classroom/join-credential",
                bearer_token_provider=lambda: "account-token",
                now_provider=object(),
            )
        self.assertIsNone(application._media_join_http)
        self.assertIsNone(application._media_join_now_provider)
        self.assertIsNone(getattr(application, "_media_join_now_provider", None))

    def test_join_uses_canonical_controller_participant_and_redacts_provider_token(self):
        application, _controller, transactions = self.application()
        self.configure(application, lambda: "account-token")
        issued = credential()

        with mock.patch.object(
            ClassroomJoinHttpClient,
            "issue",
            autospec=True,
            return_value=issued,
        ) as issue:
            rendered = application.prepare_classroom_media_join_http("room-1")

        issue.assert_called_once_with(
            application._media_join_http,
            room_id="room-1",
            participant_id="student-1",
        )
        self.assertEqual(transactions.join_calls, [(issued, NOW + timedelta(seconds=1))])
        self.assertEqual(rendered["kind"], "provider-dispatch")
        self.assertNotIn(TOKEN, repr(rendered))
        self.assertEqual(list(application._events), [rendered])

    def test_join_samples_validity_clock_after_http_issuance(self):
        application, _controller, transactions = self.application()
        order = []
        issued = JoinCredential(
            room_id="room-1",
            participant_id="student-1",
            token=TOKEN,
            issued_at=NOW + timedelta(seconds=5),
            expires_at=NOW + timedelta(minutes=1),
        )

        def now_provider():
            order.append("clock")
            return NOW + timedelta(seconds=6)

        self.configure(application, lambda: "account-token", now_provider=now_provider)

        def issue(_client, *, room_id, participant_id):
            self.assertEqual((room_id, participant_id), ("room-1", "student-1"))
            order.append("issue")
            return issued

        with mock.patch.object(
            ClassroomJoinHttpClient,
            "issue",
            autospec=True,
            side_effect=issue,
        ):
            rendered = application.prepare_classroom_media_join_http("room-1")

        self.assertEqual(order, ["issue", "clock"])
        self.assertEqual(
            transactions.join_calls,
            [(issued, NOW + timedelta(seconds=6))],
        )
        self.assertEqual(rendered["kind"], "provider-dispatch")

    def test_join_rejects_credential_expired_during_http_round_trip(self):
        application, _controller, transactions = self.application()
        issued = JoinCredential(
            room_id="room-1",
            participant_id="student-1",
            token=TOKEN,
            issued_at=NOW,
            expires_at=NOW + timedelta(seconds=2),
        )
        self.configure(
            application,
            lambda: "account-token",
            now_provider=lambda: NOW + timedelta(seconds=3),
        )

        with mock.patch.object(
            ClassroomJoinHttpClient,
            "issue",
            autospec=True,
            return_value=issued,
        ):
            with self.assertRaisesRegex(
                ClassroomMediaError,
                "join credential is not currently valid",
            ) as error:
                application.prepare_classroom_media_join_http("room-1")

        self.assertNotIn(TOKEN, repr(error.exception))
        self.assertEqual(transactions.join_calls, [])
        self.assertEqual(list(application._events), [])

    def test_invalid_room_fails_before_bearer_or_network(self):
        bearer_calls = []
        application, _controller, _transactions = self.application()
        self.configure(
            application,
            lambda: bearer_calls.append("called") or "account-token",
        )

        with self.assertRaisesRegex(
            ClassroomJoinHttpClientError,
            "^join credential request room id is invalid$",
        ):
            application.prepare_classroom_media_join_http(
                "bad room",
            )

        self.assertEqual(bearer_calls, [])
        self.assertEqual(list(application._events), [])

    def test_join_preflight_rejects_nonquiescent_or_blocked_state_before_credential(self):
        application, controller, transactions = self.application()
        self.configure(application, lambda: "account-token")
        with mock.patch.object(
            ClassroomJoinHttpClient,
            "issue",
            autospec=True,
        ) as issue:
            transactions.binder.active_lease = object()
            with self.assertRaisesRegex(RuntimeError, "not quiescent"):
                application.prepare_classroom_media_join_http("room-1")
            transactions.binder.active_lease = None
            controller.blocked = True
            with self.assertRaisesRegex(RuntimeError, "not allowed"):
                application.prepare_classroom_media_join_http("room-1")
        issue.assert_not_called()

    def test_reconnect_refreshes_exact_retained_room_and_participant(self):
        application, controller, transactions = self.application()
        self.configure(application, lambda: "account-token")
        controller.state = SimpleNamespace(
            room_id="room-retained",
            participant_id="student-1",
            connected=False,
        )
        issued = credential(room_id="room-retained")

        with mock.patch.object(
            ClassroomJoinHttpClient,
            "issue",
            autospec=True,
            return_value=issued,
        ) as issue:
            rendered = application.prepare_classroom_media_reconnect_http()

        issue.assert_called_once_with(
            application._media_join_http,
            room_id="room-retained",
            participant_id="student-1",
        )
        self.assertEqual(
            transactions.reconnect_calls,
            [(issued, NOW + timedelta(seconds=1))],
        )
        self.assertEqual(rendered["payload"]["provider"]["operation"], "reconnect")
        self.assertNotIn(TOKEN, repr(rendered))

    def test_reconnect_preflight_does_not_fetch_credential_for_invalid_session_state(self):
        application, controller, _transactions = self.application()
        self.configure(application, lambda: "account-token")
        with mock.patch.object(
            ClassroomJoinHttpClient,
            "issue",
            autospec=True,
        ) as issue:
            with self.assertRaisesRegex(RuntimeError, "no room"):
                application.prepare_classroom_media_reconnect_http()
            controller.state = SimpleNamespace(
                room_id="room-1",
                participant_id="student-1",
                connected=True,
            )
            with self.assertRaisesRegex(RuntimeError, "already connected"):
                application.prepare_classroom_media_reconnect_http()
        issue.assert_not_called()

    def test_quiescent_unbind_retires_join_http_auth_binding(self):
        application, controller, _transactions = self.application()
        self.configure(application, lambda: "account-token")
        controller.state = SimpleNamespace(
            room_id=None,
            participant_id="student-1",
            connected=False,
        )
        application.unbind_classroom_media()
        self.assertIsNone(application.media)
        self.assertIsNone(application.media_transactions)
        self.assertIsNone(application._media_join_http)


if __name__ == "__main__":
    unittest.main()
