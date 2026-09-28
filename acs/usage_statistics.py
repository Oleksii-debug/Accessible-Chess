from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping


STATS_SCHEMA_VERSION = 1
_MAX_COUNTER = 2**63 - 1
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")


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
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError("statistics payload contains unknown fields")
        return cls(
            installation_id=payload.get("installation_id", ""),
            session_seconds=payload.get("session_seconds", 0),
            sessions_started=payload.get("sessions_started", 0),
            games_started=payload.get("games_started", 0),
            games_completed=payload.get("games_completed", 0),
            exercises_attempted=payload.get("exercises_attempted", 0),
            exercises_completed=payload.get("exercises_completed", 0),
            classroom_seconds=payload.get("classroom_seconds", 0),
            classroom_sessions=payload.get("classroom_sessions", 0),
            feature_uses=payload.get("feature_uses", 0),
            schema_version=payload.get("schema_version", 0),
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
            raw = json.loads(self.path.read_text(encoding="utf-8"))
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
        tmp = self.path.with_name(self.path.name + ".tmp")
        encoded = json.dumps(
            snapshot.as_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"
        try:
            with tmp.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
