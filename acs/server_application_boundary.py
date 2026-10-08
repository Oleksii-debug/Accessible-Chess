from __future__ import annotations

"""Authenticated, domain-neutral server application boundary for Section 30.

The server validates request identity, workspace, permissions, versioned DTOs and
heavy-job lifecycle, then delegates to already-existing application commands and
queries. It deliberately contains no chess rules, PGN/GameTree parsing, classroom
membership logic, account database, or provider-specific authentication.
"""

from collections.abc import Awaitable, Callable, Mapping
from contextlib import closing
from dataclasses import dataclass
from enum import Enum
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import uuid

from .network_security import (
    DataClass, NetworkSurface, ProductionSecurityPolicy, SecurityContractError,
    SecurityGate, SecurityRequest,
)


API_SCHEMA_VERSION = 1
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_OPERATION_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
_MAX_PAYLOAD_KEYS = 64
_MAX_CONTAINER_ITEMS = 512
_MAX_DEPTH = 10
_MAX_TEXT = 16_384
_MAX_BODY = 65_536


class ServerBoundaryError(ValueError):
    """Invalid or unauthorized request at the server/application boundary."""


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """Identity asserted by trusted authentication middleware.

    Section 30 consumes this type but does not issue sessions/accounts; that
    belongs to Section 31. Browser/request payloads cannot construct authority.
    """

    actor_id: str
    workspace_id: str
    session_id: str
    roles: frozenset[str]
    permissions: frozenset[str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "actor_id", _id(self.actor_id, "actor id"))
        object.__setattr__(self, "workspace_id", _id(self.workspace_id, "workspace id"))
        object.__setattr__(self, "session_id", _id(self.session_id, "session id"))
        for label, values in (("roles", self.roles), ("permissions", self.permissions)):
            if type(values) is not frozenset or len(values) > 64:
                raise ServerBoundaryError(f"{label} must be a bounded frozenset")
            if any(type(v) is not str or _ID_RE.fullmatch(v) is None for v in values):
                raise ServerBoundaryError(f"{label} contains invalid identifier")


