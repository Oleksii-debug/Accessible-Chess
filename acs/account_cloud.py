from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping


class AccountCloudError(RuntimeError):
    pass


class AuthenticationError(AccountCloudError):
    pass


class AuthorizationError(AccountCloudError):
    pass


class SyncConflictError(AccountCloudError):
    pass


class SchemaMigrationError(AccountCloudError):
    pass


class ResourceKind(str, Enum):
    LIBRARY = "library"
    PROGRESS = "progress"
    CLASSROOM = "classroom"


class WorkspaceRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


@dataclass(frozen=True)
class VerifiedIdentity:
    issuer: str
    subject: str

    def __post_init__(self) -> None:
        _bounded_text(self.issuer, "issuer", 512)
        _bounded_text(self.subject, "subject", 512)


@dataclass(frozen=True)
class IssuedSession:
    user_id: str
    session_id: str
    token: str
    expires_at_unix_s: int

    def __repr__(self) -> str:
        return (
            f"IssuedSession(user_id={self.user_id!r}, session_id={self.session_id!r}, "
            f"token=<redacted>, expires_at_unix_s={self.expires_at_unix_s!r})"
        )


@dataclass(frozen=True)
class SessionPrincipal:
    user_id: str
    session_id: str
    expires_at_unix_s: int


@dataclass(frozen=True)
class CloudResource:
    workspace_id: str
    kind: ResourceKind
    resource_key: str
    entity_revision: int
    workspace_revision: int
    schema_version: int
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class SyncBatch:
    workspace_id: str
    since_revision: int
    current_revision: int
    resources: tuple[CloudResource, ...]


@dataclass(frozen=True)
class Notification:
    workspace_id: str
    notification_id: str
    recipient_user_id: str
    workspace_revision: int
    payload: Mapping[str, Any]
    is_read: bool


@dataclass(frozen=True)
class BackupReceipt:
    workspace_id: str
    backup_id: str
    workspace_revision: int
    digest_sha256: str


@dataclass(frozen=True)
class PublicClientConfig:
    server_base_url: str
    public_client_id: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PublicClientConfig":
        if type(value) is not dict:
            raise AccountCloudError("client configuration must be an exact mapping")
        allowed = {"server_base_url", "public_client_id"}
        keys = set(value)
        forbidden_markers = ("secret", "api_key", "apikey", "private_key", "token")
        if keys != allowed:
            if any(any(marker in str(k).lower() for marker in forbidden_markers) for k in keys):
                raise AccountCloudError("static client secrets are forbidden")
            raise AccountCloudError("client configuration has unknown or missing fields")
        base = _validate_server_url(value["server_base_url"])
        client_id = _bounded_text(value["public_client_id"], "public_client_id", 256)
        return cls(server_base_url=base, public_client_id=client_id)


def _bounded_text(value: Any, name: str, maximum: int) -> str:
    if type(value) is not str:
        raise AccountCloudError(f"{name} must be text")
    if not value or len(value) > maximum or any(ord(ch) < 32 for ch in value):
        raise AccountCloudError(f"{name} is invalid")
    return value


def _exact_nonnegative_int(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise AccountCloudError(f"{name} must be a non-negative integer")
    return value


def _canonical_payload(payload: Any) -> tuple[str, dict[str, Any]]:
    if type(payload) is not dict:
        raise AccountCloudError("payload must be an exact object")
    try:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, OverflowError):
        raise AccountCloudError("payload is not canonical JSON") from None
    if len(encoded.encode("utf-8")) > 2_000_000:
        raise AccountCloudError("payload exceeds cloud-state limit")
    decoded = json.loads(encoded)
    if type(decoded) is not dict:
        raise AccountCloudError("payload must remain an object")
    return encoded, decoded


