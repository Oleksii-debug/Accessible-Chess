from __future__ import annotations

import asyncio
import json
import traceback
import unittest

from acs.classroom_moderation_rpc import (
    ClassroomModerationRpcError,
    ClassroomModerationRpcService,
    MAX_RPC_OPERATIONS,
    MAX_RPC_PAYLOAD_BYTES,
    RPC_VERSION,
    parse_moderation_rpc,
)
from acs.classroom_realtime_media import MediaSource, ModerationAction


ROOM = "room-1"
CALLER = "teacher-1"


def operation(
    operation_id: str,
    *,
    action: str = "publish_permission",
    target_id: str = "student-1",
    source: str | None = "microphone",
    value: bool = False,
    actor_id: str = CALLER,
) -> dict[str, object]:
    return {
        "operation_id": operation_id,
        "actor_id": actor_id,
        "target_id": target_id,
        "action": action,
        "source": source,
        "value": value,
    }


def payload(*operations: dict[str, object], room_id: str = ROOM) -> str:
    return json.dumps(
        {
            "version": RPC_VERSION,
            "room_id": room_id,
            "operations": list(operations),
        },
        separators=(",", ":"),
    )


class FakeAuthorization:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, tuple[object, ...]]] = []
        self.reject = False

    def authorize_moderation_batch(self, *, room_id, caller_identity, commands):
        self.calls.append((room_id, caller_identity, commands))
        if self.reject:
            raise RuntimeError("sensitive roster authorization detail")


class FakeProviderAdmin:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.fail_once: set[str] = set()
        self.yield_before_apply = False

    async def apply_moderation_command(self, *, room_id, command):
        if self.yield_before_apply:
            await asyncio.sleep(0)
        self.calls.append((room_id, command))
        if command.operation_id in self.fail_once:
            self.fail_once.remove(command.operation_id)
            raise RuntimeError("sensitive provider implementation detail")


class FakeLedger:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.read_calls: list[tuple[str, str]] = []
        self.commit_calls: list[tuple[str, str, str]] = []
        self.fail_read = False
        self.fail_commit_for: set[str] = set()

    def committed_fingerprint(self, *, room_id, operation_id):
        self.read_calls.append((room_id, operation_id))
        if self.fail_read:
            raise RuntimeError("sensitive ledger read detail")
        return self.values.get((room_id, operation_id))

    def commit(self, *, room_id, operation_id, fingerprint):
        self.commit_calls.append((room_id, operation_id, fingerprint))
        if operation_id in self.fail_commit_for:
            raise RuntimeError("sensitive ledger commit detail")
        key = (room_id, operation_id)
        existing = self.values.get(key)
        if existing is not None and existing != fingerprint:
            raise RuntimeError("conflicting commit")
        self.values[key] = fingerprint


class ClassroomModerationRpcTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.authorization = FakeAuthorization()
        self.provider = FakeProviderAdmin()
        self.ledger = FakeLedger()
        self.service = ClassroomModerationRpcService(
            authorization=self.authorization,
            provider_admin=self.provider,
            ledger=self.ledger,
        )

    async def handle(self, wire_payload: object) -> str:
        return await self.service.handle_rpc(
            trusted_room_id=ROOM,
            trusted_caller_identity=CALLER,
            payload=wire_payload,
        )

    def assert_sanitized_exception(self, error: BaseException, secret: str) -> None:
        self.assertIsNone(error.__cause__)
        rendered = "".join(traceback.format_exception(error))
        self.assertNotIn(secret, rendered)

    def test_parser_matches_livekit_client_wire_contract(self) -> None:
        parsed = parse_moderation_rpc(
            payload(
                operation(
                    "op-publish",
                    source="camera",
                    value=False,
                ),
                operation(
                    "op-soft",
                    action="soft_mute",
                    source="microphone",
                    value=True,
                ),
                operation(
                    "op-remove",
                    action="remove",
                    source=None,
                    value=True,
                ),
            ),
            trusted_room_id=ROOM,
            trusted_caller_identity=CALLER,
        )
        self.assertEqual(parsed.room_id, ROOM)
        self.assertEqual(
            tuple(command.operation_id for command in parsed.commands),
            ("op-publish", "op-soft", "op-remove"),
        )
        self.assertIs(parsed.commands[0].action, ModerationAction.PUBLISH_PERMISSION)
        self.assertIs(parsed.commands[0].source, MediaSource.CAMERA)
        self.assertIs(parsed.commands[1].action, ModerationAction.SOFT_MUTE)
        self.assertIs(parsed.commands[1].source, MediaSource.MICROPHONE)
        self.assertIs(parsed.commands[2].action, ModerationAction.REMOVE)
        self.assertIsNone(parsed.commands[2].source)
        self.assertEqual(len(set(parsed.fingerprints)), 3)

    async def test_valid_batch_authorizes_before_provider_effects_and_exactly_acks(self) -> None:
        wire = payload(
            operation("op-1", source="camera", value=False),
            operation(
                "op-2",
                action="soft_mute",
                source="microphone",
                value=True,
                target_id="student-2",
            ),
            operation(
                "op-3",
                action="remove",
                source=None,
                value=False,
                target_id="observer-1",
            ),
        )
        response = await self.handle(wire)

        self.assertEqual(len(self.authorization.calls), 1)
        authorized = self.authorization.calls[0][2]
        self.assertEqual(
            tuple(command.operation_id for command in authorized),
            ("op-1", "op-2", "op-3"),
        )
        self.assertEqual(
            [command.operation_id for _, command in self.provider.calls],
            ["op-1", "op-2", "op-3"],
        )
        self.assertEqual(len(self.ledger.values), 3)
        self.assertEqual(
            json.loads(response),
            {
                "version": 1,
                "status": "ok",
                "accepted_operation_ids": ["op-1", "op-2", "op-3"],
            },
        )
        self.assertLessEqual(len(response.encode("utf-8")), MAX_RPC_PAYLOAD_BYTES)

    async def test_exact_replay_is_acknowledged_without_reauthorization_or_reapply(self) -> None:
        wire = payload(operation("op-replay", source="microphone", value=False))

        first = await self.handle(wire)
        second = await self.handle(wire)

        self.assertEqual(first, second)
        self.assertEqual(len(self.authorization.calls), 1)
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(len(self.ledger.commit_calls), 1)

    async def test_same_operation_id_with_different_semantics_fails_before_effect(self) -> None:
        await self.handle(payload(operation("op-stable", value=False)))
        before_auth = len(self.authorization.calls)
        before_provider = len(self.provider.calls)

        with self.assertRaisesRegex(
            ClassroomModerationRpcError,
            "reused with different semantics",
        ):
            await self.handle(payload(operation("op-stable", value=True)))

        self.assertEqual(len(self.authorization.calls), before_auth)
        self.assertEqual(len(self.provider.calls), before_provider)

    async def test_authorization_failure_is_sanitized_and_has_zero_provider_effects(self) -> None:
        self.authorization.reject = True

        with self.assertRaises(ClassroomModerationRpcError) as raised:
            await self.handle(payload(operation("op-denied")))

        self.assertEqual(str(raised.exception), "moderation request is not authorized")
        self.assertNotIn("sensitive", str(raised.exception).lower())
        self.assert_sanitized_exception(
            raised.exception,
            "sensitive roster authorization detail",
        )
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(self.ledger.values, {})

    async def test_partial_provider_failure_commits_prefix_then_retry_resumes_only_remainder(self) -> None:
        wire = payload(
            operation("op-prefix", source="camera", value=False),
            operation("op-fails-once", source="microphone", value=False),
            operation(
                "op-tail",
                action="soft_mute",
                source="microphone",
                value=True,
                target_id="student-2",
            ),
        )
        self.provider.fail_once.add("op-fails-once")

        with self.assertRaisesRegex(
            ClassroomModerationRpcError,
            "provider operation failed",
        ) as provider_error:
            await self.handle(wire)
        self.assert_sanitized_exception(
            provider_error.exception,
            "sensitive provider implementation detail",
        )

        self.assertIn((ROOM, "op-prefix"), self.ledger.values)
        self.assertNotIn((ROOM, "op-fails-once"), self.ledger.values)
        self.assertNotIn((ROOM, "op-tail"), self.ledger.values)
        self.assertEqual(
            [command.operation_id for _, command in self.provider.calls],
            ["op-prefix", "op-fails-once"],
        )

        response = await self.handle(wire)

        self.assertEqual(
            [command.operation_id for _, command in self.provider.calls],
            ["op-prefix", "op-fails-once", "op-fails-once", "op-tail"],
        )
        self.assertEqual(
            tuple(command.operation_id for command in self.authorization.calls[-1][2]),
            ("op-fails-once", "op-tail"),
        )
        self.assertEqual(len(self.ledger.values), 3)
        self.assertEqual(
            json.loads(response)["accepted_operation_ids"],
            ["op-prefix", "op-fails-once", "op-tail"],
        )

    async def test_concurrent_exact_duplicates_apply_once_within_service_participant(self) -> None:
        self.provider.yield_before_apply = True
        wire = payload(operation("op-race", source="camera", value=False))

        first, second = await asyncio.gather(
            self.handle(wire),
            self.handle(wire),
        )

        self.assertEqual(first, second)
        self.assertEqual(len(self.authorization.calls), 1)
        self.assertEqual(
            [command.operation_id for _, command in self.provider.calls],
            ["op-race"],
        )
        self.assertEqual(len(self.ledger.commit_calls), 1)

    async def test_ledger_failures_are_sanitized(self) -> None:
        self.ledger.fail_read = True
        with self.assertRaises(ClassroomModerationRpcError) as read_error:
            await self.handle(payload(operation("op-read")))
        self.assertEqual(
            str(read_error.exception),
            "moderation replay ledger read failed",
        )
        self.assert_sanitized_exception(
            read_error.exception,
            "sensitive ledger read detail",
        )
        self.assertEqual(self.authorization.calls, [])
        self.assertEqual(self.provider.calls, [])

        self.ledger.fail_read = False
        self.ledger.fail_commit_for.add("op-commit")
        with self.assertRaises(ClassroomModerationRpcError) as commit_error:
            await self.handle(payload(operation("op-commit")))
        self.assertEqual(
            str(commit_error.exception),
            "moderation replay ledger commit failed",
        )
        self.assert_sanitized_exception(
            commit_error.exception,
            "sensitive ledger commit detail",
        )
        self.assertEqual(len(self.provider.calls), 1)
        self.assertNotIn((ROOM, "op-commit"), self.ledger.values)

    def test_spoofed_or_malformed_payloads_fail_closed(self) -> None:
        valid = operation("op-good")
        malformed: tuple[tuple[str, object, str, str], ...] = (
            ("room mismatch", payload(valid, room_id="room-2"), ROOM, CALLER),
            (
                "actor mismatch",
                payload(operation("op-actor", actor_id="student-1")),
                ROOM,
                CALLER,
            ),
            (
                "unknown envelope field",
                json.dumps(
                    {
                        "version": 1,
                        "room_id": ROOM,
                        "operations": [valid],
                        "extra": True,
                    }
                ),
                ROOM,
                CALLER,
            ),
            (
                "boolean version",
                json.dumps(
                    {
                        "version": True,
                        "room_id": ROOM,
                        "operations": [valid],
                    }
                ),
                ROOM,
                CALLER,
            ),
            (
                "empty batch",
                payload(),
                ROOM,
                CALLER,
            ),
            (
                "duplicate operation ids",
                payload(operation("dup"), operation("dup", target_id="student-2")),
                ROOM,
                CALLER,
            ),
            (
                "unknown operation field",
                json.dumps(
                    {
                        "version": 1,
                        "room_id": ROOM,
                        "operations": [{**valid, "extra": "x"}],
                    }
                ),
                ROOM,
                CALLER,
            ),
            (
                "soft mute wrong source",
                payload(
                    operation(
                        "op-soft-camera",
                        action="soft_mute",
                        source="camera",
                        value=True,
                    )
                ),
                ROOM,
                CALLER,
            ),
            (
                "remove carries source",
                payload(
                    operation(
                        "op-remove-source",
                        action="remove",
                        source="microphone",
                        value=False,
                    )
                ),
                ROOM,
                CALLER,
            ),
            (
                "non boolean value",
                payload(operation("op-bool", value=1)),
                ROOM,
                CALLER,
            ),
            (
                "invalid trusted caller",
                payload(valid),
                ROOM,
                " caller ",
            ),
            (
                "invalid trusted room",
                payload(valid),
                "room with spaces",
                CALLER,
            ),
        )
        for name, wire, trusted_room, caller in malformed:
            with self.subTest(name=name):
                with self.assertRaises(ClassroomModerationRpcError):
                    parse_moderation_rpc(
                        wire,
                        trusted_room_id=trusted_room,
                        trusted_caller_identity=caller,
                    )

    def test_payload_size_and_batch_limits_fail_closed(self) -> None:
        with self.assertRaisesRegex(
            ClassroomModerationRpcError,
            "payload size",
        ):
            parse_moderation_rpc(
                "x" * (MAX_RPC_PAYLOAD_BYTES + 1),
                trusted_room_id=ROOM,
                trusted_caller_identity=CALLER,
            )

        many = [operation(f"o-{index}", target_id="s") for index in range(MAX_RPC_OPERATIONS + 1)]
        with self.assertRaises(ClassroomModerationRpcError):
            parse_moderation_rpc(
                payload(*many),
                trusted_room_id=ROOM,
                trusted_caller_identity=CALLER,
            )


if __name__ == "__main__":
    unittest.main()
