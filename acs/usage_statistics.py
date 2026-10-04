from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping


STATS_SCHEMA_VERSION = 1
_MAX_COUNTER = 2**63 - 1
_MAX_STATS_FILE_BYTES = 64 * 1024
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")


def _no_duplicate_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("statistics payload contains duplicate fields")
        result[key] = value
    return result


def normalize_installation_id(value: object) -> str:
    if type(value) is not str:
        raise ValueError("installation_id must be a bounded opaque identifier")
    normalized = value.strip().lower()
    if not _ID_RE.fullmatch(normalized):
        raise ValueError("installation_id must be a bounded opaque identifier")
    return normalized


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    if value < 0 or value > _MAX_COUNTER:
        raise ValueError(f"{field_name} must be between 0 and {_MAX_COUNTER}")
    return value


@dataclass(frozen=True)
class UsageStatisticsSnapshot:
    installation_id: str
    session_seconds: int = 0
    sessions_started: int = 0
    games_started: int = 0
    games_completed: int = 0
    exercises_attempted: int = 0
    exercises_completed: int = 0
    classroom_seconds: int = 0
    classroom_sessions: int = 0
    feature_uses: int = 0
    schema_version: int = STATS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if isinstance(self.schema_version, bool) or self.schema_version != STATS_SCHEMA_VERSION:
            raise ValueError("unsupported statistics schema")
        object.__setattr__(self, "installation_id", normalize_installation_id(self.installation_id))
        for name in (
            "session_seconds",
            "sessions_started",
            "games_started",
            "games_completed",
            "exercises_attempted",
            "exercises_completed",
            "classroom_seconds",
            "classroom_sessions",
            "feature_uses",
        ):
            object.__setattr__(self, name, _integer(getattr(self, name), name))
        if self.games_completed > self.games_started:
            raise ValueError("games_completed cannot exceed games_started")
        if self.exercises_completed > self.exercises_attempted:
            raise ValueError("exercises_completed cannot exceed exercises_attempted")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "installation_id": self.installation_id,
            "session_seconds": self.session_seconds,
            "sessions_started": self.sessions_started,
            "games_started": self.games_started,
            "games_completed": self.games_completed,
            "exercises_attempted": self.exercises_attempted,
            "exercises_completed": self.exercises_completed,
            "classroom_seconds": self.classroom_seconds,
            "classroom_sessions": self.classroom_sessions,
            "feature_uses": self.feature_uses,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "UsageStatisticsSnapshot":
        allowed = {
            "schema_version",
            "installation_id",
            "session_seconds",
            "sessions_started",
            "games_started",
            "games_completed",
            "exercises_attempted",
            "exercises_completed",
            "classroom_seconds",
            "classroom_sessions",
            "feature_uses",
        }
        actual = set(payload)
        unknown = actual - allowed
        missing = allowed - actual
        if unknown:
            raise ValueError("statistics payload contains unknown fields")
        if missing:
            raise ValueError("statistics payload is missing required fields")
        return cls(
            installation_id=payload["installation_id"],
            session_seconds=payload["session_seconds"],
            sessions_started=payload["sessions_started"],
            games_started=payload["games_started"],
            games_completed=payload["games_completed"],
            exercises_attempted=payload["exercises_attempted"],
            exercises_completed=payload["exercises_completed"],
            classroom_seconds=payload["classroom_seconds"],
            classroom_sessions=payload["classroom_sessions"],
            feature_uses=payload["feature_uses"],
            schema_version=payload["schema_version"],
        )


class AggregateUsageStatistics:
    """Aggregate counters only; never accepts chess/document/communication payloads."""

    def __init__(self, snapshot: UsageStatisticsSnapshot) -> None:
        if type(snapshot) is not UsageStatisticsSnapshot:
            raise ValueError("snapshot must be UsageStatisticsSnapshot")
        self._snapshot = snapshot

    @property
    def snapshot(self) -> UsageStatisticsSnapshot:
        return self._snapshot

    def start_session(self) -> UsageStatisticsSnapshot:
        return self._advance(sessions_started=1)

    def add_session_seconds(self, seconds: int) -> UsageStatisticsSnapshot:
        return self._advance(session_seconds=_integer(seconds, "seconds"))

    def start_game(self) -> UsageStatisticsSnapshot:
        return self._advance(games_started=1)

    def complete_game(self) -> UsageStatisticsSnapshot:
        if self._snapshot.games_completed >= self._snapshot.games_started:
            raise ValueError("cannot complete a game that was not started")
        return self._advance(games_completed=1)

    def attempt_exercise(self) -> UsageStatisticsSnapshot:
        return self._advance(exercises_attempted=1)

    def complete_exercise(self) -> UsageStatisticsSnapshot:
        if self._snapshot.exercises_completed >= self._snapshot.exercises_attempted:
            raise ValueError("cannot complete an exercise that was not attempted")
        return self._advance(exercises_completed=1)

    def start_classroom(self) -> UsageStatisticsSnapshot:
        return self._advance(classroom_sessions=1)

    def add_classroom_seconds(self, seconds: int) -> UsageStatisticsSnapshot:
        return self._advance(classroom_seconds=_integer(seconds, "seconds"))

    def record_feature_use(self) -> UsageStatisticsSnapshot:
        return self._advance(feature_uses=1)

    def _advance(self, **deltas: int) -> UsageStatisticsSnapshot:
        values: dict[str, int] = {}
        for name, delta in deltas.items():
            current = getattr(self._snapshot, name)
            if delta > _MAX_COUNTER - current:
                raise ValueError(f"{name} counter overflow")
            values[name] = current + delta
        self._snapshot = replace(self._snapshot, **values)
        return self._snapshot


class UsageStatisticsStore:
    """Atomic local snapshot store. Invalid data resets locally without exposing exception text."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.recovered_invalid_data = False

    def load(self, installation_id: str) -> UsageStatisticsSnapshot:
        normalized = normalize_installation_id(installation_id)
        self.recovered_invalid_data = False
        if not self.path.exists():
            return UsageStatisticsSnapshot(normalized)
        try:
            with self.path.open("rb") as handle:
                encoded = handle.read(_MAX_STATS_FILE_BYTES + 1)
            if len(encoded) > _MAX_STATS_FILE_BYTES:
                raise ValueError("statistics payload exceeds the supported size")
            raw = json.loads(
                encoded.decode("utf-8", errors="strict"),
                object_pairs_hook=_no_duplicate_object,
            )
            if not isinstance(raw, Mapping):
                raise ValueError("statistics payload must be an object")
            snapshot = UsageStatisticsSnapshot.from_dict(raw)
            if snapshot.installation_id != normalized:
                raise ValueError("statistics belong to another installation")
            return snapshot
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            self.recovered_invalid_data = True
            return UsageStatisticsSnapshot(normalized)

    def save(self, snapshot: UsageStatisticsSnapshot) -> None:
        if type(snapshot) is not UsageStatisticsSnapshot:
            raise ValueError("snapshot must be UsageStatisticsSnapshot")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(
            snapshot.as_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
        fd, raw_tmp = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=self.path.parent,
        )
        tmp = Path(raw_tmp)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                fd = -1
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        finally:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