def _validate_server_url(value: Any) -> str:
    text = _bounded_text(value, "server_base_url", 2048)
    parsed = urllib.parse.urlsplit(text)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AccountCloudError("server URL is not a safe origin")
    if parsed.path not in ("", "/"):
        raise AccountCloudError("server URL must be an origin")
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "https" and host:
        return text.rstrip("/")
    if parsed.scheme == "http" and host in {"127.0.0.1", "::1"}:
        return text.rstrip("/")
    raise AccountCloudError("server URL must use HTTPS except literal loopback")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class AccountCloudService:
    """Server-side account/workspace/cloud authority.

    The caller supplies an authentication proof to a trusted injected verifier.
    Session bearer values are generated here, persisted only as hashes, and never
    used as chess/domain state. Every workspace operation re-authenticates the
    bearer and re-authorizes membership.
    """

    def __init__(
        self,
        database_path: str = ":memory:",
        *,
        clock: Callable[[], float] = time.time,
        identity_verifier: Callable[[str], VerifiedIdentity],
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        if type(database_path) is not str or not database_path:
            raise AccountCloudError("database path is required")
        if not callable(identity_verifier):
            raise AccountCloudError("identity verifier is required")
        self._clock = clock
        self._identity_verifier = identity_verifier
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._lock = threading.RLock()
        self._db = sqlite3.connect(database_path, isolation_level=None, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.execute("PRAGMA journal_mode=WAL")
            self._create_schema()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _create_schema(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users(
                user_id TEXT PRIMARY KEY,
                issuer TEXT NOT NULL,
                subject TEXT NOT NULL,
                UNIQUE(issuer, subject)
            );
            CREATE TABLE IF NOT EXISTS sessions(
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at INTEGER NOT NULL CHECK(expires_at >= 0),
                revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0,1))
            );
            CREATE TABLE IF NOT EXISTS workspaces(
                workspace_id TEXT PRIMARY KEY,
                revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0)
            );
            CREATE TABLE IF NOT EXISTS memberships(
                workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
                user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('owner','admin','editor','viewer')),
                PRIMARY KEY(workspace_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS resources(
                workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
                kind TEXT NOT NULL CHECK(kind IN ('library','progress','classroom')),
                resource_key TEXT NOT NULL,
                entity_revision INTEGER NOT NULL CHECK(entity_revision >= 1),
                workspace_revision INTEGER NOT NULL CHECK(workspace_revision >= 1),
                schema_version INTEGER NOT NULL CHECK(schema_version >= 1),
                payload_json TEXT NOT NULL,
                PRIMARY KEY(workspace_id, kind, resource_key)
            );
            CREATE INDEX IF NOT EXISTS idx_resources_workspace_revision
                ON resources(workspace_id, workspace_revision);
            CREATE TABLE IF NOT EXISTS notifications(
                workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
                notification_id TEXT NOT NULL,
                recipient_user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                workspace_revision INTEGER NOT NULL CHECK(workspace_revision >= 1),
                payload_json TEXT NOT NULL,
                is_read INTEGER NOT NULL DEFAULT 0 CHECK(is_read IN (0,1)),
                PRIMARY KEY(workspace_id, notification_id)
            );
            CREATE TABLE IF NOT EXISTS backups(
                workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
                backup_id TEXT NOT NULL,
                workspace_revision INTEGER NOT NULL CHECK(workspace_revision >= 0),
                snapshot_json TEXT NOT NULL,
                digest_sha256 TEXT NOT NULL,
                PRIMARY KEY(workspace_id, backup_id)
            );
            CREATE TABLE IF NOT EXISTS operations(
                workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
                user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                operation_id TEXT NOT NULL,
                request_digest TEXT NOT NULL,
                result_json TEXT NOT NULL,
                PRIMARY KEY(workspace_id, user_id, operation_id)
            );
            """
        )

    def login(self, authentication_proof: str, *, ttl_seconds: int = 3600) -> IssuedSession:
        proof = _bounded_text(authentication_proof, "authentication_proof", 16384)
        try:
            identity = self._identity_verifier(proof)
        except Exception:
            raise AuthenticationError("authentication failed") from None
        if type(identity) is not VerifiedIdentity:
            raise AuthenticationError("authentication failed")
        if type(ttl_seconds) is not int or not (60 <= ttl_seconds <= 86400):
            raise AuthenticationError("session TTL is outside policy")
        now = int(self._clock())
        if now < 0:
            raise AuthenticationError("clock is invalid")
        token = self._token_factory()
        if type(token) is not str or len(token) < 32 or len(token) > 512:
            raise AuthenticationError("session token generator returned invalid material")
        digest = _token_hash(token)
        with self._transaction():
            row = self._db.execute(
                "SELECT user_id FROM users WHERE issuer=? AND subject=?",
                (identity.issuer, identity.subject),
            ).fetchone()
            if row is None:
                user_id = _new_id("usr")
                self._db.execute(
                    "INSERT INTO users(user_id,issuer,subject) VALUES(?,?,?)",
                    (user_id, identity.issuer, identity.subject),
                )
            else:
                user_id = str(row["user_id"])
            session_id = _new_id("ses")
            expires_at = now + ttl_seconds
            try:
                self._db.execute(
                    "INSERT INTO sessions(session_id,user_id,token_hash,expires_at,revoked) VALUES(?,?,?,?,0)",
                    (session_id, user_id, digest, expires_at),
                )
            except sqlite3.IntegrityError:
                raise AuthenticationError("session token collision") from None
        return IssuedSession(user_id, session_id, token, expires_at)

    def authenticate(self, token: str) -> SessionPrincipal:
        if type(token) is not str or len(token) < 32 or len(token) > 512:
            raise AuthenticationError("invalid session")
        digest = _token_hash(token)
        with self._lock:
            row = self._db.execute(
                "SELECT session_id,user_id,expires_at,revoked FROM sessions WHERE token_hash=?",
                (digest,),
            ).fetchone()
        if row is None or int(row["revoked"]) != 0:
            raise AuthenticationError("invalid session")
        expires = int(row["expires_at"])
        now = int(self._clock())
        if now < 0 or now >= expires:
            raise AuthenticationError("session expired")
        return SessionPrincipal(str(row["user_id"]), str(row["session_id"]), expires)

    def revoke(self, token: str) -> None:
        principal = self.authenticate(token)
        with self._transaction():
            self._db.execute(
                "UPDATE sessions SET revoked=1 WHERE session_id=? AND user_id=?",
                (principal.session_id, principal.user_id),
            )

    def create_workspace(self, token: str) -> str:
        principal = self.authenticate(token)
        workspace_id = _new_id("wsp")
        with self._transaction():
            self._db.execute("INSERT INTO workspaces(workspace_id,revision) VALUES(?,0)", (workspace_id,))
            self._db.execute(
                "INSERT INTO memberships(workspace_id,user_id,role) VALUES(?,?,?)",
                (workspace_id, principal.user_id, WorkspaceRole.OWNER.value),
            )
        return workspace_id

    def role(self, token: str, workspace_id: str) -> WorkspaceRole:
        principal = self.authenticate(token)
        workspace_id = _bounded_text(workspace_id, "workspace_id", 128)
        with self._lock:
            row = self._db.execute(
                "SELECT role FROM memberships WHERE workspace_id=? AND user_id=?",
                (workspace_id, principal.user_id),
            ).fetchone()
        if row is None:
            raise AuthorizationError("workspace access denied")
        return WorkspaceRole(str(row["role"]))

    def add_member(
        self,
        token: str,
        workspace_id: str,
        user_id: str,
        role: WorkspaceRole,
    ) -> None:
        self._authorize(token, workspace_id, {WorkspaceRole.OWNER, WorkspaceRole.ADMIN})
        user_id = _bounded_text(user_id, "user_id", 128)
        if type(role) is not WorkspaceRole or role is WorkspaceRole.OWNER:
            raise AuthorizationError("member role is not assignable")
        with self._transaction():
            if self._db.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone() is None:
                raise AuthorizationError("unknown user")
            self._db.execute(
                """
                INSERT INTO memberships(workspace_id,user_id,role) VALUES(?,?,?)
                ON CONFLICT(workspace_id,user_id) DO UPDATE SET role=excluded.role
                """,
                (workspace_id, user_id, role.value),
            )
            self._bump_workspace(workspace_id)

    def put_resource(
        self,
        token: str,
        workspace_id: str,
        kind: ResourceKind,
        resource_key: str,
        payload: Mapping[str, Any],
        *,
        expected_revision: int,
        schema_version: int,
        operation_id: str,
    ) -> CloudResource:
        principal = self._authorize(
            token, workspace_id, {WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}
        )
        if type(kind) is not ResourceKind:
            raise AccountCloudError("resource kind is invalid")
        resource_key = _bounded_text(resource_key, "resource_key", 256)
        expected_revision = _exact_nonnegative_int(expected_revision, "expected_revision")
        if type(schema_version) is not int or schema_version < 1 or schema_version > 1_000_000:
            raise AccountCloudError("schema_version is invalid")
        operation_id = _bounded_text(operation_id, "operation_id", 128)
        payload_json, detached = _canonical_payload(payload)
        request_doc = {
            "kind": kind.value,
            "resource_key": resource_key,
            "expected_revision": expected_revision,
            "schema_version": schema_version,
            "payload": detached,
        }
        request_json = json.dumps(request_doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        request_digest = hashlib.sha256(request_json.encode("utf-8")).hexdigest()
        with self._transaction():
            prior_op = self._db.execute(
                "SELECT request_digest,result_json FROM operations WHERE workspace_id=? AND user_id=? AND operation_id=?",
                (workspace_id, principal.user_id, operation_id),
            ).fetchone()
            if prior_op is not None:
                if str(prior_op["request_digest"]) != request_digest:
                    raise SyncConflictError("operation id was reused with different semantics")
                return self._resource_from_dict(json.loads(str(prior_op["result_json"])))

            current = self._db.execute(
                "SELECT entity_revision,schema_version FROM resources WHERE workspace_id=? AND kind=? AND resource_key=?",
                (workspace_id, kind.value, resource_key),
            ).fetchone()
            current_revision = 0 if current is None else int(current["entity_revision"])
            if current_revision != expected_revision:
                raise SyncConflictError("resource revision conflict")
            if current is not None and schema_version < int(current["schema_version"]):
                raise SchemaMigrationError("schema downgrade is forbidden")
            entity_revision = current_revision + 1
            workspace_revision = self._bump_workspace(workspace_id)
            self._db.execute(
                """
                INSERT INTO resources(workspace_id,kind,resource_key,entity_revision,workspace_revision,schema_version,payload_json)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(workspace_id,kind,resource_key) DO UPDATE SET
                    entity_revision=excluded.entity_revision,
                    workspace_revision=excluded.workspace_revision,
                    schema_version=excluded.schema_version,
                    payload_json=excluded.payload_json
                """,
                (
                    workspace_id,
                    kind.value,
                    resource_key,
                    entity_revision,
                    workspace_revision,
                    schema_version,
                    payload_json,
                ),
            )
            result = CloudResource(
                workspace_id, kind, resource_key, entity_revision, workspace_revision, schema_version, detached
            )
            result_json = json.dumps(self._resource_to_dict(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            self._db.execute(
                "INSERT INTO operations(workspace_id,user_id,operation_id,request_digest,result_json) VALUES(?,?,?,?,?)",
                (workspace_id, principal.user_id, operation_id, request_digest, result_json),
            )
            return result

    def get_resource(
        self, token: str, workspace_id: str, kind: ResourceKind, resource_key: str
    ) -> CloudResource | None:
        self._authorize(token, workspace_id, set(WorkspaceRole))
        if type(kind) is not ResourceKind:
            raise AccountCloudError("resource kind is invalid")
        resource_key = _bounded_text(resource_key, "resource_key", 256)
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM resources WHERE workspace_id=? AND kind=? AND resource_key=?",
                (workspace_id, kind.value, resource_key),
            ).fetchone()
        return None if row is None else self._resource_from_row(row)

    def sync_pull(self, token: str, workspace_id: str, *, since_revision: int) -> SyncBatch:
        self._authorize(token, workspace_id, set(WorkspaceRole))
        since_revision = _exact_nonnegative_int(since_revision, "since_revision")
        with self._lock:
            current = self._workspace_revision(workspace_id)
            if since_revision > current:
                raise SyncConflictError("sync cursor is ahead of workspace")
            rows = self._db.execute(
                """
                SELECT * FROM resources
                WHERE workspace_id=? AND workspace_revision>?
                ORDER BY workspace_revision,kind,resource_key
                """,
                (workspace_id, since_revision),
            ).fetchall()
        return SyncBatch(
            workspace_id,
            since_revision,
            current,
            tuple(self._resource_from_row(row) for row in rows),
        )

    def migrate_resource(
        self,
        token: str,
        workspace_id: str,
        kind: ResourceKind,
        resource_key: str,
        *,
        expected_revision: int,
        from_schema_version: int,
        to_schema_version: int,
        operation_id: str,
        migrate: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    ) -> CloudResource:
        if type(from_schema_version) is not int or type(to_schema_version) is not int:
            raise SchemaMigrationError("schema versions must be integers")
        if to_schema_version != from_schema_version + 1:
            raise SchemaMigrationError("migration must advance exactly one schema version")
        current = self.get_resource(token, workspace_id, kind, resource_key)
        if current is None:
            raise SchemaMigrationError("resource does not exist")
        if current.entity_revision != expected_revision or current.schema_version != from_schema_version:
            raise SyncConflictError("migration source revision changed")
        if not callable(migrate):
            raise SchemaMigrationError("migration function is required")
        try:
            migrated = migrate(dict(current.payload))
        except Exception:
            raise SchemaMigrationError("migration failed") from None
        return self.put_resource(
            token,
            workspace_id,
            kind,
            resource_key,
            migrated,
            expected_revision=expected_revision,
            schema_version=to_schema_version,
            operation_id=operation_id,
        )

    def notify(
        self,
        token: str,
        workspace_id: str,
        recipient_user_id: str,
        payload: Mapping[str, Any],
    ) -> Notification:
        self._authorize(
            token, workspace_id, {WorkspaceRole.OWNER, WorkspaceRole.ADMIN, WorkspaceRole.EDITOR}
        )
        recipient_user_id = _bounded_text(recipient_user_id, "recipient_user_id", 128)
        payload_json, detached = _canonical_payload(payload)
        with self._transaction():
            if self._db.execute(
                "SELECT 1 FROM memberships WHERE workspace_id=? AND user_id=?",
                (workspace_id, recipient_user_id),
            ).fetchone() is None:
                raise AuthorizationError("notification recipient is outside workspace")
            revision = self._bump_workspace(workspace_id)
            notification_id = _new_id("ntf")
            self._db.execute(
                """
                INSERT INTO notifications(workspace_id,notification_id,recipient_user_id,workspace_revision,payload_json,is_read)
                VALUES(?,?,?,?,?,0)
                """,
                (workspace_id, notification_id, recipient_user_id, revision, payload_json),
            )
        return Notification(workspace_id, notification_id, recipient_user_id, revision, detached, False)

    def notifications(self, token: str, workspace_id: str) -> tuple[Notification, ...]:
        principal = self._authorize(token, workspace_id, set(WorkspaceRole))
        with self._lock:
            rows = self._db.execute(
                """
                SELECT * FROM notifications
                WHERE workspace_id=? AND recipient_user_id=?
                ORDER BY workspace_revision,notification_id
                """,
                (workspace_id, principal.user_id),
            ).fetchall()
        return tuple(self._notification_from_row(row) for row in rows)

    def mark_notification_read(self, token: str, workspace_id: str, notification_id: str) -> Notification:
        principal = self._authorize(token, workspace_id, set(WorkspaceRole))
        notification_id = _bounded_text(notification_id, "notification_id", 128)
        with self._transaction():
            row = self._db.execute(
                """
                SELECT * FROM notifications
                WHERE workspace_id=? AND notification_id=? AND recipient_user_id=?
                """,
                (workspace_id, notification_id, principal.user_id),
            ).fetchone()
            if row is None:
                raise AuthorizationError("notification access denied")
            self._db.execute(
                "UPDATE notifications SET is_read=1 WHERE workspace_id=? AND notification_id=?",
                (workspace_id, notification_id),
            )
            values = dict(row)
            values["is_read"] = 1
        return self._notification_from_mapping(values)

    def create_backup(self, token: str, workspace_id: str) -> BackupReceipt:
        self._authorize(token, workspace_id, {WorkspaceRole.OWNER, WorkspaceRole.ADMIN})
        with self._transaction():
            revision = self._workspace_revision(workspace_id)
            members = [
                dict(row)
                for row in self._db.execute(
                    "SELECT user_id,role FROM memberships WHERE workspace_id=? ORDER BY user_id",
                    (workspace_id,),
                ).fetchall()
            ]
            resources = [
                {
                    "kind": str(row["kind"]),
                    "resource_key": str(row["resource_key"]),
                    "entity_revision": int(row["entity_revision"]),
                    "workspace_revision": int(row["workspace_revision"]),
                    "schema_version": int(row["schema_version"]),
                    "payload": json.loads(str(row["payload_json"])),
                }
                for row in self._db.execute(
                    """
                    SELECT kind,resource_key,entity_revision,workspace_revision,schema_version,payload_json
                    FROM resources WHERE workspace_id=? ORDER BY kind,resource_key
                    """,
                    (workspace_id,),
                ).fetchall()
            ]
            snapshot = {
                "format": "accessible-chess-workspace-backup",
                "version": 1,
                "workspace_id": workspace_id,
                "workspace_revision": revision,
                "members": members,
                "resources": resources,
            }
            snapshot_json = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
            digest = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()
            backup_id = _new_id("bak")
            self._db.execute(
                "INSERT INTO backups(workspace_id,backup_id,workspace_revision,snapshot_json,digest_sha256) VALUES(?,?,?,?,?)",
                (workspace_id, backup_id, revision, snapshot_json, digest),
            )
        return BackupReceipt(workspace_id, backup_id, revision, digest)

    def restore_backup(
        self,
        token: str,
        workspace_id: str,
        backup_id: str,
        *,
        expected_workspace_revision: int,
    ) -> int:
        self._authorize(token, workspace_id, {WorkspaceRole.OWNER})
        backup_id = _bounded_text(backup_id, "backup_id", 128)
        expected_workspace_revision = _exact_nonnegative_int(
            expected_workspace_revision, "expected_workspace_revision"
        )
        with self._transaction():
            current_revision = self._workspace_revision(workspace_id)
            if current_revision != expected_workspace_revision:
                raise SyncConflictError("workspace changed before restore")
            row = self._db.execute(
                "SELECT snapshot_json,digest_sha256 FROM backups WHERE workspace_id=? AND backup_id=?",
                (workspace_id, backup_id),
            ).fetchone()
            if row is None:
                raise AccountCloudError("backup not found")
            snapshot_json = str(row["snapshot_json"])
            if hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest() != str(row["digest_sha256"]):
                raise AccountCloudError("backup integrity check failed")
            try:
                snapshot = json.loads(snapshot_json)
            except json.JSONDecodeError:
                raise AccountCloudError("backup is invalid") from None
            if (
                type(snapshot) is not dict
                or snapshot.get("format") != "accessible-chess-workspace-backup"
                or snapshot.get("version") != 1
                or snapshot.get("workspace_id") != workspace_id
                or type(snapshot.get("resources")) is not list
            ):
                raise AccountCloudError("backup schema is invalid")
            new_revision = self._bump_workspace(workspace_id)
            self._db.execute("DELETE FROM resources WHERE workspace_id=?", (workspace_id,))
            for item in snapshot["resources"]:
                if type(item) is not dict:
                    raise AccountCloudError("backup resource is invalid")
                kind = ResourceKind(item["kind"])
                key = _bounded_text(item["resource_key"], "resource_key", 256)
                entity_revision = _exact_nonnegative_int(item["entity_revision"], "entity_revision")
                if entity_revision < 1:
                    raise AccountCloudError("backup entity revision is invalid")
                schema_version = _exact_nonnegative_int(item["schema_version"], "schema_version")
                if schema_version < 1:
                    raise AccountCloudError("backup schema version is invalid")
                payload_json, _ = _canonical_payload(item["payload"])
                self._db.execute(
                    """
                    INSERT INTO resources(workspace_id,kind,resource_key,entity_revision,workspace_revision,schema_version,payload_json)
                    VALUES(?,?,?,?,?,?,?)
                    """,
                    (workspace_id, kind.value, key, entity_revision, new_revision, schema_version, payload_json),
                )
            return new_revision

    def _authorize(
        self, token: str, workspace_id: str, allowed: set[WorkspaceRole]
    ) -> SessionPrincipal:
        principal = self.authenticate(token)
        workspace_id = _bounded_text(workspace_id, "workspace_id", 128)
        with self._lock:
            row = self._db.execute(
                "SELECT role FROM memberships WHERE workspace_id=? AND user_id=?",
                (workspace_id, principal.user_id),
            ).fetchone()
        if row is None:
            raise AuthorizationError("workspace access denied")
        role = WorkspaceRole(str(row["role"]))
        if role not in allowed:
            raise AuthorizationError("workspace permission denied")
        return principal

    def _workspace_revision(self, workspace_id: str) -> int:
        row = self._db.execute(
            "SELECT revision FROM workspaces WHERE workspace_id=?", (workspace_id,)
        ).fetchone()
        if row is None:
            raise AuthorizationError("workspace access denied")
        return int(row["revision"])

    def _bump_workspace(self, workspace_id: str) -> int:
        current = self._workspace_revision(workspace_id)
        updated = current + 1
        self._db.execute(
            "UPDATE workspaces SET revision=? WHERE workspace_id=? AND revision=?",
            (updated, workspace_id, current),
        )
        return updated

    def _resource_from_row(self, row: sqlite3.Row) -> CloudResource:
        return CloudResource(
            str(row["workspace_id"]),
            ResourceKind(str(row["kind"])),
            str(row["resource_key"]),
            int(row["entity_revision"]),
            int(row["workspace_revision"]),
            int(row["schema_version"]),
            json.loads(str(row["payload_json"])),
        )

    def _resource_to_dict(self, value: CloudResource) -> dict[str, Any]:
        return {
            "workspace_id": value.workspace_id,
            "kind": value.kind.value,
            "resource_key": value.resource_key,
            "entity_revision": value.entity_revision,
            "workspace_revision": value.workspace_revision,
            "schema_version": value.schema_version,
            "payload": dict(value.payload),
        }

    def _resource_from_dict(self, value: Mapping[str, Any]) -> CloudResource:
        return CloudResource(
            str(value["workspace_id"]),
            ResourceKind(str(value["kind"])),
            str(value["resource_key"]),
            int(value["entity_revision"]),
            int(value["workspace_revision"]),
            int(value["schema_version"]),
            dict(value["payload"]),
        )

    def _notification_from_row(self, row: sqlite3.Row) -> Notification:
        return self._notification_from_mapping(dict(row))

    def _notification_from_mapping(self, row: Mapping[str, Any]) -> Notification:
        return Notification(
            str(row["workspace_id"]),
            str(row["notification_id"]),
            str(row["recipient_user_id"]),
            int(row["workspace_revision"]),
            json.loads(str(row["payload_json"])),
            bool(int(row["is_read"])),
        )

    class _Transaction:
        def __init__(self, service: "AccountCloudService") -> None:
            self._service = service

        def __enter__(self) -> None:
            self._service._lock.acquire()
            self._service._db.execute("BEGIN IMMEDIATE")

        def __exit__(self, exc_type, exc, tb) -> bool:
            try:
                self._service._db.execute("ROLLBACK" if exc_type else "COMMIT")
            finally:
                self._service._lock.release()
            return False

    def _transaction(self) -> "_Transaction":
        return self._Transaction(self)