@dataclass(frozen=True, slots=True)
class EntityRef:
    entity_id: str
    revision: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "entity_id", _id(self.entity_id, "entity id"))
        if type(self.revision) is not int or self.revision < 0:
            raise ServerBoundaryError("entity revision must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class ApiRequest:
    schema_version: int
    request_id: str
    workspace_id: str
    operation: str
    payload: Mapping[str, object]
    entity: EntityRef | None = None

    def __post_init__(self) -> None:
        if self.schema_version != API_SCHEMA_VERSION:
            raise ServerBoundaryError("unsupported API schema version")
        object.__setattr__(self, "request_id", _id(self.request_id, "request id"))
        object.__setattr__(self, "workspace_id", _id(self.workspace_id, "workspace id"))
        object.__setattr__(self, "operation", _operation(self.operation))
        if not isinstance(self.payload, Mapping):
            raise ServerBoundaryError("request payload must be a mapping")
        clean = _validate_json(dict(self.payload))
        if type(clean) is not dict:
            raise ServerBoundaryError("request payload is invalid")
        object.__setattr__(self, "payload", clean)
        if self.entity is not None and type(self.entity) is not EntityRef:
            raise ServerBoundaryError("request entity reference is invalid")


@dataclass(frozen=True, slots=True)
class ServerOperation:
    operation: str
    mutates: bool
    permission: str
    handler: Callable[
        [AuthenticatedPrincipal, Mapping[str, object], EntityRef | None],
        Mapping[str, object],
    ]
    heavy: bool = False
    surface: NetworkSurface = NetworkSurface.SERVER
    data_classes: frozenset[DataClass] = frozenset()
    requested_retention_days: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation", _operation(self.operation))
        if type(self.mutates) is not bool or type(self.heavy) is not bool:
            raise ServerBoundaryError("operation flags must be boolean")
        if type(self.permission) is not str or _ID_RE.fullmatch(self.permission) is None:
            raise ServerBoundaryError("operation permission is invalid")
        if not callable(self.handler):
            raise ServerBoundaryError("operation handler must be callable")
        if type(self.surface) is not NetworkSurface:
            raise ServerBoundaryError("operation surface is invalid")
        if type(self.data_classes) is not frozenset or any(
            type(item) is not DataClass for item in self.data_classes
        ):
            raise ServerBoundaryError("operation data classes are invalid")
        if self.requested_retention_days is not None and (
            type(self.requested_retention_days) is not int
            or self.requested_retention_days <= 0
        ):
            raise ServerBoundaryError("operation retention is invalid")


@dataclass(frozen=True, slots=True)
class JobRecord:
    job_id: str
    request_id: str
    workspace_id: str
    operation: str
    state: JobState
    progress: int
    attempts: int
    cancel_requested: bool
    payload: Mapping[str, object]
    entity: EntityRef | None
    result: Mapping[str, object] | None = None
    error_code: str | None = None


class SqliteJobStore:
    """Durable Section-30 heavy-job lifecycle and restart authority."""

    _SCHEMA = 1

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if str(self.path) in {"", ":memory:"}:
            raise ServerBoundaryError("durable job store path is required")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def _initialize(self) -> None:
        with self._lock, closing(self._connect()) as db, db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS server_job_meta(
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    schema_version INTEGER NOT NULL
                )
                """
            )
            row = db.execute(
                "SELECT schema_version FROM server_job_meta WHERE singleton=1"
            ).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO server_job_meta(singleton,schema_version) VALUES(1,?)",
                    (self._SCHEMA,),
                )
            elif row["schema_version"] != self._SCHEMA:
                raise ServerBoundaryError("unsupported durable job schema")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS server_jobs(
                    job_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE,
                    workspace_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    state TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    attempts INTEGER NOT NULL,
                    cancel_requested INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    entity_id TEXT,
                    entity_revision INTEGER,
                    result_json TEXT,
                    error_code TEXT
                )
                """
            )

    def enqueue(self, request: ApiRequest) -> JobRecord:
        payload_json = _json_text(dict(request.payload))
        with self._lock, closing(self._connect()) as db, db:
            existing = db.execute(
                "SELECT * FROM server_jobs WHERE request_id=?",
                (request.request_id,),
            ).fetchone()
            if existing is not None:
                record = self._row(existing)
                if (
                    record.workspace_id != request.workspace_id
                    or record.operation != request.operation
                    or dict(record.payload) != dict(request.payload)
                    or record.entity != request.entity
                ):
                    raise ServerBoundaryError("request id is already bound to another job")
                return record
            job_id = uuid.uuid4().hex
            db.execute(
                """
                INSERT INTO server_jobs(
                    job_id,request_id,workspace_id,operation,state,progress,
                    attempts,cancel_requested,payload_json,entity_id,
                    entity_revision,result_json,error_code
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    job_id, request.request_id, request.workspace_id,
                    request.operation, JobState.QUEUED.value, 0, 0, 0,
                    payload_json,
                    request.entity.entity_id if request.entity else None,
                    request.entity.revision if request.entity else None,
                    None, None,
                ),
            )
        return self.get(job_id)

    def get(self, job_id: str) -> JobRecord:
        key = _id(job_id, "job id")
        with self._lock, closing(self._connect()) as db, db:
            row = db.execute("SELECT * FROM server_jobs WHERE job_id=?", (key,)).fetchone()
            if row is None:
                raise ServerBoundaryError("unknown job")
            return self._row(row)

    def claim_next(self) -> JobRecord | None:
        with self._lock, closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM server_jobs WHERE state=? ORDER BY rowid LIMIT 1",
                (JobState.QUEUED.value,),
            ).fetchone()
            if row is None:
                db.rollback()
                return None
            if bool(row["cancel_requested"]):
                db.execute(
                    "UPDATE server_jobs SET state=? WHERE job_id=?",
                    (JobState.CANCELLED.value, row["job_id"]),
                )
                db.commit()
                return self.get(row["job_id"])
            db.execute(
                "UPDATE server_jobs SET state=?,attempts=attempts+1 WHERE job_id=? AND state=?",
                (JobState.RUNNING.value, row["job_id"], JobState.QUEUED.value),
            )
            db.commit()
            return self.get(row["job_id"])

    def progress(self, job_id: str, percent: int) -> JobRecord:
        key = _id(job_id, "job id")
        if type(percent) is not int or not (0 <= percent <= 100):
            raise ServerBoundaryError("job progress must be 0..100")
        with self._lock, closing(self._connect()) as db, db:
            row = db.execute(
                "SELECT state,progress,cancel_requested FROM server_jobs WHERE job_id=?",
                (key,),
            ).fetchone()
            if row is None:
                raise ServerBoundaryError("unknown job")
            if row["state"] != JobState.RUNNING.value:
                raise ServerBoundaryError("only a running job may publish progress")
            if bool(row["cancel_requested"]):
                raise ServerBoundaryError("job cancellation requested")
            if percent < row["progress"]:
                raise ServerBoundaryError("job progress must be monotonic")
            db.execute("UPDATE server_jobs SET progress=? WHERE job_id=?", (percent, key))
        return self.get(key)

    def request_cancel(self, job_id: str) -> JobRecord:
        key = _id(job_id, "job id")
        with self._lock, closing(self._connect()) as db, db:
            row = db.execute("SELECT state FROM server_jobs WHERE job_id=?", (key,)).fetchone()
            if row is None:
                raise ServerBoundaryError("unknown job")
            state = JobState(row["state"])
            if state in {JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED}:
                return self.get(key)
            if state is JobState.QUEUED:
                db.execute(
                    "UPDATE server_jobs SET cancel_requested=1,state=? WHERE job_id=?",
                    (JobState.CANCELLED.value, key),
                )
            else:
                db.execute(
                    "UPDATE server_jobs SET cancel_requested=1 WHERE job_id=?",
                    (key,),
                )
        return self.get(key)

    def complete(self, job_id: str, result: Mapping[str, object]) -> JobRecord:
        key = _id(job_id, "job id")
        clean = _validate_json(dict(result))
        if type(clean) is not dict:
            raise ServerBoundaryError("job result must be a mapping")
        with self._lock, closing(self._connect()) as db, db:
            row = db.execute(
                "SELECT state,cancel_requested FROM server_jobs WHERE job_id=?",
                (key,),
            ).fetchone()
            if row is None or row["state"] != JobState.RUNNING.value:
                raise ServerBoundaryError("only a running job may complete")
            if bool(row["cancel_requested"]):
                db.execute(
                    "UPDATE server_jobs SET state=? WHERE job_id=?",
                    (JobState.CANCELLED.value, key),
                )
            else:
                db.execute(
                    "UPDATE server_jobs SET state=?,progress=100,result_json=?,error_code=NULL WHERE job_id=?",
                    (JobState.SUCCEEDED.value, _json_text(clean), key),
                )
        return self.get(key)

    def fail(self, job_id: str, *, error_code: str, retryable: bool) -> JobRecord:
        key = _id(job_id, "job id")
        code = _id(error_code, "error code")
        if type(retryable) is not bool:
            raise ServerBoundaryError("retryable flag must be boolean")
        with self._lock, closing(self._connect()) as db, db:
            row = db.execute(
                "SELECT state,cancel_requested FROM server_jobs WHERE job_id=?",
                (key,),
            ).fetchone()
            if row is None or row["state"] != JobState.RUNNING.value:
                raise ServerBoundaryError("only a running job may fail")
            if bool(row["cancel_requested"]):
                state = JobState.CANCELLED
            else:
                state = JobState.QUEUED if retryable else JobState.FAILED
            db.execute(
                "UPDATE server_jobs SET state=?,error_code=?,result_json=NULL WHERE job_id=?",
                (state.value, code, key),
            )
        return self.get(key)

    def recover_after_restart(self) -> int:
        with self._lock, closing(self._connect()) as db, db:
            rows = db.execute(
                "SELECT job_id,cancel_requested FROM server_jobs WHERE state=?",
                (JobState.RUNNING.value,),
            ).fetchall()
            for row in rows:
                state = JobState.CANCELLED.value if bool(row["cancel_requested"]) else JobState.QUEUED.value
                db.execute(
                    "UPDATE server_jobs SET state=?,error_code=? WHERE job_id=?",
                    (state, "restart_recovery", row["job_id"]),
                )
            return len(rows)

    def _row(self, row: sqlite3.Row) -> JobRecord:
        try:
            state = JobState(row["state"])
            payload = json.loads(row["payload_json"])
            result = None if row["result_json"] is None else json.loads(row["result_json"])
            entity = None if row["entity_id"] is None else EntityRef(
                row["entity_id"], row["entity_revision"]
            )
            if type(payload) is not dict or (result is not None and type(result) is not dict):
                raise ValueError
            return JobRecord(
                job_id=_id(row["job_id"], "job id"),
                request_id=_id(row["request_id"], "request id"),
                workspace_id=_id(row["workspace_id"], "workspace id"),
                operation=_operation(row["operation"]),
                state=state,
                progress=int(row["progress"]),
                attempts=int(row["attempts"]),
                cancel_requested=bool(row["cancel_requested"]),
                payload=_validate_json(payload),
                entity=entity,
                result=None if result is None else _validate_json(result),
                error_code=row["error_code"],
            )
        except Exception:
            raise ServerBoundaryError("durable job record is corrupt") from None


class ServerApplicationBoundary:
    """Validates untrusted server requests, then delegates to canonical owners."""

    def __init__(
        self,
        *,
        security_policy: ProductionSecurityPolicy,
        security_gate: SecurityGate,
        operations: tuple[ServerOperation, ...],
        job_store: SqliteJobStore | None = None,
    ) -> None:
        if type(security_policy) is not ProductionSecurityPolicy:
            raise ServerBoundaryError("production security policy is required")
        try:
            security_policy.verify_gate(security_gate)
        except SecurityContractError as error:
            raise ServerBoundaryError(str(error)) from None
        if type(operations) is not tuple or not operations:
            raise ServerBoundaryError("at least one server operation is required")
        mapping: dict[str, ServerOperation] = {}
        for operation in operations:
            if type(operation) is not ServerOperation:
                raise ServerBoundaryError("invalid server operation")
            if operation.operation in mapping:
                raise ServerBoundaryError("duplicate server operation")
            if operation.heavy and job_store is None:
                raise ServerBoundaryError("heavy operation requires durable job store")
            mapping[operation.operation] = operation
        self._security_policy = security_policy
        self._security_gate = security_gate
        self._operations = mapping
        self._job_store = job_store

    def handle(self, principal: AuthenticatedPrincipal, request: ApiRequest) -> dict[str, object]:
        if type(principal) is not AuthenticatedPrincipal:
            raise ServerBoundaryError("authenticated principal is required")
        if type(request) is not ApiRequest:
            raise ServerBoundaryError("versioned API request is required")
        if request.workspace_id != principal.workspace_id:
            raise ServerBoundaryError("cross-workspace request is forbidden")
        operation = self._operations.get(request.operation)
        if operation is None:
            raise ServerBoundaryError("unsupported server operation")
        if operation.mutates and request.entity is None:
            raise ServerBoundaryError("state-changing request requires entity id and expected revision")
        try:
            self._security_policy.verify_gate(self._security_gate)
            self._security_policy.authorize(SecurityRequest(
                surface=operation.surface,
                operation=operation.operation,
                purpose="product",
                actor_role=_primary_role(principal.roles),
                required_permission=operation.permission if operation.mutates else None,
                granted_permissions=principal.permissions,
                data_classes=operation.data_classes,
                mutates=operation.mutates,
                requested_retention_days=operation.requested_retention_days,
                malware_scan_required=(operation.surface is NetworkSurface.FILE_UPLOAD),
            ))
        except SecurityContractError as error:
            raise ServerBoundaryError(str(error)) from None
        if operation.permission not in principal.permissions:
            raise ServerBoundaryError("operation permission is not granted")
        if operation.heavy:
            assert self._job_store is not None
            return _response(request, {"job": _job_payload(self._job_store.enqueue(request))})
        try:
            value = operation.handler(principal, request.payload, request.entity)
        except ServerBoundaryError:
            raise
        except Exception:
            raise ServerBoundaryError("canonical application operation failed") from None
        if not isinstance(value, Mapping):
            raise ServerBoundaryError("canonical application result must be a mapping")
        clean = _validate_json(dict(value))
        if type(clean) is not dict:
            raise ServerBoundaryError("canonical application result is invalid")
        return _response(request, {"result": clean})

    def job_status(self, principal: AuthenticatedPrincipal, *, job_id: str) -> dict[str, object]:
        if self._job_store is None:
            raise ServerBoundaryError("durable jobs are unavailable")
        job = self._job_store.get(job_id)
        if job.workspace_id != principal.workspace_id:
            raise ServerBoundaryError("cross-workspace job access is forbidden")
        return {"schema_version": API_SCHEMA_VERSION, "job": _job_payload(job)}

    def cancel_job(self, principal: AuthenticatedPrincipal, *, job_id: str) -> dict[str, object]:
        if "jobs.cancel" not in principal.permissions:
            raise ServerBoundaryError("job cancellation permission is not granted")
        if self._job_store is None:
            raise ServerBoundaryError("durable jobs are unavailable")
        current = self._job_store.get(job_id)
        if current.workspace_id != principal.workspace_id:
            raise ServerBoundaryError("cross-workspace job access is forbidden")
        return {
            "schema_version": API_SCHEMA_VERSION,
            "job": _job_payload(self._job_store.request_cancel(job_id)),
        }


def build_application_operations(
    *,
    snapshot: Callable[[], Mapping[str, object]],
    dispatch: Callable[[str, Mapping[str, object]], object],
) -> tuple[ServerOperation, ...]:
    """Bind existing application snapshot/action seams without copying domain logic."""
    if not callable(snapshot) or not callable(dispatch):
        raise ServerBoundaryError("canonical snapshot and dispatch callables are required")

    def query(_principal, payload, entity):
        if payload or entity is not None:
            raise ServerBoundaryError("application snapshot takes no payload/entity")
        value = snapshot()
        if not isinstance(value, Mapping):
            raise ServerBoundaryError("canonical application snapshot must be a mapping")
        return dict(value)

    def command(_principal, payload, _entity):
        if set(payload) != {"action_id", "payload"}:
            raise ServerBoundaryError("application command envelope is invalid")
        action_id = payload["action_id"]
        action_payload = payload["payload"]
        if type(action_id) is not str or _OPERATION_RE.fullmatch(action_id) is None:
            raise ServerBoundaryError("application action id is invalid")
        if type(action_payload) is not dict:
            raise ServerBoundaryError("application action payload must be an object")
        result = dispatch(action_id, action_payload)
        if result is None:
            return {"accepted": True}
        if isinstance(result, Mapping):
            return dict(result)
        if type(result) in {str, int, float, bool}:
            return {"value": result}
        raise ServerBoundaryError("canonical action result is not serializable")

    return (
        ServerOperation("server.application.snapshot", False, "app.read", query),
        ServerOperation("server.application.command", True, "app.write", command),
    )


class AuthenticatedServerAsgi:
    """Strict API transport. Authentication/account issuance remains Section 31."""

    def __init__(self, boundary: ServerApplicationBoundary) -> None:
        if not isinstance(boundary, ServerApplicationBoundary):
            raise TypeError("boundary must be ServerApplicationBoundary")
        self._boundary = boundary

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            return
        try:
            principal = _trusted_principal(scope)
            method = scope.get("method")
            path = scope.get("path")
            if method == "POST" and path in {"/v1/query", "/v1/command"}:
                request = _request_from_wire(_strict_json(await _read_body(receive)))
                await _send_json(send, 200, self._boundary.handle(principal, request))
                return
            if method == "POST" and path == "/v1/jobs/cancel":
                body = _strict_json(await _read_body(receive))
                if set(body) != {"job_id"}:
                    raise ServerBoundaryError("invalid job cancel request")
                await _send_json(send, 200, self._boundary.cancel_job(principal, job_id=body["job_id"]))
                return
            if method == "POST" and path == "/v1/jobs/status":
                body = _strict_json(await _read_body(receive))
                if set(body) != {"job_id"}:
                    raise ServerBoundaryError("invalid job status request")
                await _send_json(send, 200, self._boundary.job_status(principal, job_id=body["job_id"]))
                return
            await _send_json(send, 404, {"ok": False, "error": "Not found."})
        except ServerBoundaryError:
            await _send_json(send, 400, {"ok": False, "error": "Invalid server request."})
        except Exception:
            await _send_json(send, 500, {"ok": False, "error": "The action could not be completed."})


def _trusted_principal(scope: Mapping[str, object]) -> AuthenticatedPrincipal:
    state = scope.get("state")
    if not isinstance(state, Mapping):
        raise ServerBoundaryError("authentication required")
    principal = state.get("accessible_chess_principal")
    if type(principal) is not AuthenticatedPrincipal:
        raise ServerBoundaryError("authentication required")
    return principal


async def _read_body(receive: Callable[[], Awaitable[Mapping[str, object]]]) -> bytes:
    body = bytearray()
    for _ in range(32):
        event = await receive()
        if event.get("type") != "http.request":
            raise ServerBoundaryError("invalid HTTP request")
        chunk = event.get("body", b"")
        if type(chunk) is not bytes:
            raise ServerBoundaryError("invalid HTTP request")
        body.extend(chunk)
        if len(body) > _MAX_BODY:
            raise ServerBoundaryError("request body too large")
        if not event.get("more_body", False):
            return bytes(body)
    raise ServerBoundaryError("too many HTTP request events")


def _strict_json(data: bytes) -> dict[str, object]:
    try:
        text = data.decode("utf-8", errors="strict")
        value = json.loads(
            text, object_pairs_hook=_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, ValueError, TypeError):
        raise ServerBoundaryError("invalid JSON request") from None
    if type(value) is not dict:
        raise ServerBoundaryError("JSON request must be an object")
    return value


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON field")
        value[key] = item
    return value


def _request_from_wire(value: dict[str, object]) -> ApiRequest:
    if set(value) != {"schema_version", "request_id", "workspace_id", "operation", "payload", "entity"}:
        raise ServerBoundaryError("invalid request envelope")
    entity_value = value["entity"]
    if entity_value is None:
        entity = None
    elif type(entity_value) is dict and set(entity_value) == {"entity_id", "revision"}:
        entity = EntityRef(entity_value["entity_id"], entity_value["revision"])
    else:
        raise ServerBoundaryError("invalid entity reference")
    return ApiRequest(
        schema_version=value["schema_version"],
        request_id=value["request_id"],
        workspace_id=value["workspace_id"],
        operation=value["operation"],
        payload=value["payload"],
        entity=entity,
    )


async def _send_json(send, status: int, value: object) -> None:
    body = _json_text(value).encode("utf-8")
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"content-length", str(len(body)).encode("ascii")),
            (b"cache-control", b"no-store"),
            (b"x-content-type-options", b"nosniff"),
            (b"referrer-policy", b"no-referrer"),
        ],
    })
    await send({"type": "http.response.body", "body": body})


def _response(request: ApiRequest, body: Mapping[str, object]) -> dict[str, object]:
    result = {
        "schema_version": API_SCHEMA_VERSION,
        "request_id": request.request_id,
        "workspace_id": request.workspace_id,
    }
    result.update(body)
    return result


def _job_payload(job: JobRecord) -> dict[str, object]:
    return {
        "job_id": job.job_id,
        "request_id": job.request_id,
        "workspace_id": job.workspace_id,
        "operation": job.operation,
        "state": job.state.value,
        "progress": job.progress,
        "attempts": job.attempts,
        "cancel_requested": job.cancel_requested,
        "result": None if job.result is None else dict(job.result),
        "error_code": job.error_code,
    }


def _primary_role(roles: frozenset[str]) -> str:
    for role in ("admin", "teacher", "co_teacher", "student", "observer", "user"):
        if role in roles:
            return role
    return sorted(roles)[0] if roles else "user"


def _id(value: object, label: str) -> str:
    if type(value) is not str or _ID_RE.fullmatch(value) is None:
        raise ServerBoundaryError(f"invalid {label}")
    return value


def _operation(value: object) -> str:
    if type(value) is not str or _OPERATION_RE.fullmatch(value) is None:
        raise ServerBoundaryError("invalid operation id")
    return value


def _validate_json(value: object, *, depth: int = 0) -> object:
    if depth > _MAX_DEPTH:
        raise ServerBoundaryError("JSON value is too deeply nested")
    if value is None or type(value) in {bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ServerBoundaryError("non-finite JSON number")
        return value
    if type(value) is str:
        if len(value) > _MAX_TEXT or "\x00" in value:
            raise ServerBoundaryError("invalid JSON text")
        return value
    if type(value) in {list, tuple}:
        if len(value) > _MAX_CONTAINER_ITEMS:
            raise ServerBoundaryError("too many JSON items")
        return [_validate_json(item, depth=depth + 1) for item in value]
    if isinstance(value, Mapping):
        if len(value) > _MAX_PAYLOAD_KEYS:
            raise ServerBoundaryError("too many JSON fields")
        result: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str or not key or len(key) > 96 or "\x00" in key:
                raise ServerBoundaryError("invalid JSON field")
            result[key] = _validate_json(item, depth=depth + 1)
        return result
    raise ServerBoundaryError("unsupported JSON value")


def _json_text(value: object) -> str:
    clean = _validate_json(value)
    return json.dumps(
        clean, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )


__all__ = [
    "API_SCHEMA_VERSION", "ApiRequest", "AuthenticatedPrincipal",
    "AuthenticatedServerAsgi", "EntityRef", "JobRecord", "JobState",
    "ServerApplicationBoundary", "ServerBoundaryError", "ServerOperation",
    "SqliteJobStore", "build_application_operations",
]
