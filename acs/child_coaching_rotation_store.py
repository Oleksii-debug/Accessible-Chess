from __future__ import annotations

"""Atomic local persistence for one child-coaching rotation session."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Mapping

from .child_coaching_store import (
    _StoreLockBusy,
    _exclusive_store_lock,
    _sync_directory,
)
from .child_coaching_rotation import (
    ChildCoachingRotationError,
    RotationActivity,
    RotationPhase,
    RotationPlan,
    RotationState,
    current_round,
)

ROTATION_STORE_SCHEMA_VERSION = 1
MAX_ROTATION_STORE_BYTES = 1_000_000
MAX_WIRE_INTEGER = (1 << 53) - 1
_ENVELOPE_FIELDS = frozenset({"schema_version", "plan", "state"})
_PLATFORM_PATH_TYPE = type(Path())


class ChildCoachingRotationStoreError(ValueError):
    """Malformed or unsupported durable rotation data."""


class ChildCoachingRotationStoreConflictError(RuntimeError):
    """Durable rotation changed since the caller observed it."""


class ChildCoachingRotationStoreBusyError(RuntimeError):
    """Another writer currently owns the rotation publication lock."""


@dataclass(frozen=True, slots=True)
class LoadedRotationSession:
    plan: RotationPlan
    state: RotationState
    revision: str


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
        raise ChildCoachingRotationStoreError(
            "expected revision must be a lowercase SHA-256 digest or null"
        )
    return value


def _canonical_bytes(plan: RotationPlan, state: RotationState) -> bytes:
    _validate_pair(plan, state)
    payload = {
        "schema_version": ROTATION_STORE_SCHEMA_VERSION,
        "plan": plan.to_record(),
        "state": state.to_record(),
    }
    try:
        data = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise ChildCoachingRotationStoreError(
            "rotation session cannot be serialized"
        ) from exc
    if len(data) > MAX_ROTATION_STORE_BYTES:
        raise ChildCoachingRotationStoreError("rotation store exceeds size limit")
    return data


def _reachable_revision(plan: RotationPlan, state: RotationState) -> int:
    """Return the only revision reachable through the canonical transition API."""

    if state.phase is RotationPhase.PLANNED:
        return 0

    # start_rotation() publishes ACTIVE round zero at revision 1. Every completed
    # prior round contributes one advance, while every prior pair-play round also
    # contributes its mandatory bind before that advance.
    expected = 1 + state.round_index
    expected += sum(
        1
        for item in plan.rounds[: state.round_index]
        if item.activity is RotationActivity.PAIR_PLAY
    )

    item = plan.rounds[state.round_index]
    if state.phase is RotationPhase.COMPLETED:
        # Completion is the final round's advance. A final pair-play round must
        # also have been bound before that advance, even though completion clears
        # the opaque batch reference from durable state.
        expected += 1
        if item.activity is RotationActivity.PAIR_PLAY:
            expected += 1
    elif (
        item.activity is RotationActivity.PAIR_PLAY
        and state.pair_play_batch_ref is not None
    ):
        # The current pair-play binding is itself one canonical transition.
        expected += 1
    return expected


def _validate_pair(plan: RotationPlan, state: RotationState) -> None:
    if type(plan) is not RotationPlan or type(state) is not RotationState:
        raise TypeError("rotation store requires RotationPlan and RotationState")
    if state.rotation_id != plan.rotation_id or state.plan_digest != plan.digest:
        raise ChildCoachingRotationStoreError("rotation state does not match plan")
    if state.phase is not RotationPhase.COMPLETED:
        try:
            item = current_round(plan, state)
        except ChildCoachingRotationError as exc:
            raise ChildCoachingRotationStoreError(
                "rotation state is outside plan bounds"
            ) from exc
        if (
            state.pair_play_batch_ref is not None
            and item.activity is not RotationActivity.PAIR_PLAY
        ):
            raise ChildCoachingRotationStoreError(
                "pair-play reference is attached to a non-pair-play round"
            )
    elif state.round_index != len(plan.rounds) - 1:
        raise ChildCoachingRotationStoreError(
            "completed rotation must reference the final plan round"
        )

    if state.revision != _reachable_revision(plan, state):
        raise ChildCoachingRotationStoreError(
            "rotation state revision is unreachable for the plan"
        )


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ChildCoachingRotationStoreError(
                f"duplicate durable rotation JSON key: {key}"
            )
        result[key] = value
    return result


def _reject_constant(value):
    raise ChildCoachingRotationStoreError(
        f"non-finite durable rotation JSON constant: {value}"
    )


def _parse_wire_integer(value: str) -> int:
    digits = value[1:] if value.startswith("-") else value
    if not digits or len(digits) > 16:
        raise ChildCoachingRotationStoreError(
            "durable rotation JSON integer exceeds exact wire bounds"
        )
    parsed = int(value, 10)
    if not -MAX_WIRE_INTEGER <= parsed <= MAX_WIRE_INTEGER:
        raise ChildCoachingRotationStoreError(
            "durable rotation JSON integer exceeds exact wire bounds"
        )
    return parsed


class ChildCoachingRotationStore:
    """Atomic file store with exact file-level compare-and-swap."""

    def __init__(self, path: str | Path) -> None:
        if type(path) is str:
            candidate = Path(path)
        elif type(path) is _PLATFORM_PATH_TYPE:
            candidate = path
        else:
            raise TypeError("path must be built-in text or an exact platform Path")
        self.path = candidate.expanduser()
        if str(self.path) in {"", "."}:
            raise ValueError("path must identify a rotation session file")
        self._lock_path = self.path.with_name(f".{self.path.name}.lock")

    def _read_current(self) -> bytes | None:
        try:
            with self.path.open("rb") as handle:
                data = handle.read(MAX_ROTATION_STORE_BYTES + 1)
        except FileNotFoundError:
            return None
        if len(data) > MAX_ROTATION_STORE_BYTES:
            raise ChildCoachingRotationStoreError("rotation store exceeds size limit")
        return data

    def load(self) -> LoadedRotationSession | None:
        data = self._read_current()
        if data is None:
            return None
        try:
            payload = json.loads(
                data.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_pairs,
                parse_constant=_reject_constant,
                parse_int=_parse_wire_integer,
            )
        except ChildCoachingRotationStoreError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise ChildCoachingRotationStoreError("invalid rotation store") from exc
        if type(payload) is not dict or set(payload) != _ENVELOPE_FIELDS:
            raise ChildCoachingRotationStoreError("invalid rotation store envelope")
        schema = payload["schema_version"]
        if type(schema) is not int or schema != ROTATION_STORE_SCHEMA_VERSION:
            raise ChildCoachingRotationStoreError(
                f"unsupported rotation store schema version: {schema!r}"
            )
        if not isinstance(payload["plan"], Mapping) or not isinstance(payload["state"], Mapping):
            raise ChildCoachingRotationStoreError("rotation plan/state must be objects")
        try:
            plan = RotationPlan.from_record(payload["plan"])
            state = RotationState.from_record(payload["state"])
        except ChildCoachingRotationError as exc:
            raise ChildCoachingRotationStoreError(
                "invalid rotation plan/state payload"
            ) from exc
        _validate_pair(plan, state)
        return LoadedRotationSession(
            plan=plan,
            state=state,
            revision=_revision(data),
        )

    def save(
        self,
        plan: RotationPlan,
        state: RotationState,
        *,
        expected_revision: str | None,
    ) -> str:
        expected = _validate_revision(expected_revision)
        data = _canonical_bytes(plan, state)
        new_revision = _revision(data)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with _exclusive_store_lock(self._lock_path):
                temporary: Path | None = None
                try:
                    current = self._read_current()
                    current_revision = None if current is None else _revision(current)
                    if current_revision != expected:
                        raise ChildCoachingRotationStoreConflictError(
                            "rotation session changed since the caller last observed it"
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

                    # The lock coordinates canonical writers, but the file can
                    # still be changed by a non-cooperating process while this
                    # writer prepares/fsyncs its private temp. Re-check the exact
                    # target generation immediately before publication so stale
                    # prepared state never silently replaces a newer/foreign one.
                    latest = self._read_current()
                    latest_revision = None if latest is None else _revision(latest)
                    if latest_revision != expected:
                        raise ChildCoachingRotationStoreConflictError(
                            "rotation session changed since the caller last observed it"
                        )

                    os.replace(temporary, self.path)
                    temporary = None
                    _sync_directory(self.path.parent)
                    return new_revision
                finally:
                    if temporary is not None and temporary.exists():
                        temporary.unlink()
        except _StoreLockBusy as exc:
            raise ChildCoachingRotationStoreBusyError(
                "rotation store is busy"
            ) from exc
