from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence


USAGE_SYNC_SCHEMA_VERSION = 1

_ALLOWED_EVENT_KINDS = frozenset(
    {
        "session",
        "game",
        "training",
        "classroom",
        "assignment",
        "feature",
    }
)
_ALLOWED_COUNTERS = frozenset(
    {
        "sessions_started",
        "active_seconds",
        "games_started",
        "games_completed",
        "games_won",
        "games_drawn",
        "games_lost",
        "exercises_attempted",
        "exercises_completed",
        "classroom_joins",
        "classroom_seconds",
        "assignments_completed",
        "feature_uses",
    }
)


@dataclass(frozen=True)
class UsageEvent:
    event_id: str
    installation_id: str
    kind: str
    counters: Mapping[str, int]
    created_at_utc: str
    schema_version: int = USAGE_SYNC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        event_id = str(self.event_id).strip().lower()
        installation_id = str(self.installation_id).strip().lower()
        kind = str(self.kind).strip().lower()
        created_at = str(self.created_at_utc).strip()
        if not event_id:
            raise ValueError("event_id must not be empty")
        if not installation_id:
            raise ValueError("installation_id must not be empty")
        if kind not in _ALLOWED_EVENT_KINDS:
            raise ValueError("unsupported aggregate event kind")
        if not created_at:
            raise ValueError("created_at_utc must not be empty")
        if int(self.schema_version) != USAGE_SYNC_SCHEMA_VERSION:
            raise ValueError("unsupported usage sync schema")

        normalized: dict[str, int] = {}
        for key, raw_value in self.counters.items():
            name = str(key).strip().lower()
            if name not in _ALLOWED_COUNTERS:
                raise ValueError(f"counter is not allowed in ordinary analytics: {name}")
            if isinstance(raw_value, bool):
                raise ValueError(f"{name} must be a non-negative integer")
            try:
                value = int(raw_value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{name} must be a non-negative integer") from exc
            if value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
            normalized[name] = value

        if not normalized:
            raise ValueError("aggregate event must contain at least one counter")
        object.__setattr__(self, "event_id", event_id)
        object.__setattr__(self, "installation_id", installation_id)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "counters", normalized)
        object.__setattr__(self, "created_at_utc", created_at)
        object.__setattr__(self, "schema_version", USAGE_SYNC_SCHEMA_VERSION)

    @classmethod
    def create(
        cls,
        installation_id: str,
        kind: str,
        counters: Mapping[str, int],
        created_at_utc: str,
        *,
        event_id: str | None = None,
    ) -> "UsageEvent":
        return cls(
            event_id=event_id or uuid.uuid4().hex,
            installation_id=installation_id,
            kind=kind,
            counters=counters,
            created_at_utc=created_at_utc,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "installation_id": self.installation_id,
            "kind": self.kind,
            "counters": dict(self.counters),
            "created_at_utc": self.created_at_utc,
        }


@dataclass(frozen=True)
class MinorAnalyticsPolicy:
    is_minor: bool
    consent_state: str = "unknown"
    retention_days: int | None = None

    def allows_sync(self) -> bool:
        if not self.is_minor:
            return True
        if self.consent_state != "granted":
            return False
        if self.retention_days is None:
            return False
        return 0 < int(self.retention_days) <= 3650


@dataclass(frozen=True)
class ProfileEnrollmentRequest:
    installation_id: str

    def __post_init__(self) -> None:
        value = str(self.installation_id).strip().lower()
        if not value:
            raise ValueError("installation_id must not be empty")
        object.__setattr__(self, "installation_id", value)


@dataclass(frozen=True)
class ProfileEnrollmentResult:
    server_profile_id: str
    access_token: str
    expires_at_utc: str

    def __post_init__(self) -> None:
        if not str(self.server_profile_id).strip():
            raise ValueError("server_profile_id must not be empty")
        if not str(self.access_token).strip():
            raise ValueError("access_token must not be empty")
        if not str(self.expires_at_utc).strip():
            raise ValueError("expires_at_utc must not be empty")


class UsageSyncPort(Protocol):
    """Provider-neutral aggregate analytics sync. Implementations receive no raw user content."""

    def sync_events(self, events: Sequence[UsageEvent]) -> Sequence[str]: ...


class ProfileEnrollmentPort(Protocol):
    """Provider-neutral enrollment using a server-issued short-lived credential response."""

    def enroll(self, request: ProfileEnrollmentRequest) -> ProfileEnrollmentResult: ...


