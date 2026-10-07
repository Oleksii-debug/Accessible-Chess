from __future__ import annotations

import os
import tempfile
import unittest

from acs.account_cloud import (
    AccountCloudError,
    AccountCloudService,
    AuthenticationError,
    AuthorizationError,
    PublicClientConfig,
    ResourceKind,
    SchemaMigrationError,
    SyncConflictError,
    VerifiedIdentity,
    WorkspaceRole,
)


class MutableClock:
    def __init__(self, value: int = 1_800_000_000) -> None:
        self.value = value

    def __call__(self) -> float:
        return float(self.value)


class AccountCloudSection31Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = MutableClock()
        identities = {
            "proof-alice": VerifiedIdentity("https://issuer.example", "alice"),
            "proof-bob": VerifiedIdentity("https://issuer.example", "bob"),
            "proof-carol": VerifiedIdentity("https://issuer.example", "carol"),
        }

        def verify(proof: str) -> VerifiedIdentity:
            if proof not in identities:
                raise ValueError("bad proof")
            return identities[proof]

        self.verify = verify
        self.tokens = iter(("a" * 48, "b" * 48, "c" * 48, "d" * 48, "e" * 48))
        self.service = AccountCloudService(
            identity_verifier=verify,
            clock=self.clock,
            token_factory=lambda: next(self.tokens),
        )
        self.alice = self.service.login("proof-alice")
        self.bob = self.service.login("proof-bob")
        self.carol = self.service.login("proof-carol")

    def tearDown(self) -> None:
        self.service.close()

    def test_authentication_uses_verified_identity_hashes_bearer_and_revokes(self) -> None:
        principal = self.service.authenticate(self.alice.token)
        self.assertEqual(principal.user_id, self.alice.user_id)
        row = self.service._db.execute(
            "SELECT token_hash FROM sessions WHERE session_id=?", (self.alice.session_id,)
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertNotEqual(row["token_hash"], self.alice.token)
        self.assertNotIn(self.alice.token, repr(self.alice))
        with self.assertRaisesRegex(AuthenticationError, "authentication failed"):
            self.service.login("forged-proof")
        self.service.revoke(self.alice.token)
        with self.assertRaises(AuthenticationError):
            self.service.authenticate(self.alice.token)

    def test_session_expiry_survives_server_restart_without_plaintext_token_storage(self) -> None:
        fd, path = tempfile.mkstemp(prefix="acs-account-cloud-", suffix=".sqlite3")
        os.close(fd)
        try:
            tokens = iter(("x" * 48, "y" * 48))
            first = AccountCloudService(
                path,
                identity_verifier=self.verify,
                clock=self.clock,
                token_factory=lambda: next(tokens),
            )
            issued = first.login("proof-alice", ttl_seconds=60)
            first.close()
            with open(path, "rb") as handle:
                raw = handle.read()
            self.assertNotIn(issued.token.encode("utf-8"), raw)
            second = AccountCloudService(path, identity_verifier=self.verify, clock=self.clock)
            self.assertEqual(second.authenticate(issued.token).user_id, issued.user_id)
            self.clock.value += 60
            with self.assertRaisesRegex(AuthenticationError, "expired"):
                second.authenticate(issued.token)
            second.close()
        finally:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

    def test_workspace_isolation_and_roles_fail_closed(self) -> None:
        workspace = self.service.create_workspace(self.alice.token)
        other = self.service.create_workspace(self.bob.token)
        with self.assertRaises(AuthorizationError):
            self.service.role(self.bob.token, workspace)
        self.service.add_member(
            self.alice.token, workspace, self.bob.user_id, WorkspaceRole.VIEWER
        )
        self.assertEqual(
            self.service.role(self.bob.token, workspace), WorkspaceRole.VIEWER
        )
        with self.assertRaises(AuthorizationError):
            self.service.put_resource(
                self.bob.token,
                workspace,
                ResourceKind.PROGRESS,
                "course",
                {"done": 1},
                expected_revision=0,
                schema_version=1,
                operation_id="viewer-write",
            )
        with self.assertRaises(AuthorizationError):
            self.service.get_resource(
                self.alice.token, other, ResourceKind.PROGRESS, "course"
            )

    def test_library_progress_and_classroom_cloud_state_have_cas_and_idempotency(self) -> None:
        workspace = self.service.create_workspace(self.alice.token)
        for index, kind in enumerate(ResourceKind, start=1):
            created = self.service.put_resource(
                self.alice.token,
                workspace,
                kind,
                f"item-{index}",
                {"value": index},
                expected_revision=0,
                schema_version=1,
                operation_id=f"create-{index}",
            )
            self.assertEqual(created.entity_revision, 1)
            retry = self.service.put_resource(
                self.alice.token,
                workspace,
                kind,
                f"item-{index}",
                {"value": index},
                expected_revision=0,
                schema_version=1,
                operation_id=f"create-{index}",
            )
            self.assertEqual(retry, created)
        with self.assertRaisesRegex(SyncConflictError, "different semantics"):
            self.service.put_resource(
                self.alice.token,
                workspace,
                ResourceKind.LIBRARY,
                "item-1",
                {"value": 99},
                expected_revision=0,
                schema_version=1,
                operation_id="create-1",
            )
        with self.assertRaisesRegex(SyncConflictError, "revision conflict"):
            self.service.put_resource(
                self.alice.token,
                workspace,
                ResourceKind.LIBRARY,
                "item-1",
                {"value": 2},
                expected_revision=0,
                schema_version=1,
                operation_id="stale-write",
            )

    def test_reconnect_pull_is_workspace_scoped_ordered_and_cursor_guarded(self) -> None:
        workspace = self.service.create_workspace(self.alice.token)
        first = self.service.put_resource(
            self.alice.token,
            workspace,
            ResourceKind.PROGRESS,
            "student",
            {"score": 1},
            expected_revision=0,
            schema_version=1,
            operation_id="p1",
        )
        self.service.put_resource(
            self.alice.token,
            workspace,
            ResourceKind.CLASSROOM,
            "lesson",
            {"active": True},
            expected_revision=0,
            schema_version=1,
            operation_id="c1",
        )
        batch = self.service.sync_pull(
            self.alice.token, workspace, since_revision=first.workspace_revision
        )
        self.assertEqual([r.resource_key for r in batch.resources], ["lesson"])
        self.assertGreater(batch.current_revision, batch.since_revision)
        with self.assertRaises(SyncConflictError):
            self.service.sync_pull(
                self.alice.token,
                workspace,
                since_revision=batch.current_revision + 1,
            )

    def test_migration_is_one_step_and_conflict_guarded(self) -> None:
        workspace = self.service.create_workspace(self.alice.token)
        value = self.service.put_resource(
            self.alice.token,
            workspace,
            ResourceKind.PROGRESS,
            "student",
            {"score": 1},
            expected_revision=0,
            schema_version=1,
            operation_id="seed",
        )
        migrated = self.service.migrate_resource(
            self.alice.token,
            workspace,
            ResourceKind.PROGRESS,
            "student",
            expected_revision=value.entity_revision,
            from_schema_version=1,
            to_schema_version=2,
            operation_id="migrate-v2",
            migrate=lambda p: {"score": p["score"], "unit": "points"},
        )
        self.assertEqual(migrated.schema_version, 2)
        with self.assertRaises(SchemaMigrationError):
            self.service.migrate_resource(
                self.alice.token,
                workspace,
                ResourceKind.PROGRESS,
                "student",
                expected_revision=migrated.entity_revision,
                from_schema_version=2,
                to_schema_version=4,
                operation_id="skip-version",
                migrate=lambda p: p,
            )

    def test_notifications_are_member_scoped_and_not_cross_tenant(self) -> None:
        workspace = self.service.create_workspace(self.alice.token)
        self.service.add_member(
            self.alice.token, workspace, self.bob.user_id, WorkspaceRole.VIEWER
        )
        note = self.service.notify(
            self.alice.token, workspace, self.bob.user_id, {"text": "Lesson updated"}
        )
        self.assertEqual(self.service.notifications(self.alice.token, workspace), ())
        bob_notes = self.service.notifications(self.bob.token, workspace)
        self.assertEqual([n.notification_id for n in bob_notes], [note.notification_id])
        read = self.service.mark_notification_read(
            self.bob.token, workspace, note.notification_id
        )
        self.assertTrue(read.is_read)
        with self.assertRaises(AuthorizationError):
            self.service.notify(
                self.alice.token, workspace, self.carol.user_id, {"text": "no"}
            )

    def test_backup_is_digest_bound_excludes_sessions_and_restores_with_workspace_cas(self) -> None:
        workspace = self.service.create_workspace(self.alice.token)
        original = self.service.put_resource(
            self.alice.token,
            workspace,
            ResourceKind.LIBRARY,
            "collection",
            {"games": [1, 2, 3]},
            expected_revision=0,
            schema_version=1,
            operation_id="original",
        )
        receipt = self.service.create_backup(self.alice.token, workspace)
        row = self.service._db.execute(
            "SELECT snapshot_json FROM backups WHERE workspace_id=? AND backup_id=?",
            (workspace, receipt.backup_id),
        ).fetchone()
        self.assertNotIn("sessions", row["snapshot_json"])
        self.assertNotIn(self.alice.token, row["snapshot_json"])
        self.service.put_resource(
            self.alice.token,
            workspace,
            ResourceKind.LIBRARY,
            "collection",
            {"games": [9]},
            expected_revision=original.entity_revision,
            schema_version=1,
            operation_id="changed",
        )
        current = self.service.sync_pull(
            self.alice.token, workspace, since_revision=0
        ).current_revision
        restored_revision = self.service.restore_backup(
            self.alice.token,
            workspace,
            receipt.backup_id,
            expected_workspace_revision=current,
        )
        restored = self.service.get_resource(
            self.alice.token, workspace, ResourceKind.LIBRARY, "collection"
        )
        self.assertEqual(restored.payload, {"games": [1, 2, 3]})
        self.assertEqual(restored.workspace_revision, restored_revision)
        with self.assertRaises(SyncConflictError):
            self.service.restore_backup(
                self.alice.token,
                workspace,
                receipt.backup_id,
                expected_workspace_revision=current,
            )

    def test_public_client_configuration_forbids_static_secrets(self) -> None:
        cfg = PublicClientConfig.from_mapping(
            {
                "server_base_url": "https://chess.example",
                "public_client_id": "accessible-chess-desktop",
            }
        )
        self.assertEqual(cfg.server_base_url, "https://chess.example")
        with self.assertRaisesRegex(AccountCloudError, "secrets are forbidden"):
            PublicClientConfig.from_mapping(
                {
                    "server_base_url": "https://chess.example",
                    "public_client_id": "desktop",
                    "client_secret": "forbidden",
                }
            )
        with self.assertRaises(AccountCloudError):
            PublicClientConfig.from_mapping(
                {
                    "server_base_url": "http://example.test",
                    "public_client_id": "desktop",
                }
            )
        loopback = PublicClientConfig.from_mapping(
            {
                "server_base_url": "http://127.0.0.1:8787",
                "public_client_id": "desktop",
            }
        )
        self.assertEqual(loopback.server_base_url, "http://127.0.0.1:8787")

    def test_resource_payload_is_detached_from_caller_mutation(self) -> None:
        workspace = self.service.create_workspace(self.alice.token)
        payload = {"items": [{"id": 1}]}
        stored = self.service.put_resource(
            self.alice.token,
            workspace,
            ResourceKind.LIBRARY,
            "lib",
            payload,
            expected_revision=0,
            schema_version=1,
            operation_id="detached",
        )
        payload["items"][0]["id"] = 99
        reopened = self.service.get_resource(
            self.alice.token, workspace, ResourceKind.LIBRARY, "lib"
        )
        self.assertEqual(stored.payload, {"items": [{"id": 1}]})
        self.assertEqual(reopened.payload, {"items": [{"id": 1}]})


if __name__ == "__main__":
    unittest.main()
