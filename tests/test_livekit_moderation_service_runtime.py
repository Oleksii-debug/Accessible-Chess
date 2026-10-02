from __future__ import annotations

import json
import traceback
from types import SimpleNamespace
import unittest

from acs.livekit_moderation_rpc_transport import (
    LIVEKIT_RTC_VERSION,
    MODERATION_RPC_METHOD,
)
from acs.livekit_moderation_service_runtime import (
    LiveKitModerationServiceRuntime,
    LiveKitModerationServiceRuntimeError,
    MAX_LIVEKIT_REALTIME_URL_CHARS,
    MAX_MODERATION_SERVICE_TOKEN_CHARS,
)


ROOM = "room-1"
SERVICE_ID = "moderation-service"
TOKEN = "header.payload.signature"


class FakeRpcError(Exception):
    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class FakeRoomOptions:
    def __init__(self, *, auto_subscribe=True):
        self.auto_subscribe = auto_subscribe


class FakeParticipant:
    def __init__(self, identity):
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

    def unregister_rpc_method(self, method):
        self.unregister_calls.append(method)
        if self.unregister_error is not None:
            error = self.unregister_error
            self.unregister_error = None
            raise error
        self.handlers.pop(method, None)


class FakeRoom:
    instances = []
    next_name = ROOM
    next_identity = SERVICE_ID
    next_connect_error = None
    next_disconnect_error = None

    def __init__(self):
        self.name = self.next_name
        self.local_participant = FakeParticipant(self.next_identity)
        self.connected = False
        self.connect_calls = []
        self.disconnect_calls = 0
        self.connect_error = self.next_connect_error
        self.disconnect_error = self.next_disconnect_error
        type(self).instances.append(self)

    async def connect(self, url, token, *, options=None):
        self.connect_calls.append((url, token, options))
        if self.connect_error is not None:
            error = self.connect_error
            self.connect_error = None
            raise error
        self.connected = True

    async def disconnect(self):
        self.disconnect_calls += 1
        if self.disconnect_error is not None:
            error = self.disconnect_error
            self.disconnect_error = None
            raise error
        self.connected = False

    def isconnected(self):
        return self.connected


class FakeRtc:
    Room = FakeRoom
    RoomOptions = FakeRoomOptions
    RpcError = FakeRpcError


class EchoModerationService:
    def __init__(self):
        self.calls = []
        self.error = None

    async def handle_rpc(
        self,
        *,
        trusted_room_id,
        trusted_caller_identity,
        payload,
    ):
        self.calls.append((trusted_room_id, trusted_caller_identity, payload))
        if self.error is not None:
            raise self.error
        return json.dumps(
            {
                "version": 1,
                "status": "ok",
                "accepted_operation_ids": ["op-1"],
            },
            separators=(",", ":"),
        )


class LiveKitModerationServiceRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        FakeRoom.instances.clear()
        FakeRoom.next_name = ROOM
        FakeRoom.next_identity = SERVICE_ID
        FakeRoom.next_connect_error = None
        FakeRoom.next_disconnect_error = None
        self.service = EchoModerationService()

    def runtime(self, **overrides):
        values = {
            "provider_url": "wss://classroom.example.invalid",
            "trusted_room_id": ROOM,
            "moderation_participant_identity": SERVICE_ID,
            "service": self.service,
            "rtc_module": FakeRtc,
            "sdk_version": LIVEKIT_RTC_VERSION,
        }
        values.update(overrides)
        return LiveKitModerationServiceRuntime(**values)

    async def connect(self, runtime=None, *, token=TOKEN):
        runtime = runtime or self.runtime()
        await runtime.connect(service_token=token)
        return runtime

    async def test_connects_exact_room_without_subscribing_and_binds_rpc(self):
        runtime = await self.connect()
        room = FakeRoom.instances[-1]
        participant = room.local_participant

        self.assertTrue(runtime.connected)
        self.assertTrue(runtime.ready)
        self.assertFalse(runtime.closed)
        self.assertFalse(runtime.cleanup_required)
        self.assertEqual(len(room.connect_calls), 1)
        url, token, options = room.connect_calls[0]
        self.assertEqual(url, "wss://classroom.example.invalid")
        self.assertEqual(token, TOKEN)
        self.assertIs(type(options), FakeRoomOptions)
        self.assertFalse(options.auto_subscribe)
        self.assertIn(MODERATION_RPC_METHOD, participant.handlers)
        self.assertEqual(runtime.moderation_transport.method, MODERATION_RPC_METHOD)

        handler = participant.handlers[MODERATION_RPC_METHOD]
        response = await handler(
            SimpleNamespace(
                caller_identity="teacher-1",
                payload=json.dumps(
                    {
                        "version": 1,
                        "room_id": ROOM,
                        "operations": [
                            {
                                "operation_id": "op-1",
                                "actor_id": "teacher-1",
                                "target_id": "student-1",
                                "action": "publish_permission",
                                "source": "microphone",
                                "value": False,
                            }
                        ],
                    },
                    separators=(",", ":"),
                ),
            )
        )
        self.assertEqual(json.loads(response)["accepted_operation_ids"], ["op-1"])
        self.assertEqual(self.service.calls[-1][0:2], (ROOM, "teacher-1"))

        await runtime.aclose()
        self.assertTrue(runtime.closed)
        self.assertFalse(runtime.ready)
        self.assertEqual(participant.unregister_calls, [MODERATION_RPC_METHOD])
        self.assertEqual(room.disconnect_calls, 1)

    async def test_wrapper_does_not_copy_or_render_service_token_or_context(self):
        secret = "very-secret-token.payload.signature"
        runtime = await self.connect(token=secret)
        rendered = repr(runtime)
        self.assertNotIn(secret, rendered)
        self.assertNotIn("classroom.example.invalid", rendered)
        self.assertNotIn(ROOM, rendered)
        self.assertNotIn(SERVICE_ID, rendered)
        self.assertNotIn("_token", runtime.__slots__)
        self.assertIn("token=<redacted>", rendered)
        room = FakeRoom.instances[-1]
        await runtime.aclose()
        self.assertIsNone(runtime._room)
        self.assertFalse(room.connected)

    def test_constructor_rejects_untrusted_urls_identity_and_bad_sdk(self):
        invalid_urls = (
            "",
            " wss://classroom.example.invalid",
            "wss://user:secret@classroom.example.invalid",
            "wss://classroom.example.invalid/path",
            "wss://classroom.example.invalid?token=x",
            "wss://classroom.example.invalid#fragment",
            "ws://classroom.example.invalid",
            "https://classroom.example.invalid",
            "wss://class room.example.invalid",
            "wss://classroom.example.invalid:" ,
            "wss://" + "x" * MAX_LIVEKIT_REALTIME_URL_CHARS,
        )
        for value in invalid_urls:
            with self.subTest(value=repr(value)[:80]):
                with self.assertRaises(LiveKitModerationServiceRuntimeError):
                    self.runtime(provider_url=value)

        for value in (" room", "", "bad identity", "x" * 129):
            with self.subTest(identity=value):
                with self.assertRaises(LiveKitModerationServiceRuntimeError):
                    self.runtime(trusted_room_id=value)

        with self.assertRaisesRegex(
            LiveKitModerationServiceRuntimeError,
            "version is not approved",
        ):
            self.runtime(sdk_version="1.1.18")
        with self.assertRaisesRegex(
            LiveKitModerationServiceRuntimeError,
            "service is unavailable",
        ):
            self.runtime(service=object())

    def test_loopback_ws_is_allowed_for_explicit_local_development(self):
        for value in (
            "ws://localhost:7880",
            "ws://127.0.0.1:7880",
            "ws://[::1]:7880",
        ):
            with self.subTest(value=value):
                runtime = self.runtime(provider_url=value)
                self.assertFalse(runtime.closed)

    async def test_invalid_token_fails_before_any_provider_connect(self):
        runtime = self.runtime()
        invalid = (
            "",
            " token",
            "token ",
            "token with space",
            "token\nvalue",
            "x" * (MAX_MODERATION_SERVICE_TOKEN_CHARS + 1),
            None,
            7,
        )
        for value in invalid:
            with self.subTest(value=repr(value)[:50]):
                with self.assertRaisesRegex(
                    LiveKitModerationServiceRuntimeError,
                    "token is invalid",
                ):
                    await runtime.connect(service_token=value)
        self.assertEqual(FakeRoom.instances[-1].connect_calls, [])
        self.assertFalse(runtime.closed)

    async def test_connect_failure_is_sanitized_and_closes_one_shot_runtime(self):
        secret = "provider-connect-secret"
        FakeRoom.next_connect_error = RuntimeError(secret)
        runtime = self.runtime()

        with self.assertRaisesRegex(
            LiveKitModerationServiceRuntimeError,
            "^LiveKit moderation service connection failed$",
        ) as caught:
            await runtime.connect(service_token=TOKEN)

        room = FakeRoom.instances[-1]
        self.assertTrue(runtime.closed)
        self.assertFalse(runtime.cleanup_required)
        self.assertEqual(room.disconnect_calls, 1)
        self.assertNotIn(secret, "".join(traceback.format_exception(caught.exception)))
        self.assertIsNone(caught.exception.__cause__)

    async def test_room_identity_mismatch_disconnects_before_failing(self):
        FakeRoom.next_name = "wrong-room"
        runtime = self.runtime()

        with self.assertRaisesRegex(
            LiveKitModerationServiceRuntimeError,
            "^LiveKit moderation service room identity mismatch$",
        ):
            await runtime.connect(service_token=TOKEN)

        room = FakeRoom.instances[-1]
        self.assertTrue(runtime.closed)
        self.assertFalse(runtime.ready)
        self.assertFalse(room.connected)
        self.assertEqual(room.disconnect_calls, 1)
        self.assertEqual(room.local_participant.register_calls, [])

    async def test_participant_identity_mismatch_disconnects_before_binding(self):
        FakeRoom.next_identity = "wrong-service"
        runtime = self.runtime()

        with self.assertRaisesRegex(
            LiveKitModerationServiceRuntimeError,
            "^LiveKit moderation service participant identity mismatch$",
        ):
            await runtime.connect(service_token=TOKEN)

        room = FakeRoom.instances[-1]
        self.assertTrue(runtime.closed)
        self.assertFalse(room.connected)
        self.assertEqual(room.local_participant.register_calls, [])

    async def test_rpc_bind_failure_disconnects_and_sanitizes_provider_detail(self):
        secret = "provider-register-secret"
        runtime = self.runtime()
        room = FakeRoom.instances[-1]
        room.local_participant.register_error = RuntimeError(secret)

        with self.assertRaisesRegex(
            LiveKitModerationServiceRuntimeError,
            "^LiveKit moderation service RPC binding failed$",
        ) as caught:
            await runtime.connect(service_token=TOKEN)

        self.assertTrue(runtime.closed)
        self.assertFalse(room.connected)
        self.assertEqual(room.disconnect_calls, 1)
        self.assertNotIn(secret, "".join(traceback.format_exception(caught.exception)))
        self.assertIsNone(caught.exception.__cause__)

    async def test_failed_connect_cleanup_retains_retryable_room_handle(self):
        secret = "provider-disconnect-secret"
        FakeRoom.next_name = "wrong-room"
        FakeRoom.next_disconnect_error = RuntimeError(secret)
        runtime = self.runtime()

        with self.assertRaisesRegex(
            LiveKitModerationServiceRuntimeError,
            "room identity mismatch; cleanup is required$",
        ) as caught:
            await runtime.connect(service_token=TOKEN)

        room = FakeRoom.instances[-1]
        self.assertFalse(runtime.closed)
        self.assertTrue(runtime.cleanup_required)
        self.assertFalse(runtime.ready)
        self.assertTrue(room.connected)
        self.assertIn("state='cleanup_required'", repr(runtime))
        self.assertNotIn(secret, "".join(traceback.format_exception(caught.exception)))

        await runtime.aclose()
        self.assertTrue(runtime.closed)
        self.assertFalse(runtime.cleanup_required)
        self.assertFalse(room.connected)
        self.assertEqual(room.disconnect_calls, 2)

    async def test_unregister_failure_disconnects_network_and_retains_cleanup_owner(self):
        runtime = await self.connect()
        room = FakeRoom.instances[-1]
        participant = room.local_participant
        participant.unregister_error = RuntimeError("private unregister detail")

        with self.assertRaisesRegex(
            LiveKitModerationServiceRuntimeError,
            "^LiveKit moderation service cleanup failed$",
        ):
            await runtime.aclose()

        self.assertFalse(runtime.closed)
        self.assertTrue(runtime.cleanup_required)
        self.assertFalse(runtime.ready)
        self.assertFalse(room.connected)
        self.assertEqual(room.disconnect_calls, 1)
        self.assertIn(MODERATION_RPC_METHOD, participant.handlers)

        await runtime.aclose()
        self.assertTrue(runtime.closed)
        self.assertFalse(runtime.cleanup_required)
        self.assertNotIn(MODERATION_RPC_METHOD, participant.handlers)
        self.assertEqual(participant.unregister_calls, [MODERATION_RPC_METHOD] * 2)

    async def test_disconnect_failure_after_unbind_is_retryable_and_fail_closed(self):
        runtime = await self.connect()
        room = FakeRoom.instances[-1]
        room.disconnect_error = RuntimeError("private disconnect detail")

        with self.assertRaisesRegex(
            LiveKitModerationServiceRuntimeError,
            "^LiveKit moderation service cleanup failed$",
        ):
            await runtime.aclose()

        self.assertFalse(runtime.closed)
        self.assertTrue(runtime.cleanup_required)
        self.assertFalse(runtime.ready)
        self.assertTrue(room.connected)
        self.assertNotIn(MODERATION_RPC_METHOD, room.local_participant.handlers)

        await runtime.aclose()
        self.assertTrue(runtime.closed)
        self.assertFalse(runtime.cleanup_required)
        self.assertFalse(room.connected)
        self.assertEqual(room.disconnect_calls, 2)

    async def test_external_disconnect_makes_runtime_not_ready(self):
        runtime = await self.connect()
        room = FakeRoom.instances[-1]
        room.connected = False

        self.assertFalse(runtime.connected)
        self.assertFalse(runtime.ready)
        with self.assertRaisesRegex(
            LiveKitModerationServiceRuntimeError,
            "runtime is not ready",
        ):
            _ = runtime.moderation_transport

        await runtime.aclose()
        self.assertTrue(runtime.closed)

    async def test_second_connect_and_use_before_connect_fail_closed(self):
        runtime = self.runtime()
        with self.assertRaisesRegex(
            LiveKitModerationServiceRuntimeError,
            "runtime is not ready",
        ):
            _ = runtime.moderation_transport

        await runtime.connect(service_token=TOKEN)
        with self.assertRaisesRegex(
            LiveKitModerationServiceRuntimeError,
            "already connected",
        ):
            await runtime.connect(service_token=TOKEN)
        await runtime.aclose()

    async def test_context_manager_requires_ready_and_closes_exact_runtime(self):
        runtime = self.runtime()
        with self.assertRaisesRegex(
            LiveKitModerationServiceRuntimeError,
            "runtime is not ready",
        ):
            await runtime.__aenter__()

        await runtime.connect(service_token=TOKEN)
        async with runtime as entered:
            self.assertIs(entered, runtime)
            self.assertTrue(entered.ready)
        self.assertTrue(runtime.closed)

    def test_missing_room_api_fails_before_room_construction(self):
        class BadRtc:
            RpcError = FakeRpcError

        with self.assertRaisesRegex(
            LiveKitModerationServiceRuntimeError,
            "room API is unavailable",
        ):
            self.runtime(rtc_module=BadRtc)


if __name__ == "__main__":
    unittest.main()
