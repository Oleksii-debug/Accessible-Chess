"""Fail-closed remote connectivity boundary for Accessible Chess teaching sessions.

This module owns wire validation, authenticated remote identity and transport
configuration. It deliberately does not own classroom membership, teaching
state, chess rules, or durable remote-session state. Those stay with the
canonical Product authorities and :mod:`acs.remote_session`.

Credentials are injected at runtime and are never serialized by the types in
this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import re
import socket
import ssl
import struct
from typing import Any, Mapping, Protocol

from .classroom_domain import ClassroomSnapshot
from .remote_session import RemoteSessionError, RemoteSessionEvent, RemoteSessionLog
from .teaching_session import LessonSession


REMOTE_PROTOCOL_VERSION = 1
MAX_REMOTE_ENVELOPE_BYTES = 64 * 1024
MAX_REMOTE_PAYLOAD_BYTES = 48 * 1024
MAX_REMOTE_ID_LENGTH = 128
MAX_REMOTE_HOST_LENGTH = 253
MAX_REMOTE_SECRET_LENGTH = 4096
DEFAULT_CONNECT_TIMEOUT_SECONDS = 5.0
DEFAULT_REQUEST_TIMEOUT_SECONDS = 5.0

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
_HEX_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class RemoteConnectivityError(ValueError):
    """Stable remote-boundary failure whose message is safe for user logs."""


class RemoteRole(str, Enum):
    TEACHER = "teacher"
    STUDENT = "student"


class RemoteMessageKind(str, Enum):
    EVENT = "event"
    ACK = "ack"
    RESUME = "resume"
    LEAVE = "leave"
    ERROR = "error"


class RemoteIngressDisposition(str, Enum):
    APPLIED = "applied"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    class_id: str
    session_id: str
    person_id: str
    role: RemoteRole

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_id", _remote_id(self.class_id, "class id"))
        object.__setattr__(self, "session_id", _remote_id(self.session_id, "session id"))
        object.__setattr__(self, "person_id", _remote_id(self.person_id, "person id"))
        try:
            role = RemoteRole(self.role)
        except (TypeError, ValueError) as exc:
            raise RemoteConnectivityError("remote role is unsupported") from exc
        object.__setattr__(self, "role", role)

    def to_claims(self) -> dict[str, str]:
        return {
            "class_id": self.class_id,
            "session_id": self.session_id,
            "person_id": self.person_id,
            "role": self.role.value,
        }

    @classmethod
    def from_claims(cls, value: object) -> "AuthenticatedPrincipal":
        data = _mapping(value, "authenticated claims")
        _exact_keys(
            data,
            {"class_id", "session_id", "person_id", "role"},
            "authenticated claims",
        )
        return cls(data["class_id"], data["session_id"], data["person_id"], data["role"])


@dataclass(frozen=True, slots=True)
class RemoteEndpointProfile:
    """Non-secret connection profile safe for ordinary configuration storage."""

    profile_id: str
    host: str
    port: int
    server_name: str
    credential_key: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_id", _remote_id(self.profile_id, "profile id"))
        host = _host(self.host, "remote host")
        server_name = _host(self.server_name, "TLS server name")
        if type(self.port) is not int or isinstance(self.port, bool) or not (1 <= self.port <= 65535):
            raise RemoteConnectivityError("remote port is invalid")
        object.__setattr__(self, "host", host)
        object.__setattr__(self, "server_name", server_name)
        object.__setattr__(self, "credential_key", _remote_id(self.credential_key, "credential key"))

    def to_record(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "host": self.host,
            "port": self.port,
            "server_name": self.server_name,
            "credential_key": self.credential_key,
        }

    @classmethod
    def from_record(cls, value: object) -> "RemoteEndpointProfile":
        data = _mapping(value, "remote endpoint profile")
        _exact_keys(
            data,
            {"profile_id", "host", "port", "server_name", "credential_key"},
            "remote endpoint profile",
        )
        return cls(
            data["profile_id"],
            data["host"],
            data["port"],
            data["server_name"],
            data["credential_key"],
        )


@dataclass(frozen=True, slots=True)
class RemoteEnvelope:
    version: int
    kind: RemoteMessageKind
    message_id: str
    session_id: str
    actor_id: str
    role: RemoteRole
    sequence: int | None
    payload: Mapping[str, Any]
    checkpoint_digest: str | None = None

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != REMOTE_PROTOCOL_VERSION:
            raise RemoteConnectivityError("remote protocol version is unsupported")
        try:
            kind = RemoteMessageKind(self.kind)
            role = RemoteRole(self.role)
        except (TypeError, ValueError) as exc:
            raise RemoteConnectivityError("remote envelope enum value is unsupported") from exc
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "message_id", _remote_id(self.message_id, "message id"))
        object.__setattr__(self, "session_id", _remote_id(self.session_id, "session id"))
        object.__setattr__(self, "actor_id", _remote_id(self.actor_id, "actor id"))
        if self.sequence is not None and (
            type(self.sequence) is not int
            or isinstance(self.sequence, bool)
            or self.sequence < 0
        ):
            raise RemoteConnectivityError("remote sequence is invalid")
        if kind is RemoteMessageKind.EVENT and (
            type(self.sequence) is not int
            or isinstance(self.sequence, bool)
            or self.sequence < 1
        ):
            raise RemoteConnectivityError("remote event sequence is invalid")
        payload = _json_object(self.payload, "remote payload")
        if len(_canonical_json(payload)) > MAX_REMOTE_PAYLOAD_BYTES:
            raise RemoteConnectivityError("remote payload exceeds size limit")
        object.__setattr__(self, "payload", payload)
        if self.checkpoint_digest is not None:
            if (
                type(self.checkpoint_digest) is not str
                or not _HEX_DIGEST_RE.fullmatch(self.checkpoint_digest)
            ):
                raise RemoteConnectivityError("checkpoint digest is invalid")
        if len(self.to_json_bytes()) > MAX_REMOTE_ENVELOPE_BYTES:
            raise RemoteConnectivityError("remote envelope exceeds size limit")

    def to_record(self) -> dict[str, object]:
        return {
            "version": self.version,
            "kind": self.kind.value,
            "message_id": self.message_id,
            "session_id": self.session_id,
            "actor_id": self.actor_id,
            "role": self.role.value,
            "sequence": self.sequence,
            "payload": _copy_json(self.payload),
            "checkpoint_digest": self.checkpoint_digest,
        }

    def to_json_bytes(self) -> bytes:
        return _canonical_json(self.to_record())

    @classmethod
    def from_record(cls, value: object) -> "RemoteEnvelope":
        data = _mapping(value, "remote envelope")
        _exact_keys(
            data,
            {
                "version",
                "kind",
                "message_id",
                "session_id",
                "actor_id",
                "role",
                "sequence",
                "payload",
                "checkpoint_digest",
            },
            "remote envelope",
        )
        return cls(
            data["version"],
            data["kind"],
            data["message_id"],
            data["session_id"],
            data["actor_id"],
            data["role"],
            data["sequence"],
            data["payload"],
            data["checkpoint_digest"],
        )

    @classmethod
    def from_json_bytes(cls, value: bytes) -> "RemoteEnvelope":
        if type(value) is not bytes or len(value) > MAX_REMOTE_ENVELOPE_BYTES:
            raise RemoteConnectivityError("remote envelope bytes are invalid")
        try:
            text = value.decode("utf-8", errors="strict")
            data = json.loads(
                text,
                object_pairs_hook=_reject_duplicate_pairs,
                parse_constant=_reject_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RemoteConnectivityError("remote envelope JSON is invalid") from exc
        return cls.from_record(data)


class SecretProvider(Protocol):
    def get_secret(self, credential_key: str) -> str | None:
        """Return one runtime secret, or ``None`` when it is unavailable."""


class MembershipAuthorizer(Protocol):
    def authorize(self, principal: AuthenticatedPrincipal) -> bool:
        """Consult the canonical Product membership/role authority."""


@dataclass(frozen=True, slots=True)
class RemoteConnectionContext:
    principal: AuthenticatedPrincipal
    protocol_version: int = REMOTE_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.principal, AuthenticatedPrincipal):
            raise RemoteConnectivityError("authenticated principal is unavailable")
        if self.protocol_version != REMOTE_PROTOCOL_VERSION:
            raise RemoteConnectivityError("remote protocol version is unsupported")


class CanonicalStudentAuthorizer:
    """Student membership adapter over existing LessonSession/ClassroomSnapshot.

    Teacher identity is intentionally not inferred here: the existing classroom
    adapter receives teacher identity out-of-band, so a separate trusted Product
    authority must authorize teacher principals.
    """

    def __init__(
        self,
        plan: LessonSession,
        classroom: ClassroomSnapshot,
        class_id: str,
    ) -> None:
        if type(plan) is not LessonSession or type(classroom) is not ClassroomSnapshot:
            raise RemoteConnectivityError("canonical classroom authority is unavailable")
        self._plan = plan
        self._classroom = classroom
        self._class_id = _remote_id(class_id, "class id")

    def authorize(self, principal: AuthenticatedPrincipal) -> bool:
        if not isinstance(principal, AuthenticatedPrincipal):
            return False
        if principal.role is not RemoteRole.STUDENT:
            return False
        if principal.class_id != self._class_id or principal.session_id != self._plan.session_id:
            return False
        if principal.person_id not in self._plan.student_ids:
            return False
        return any(
            item.student_id == principal.person_id and not item.deleted
            for item in self._classroom.students
        )


def require_runtime_secret(provider: SecretProvider, credential_key: str) -> str:
    if provider is None or not callable(getattr(provider, "get_secret", None)):
        raise RemoteConnectivityError("remote credentials are unavailable")
    try:
        secret = provider.get_secret(_remote_id(credential_key, "credential key"))
    except Exception as exc:
        raise RemoteConnectivityError("remote credentials are unavailable") from exc
    if type(secret) is not str or not secret or secret != secret.strip():
        raise RemoteConnectivityError("remote credentials are unavailable")
    if len(secret.encode("utf-8")) > MAX_REMOTE_SECRET_LENGTH:
        raise RemoteConnectivityError("remote credentials are unavailable")
    return secret


def event_envelope(
    event: RemoteSessionEvent,
    principal: AuthenticatedPrincipal,
) -> RemoteEnvelope:
    if not isinstance(event, RemoteSessionEvent) or not isinstance(principal, AuthenticatedPrincipal):
        raise RemoteConnectivityError("remote event context is invalid")
    if event.session_id != principal.session_id or event.actor_id != principal.person_id:
        raise RemoteConnectivityError("remote event identity does not match authenticated principal")
    return RemoteEnvelope(
        REMOTE_PROTOCOL_VERSION,
        RemoteMessageKind.EVENT,
        event.event_id,
        event.session_id,
        principal.person_id,
        principal.role,
        event.sequence,
        event.to_record(),
    )


class RemoteIngressGuard:
    """Authorize a wire event before delegating mutation to RemoteSessionLog."""

    def __init__(self, log: RemoteSessionLog, authorizer: MembershipAuthorizer) -> None:
        if not isinstance(log, RemoteSessionLog):
            raise RemoteConnectivityError("remote session log is unavailable")
        if authorizer is None or not callable(getattr(authorizer, "authorize", None)):
            raise RemoteConnectivityError("remote membership authority is unavailable")
        self._log = log
        self._authorizer = authorizer

    def apply(
        self,
        envelope: RemoteEnvelope,
        context: RemoteConnectionContext,
    ) -> RemoteIngressDisposition:
        if not isinstance(envelope, RemoteEnvelope) or not isinstance(context, RemoteConnectionContext):
            raise RemoteConnectivityError("remote ingress context is invalid")
        principal = context.principal
        if (
            envelope.session_id != principal.session_id
            or envelope.actor_id != principal.person_id
            or envelope.role is not principal.role
        ):
            raise RemoteConnectivityError("remote envelope identity is not authorized")
        try:
            authorized = self._authorizer.authorize(principal)
        except Exception as exc:
            raise RemoteConnectivityError("remote membership could not be verified") from exc
        if authorized is not True:
            raise RemoteConnectivityError("remote participant is not authorized")
        if envelope.kind is not RemoteMessageKind.EVENT:
            raise RemoteConnectivityError("remote message cannot mutate canonical session state")
        try:
            event = RemoteSessionEvent.from_record(envelope.payload)
        except (RemoteSessionError, TypeError, ValueError) as exc:
            raise RemoteConnectivityError("remote event payload is invalid") from exc
        if (
            event.event_id != envelope.message_id
            or event.session_id != envelope.session_id
            or event.sequence != envelope.sequence
            or event.actor_id != envelope.actor_id
        ):
            raise RemoteConnectivityError("remote event envelope does not match canonical event")
        try:
            applied = self._log.append(event)
        except RemoteSessionError as exc:
            raise RemoteConnectivityError("remote event is stale, out of order, or invalid") from exc
        return (
            RemoteIngressDisposition.APPLIED
            if applied
            else RemoteIngressDisposition.DUPLICATE
        )


@dataclass(frozen=True, slots=True)
class RemoteRetryPolicy:
    max_attempts: int = 3
    connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS
    initial_backoff_seconds: float = 0.25
    max_backoff_seconds: float = 2.0

    def __post_init__(self) -> None:
        if (
            type(self.max_attempts) is not int
            or isinstance(self.max_attempts, bool)
            or not (1 <= self.max_attempts <= 5)
        ):
            raise RemoteConnectivityError("remote retry attempt count is invalid")
        for name in (
            "connect_timeout_seconds",
            "request_timeout_seconds",
            "initial_backoff_seconds",
            "max_backoff_seconds",
        ):
            value = getattr(self, name)
            if (
                type(value) not in {int, float}
                or isinstance(value, bool)
                or value <= 0
                or value > 30
            ):
                raise RemoteConnectivityError("remote retry timing is invalid")
        if self.initial_backoff_seconds > self.max_backoff_seconds:
            raise RemoteConnectivityError("remote retry backoff is invalid")


class TlsRelayClient:
    """Bounded authenticated TLS client for a self-hosted Accessible Chess relay.

    Frames are a four-byte big-endian length followed by strict UTF-8 JSON. The
    relay protocol never falls back to another endpoint or to plaintext.
    """

    def __init__(
        self,
        profile: RemoteEndpointProfile,
        policy: RemoteRetryPolicy | None = None,
    ) -> None:
        if not isinstance(profile, RemoteEndpointProfile):
            raise RemoteConnectivityError("remote endpoint profile is invalid")
        self._profile = profile
        self._policy = policy or RemoteRetryPolicy()
        self._socket: ssl.SSLSocket | None = None

    def connect(
        self,
        principal: AuthenticatedPrincipal,
        secret: str,
    ) -> RemoteConnectionContext:
        if not isinstance(principal, AuthenticatedPrincipal):
            raise RemoteConnectivityError("remote principal is invalid")
        if (
            type(secret) is not str
            or not secret
            or secret != secret.strip()
            or len(secret.encode("utf-8")) > MAX_REMOTE_SECRET_LENGTH
        ):
            raise RemoteConnectivityError("remote credentials are unavailable")
        if self._socket is not None:
            raise RemoteConnectivityError("remote connection is already active")
        raw: socket.socket | None = None
        tls: ssl.SSLSocket | None = None
        try:
            raw = socket.create_connection(
                (self._profile.host, self._profile.port),
                timeout=self._policy.connect_timeout_seconds,
            )
            context = ssl.create_default_context()
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.check_hostname = True
            context.verify_mode = ssl.CERT_REQUIRED
            tls = context.wrap_socket(raw, server_hostname=self._profile.server_name)
            tls.settimeout(self._policy.request_timeout_seconds)
            request = {
                "version": REMOTE_PROTOCOL_VERSION,
                "kind": "authenticate",
                "claims": principal.to_claims(),
                "credential": secret,
            }
            _send_frame(tls, _canonical_json(request))
            response = _receive_json_frame(tls)
            _exact_keys(
                response,
                {"version", "kind", "claims"},
                "remote authentication response",
            )
            if (
                response["version"] != REMOTE_PROTOCOL_VERSION
                or response["kind"] != "authenticated"
            ):
                raise RemoteConnectivityError("remote authentication failed")
            verified = AuthenticatedPrincipal.from_claims(response["claims"])
            if verified != principal:
                raise RemoteConnectivityError("remote authenticated identity mismatch")
            self._socket = tls
            tls = None
            return RemoteConnectionContext(verified)
        except RemoteConnectivityError:
            raise
        except (OSError, ssl.SSLError, TimeoutError) as exc:
            raise RemoteConnectivityError("remote endpoint is unavailable") from exc
        finally:
            if tls is not None:
                tls.close()
            elif raw is not None and self._socket is None:
                raw.close()

    def exchange(self, envelope: RemoteEnvelope) -> RemoteEnvelope:
        if self._socket is None:
            raise RemoteConnectivityError("remote connection is unavailable")
        try:
            _send_frame(self._socket, envelope.to_json_bytes())
            return RemoteEnvelope.from_json_bytes(_receive_frame(self._socket))
        except RemoteConnectivityError:
            self.close()
            raise
        except (OSError, ssl.SSLError, TimeoutError) as exc:
            self.close()
            raise RemoteConnectivityError("remote endpoint is unavailable") from exc

    def close(self) -> None:
        sock = self._socket
        self._socket = None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()


def _send_frame(sock: socket.socket, body: bytes) -> None:
    if type(body) is not bytes or not body or len(body) > MAX_REMOTE_ENVELOPE_BYTES:
        raise RemoteConnectivityError("remote frame is invalid")
    sock.sendall(struct.pack("!I", len(body)) + body)


def _receive_frame(sock: socket.socket) -> bytes:
    header = _recv_exact(sock, 4)
    length = struct.unpack("!I", header)[0]
    if length < 1 or length > MAX_REMOTE_ENVELOPE_BYTES:
        raise RemoteConnectivityError("remote frame size is invalid")
    return _recv_exact(sock, length)


def _receive_json_frame(sock: socket.socket) -> dict[str, Any]:
    body = _receive_frame(sock)
    try:
        data = json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RemoteConnectivityError("remote authentication response is invalid") from exc
    return dict(_mapping(data, "remote authentication response"))


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise RemoteConnectivityError("remote connection closed unexpectedly")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _remote_id(value: object, label: str) -> str:
    if (
        type(value) is not str
        or len(value) > MAX_REMOTE_ID_LENGTH
        or not _ID_RE.fullmatch(value)
    ):
        raise RemoteConnectivityError(f"{label} is invalid")
    return value


def _host(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > MAX_REMOTE_HOST_LENGTH
        or not _HOST_RE.fullmatch(value)
    ):
        raise RemoteConnectivityError(f"{label} is invalid")
    return value.lower()


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise RemoteConnectivityError(f"{label} must be an object")
    return value


def _exact_keys(data: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(data) != expected:
        raise RemoteConnectivityError(f"{label} shape is invalid")


def _json_object(value: object, label: str) -> dict[str, Any]:
    data = _mapping(value, label)
    try:
        encoded = _canonical_json(data)
        decoded = json.loads(encoded.decode("utf-8"), parse_constant=_reject_constant)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise RemoteConnectivityError(f"{label} is not canonical JSON") from exc
    if not isinstance(decoded, dict):
        raise RemoteConnectivityError(f"{label} must be an object")
    return decoded


def _copy_json(value: object) -> Any:
    return json.loads(
        _canonical_json(value).decode("utf-8"),
        parse_constant=_reject_constant,
    )


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise RemoteConnectivityError("remote JSON value is invalid") from exc


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RemoteConnectivityError("remote JSON contains duplicate keys")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise RemoteConnectivityError("remote JSON contains a non-finite number")
