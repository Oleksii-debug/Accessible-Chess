from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
import traceback
import unittest

from acs.classroom_moderation_rpc import (
    ClassroomModerationRpcError,
    ClassroomModerationProviderStateVerifierPort,
    ClassroomModerationRpcService,
    ModerationOperationState,
    MAX_RPC_OPERATIONS,
    MAX_RPC_PAYLOAD_BYTES,
    RPC_VERSION,
    parse_moderation_rpc,
)
from acs.classroom_realtime_media import MediaSource, ModerationAction
from acs.sqlite_classroom_moderation_ledger import SqliteClassroomModerationLedger


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
        self.apply_started: asyncio.Event | None = None
        self.apply_continue: asyncio.Event | None = None

    async def apply_moderation_command(self, *, room_id, command):
        if self.apply_started is not None:
            self.apply_started.set()
        if self.apply_continue is not None:
            await self.apply_continue.wait()
        elif self.yield_before_apply:
            await asyncio.sleep(0)
        self.calls.append((room_id, command))
        if command.operation_id in self.fail_once:
            self.fail_once.remove(command.operation_id)
            raise RuntimeError("sensitive provider implementation detail")


class FakeProviderStateVerifier:
    def __init__(self) -> None:
        self.matches: object = True
        self.fail = False
        self.calls: list[tuple[str, object]] = []

    async def moderation_effect_matches(self, *, room_id, command):
        self.calls.append((room_id, command))
        if self.fail:
            raise RuntimeError("sensitive provider state detail")
        return self.matches


class FakeLedger:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.reservations: dict[tuple[str, str], tuple[str, str]] = {}
        self.read_calls: list[tuple[str, str]] = []
        self.reserve_calls: list[tuple[str, str, str, str]] = []
        self.commit_calls: list[tuple[str, str, str, str]] = []
        self.fail_read = False
        self.fail_reserve_for: set[str] = set()
        self.fail_commit_for: set[str] = set()

    def operation_state(self, *, room_id, operation_id):
        self.read_calls.append((room_id, operation_id))
        if self.fail_read:
            raise RuntimeError("sensitive ledger read detail")
        key = (room_id, operation_id)
        if key in self.values:
            return ModerationOperationState(
                fingerprint=self.values[key],
                committed=True,
            )
        if key in self.reservations:
            fingerprint, reservation_owner = self.reservations[key]
            return ModerationOperationState(
                fingerprint=fingerprint,
                committed=False,
                reservation_owner=reservation_owner,
            )
        return None

    def reserve(self, *, room_id, operation_id, fingerprint, reservation_owner):
        self.reserve_calls.append(
            (room_id, operation_id, fingerprint, reservation_owner)
        )
        if operation_id in self.fail_reserve_for:
            raise RuntimeError("sensitive ledger reservation detail")
        key = (room_id, operation_id)
        if key in self.values:
            return ModerationOperationState(
                fingerprint=self.values[key],
                committed=True,
            )
        existing = self.reservations.get(key)
        if existing is None:
            existing = (fingerprint, reservation_owner)
            self.reservations[key] = existing
        existing_fingerprint, existing_owner = existing
        return ModerationOperationState(
            fingerprint=existing_fingerprint,
            committed=False,
            reservation_owner=existing_owner,
        )

    def commit(
        self,
        *,
        room_id,
        operation_id,
        fingerprint,
        reservation_owner,
    ):
        self.commit_calls.append(
            (room_id, operation_id, fingerprint, reservation_owner)
        )
        if operation_id in self.fail_commit_for:
            raise RuntimeError("sensitive ledger commit detail")
        key = (room_id, operation_id)
        existing = self.values.get(key)
        if existing is not None:
            if existing != fingerprint:
                raise RuntimeError("conflicting committed fingerprint")
            return
        reserved = self.reservations.get(key)
        if reserved != (fingerprint, reservation_owner):
            raise RuntimeError("commit does not match owned reservation")
        del self.reservations[key]
        self.values[key] = fingerprint


class ClassroomModerationPendingRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.authorization = FakeAuthorization()
        self.original_provider = FakeProviderAdmin()
        self.restarted_provider = FakeProviderAdmin()
        self.ledger = FakeLedger()
        self.verifier = FakeProviderStateVerifier()
        self.original = ClassroomModerationRpcService(
            authorization=self.authorization,
            provider_admin=self.original_provider,
            ledger=self.ledger,
        )

    def command(self, operation_id: str = "op-recover", *, value: bool = False):
        return parse_moderation_rpc(
            payload(operation(operation_id, value=value)),
            trusted_room_id=ROOM,
            trusted_caller_identity=CALLER,
        ).commands[0]

    async def leave_ambiguous_pending(self, operation_id: str = "op-recover"):
        wire = payload(operation(operation_id))
        self.original_provider.fail_once.add(operation_id)
        with self.assertRaisesRegex(
            ClassroomModerationRpcError,
            "provider operation failed",
        ):
            await self.original.handle_rpc(
                trusted_room_id=ROOM,
                trusted_caller_identity=CALLER,
                payload=wire,
            )
        self.assertIn((ROOM, operation_id), self.ledger.reservations)
        self.assertNotIn((ROOM, operation_id), self.ledger.values)
        return wire

    def restarted(self, *, verifier=...):
        if verifier is ...:
            verifier = self.verifier
        return ClassroomModerationRpcService(
            authorization=FakeAuthorization(),
            provider_admin=self.restarted_provider,
            ledger=self.ledger,
            provider_state_verifier=verifier,
        )

    async def test_verified_provider_state_commits_ambiguous_pending_without_reapplying_effect(self) -> None:
        wire = await self.leave_ambiguous_pending()
        original_owner = self.ledger.reservations[(ROOM, "op-recover")][1]
        restarted = self.restarted()

        await restarted.reconcile_verified_pending(
            room_id=ROOM,
            command=self.command(),
        )

        self.assertEqual(len(self.verifier.calls), 1)
        self.assertEqual(self.restarted_provider.calls, [])
        self.assertNotIn((ROOM, "op-recover"), self.ledger.reservations)
        self.assertIn((ROOM, "op-recover"), self.ledger.values)
        self.assertIn(
            (ROOM, "op-recover", self.ledger.values[(ROOM, "op-recover")], original_owner),
            self.ledger.commit_calls,
        )

        response = await restarted.handle_rpc(
            trusted_room_id=ROOM,
            trusted_caller_identity=CALLER,
            payload=wire,
        )
        self.assertEqual(json.loads(response)["accepted_operation_ids"], ["op-recover"])
        self.assertEqual(self.restarted_provider.calls, [])

    async def test_exact_retry_after_restart_auto_reconciles_verified_pending(self) -> None:
        wire = await self.leave_ambiguous_pending()
        restarted = self.restarted()

        response = await restarted.handle_rpc(
            trusted_room_id=ROOM,
            trusted_caller_identity=CALLER,
            payload=wire,
        )

        self.assertEqual(
            json.loads(response)["accepted_operation_ids"],
            ["op-recover"],
        )
        self.assertEqual(len(self.verifier.calls), 1)
        self.assertEqual(self.restarted_provider.calls, [])
        self.assertNotIn((ROOM, "op-recover"), self.ledger.reservations)
        self.assertIn((ROOM, "op-recover"), self.ledger.values)

    async def test_unconfirmed_provider_state_remains_pending_and_fail_closed(self) -> None:
        wire = await self.leave_ambiguous_pending()
        pending_before = self.ledger.reservations[(ROOM, "op-recover")]
        self.verifier.matches = False
        restarted = self.restarted()

        with self.assertRaisesRegex(
            ClassroomModerationRpcError,
            "does not confirm pending operation",
        ):
            await restarted.reconcile_verified_pending(
                room_id=ROOM,
                command=self.command(),
            )

        self.assertEqual(
            self.ledger.reservations[(ROOM, "op-recover")],
            pending_before,
        )
        self.assertNotIn((ROOM, "op-recover"), self.ledger.values)
        self.assertEqual(self.restarted_provider.calls, [])
        with self.assertRaisesRegex(
            ClassroomModerationRpcError,
            "does not confirm pending operation",
        ):
            await restarted.handle_rpc(
                trusted_room_id=ROOM,
                trusted_caller_identity=CALLER,
                payload=wire,
            )

    async def test_conflicting_recovery_semantics_fail_before_provider_verification(self) -> None:
        await self.leave_ambiguous_pending()
        restarted = self.restarted()

        with self.assertRaisesRegex(
            ClassroomModerationRpcError,
            "reused with different semantics",
        ):
            await restarted.reconcile_verified_pending(
                room_id=ROOM,
                command=self.command(value=True),
            )

        self.assertEqual(self.verifier.calls, [])
        self.assertEqual(self.restarted_provider.calls, [])
        self.assertIn((ROOM, "op-recover"), self.ledger.reservations)

    async def test_recovery_requires_explicit_verifier_and_sanitizes_verifier_failure(self) -> None:
        await self.leave_ambiguous_pending()
        without_verifier = self.restarted(verifier=None)
        with self.assertRaisesRegex(
            ClassroomModerationRpcError,
            "state verification is unavailable",
        ):
            await without_verifier.reconcile_verified_pending(
                room_id=ROOM,
                command=self.command(),
            )

        self.verifier.fail = True
        restarted = self.restarted()
        with self.assertRaisesRegex(
            ClassroomModerationRpcError,
            "state verification failed",
        ) as context:
            await restarted.reconcile_verified_pending(
                room_id=ROOM,
                command=self.command(),
            )
        self.assertIsNone(context.exception.__cause__)
        self.assertNotIn(
            "sensitive provider state detail",
            "".join(traceback.format_exception(context.exception)),
        )
        self.assertIn((ROOM, "op-recover"), self.ledger.reservations)

    async def test_two_restarted_reconcilers_converge_without_provider_effect(self) -> None:
        await self.leave_ambiguous_pending()
        first_verifier = FakeProviderStateVerifier()
        second_verifier = FakeProviderStateVerifier()
        first_restarted = self.restarted(verifier=first_verifier)
        second_restarted = self.restarted(verifier=second_verifier)
        command = self.command()

        results = await asyncio.gather(
            first_restarted.reconcile_verified_pending(
                room_id=ROOM,
                command=command,
            ),
            second_restarted.reconcile_verified_pending(
                room_id=ROOM,
                command=command,
            ),
            return_exceptions=True,
        )

        self.assertEqual(results, [None, None])
        self.assertEqual(self.restarted_provider.calls, [])
        self.assertNotIn((ROOM, "op-recover"), self.ledger.reservations)
        self.assertIn((ROOM, "op-recover"), self.ledger.values)
        verifier_call_count = len(first_verifier.calls) + len(second_verifier.calls)
        self.assertGreaterEqual(verifier_call_count, 1)
        self.assertLessEqual(verifier_call_count, 2)

    async def test_committed_or_missing_recovery_never_queries_provider_state(self) -> None:
        command = self.command()
        restarted = self.restarted()
        with self.assertRaisesRegex(
            ClassroomModerationRpcError,
            "not pending recovery",
        ):
            await restarted.reconcile_verified_pending(
                room_id=ROOM,
                command=command,
            )
        self.assertEqual(self.verifier.calls, [])

        await self.leave_ambiguous_pending()
        await restarted.reconcile_verified_pending(
            room_id=ROOM,
            command=command,
        )
        verifier_calls = len(self.verifier.calls)
        await restarted.reconcile_verified_pending(
            room_id=ROOM,
            command=command,
        )
        self.assertEqual(len(self.verifier.calls), verifier_calls)
        self.assertEqual(self.restarted_provider.calls, [])

    async def test_real_sqlite_restart_reconciles_verified_pending_and_reopens_committed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ledger_path = Path(temporary) / "moderation-replay.sqlite3"
            original_ledger = SqliteClassroomModerationLedger(ledger_path)
            original_provider = FakeProviderAdmin()
            original_provider.fail_once.add("op-sqlite-restart")
            original = ClassroomModerationRpcService(
                authorization=FakeAuthorization(),
                provider_admin=original_provider,
                ledger=original_ledger,
            )
            wire = payload(operation("op-sqlite-restart"))
            with self.assertRaisesRegex(
                ClassroomModerationRpcError,
                "provider operation failed",
            ):
                await original.handle_rpc(
                    trusted_room_id=ROOM,
                    trusted_caller_identity=CALLER,
                    payload=wire,
                )

            pending = original_ledger.operation_state(
                room_id=ROOM,
                operation_id="op-sqlite-restart",
            )
            self.assertIsNotNone(pending)
            self.assertFalse(pending.committed)
            self.assertIsNotNone(pending.reservation_owner)

            verifier = FakeProviderStateVerifier()
            restarted_provider = FakeProviderAdmin()
            restarted = ClassroomModerationRpcService(
                authorization=FakeAuthorization(),
                provider_admin=restarted_provider,
                ledger=SqliteClassroomModerationLedger(ledger_path),
                provider_state_verifier=verifier,
            )
            command = parse_moderation_rpc(
                wire,
                trusted_room_id=ROOM,
                trusted_caller_identity=CALLER,
            ).commands[0]

            response = await restarted.handle_rpc(
                trusted_room_id=ROOM,
                trusted_caller_identity=CALLER,
                payload=wire,
            )
            self.assertEqual(
                json.loads(response)["accepted_operation_ids"],
                ["op-sqlite-restart"],
            )

            reopened = SqliteClassroomModerationLedger(ledger_path)
            committed = reopened.operation_state(
                room_id=ROOM,
                operation_id="op-sqlite-restart",
            )
            self.assertIsNotNone(committed)
            self.assertTrue(committed.committed)
            self.assertIsNone(committed.reservation_owner)
            self.assertEqual(restarted_provider.calls, [])
            self.assertEqual(len(verifier.calls), 1)

            response = await restarted.handle_rpc(
                trusted_room_id=ROOM,
                trusted_caller_identity=CALLER,
                payload=wire,
            )
            self.assertEqual(
                json.loads(response)["accepted_operation_ids"],
                ["op-sqlite-restart"],
            )
            self.assertEqual(restarted_provider.calls, [])

    async def test_reconciliation_commit_failure_is_sanitized_and_preserves_pending(self) -> None:
        await self.leave_ambiguous_pending()
        pending_before = self.ledger.reservations[(ROOM, "op-recover")]
        self.ledger.fail_commit_for.add("op-recover")
        restarted = self.restarted()

        with self.assertRaisesRegex(
            ClassroomModerationRpcError,
            "reconciliation commit failed",
        ) as context:
            await restarted.reconcile_verified_pending(
                room_id=ROOM,
                command=self.command(),
            )

        self.assertIsNone(context.exception.__cause__)
        self.assertNotIn(
            "sensitive ledger commit detail",
            "".join(traceback.format_exception(context.exception)),
        )
        self.assertEqual(
            self.ledger.reservations[(ROOM, "op-recover")],
            pending_before,
        )
        self.assertNotIn((ROOM, "op-recover"), self.ledger.values)
        self.assertEqual(self.restarted_provider.calls, [])

    async def test_non_boolean_verifier_result_cannot_commit_pending_operation(self) -> None:
        await self.leave_ambiguous_pending()
        self.verifier.matches = 1
        restarted = self.restarted()

        with self.assertRaisesRegex(
            ClassroomModerationRpcError,
            "returned invalid result",
        ):
            await restarted.reconcile_verified_pending(
                room_id=ROOM,
                command=self.command(),
            )

        self.assertIn((ROOM, "op-recover"), self.ledger.reservations)
        self.assertNotIn((ROOM, "op-recover"), self.ledger.values)
        self.assertEqual(self.restarted_provider.calls, [])