class UsageEventQueue:
    """Versioned offline queue for bounded aggregate usage events only."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _migrate(self) -> None:
        with self._connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version not in (0, USAGE_SYNC_SCHEMA_VERSION):
                raise ValueError(f"unsupported usage sync database schema: {version}")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_events (
                    event_id TEXT PRIMARY KEY,
                    installation_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    counters_json TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    sync_state TEXT NOT NULL CHECK(sync_state IN ('pending', 'synced'))
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS ix_usage_events_pending "
                "ON usage_events(sync_state, created_at_utc, event_id)"
            )
            connection.execute(f"PRAGMA user_version = {USAGE_SYNC_SCHEMA_VERSION}")

    def enqueue(self, event: UsageEvent) -> None:
        counters_json = json.dumps(dict(event.counters), sort_keys=True, separators=(",", ":"))
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT installation_id, kind, counters_json, created_at_utc FROM usage_events WHERE event_id = ?",
                (event.event_id,),
            ).fetchone()
            if existing is not None:
                expected = (
                    event.installation_id,
                    event.kind,
                    counters_json,
                    event.created_at_utc,
                )
                actual = (
                    existing["installation_id"],
                    existing["kind"],
                    existing["counters_json"],
                    existing["created_at_utc"],
                )
                if actual != expected:
                    raise ValueError("event_id already exists with different aggregate data")
                return
            connection.execute(
                "INSERT INTO usage_events(event_id, installation_id, kind, counters_json, created_at_utc, sync_state) "
                "VALUES (?, ?, ?, ?, ?, 'pending')",
                (
                    event.event_id,
                    event.installation_id,
                    event.kind,
                    counters_json,
                    event.created_at_utc,
                ),
            )

    def pending(self, *, limit: int = 100) -> tuple[UsageEvent, ...]:
        if isinstance(limit, bool) or int(limit) < 0:
            raise ValueError("limit must be a non-negative integer")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT event_id, installation_id, kind, counters_json, created_at_utc "
                "FROM usage_events WHERE sync_state = 'pending' "
                "ORDER BY created_at_utc, event_id LIMIT ?",
                (int(limit),),
            ).fetchall()
        return tuple(self._row_to_event(row) for row in rows)

    def sync_pending(
        self,
        port: UsageSyncPort,
        policy: MinorAnalyticsPolicy,
        *,
        limit: int = 100,
    ) -> int:
        if not policy.allows_sync():
            return 0
        events = self.pending(limit=limit)
        if not events:
            return 0
        acknowledged = tuple(str(value).strip().lower() for value in port.sync_events(events))
        pending_ids = {event.event_id for event in events}
        if len(set(acknowledged)) != len(acknowledged):
            raise ValueError("sync adapter returned duplicate acknowledgements")
        if not set(acknowledged).issubset(pending_ids):
            raise ValueError("sync adapter acknowledged an event outside this batch")
        if not acknowledged:
            return 0
        with self._connect() as connection:
            connection.executemany(
                "UPDATE usage_events SET sync_state = 'synced' WHERE event_id = ?",
                ((event_id,) for event_id in acknowledged),
            )
        return len(acknowledged)

    def export_for_installation(self, installation_id: str) -> dict[str, object]:
        normalized = str(installation_id).strip().lower()
        if not normalized:
            raise ValueError("installation_id must not be empty")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT event_id, installation_id, kind, counters_json, created_at_utc, sync_state "
                "FROM usage_events WHERE installation_id = ? ORDER BY created_at_utc, event_id",
                (normalized,),
            ).fetchall()
        events = []
        for row in rows:
            event = self._row_to_event(row)
            payload = event.as_dict()
            payload["sync_state"] = row["sync_state"]
            events.append(payload)
        return {
            "schema_version": USAGE_SYNC_SCHEMA_VERSION,
            "installation_id": normalized,
            "events": events,
        }

    def delete_for_installation(self, installation_id: str) -> int:
        normalized = str(installation_id).strip().lower()
        if not normalized:
            raise ValueError("installation_id must not be empty")
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM usage_events WHERE installation_id = ?",
                (normalized,),
            )
            return int(cursor.rowcount)

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> UsageEvent:
        counters = json.loads(row["counters_json"])
        if not isinstance(counters, Mapping):
            raise ValueError("stored aggregate counters must be an object")
        return UsageEvent(
            event_id=row["event_id"],
            installation_id=row["installation_id"],
            kind=row["kind"],
            counters=counters,
            created_at_utc=row["created_at_utc"],
        )
