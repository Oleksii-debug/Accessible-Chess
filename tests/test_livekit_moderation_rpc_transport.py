from __future__ import annotations

import json
from pathlib import Path
import traceback
from types import SimpleNamespace
import unittest

from acs.classroom_moderation_rpc import (
    ClassroomModerationRpcError,
    MAX_RPC_PAYLOAD_BYTES,
    RPC_VERSION,
    parse_moderation_rpc,
)
from acs.livekit_moderation_rpc_transport import (
    LIVEKIT_RTC_VERSION,
    LiveKitModerationRpcTransport,
    LiveKitModerationRpcTransportError,
    MAX_RPC_ERROR_MESSAGE_BYTES,
    MODERATION_RPC_ERROR_CODE,
    MODERATION_RPC_METHOD,
)


ROOM = "room-1"
SERVICE_ID = "moderation-service"
CALLER = "teacher-1"


class FakeRpcError(Exception):
    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class FakeRtc:
    RpcError = FakeRpcError


class FakeParticipant:
    def __init__(self, identity=SERVICE_ID):
        self.identity = identity
        self.handlers = {}
        self.register_calls = []
        self.unregister_calls = []
        self.register_error = None
        self.unregister_error = None

    def register_rpc_method(self, method, handler):
        self.register_calls.append((method, handler))
        if self.register_error is not None:
            raise self.register_error
        self.handlers[method] = handler
        return handler

    def unregister_rpc_method(self, method):
        self.unregister_calls.append(method)
        if self.unregister_error is not None:
            error = self.unregister_error
            self.unregister_error = None
            raise error
        self.handlers.pop(method, None)


class ParsingService:
    def __init__(self):
        self.calls = []
        self.unexpected_error = None
        self.response_override = None

    async def handle_rpc(
        self,
        *,
        trusted_room_id,
        trusted_caller_identity,
        payload,
    ):
        self.calls.append((trusted_room_id, trusted_caller_identity, payload))
        if self.unexpected_error is not None:
            raise self.unexpected_error
        parsed = parse_moderation_rpc(
            payload,
            trusted_room_id=trusted_room_id,
            trusted_caller_identity=trusted_caller_identity,
        )
        if self.response_override is not None:
            return self.response_override
        return json.dumps(
            {
                "version": RPC_VERSION,
                "status": "ok",
                "accepted_operation_ids": [
                    command.operation_id for command in parsed.commands
                ],
            },
            separators=(",", ":"),
        )


def payload(
    *,
    actor_id=CALLER,
    room_id=ROOM,
    operation_id="op-1",
):
    return json.dumps(
        {
            "version": RPC_VERSION,
            "room_id": room_id,
            "operations": [
                {
                    "operation_id": operation_id,
                    "actor_id": actor_id,
                    "target_id": "student-1",
                    "action": "publish_permission",
                    "source": "microphone",
                    "value": False,
                }
            ],
        },
        separators=(",", ":"),
    )


class LiveKitModerationRpcTransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.participant = FakeParticipant()
        self.service = ParsingService()
        self.transport = None

    def tearDown(self):
        if self.transport is not None and not self.transport.closed:
            self.transport.close()

    def bind(self, **overrides):
        values = {
            "local_participant": self.participant,
            "trusted_room_id": ROOM,
            "moderation_participant_identity": SERVICE_ID,
            "service": self.service,
            "rtc_module": FakeRtc,
            "sdk_version": LIVEKIT_RTC_VERSION,
        }
        values.update(overrides)
        transport = LiveKitModerationRpcTransport.bind(**values)
        if values["local_participant"] is self.participant:
            self.transport = transport
        return transport

    async def invoke(self, *, caller=CALLER, wire=None):
        handler = self.participant.handlers[MODERATION_RPC_METHOD]
        return await handler(
            SimpleNamespace(
                request_id="request-1",
                caller_identity=caller,
                payload=payload() if wire is None else wire,
                response_timeout=5.0,
                method=MODERATION_RPC_METHOD,
            )
        )

    def assert_rpc_error(self, error, message=None):
        self.assertIsInstance(error, FakeRpcError)
        self.assertEqual(error.code, MODERATION_RPC_ERROR_CODE)
        self.assertIsNone(error.data)
        if message is not None:
            self.assertEqual(error.message, message)

    def test_bind_registers_exact_canonical_method_and_redacts_context(self):
        transport = self.bind()
        self.assertEqual(transport.method, MODERATION_RPC_METHOD)
        self.assertEqual(len(self.participant.register_calls), 1)
        method, handler = self.participant.register_calls[0]
        self.assertEqual(method, "accessible-chess.classroom.moderation.v1")
        self.assertIs(handler, self.participant.handlers[method])
        rendered = repr(transport)
        self.assertNotIn(ROOM, rendered)
        self.assertNotIn(SERVICE_ID, rendered)
        self.assertIn(MODERATION_RPC_METHOD, rendered)

    async def test_provider_caller_identity_is_forwarded_as_trusted_context(self):
        self.bind()
        response = await self.invoke()
        self.assertEqual(
            self.service.calls,
            [(ROOM, CALLER, payload())],
        )
        self.assertEqual(
            json.loads(response)["accepted_operation_ids"],
            ["op-1"],
        )

    async def test_payload_actor_cannot_spoof_provider_caller_identity(self):
        self.bind()
        wire = payload(actor_id="other-teacher")
        with self.assertRaises(FakeRpcError) as raised:
            await self.invoke(caller=CALLER, wire=wire)
        self.assert_rpc_error(
            raised.exception,
            "moderation actor does not match trusted caller",
        )
        self.assertEqual(self.service.calls[-1], (ROOM, CALLER, wire))

    async def test_payload_room_cannot_spoof_bound_room_identity(self):
        self.bind()
        wire = payload(room_id="room-other")
        with self.assertRaises(FakeRpcError) as raised:
            await self.invoke(wire=wire)
        self.assert_rpc_error(
            raised.exception,
            "moderation RPC room identity mismatch",
        )
        self.assertEqual(self.service.calls[-1][0], ROOM)

    async def test_transport_rejects_invalid_provider_caller_before_core(self):
        self.bind()
        for caller in ("", " teacher", "teacher name", "x" * 129, None, 7):
            with self.subTest(caller=repr(caller)[:40]):
                with self.assertRaises(FakeRpcError) as raised:
                    await self.invoke(caller=caller)
                self.assert_rpc_error(
                    raised.exception,
                    "moderation caller identity is invalid",
                )
        self.assertEqual(self.service.calls, [])

    async def test_transport_rejects_bad_payload_shape_and_size_before_core(self):
        self.bind()
        bad_values = (
            None,
            b"{}",
            "",
            "x" * (MAX_RPC_PAYLOAD_BYTES + 1),
            "\ud800",
        )
        for wire in bad_values:
            with self.subTest(wire=repr(wire)[:40]):
                with self.assertRaises(FakeRpcError) as raised:
                    await self.invoke(wire=wire)
                self.assertEqual(raised.exception.code, MODERATION_RPC_ERROR_CODE)
        self.assertEqual(self.service.calls, [])

    async def test_safe_core_error_is_transmitted_without_data(self):
        class RejectingService:
            async def handle_rpc(self, **kwargs):
                raise ClassroomModerationRpcError(
                    "moderation request is not authorized"
                )

        self.bind(service=RejectingService())
        with self.assertRaises(FakeRpcError) as raised:
            await self.invoke()
        self.assert_rpc_error(
            raised.exception,
            "moderation request is not authorized",
        )

    async def test_oversized_or_control_core_error_falls_back_to_generic_wire_error(self):
        for message in (
            "x" * (MAX_RPC_ERROR_MESSAGE_BYTES + 1),
            "bad\nwire",
        ):
            class RejectingService:
                async def handle_rpc(self, **kwargs):
                    raise ClassroomModerationRpcError(message)

            participant = FakeParticipant()
            transport = self.bind(
                local_participant=participant,
                service=RejectingService(),
            )
            handler = participant.handlers[MODERATION_RPC_METHOD]
            with self.subTest(message=repr(message)[:30]):
                with self.assertRaises(FakeRpcError) as raised:
                    await handler(
                        SimpleNamespace(
                            caller_identity=CALLER,
                            payload=payload(),
                        )
                    )
                self.assert_rpc_error(
                    raised.exception,
                    "moderation request failed",
                )
            transport.close()

    async def test_unexpected_service_failure_is_sanitized_and_has_no_cause(self):
        secret = "private-provider-or-ledger-detail"
        self.service.unexpected_error = RuntimeError(secret)
        self.bind()

        with self.assertRaises(FakeRpcError) as raised:
            await self.invoke()

        self.assert_rpc_error(raised.exception, "moderation request failed")
        rendered = "".join(traceback.format_exception(raised.exception))
        self.assertNotIn(secret, rendered)
        self.assertIsNone(raised.exception.__cause__)

    async def test_bad_service_response_is_rejected_on_wire_boundary(self):
        self.bind()
        for response in (
            None,
            "",
            b"{}",
            "x" * (MAX_RPC_PAYLOAD_BYTES + 1),
            "\ud800",
        ):
            with self.subTest(response=repr(response)[:40]):
                self.service.response_override = response
                with self.assertRaises(FakeRpcError) as raised:
                    await self.invoke()
                self.assert_rpc_error(
                    raised.exception,
                    "moderation acknowledgement is invalid",
                )

    def test_second_binding_cannot_clobber_same_participant_method(self):
        first = self.bind()
        original = self.participant.handlers[MODERATION_RPC_METHOD]

        with self.assertRaisesRegex(
            LiveKitModerationRpcTransportError,
            "already bound",
        ):
            LiveKitModerationRpcTransport.bind(
                local_participant=self.participant,
                trusted_room_id=ROOM,
                moderation_participant_identity=SERVICE_ID,
                service=ParsingService(),
                rtc_module=FakeRtc,
                sdk_version=LIVEKIT_RTC_VERSION,
            )

        self.assertIs(
            self.participant.handlers[MODERATION_RPC_METHOD],
            original,
        )
        self.assertEqual(len(self.participant.register_calls), 1)
        self.assertIs(first, self.transport)

    def test_registration_failure_releases_local_claim_for_retry(self):
        self.participant.register_error = RuntimeError("provider register detail")
        with self.assertRaisesRegex(
            LiveKitModerationRpcTransportError,
            "registration failed",
        ) as raised:
            self.bind()
        self.assertIsNone(raised.exception.__cause__)

        self.participant.register_error = None
        transport = self.bind()
        self.assertIn(MODERATION_RPC_METHOD, self.participant.handlers)
        self.assertIs(transport, self.transport)

    def test_close_unregisters_exact_method_once_and_is_idempotent(self):
        transport = self.bind()
        transport.close()
        transport.close()
        self.assertTrue(transport.closed)
        self.assertEqual(
            self.participant.unregister_calls,
            [MODERATION_RPC_METHOD],
        )
        self.assertNotIn(MODERATION_RPC_METHOD, self.participant.handlers)

    async def test_captured_handler_fails_closed_after_transport_close(self):
        transport = self.bind()
        handler = self.participant.handlers[MODERATION_RPC_METHOD]
        transport.close()

        with self.assertRaises(FakeRpcError) as raised:
            await handler(
                SimpleNamespace(caller_identity=CALLER, payload=payload())
            )
        self.assert_rpc_error(
            raised.exception,
            "moderation RPC transport is unavailable",
        )
        self.assertEqual(self.service.calls, [])

    def test_unregister_failure_keeps_transport_bound_for_safe_retry(self):
        transport = self.bind()
        self.participant.unregister_error = RuntimeError(
            "provider unregister detail"
        )

        with self.assertRaisesRegex(
            LiveKitModerationRpcTransportError,
            "unregister failed",
        ) as raised:
            transport.close()
        self.assertIsNone(raised.exception.__cause__)
        self.assertFalse(transport.closed)

        transport.close()
        self.assertTrue(transport.closed)
        self.assertEqual(
            self.participant.unregister_calls,
            [MODERATION_RPC_METHOD, MODERATION_RPC_METHOD],
        )

    def test_bind_validates_trusted_room_service_identity_and_sdk_before_registration(self):
        cases = (
            {"trusted_room_id": " room"},
            {"moderation_participant_identity": "wrong-service"},
            {"service": object()},
            {"sdk_version": "1.1.18"},
        )
        for overrides in cases:
            participant = FakeParticipant()
            overrides = dict(overrides)
            overrides.setdefault("local_participant", participant)
            if "moderation_participant_identity" not in overrides:
                overrides["moderation_participant_identity"] = SERVICE_ID
            if "trusted_room_id" not in overrides:
                overrides["trusted_room_id"] = ROOM
            if "service" not in overrides:
                overrides["service"] = ParsingService()
            overrides["rtc_module"] = FakeRtc
            overrides.setdefault("sdk_version", LIVEKIT_RTC_VERSION)
            with self.subTest(overrides=overrides):
                with self.assertRaises(LiveKitModerationRpcTransportError):
                    LiveKitModerationRpcTransport.bind(**overrides)
                self.assertEqual(participant.register_calls, [])

    def test_incomplete_participant_rpc_api_fails_before_registration(self):
        participant = SimpleNamespace(identity=SERVICE_ID)
        with self.assertRaisesRegex(
            LiveKitModerationRpcTransportError,
            "participant RPC API is unavailable",
        ):
            self.bind(local_participant=participant)

    def test_canonical_method_matches_browser_livekit_adapter(self):
        source = (
            Path(__file__).parents[1]
            / "web"
            / "livekit_classroom_media.js"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'const DEFAULT_MODERATION_METHOD = "'
            + MODERATION_RPC_METHOD
            + '";',
            source,
        )


if __name__ == "__main__":
    unittest.main()
