from __future__ import annotations

"""Crash-safe local persistence for one canonical TeachingSession.

The store owns no chess, lesson, Classroom, or presentation semantics. It only
publishes a validated LessonSession + TeachingSessionState pair atomically so
the one local V2 application can recover an interrupted lesson after restart.
"""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Mapping

from .teaching_session import LessonSession, TeachingSessionError, TeachingSessionState


TEACHING_SESSION_STORE_VERSION = 1
MAX_TEACHING_SESSION_STORE_BYTES = 4_000_000
MAX_WIRE_INTEGER = (1 << 53) - 1
_ENVELOPE_FIELDS = frozenset({"schema_version", "plan", "state"})


class TeachingSessionConflictError(RuntimeError):
    """Durable state changed after the caller observed it."""


class TeachingSessionBusyError(RuntimeError):
    """Another writer owns the publication lock."""


class TeachingSessionStoreError(ValueError):
    """Malformed, unsupported, oversized, or non-canonical durable state."""


@dataclass(frozen=True)
class LoadedTeachingSession:
    plan: LessonSession
    state: TeachingSessionState
    revision: str


def _canonical_bytes(payload: Mapping[str, object]) -> bytes:
    try:
        text = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        data = text.encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise TeachingSessionStoreError(
            "teaching session cannot be serialized for durable storage"
        ) from exc
    if len(data) > MAX_TEACHING_SESSION_STORE_BYTES:
        raise TeachingSessionStoreError("teaching session store exceeds size limit")
    return data


def _revision(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_revision(value: object) -> str | None:
    if value is None:
        return None
    if (
        type(value) is not str
        or len(value) != 64
        or value != value.lower()
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise TeachingSessionStoreError(
            "expected revision must be a lowercase SHA-256 digest or null"
        )
    return value


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise TeachingSessionStoreError(f"duplicate durable JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise TeachingSessionStoreError(
        f"non-finite durable JSON constant is not allowed: {value}"
    )


def _parse_wire_integer(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if not digits or len(digits) > 16:
        raise TeachingSessionStoreError(
            "durable JSON integer exceeds exact wire bounds"
        )
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise TeachingSessionStoreError("invalid durable JSON integer") from exc
    if not -MAX_WIRE_INTEGER <= parsed <= MAX_WIRE_INTEGER:
        raise TeachingSessionStoreError(
            "durable JSON integer exceeds exact wire bounds"
        )
    return parsed


def _validate_pair(
    plan: LessonSession,
    state: TeachingSessionState,
) -> tuple[LessonSession, TeachingSessionState]:
    try:
        canonical_plan = LessonSession.from_record(plan.to_record())
        canonical_state = TeachingSessionState.from_record(state.to_record())
    except TeachingSessionError as exc:
        raise TeachingSessionStoreError(
            "teaching session is not canonical"
        ) from exc
    if canonical_state.session_id != canonical_plan.session_id:
        raise TeachingSessionStoreError(
            "teaching state belongs to another lesson session"
        )
    if canonical_state.plan_digest != canonical_plan.digest:
        raise TeachingSessionStoreError(
            "teaching state plan digest does not match lesson session"
        )
    if canonical_state.step_index >= len(canonical_plan.steps):
        raise TeachingSessionStoreError(
            "teaching state step is outside lesson session"
        )
    return canonical_plan, canonical_state


class TeachingSessionStore:
    """Atomic single-session file store with exact file-level CAS."""

    def __init__(self, path: str | Path) -> None:
        if not isinstance(path, (str, Path)):
            raise TypeError("path must be a filesystem path")
        self.path = Path(path).expanduser()
        if str(self.path) in {"", "."}:
            raise ValueError("path must identify a teaching session file")
        self._lock_path = self.path.with_name(f".{self.path.name}.lock")

    def _read_current_bytes(self) -> bytes | None:
        try:
            with self.path.open("rb") as handle:
                data = handle.read(MAX_TEACHING_SESSION_STORE_BYTES + 1)
        except FileNotFoundError:
            return None
        if len(data) > MAX_TEACHING_SESSION_STORE_BYTES:
            raise TeachingSessionStoreError("teaching session store exceeds size limit")
        return data

    def load(self) -> LoadedTeachingSession | None:
        data = self._read_current_bytes()
        if data is None:
            return None
        try:
            payload = json.loads(
                data.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_pairs,
                parse_constant=_reject_constant,
                parse_int=_parse_wire_integer,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise TeachingSessionStoreError("invalid teaching session store") from exc
        if type(payload) is not dict or set(payload) != _ENVELOPE_FIELDS:
            raise TeachingSessionStoreError("invalid teaching session store envelope")
        schema = payload["schema_version"]
        if type(schema) is not int or schema != TEACHING_SESSION_STORE_VERSION:
            raise TeachingSessionStoreError(
                f"unsupported teaching session store schema version: {schema!r}"
            )
        raw_plan = payload["plan"]
        raw_state = payload["state"]
        if not isinstance(raw_plan, Mapping) or not isinstance(raw_state, Mapping):
            raise TeachingSessionStoreError(
                "teaching session plan/state payloads must be objects"
            )
        try:
            plan = LessonSession.from_record(raw_plan)
            state = TeachingSessionState.from_record(raw_state)
        except TeachingSessionError as exc:
            raise TeachingSessionStoreError(
                "invalid teaching session payload"
            ) from exc
        plan, state = _validate_pair(plan, state)
        return LoadedTeachingSession(plan, state, _revision(data))

    def save(
        self,
        plan: LessonSession,
        state: TeachingSessionState,
        *,
        expected_revision: str | None,
    ) -> str:
        if type(plan) is not LessonSession or type(state) is not TeachingSessionState:
            raise TypeError("plan/state must be canonical teaching session values")
        plan, state = _validate_pair(plan, state)
        expected = _validate_revision(expected_revision)
        data = _canonical_bytes(
            {
                "schema_version": TEACHING_SESSION_STORE_VERSION,
                "plan": plan.to_record(),
                "state": state.to_record(),
            }
        )
        new_revision = _revision(data)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._acquire_lock()
        temporary: Path | None = None
        try:
            current_data = self._read_current_bytes()
            current_revision = None if current_data is None else _revision(current_data)
            if current_revision != expected:
                raise TeachingSessionConflictError(
                    "teaching session changed since the caller last observed it"
                )
            fd, raw_path = tempfile.mkstemp(
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                dir=str(self.path.parent),
            )
            temporary = Path(raw_path)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                if temporary.exists():
                    temporary.unlink()
                temporary = None
                raise
            os.replace(temporary, self.path)
            temporary = None
            return new_revision
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
            self._release_lock()

    def clear(self, *, expected_revision: str) -> None:
        expected = _validate_revision(expected_revision)
        if expected is None:
            raise TeachingSessionStoreError(
                "clear requires the exact observed teaching session revision"
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._acquire_lock()
        try:
            current_data = self._read_current_bytes()
            current_revision = None if current_data is None else _revision(current_data)
            if current_revision != expected:
                raise TeachingSessionConflictError(
                    "teaching session changed since the caller last observed it"
                )
            try:
                self.path.unlink()
            except FileNotFoundError as exc:
                raise TeachingSessionConflictError(
                    "teaching session disappeared before clear"
                ) from exc
        finally:
            self._release_lock()

    def _acquire_lock(self) -> None:
        try:
            self._lock_path.mkdir()
        except FileExistsError as exc:
            raise TeachingSessionBusyError("teaching session store is busy") from exc

    def _release_lock(self) -> None:
        try:
            self._lock_path.rmdir()
        except FileNotFoundError:
            pass
