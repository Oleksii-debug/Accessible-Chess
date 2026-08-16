from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping


STATS_SCHEMA_VERSION = 1


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
    schema_version: int = STATS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        installation_id = str(self.installation_id).strip().lower()
        if not installation_id:
            raise ValueError("installation_id must not be empty")
        if int(self.schema_version) != STATS_SCHEMA_VERSION:
            raise ValueError("unsupported statistics schema")
        fields = (
            "session_seconds",
            "sessions_started",
            "games_started",
            "games_completed",
            "exercises_attempted",
            "exercises_completed",
            "classroom_seconds",
            "classroom_sessions",
        )
        for name in fields:
            value = getattr(self, name)
            if isinstance(value, bool) or int(value) < 0:
                raise ValueError(f"{name} must be a non-negative integer")
            object.__setattr__(self, name, int(value))
        if self.games_completed > self.games_started:
            raise ValueError("games_completed cannot exceed games_started")
        if self.exercises_completed > self.exercises_attempted:
            raise ValueError("exercises_completed cannot exceed exercises_attempted")
        object.__setattr__(self, "installation_id", installation_id)
        object.__setattr__(self, "schema_version", STATS_SCHEMA_VERSION)

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
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "UsageStatisticsSnapshot":
        try:
            version = int(payload.get("schema_version", 0))
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid statistics schema") from exc
        return cls(
            installation_id=str(payload.get("installation_id", "")),
            session_seconds=_integer(payload.get("session_seconds", 0), "session_seconds"),
            sessions_started=_integer(payload.get("sessions_started", 0), "sessions_started"),
            games_started=_integer(payload.get("games_started", 0), "games_started"),
            games_completed=_integer(payload.get("games_completed", 0), "games_completed"),
            exercises_attempted=_integer(payload.get("exercises_attempted", 0), "exercises_attempted"),
            exercises_completed=_integer(payload.get("exercises_completed", 0), "exercises_completed"),
            classroom_seconds=_integer(payload.get("classroom_seconds", 0), "classroom_seconds"),
            classroom_sessions=_integer(payload.get("classroom_sessions", 0), "classroom_sessions"),
            schema_version=version,
        )


class AggregateUsageStatistics:
    """Aggregate counters only; no PGN, book, audio, typed text or position payloads."""

    def __init__(self, snapshot: UsageStatisticsSnapshot) -> None:
        self._snapshot = snapshot

    @property
    def snapshot(self) -> UsageStatisticsSnapshot:
        return self._snapshot

    def start_session(self) -> UsageStatisticsSnapshot:
        self._snapshot = replace(
            self._snapshot,
            sessions_started=self._snapshot.sessions_started + 1,
        )
        return self._snapshot

    def add_session_seconds(self, seconds: int) -> UsageStatisticsSnapshot:
        seconds = _non_negative(seconds, "seconds")
        self._snapshot = replace(
            self._snapshot,
            session_seconds=self._snapshot.session_seconds + seconds,
        )
        return self._snapshot

    def start_game(self) -> UsageStatisticsSnapshot:
        self._snapshot = replace(self._snapshot, games_started=self._snapshot.games_started + 1)
        return self._snapshot

    def complete_game(self) -> UsageStatisticsSnapshot:
        if self._snapshot.games_completed >= self._snapshot.games_started:
            raise ValueError("cannot complete a game that was not started")
        self._snapshot = replace(self._snapshot, games_completed=self._snapshot.games_completed + 1)
        return self._snapshot

    def attempt_exercise(self) -> UsageStatisticsSnapshot:
        self._snapshot = replace(
            self._snapshot,
            exercises_attempted=self._snapshot.exercises_attempted + 1,
        )
        return self._snapshot

    def complete_exercise(self) -> UsageStatisticsSnapshot:
        if self._snapshot.exercises_completed >= self._snapshot.exercises_attempted:
            raise ValueError("cannot complete an exercise that was not attempted")
        self._snapshot = replace(
            self._snapshot,
            exercises_completed=self._snapshot.exercises_completed + 1,
        )
        return self._snapshot

    def start_classroom(self) -> UsageStatisticsSnapshot:
        self._snapshot = replace(
            self._snapshot,
            classroom_sessions=self._snapshot.classroom_sessions + 1,
        )
        return self._snapshot

    def add_classroom_seconds(self, seconds: int) -> UsageStatisticsSnapshot:
        seconds = _non_negative(seconds, "seconds")
        self._snapshot = replace(
            self._snapshot,
            classroom_seconds=self._snapshot.classroom_seconds + seconds,
        )
        return self._snapshot


class UsageStatisticsStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.warning: str | None = None

    def load(self, installation_id: str) -> UsageStatisticsSnapshot:
        self.warning = None
        if not self.path.exists():
            return UsageStatisticsSnapshot(installation_id)
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, Mapping):
                raise ValueError("statistics file must contain an object")
            snapshot = UsageStatisticsSnapshot.from_dict(raw)
            if snapshot.installation_id != str(installation_id).strip().lower():
                raise ValueError("statistics belong to another installation")
            return snapshot
        except Exception as exc:
            self.warning = f"usage statistics recovery: {exc}"
            return UsageStatisticsSnapshot(installation_id)

    def save(self, snapshot: UsageStatisticsSnapshot) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(snapshot.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def _non_negative(value: object, field_name: str) -> int:
    parsed = _integer(value, field_name)
    if parsed < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return parsed