class ClassroomModerationRecoveryConstructionTests(unittest.TestCase):
    def test_state_verifier_port_must_expose_callable_verification(self) -> None:
        with self.assertRaisesRegex(
            TypeError,
            "provider state verifier is invalid",
        ):
            ClassroomModerationRpcService(
                authorization=FakeAuthorization(),
                provider_admin=FakeProviderAdmin(),
                ledger=FakeLedger(),
                provider_state_verifier=object(),
            )

    def test_pending_recovery_workflow_binds_scope_to_live_ledger_target(self) -> None:
        workflow = (
            Path(__file__).parents[1]
            / ".github"
            / "workflows"
            / "classroom-moderation-pending-recovery.yml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "EVENT_BASE_SHA: ${{ github.event.pull_request.base.sha }}",
            workflow,
        )
        self.assertIn(
            "EXPECTED_BASE_REF: ${{ github.event.pull_request.base.ref }}",
            workflow,
        )
        self.assertIn(
            'git fetch --no-tags origin "+refs/heads/$EXPECTED_BASE_REF:refs/remotes/origin/$EXPECTED_BASE_REF"',
            workflow,
        )
        self.assertIn(
            'live_base="$(git rev-parse "refs/remotes/origin/$EXPECTED_BASE_REF")"',
            workflow,
        )
        self.assertIn(
            'git merge-base --is-ancestor "$EVENT_BASE_SHA" "$live_base"',
            workflow,
        )
        self.assertIn(
            'test "$(git merge-base "$EVENT_BASE_SHA" "$live_base")" = "$EVENT_BASE_SHA"',
            workflow,
        )
        self.assertIn('git merge-base --is-ancestor "$live_base" HEAD', workflow)
        self.assertIn(
            'test "$(git merge-base "$live_base" HEAD)" = "$live_base"',
            workflow,
        )
        self.assertIn('git diff --check "$live_base...HEAD"', workflow)
        self.assertIn(
            'changed="$(git diff --name-only "$live_base...HEAD" | LC_ALL=C sort)"',
            workflow,
        )
        self.assertNotIn('git diff --check "$EVENT_BASE_SHA...HEAD"', workflow)
        for exact_path in (
            ".github/workflows/classroom-moderation-pending-recovery.yml",
            "acs/classroom_moderation_rpc.py",
            "tests/test_classroom_moderation_rpc.py",
        ):
            with self.subTest(exact_path=exact_path):
                self.assertIn(exact_path, workflow)


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

    def test_workflow_binds_scope_to_live_product_base_fail_closed(self) -> None:
        workflow = (
            Path(__file__).parents[1]
            / ".github"
            / "workflows"
            / "classroom-moderation-rpc.yml"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "EVENT_BASE_SHA: ${{ github.event.pull_request.base.sha }}",
            workflow,
        )
        self.assertIn('git merge-base --is-ancestor "$EVENT_BASE_SHA" HEAD', workflow)
        self.assertIn('git fetch --no-tags origin "$PR_BASE_REF"', workflow)
        self.assertIn(
            'base="$(git rev-parse "refs/remotes/origin/$PR_BASE_REF")"',
            workflow,
        )
        self.assertIn('git merge-base --is-ancestor "$base" HEAD', workflow)
        self.assertIn('git diff --name-only "$base...HEAD"', workflow)
        self.assertNotIn('base="$EVENT_BASE_SHA"', workflow)

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
        self.assertEqual(self.ledger.reservations, {})

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

    async def test_cross_instance_exact_duplicate_has_one_provider_owner(self) -> None:
        shared_ledger = FakeLedger()
        first_authorization = FakeAuthorization()
        second_authorization = FakeAuthorization()
        first_provider = FakeProviderAdmin()
        second_provider = FakeProviderAdmin()
        first_provider.apply_started = asyncio.Event()
        first_provider.apply_continue = asyncio.Event()
        first_service = ClassroomModerationRpcService(
            authorization=first_authorization,
            provider_admin=first_provider,
            ledger=shared_ledger,
        )
        second_service = ClassroomModerationRpcService(
            authorization=second_authorization,
            provider_admin=second_provider,
            ledger=shared_ledger,
        )
        wire = payload(operation("op-cross-exact", source="camera", value=False))

        first_task = asyncio.create_task(
            first_service.handle_rpc(
                trusted_room_id=ROOM,
                trusted_caller_identity=CALLER,
                payload=wire,
            )
        )
        await first_provider.apply_started.wait()

        with self.assertRaisesRegex(
            ClassroomModerationRpcError,
            "pending in another service participant",
        ):
            await second_service.handle_rpc(
                trusted_room_id=ROOM,
                trusted_caller_identity=CALLER,
                payload=wire,
            )

        self.assertEqual(second_authorization.calls, [])
        self.assertEqual(second_provider.calls, [])
        self.assertIn((ROOM, "op-cross-exact"), shared_ledger.reservations)

        first_provider.apply_continue.set()
        response = await first_task

        self.assertEqual(
            json.loads(response)["accepted_operation_ids"],
            ["op-cross-exact"],
        )
        self.assertEqual(
            [command.operation_id for _, command in first_provider.calls],
            ["op-cross-exact"],
        )
        self.assertEqual(second_provider.calls, [])
        self.assertNotIn((ROOM, "op-cross-exact"), shared_ledger.reservations)
        self.assertIn((ROOM, "op-cross-exact"), shared_ledger.values)

    async def test_cross_instance_conflicting_semantics_fail_before_second_provider_effect(self) -> None:
        shared_ledger = FakeLedger()
        first_authorization = FakeAuthorization()
        second_authorization = FakeAuthorization()
        first_provider = FakeProviderAdmin()
        second_provider = FakeProviderAdmin()
        first_provider.yield_before_apply = True
        second_provider.yield_before_apply = True
        first_service = ClassroomModerationRpcService(
            authorization=first_authorization,
            provider_admin=first_provider,
            ledger=shared_ledger,
        )
        second_service = ClassroomModerationRpcService(
            authorization=second_authorization,
            provider_admin=second_provider,
            ledger=shared_ledger,
        )

        first_wire = payload(operation("op-cross-instance", value=False))
        conflicting_wire = payload(operation("op-cross-instance", value=True))
        first_result, conflicting_result = await asyncio.gather(
            first_service.handle_rpc(
                trusted_room_id=ROOM,
                trusted_caller_identity=CALLER,
                payload=first_wire,
            ),
            second_service.handle_rpc(
                trusted_room_id=ROOM,
                trusted_caller_identity=CALLER,
                payload=conflicting_wire,
            ),
            return_exceptions=True,
        )

        results = (first_result, conflicting_result)
        self.assertEqual(sum(isinstance(item, str) for item in results), 1)
        errors = [item for item in results if isinstance(item, Exception)]
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], ClassroomModerationRpcError)
        self.assertIn("reused with different semantics", str(errors[0]))
        self.assertEqual(
            len(first_provider.calls) + len(second_provider.calls),
            1,
        )
        self.assertEqual(
            shared_ledger.values[(ROOM, "op-cross-instance")],
            next(iter(shared_ledger.values.values())),
        )
        self.assertNotIn((ROOM, "op-cross-instance"), shared_ledger.reservations)

    async def test_pending_exact_reservation_is_retriable_after_provider_failure(self) -> None:
        wire = payload(operation("op-pending-retry", source="camera", value=False))
        self.provider.fail_once.add("op-pending-retry")

        with self.assertRaisesRegex(
            ClassroomModerationRpcError,
            "provider operation failed",
        ):
            await self.handle(wire)

        self.assertIn((ROOM, "op-pending-retry"), self.ledger.reservations)
        self.assertNotIn((ROOM, "op-pending-retry"), self.ledger.values)

        await self.handle(wire)

        self.assertNotIn((ROOM, "op-pending-retry"), self.ledger.reservations)
        self.assertIn((ROOM, "op-pending-retry"), self.ledger.values)
        self.assertEqual(
            [command.operation_id for _, command in self.provider.calls],
            ["op-pending-retry", "op-pending-retry"],
        )

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
        self.ledger.fail_reserve_for.add("op-reserve")
        with self.assertRaises(ClassroomModerationRpcError) as reserve_error:
            await self.handle(payload(operation("op-reserve")))
        self.assertEqual(
            str(reserve_error.exception),
            "moderation replay ledger reservation failed",
        )
        self.assert_sanitized_exception(
            reserve_error.exception,
            "sensitive ledger reservation detail",
        )
        self.assertEqual(self.provider.calls, [])

        self.ledger.fail_reserve_for.clear()
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

    def test_non_utf8_surrogate_text_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            ClassroomModerationRpcError,
            "valid UTF-8",
        ):
            parse_moderation_rpc(
                "\ud800",
                trusted_room_id=ROOM,
                trusted_caller_identity=CALLER,
            )

    def test_duplicate_json_object_fields_fail_closed(self) -> None:
        base = payload(operation("op-duplicate"))
        duplicate_envelope = base.replace(
            '"version":1,',
            '"version":1,"version":1,',
            1,
        )
        duplicate_operation = base.replace(
            '"operation_id":"op-duplicate",',
            '"operation_id":"op-duplicate","operation_id":"op-duplicate",',
            1,
        )

        for name, wire in (
            ("duplicate envelope field", duplicate_envelope),
            ("duplicate operation field", duplicate_operation),
        ):
            with self.subTest(name=name):
                with self.assertRaises(ClassroomModerationRpcError):
                    parse_moderation_rpc(
                        wire,
                        trusted_room_id=ROOM,
                        trusted_caller_identity=CALLER,
                    )

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
