from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import islice
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Iterator, Mapping, Protocol, Sequence

from .usage_statistics import (
    _prepare_direct_directory_chain,
    _require_private_regular,
    _same_file_identity,
    _verify_direct_directory_chain,
    normalize_installation_id,
)


USAGE_SYNC_SCHEMA_VERSION = 1
_MAX_COUNTER = 2**63 - 1
_MAX_BATCH = 250
_MAX_PENDING_PER_INSTALLATION = 10_000
_MAX_STORED_COUNTERS_JSON_CHARS = 4096
_EVENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")

_ALLOWED_EVENT_KINDS = frozenset(
    {"session", "game", "training", "classroom", "assignment", "feature"}
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


def _normalize_event_id(value: object) -> str:
    if type(value) is not str:
        raise ValueError("event_id must be a bounded opaque identifier")
    normalized = value.strip().lower()
    if not _EVENT_ID_RE.fullmatch(normalized):
        raise ValueError("event_id must be a bounded opaque identifier")
    return normalized


def _parse_utc(value: object) -> datetime:
    if type(value) is not str:
        raise ValueError("created_at_utc must be a bounded UTC timestamp ending in Z")
    text = value.strip()
    if len(text) > 32 or not text.endswith("Z"):
        raise ValueError("created_at_utc must be a bounded UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("created_at_utc must be a valid UTC timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise ValueError("created_at_utc must be UTC")
    return parsed


def _decode_stored_counters(value: object) -> Mapping[str, object]:
    if type(value) is not str:
        raise ValueError("stored aggregate counters must be bounded JSON text")
    if len(value) > _MAX_STORED_COUNTERS_JSON_CHARS:
        raise ValueError("stored aggregate counters exceed the JSON size limit")

    def unique_object(pairs: list[tuple[object, object]]) -> dict[object, object]:
        if len(pairs) > len(_ALLOWED_COUNTERS):
            raise ValueError("stored aggregate counters contain too many object members")
        result: dict[object, object] = {}
        for key, raw_value in pairs:
            if key in result:
                raise ValueError("stored aggregate counters contain duplicate object keys")
            result[key] = raw_value
        return result

    try:
        decoded = json.loads(value, object_pairs_hook=unique_object)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("stored aggregate counters contain invalid JSON") from exc
    if not isinstance(decoded, Mapping):
        raise ValueError("stored aggregate counters must be an object")
    return decoded


def _snapshot_acknowledgements(value: object, *, max_count: int) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError("sync adapter acknowledgements must be a sequence of event IDs")
    try:
        raw_values = tuple(islice(iter(value), max_count + 1))
    except Exception:
        raise ValueError("sync adapter acknowledgements could not be read") from None
    if len(raw_values) > max_count:
        raise ValueError("sync adapter acknowledged an event outside this batch")
    return tuple(_normalize_event_id(item) for item in raw_values)


@dataclass(frozen=True)
class UsageEvent:
    event_id: str
    installation_id: str
    kind: str
    counters: Mapping[str, int]
    created_at_utc: str
    schema_version: int = USAGE_SYNC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if isinstance(self.schema_version, bool) or self.schema_version != USAGE_SYNC_SCHEMA_VERSION:
            raise ValueError("unsupported usage sync schema")
        event_id = _normalize_event_id(self.event_id)
        installation_id = normalize_installation_id(self.installation_id)
        if type(self.kind) is not str:
            raise ValueError("aggregate event kind must be text")
        kind = self.kind.strip().lower()
        if kind not in _ALLOWED_EVENT_KINDS:
            raise ValueError("unsupported aggregate event kind")
        parsed_time = _parse_utc(self.created_at_utc)

        if not isinstance(self.counters, Mapping):
            raise ValueError("aggregate counters must be a mapping")
        normalized: dict[str, int] = {}
        for key, raw_value in self.counters.items():
            if type(key) is not str:
                raise ValueError("aggregate counter names must be text")
            name = key.strip().lower()
            if name not in _ALLOWED_COUNTERS:
                raise ValueError(f"counter is not allowed in aggregate usage statistics: {name}")
            if name in normalized:
                raise ValueError("aggregate counter names must be unique after normalization")
            if isinstance(raw_value, bool) or not isinstance(raw_value, int):
                raise ValueError(f"{name} must be a non-negative integer")
            if raw_value < 0 or raw_value > _MAX_COUNTER:
                raise ValueError(f"{name} must be a bounded non-negative integer")
            normalized[name] = raw_value
        if not normalized:
            raise ValueError("aggregate event must contain at least one counter")

        object.__setattr__(self, "event_id", event_id)
        object.__setattr__(self, "installation_id", installation_id)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "counters", MappingProxyType(normalized))
        object.__setattr__(
            self,
            "created_at_utc",
            parsed_time.isoformat(timespec="seconds").replace("+00:00", "Z"),
        )
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
            event_id=uuid.uuid4().hex if event_id is None else event_id,
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
class UsageAnalyticsPolicy:
    """Optional analytics policy. Collection and sync are both fail-closed."""

    analytics_enabled: bool = False
    is_minor: bool = False
    consent_state: str = "unknown"
    retention_days: int | None = None

    def __post_init__(self) -> None:
        if type(self.analytics_enabled) is not bool or type(self.is_minor) is not bool:
            raise ValueError("analytics policy flags must be booleans")
        if type(self.consent_state) is not str:
            raise ValueError("analytics consent state must be text")
        consent = self.consent_state.strip().lower()
        if consent not in {"unknown", "granted", "denied"}:
            raise ValueError("unsupported analytics consent state")
        retention = self.retention_days
        if retention is not None:
            if isinstance(retention, bool) or not isinstance(retention, int):
                raise ValueError("retention_days must be an integer or None")
            if not 0 < retention <= 3650:
                raise ValueError("retention_days must be between 1 and 3650")
        object.__setattr__(self, "consent_state", consent)

    def allows_collection(self) -> bool:
        if not self.analytics_enabled or self.consent_state == "denied":
            return False
        if not self.is_minor:
            return True
        return self.consent_state == "granted" and self.retention_days is not None

    def allows_sync(self) -> bool:
        return self.allows_collection()


class UsageSyncPort(Protocol):
    """Provider-neutral aggregate usage sync. Implementations receive no raw user content."""

    def sync_events(self, events: Sequence[UsageEvent]) -> Sequence[str]: ...


class UsageEventQueue:
    """Durable idempotent offline queue for bounded aggregate usage events only."""

    def __init__(
        self,
        path: str | Path,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if not callable(now):
            raise ValueError("now must be callable")
        requested_path = Path(path)
        parent, self._directory_snapshot = _prepare_direct_directory_chain(
            requested_path.parent,
            label="usage sync directory",
        )
        self.path = parent / requested_path.name
        self._now = now
        self._migrate()

    def _verify_database_path(self, expected: object) -> None:
        _verify_direct_directory_chain(
            self._directory_snapshot,
            label="usage sync directory",
        )
        current = self.path.lstat()
        _require_private_regular(current, "usage sync database")
        if expected is not None and not _same_file_identity(expected, current):
            raise OSError("usage sync database changed unexpectedly")

    def _connect(self) -> tuple[sqlite3.Connection, object]:
        _verify_direct_directory_chain(
            self._directory_snapshot,
            label="usage sync directory",
        )
        try:
            before = self.path.lstat()
        except FileNotFoundError:
            before = None
        else:
            _require_private_regular(before, "usage sync database")

        connection = sqlite3.connect(self.path, timeout=5.0)
        try:
            _verify_direct_directory_chain(
                self._directory_snapshot,
                label="usage sync directory",
            )
            opened = self.path.lstat()
            _require_private_regular(opened, "usage sync database")
            if before is not None and not _same_file_identity(before, opened):
                raise OSError("usage sync database changed while being opened")
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            return connection, opened
        except BaseException:
            connection.close()
            raise

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection, opened = self._connect()
        try:
            with connection:
                yield connection
            self._verify_database_path(opened)
        finally:
            connection.close()

    def _migrate(self) -> None:
        with self._connection() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version not in (0, USAGE_SYNC_SCHEMA_VERSION):
                raise ValueError(f"unsupported usage sync database schema: {version}")
            existing = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'usage_events'"
            ).fetchone()
            if version == 0 and existing is not None:
                raise ValueError("unversioned usage sync database contains a preexisting usage_events table")
            if version == USAGE_SYNC_SCHEMA_VERSION and existing is None:
                raise ValueError("usage sync database schema is incomplete")
            if version == 0:
                connection.execute(
                    """
                    CREATE TABLE usage_events (
                        event_id TEXT PRIMARY KEY,
                        installation_id TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        counters_json TEXT NOT NULL,
                        created_at_utc TEXT NOT NULL,
                        sync_state TEXT NOT NULL CHECK(sync_state IN ('pending', 'synced'))
                    )
                    """
                )
                connection.execute(f"PRAGMA user_version = {USAGE_SYNC_SCHEMA_VERSION}")
            self._validate_schema(connection)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS ix_usage_events_pending "
                "ON usage_events(sync_state, created_at_utc, event_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS ix_usage_events_installation "
                "ON usage_events(installation_id, created_at_utc, event_id)"
            )

    @staticmethod
    def _validate_schema(connection: sqlite3.Connection) -> None:
        rows = connection.execute("PRAGMA table_info(usage_events)").fetchall()
        actual = tuple(
            (row["name"], str(row["type"]).upper(), int(row["notnull"]), int(row["pk"]))
            for row in rows
        )
        expected = (
            ("event_id", "TEXT", 0, 1),
            ("installation_id", "TEXT", 1, 0),
            ("kind", "TEXT", 1, 0),
            ("counters_json", "TEXT", 1, 0),
            ("created_at_utc", "TEXT", 1, 0),
            ("sync_state", "TEXT", 1, 0),
        )
        if actual != expected:
            raise ValueError("usage sync database table schema mismatch")
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'usage_events'"
        ).fetchone()
        sql = "" if row is None or row["sql"] is None else str(row["sql"]).lower()
        normalized = " ".join(sql.replace("\n", " ").split())
        if "check(sync_state in ('pending', 'synced'))" not in normalized:
            raise ValueError("usage sync database state constraint is missing")

    def _read_now(self) -> datetime:
        value = self._now()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("now must return an aware datetime")
        return value.astimezone(timezone.utc)

    def purge_expired(
        self,
        installation_id: str,
        policy: UsageAnalyticsPolicy,
    ) -> int:
        normalized = normalize_installation_id(installation_id)
        if type(policy) is not UsageAnalyticsPolicy:
            raise ValueError("policy must be UsageAnalyticsPolicy")
        if policy.retention_days is None:
            return 0
        cutoff = self._read_now() - timedelta(days=policy.retention_days)
        cutoff_text = cutoff.isoformat(timespec="seconds").replace("+00:00", "Z")
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM usage_events WHERE installation_id = ? AND created_at_utc < ?",
                (normalized, cutoff_text),
            )
            return int(cursor.rowcount)

    def enqueue(self, event: UsageEvent, policy: UsageAnalyticsPolicy) -> bool:
        if type(event) is not UsageEvent:
            raise ValueError("event must be UsageEvent")
        if type(policy) is not UsageAnalyticsPolicy:
            raise ValueError("policy must be UsageAnalyticsPolicy")
        if not policy.allows_collection():
            return False
        now = self._read_now()
        event_time = _parse_utc(event.created_at_utc)
        if event_time > now:
            raise ValueError("usage event timestamp cannot be in the future")
        self.purge_expired(event.installation_id, policy)
        if policy.retention_days is not None:
            cutoff = now - timedelta(days=policy.retention_days)
            if event_time < cutoff:
                return False
        counters_json = json.dumps(
            dict(event.counters), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        with self._connection() as connection:
            existing = connection.execute(
                "SELECT installation_id, kind, counters_json, created_at_utc "
                "FROM usage_events WHERE event_id = ?",
                (event.event_id,),
            ).fetchone()
            if existing is not None:
                actual = (
                    existing["installation_id"],
                    existing["kind"],
                    existing["counters_json"],
                    existing["created_at_utc"],
                )
                expected = (
                    event.installation_id,
                    event.kind,
                    counters_json,
                    event.created_at_utc,
                )
                if actual != expected:
                    raise ValueError("event_id already exists with different aggregate data")
                return True
            pending_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM usage_events "
                    "WHERE installation_id = ? AND sync_state = 'pending'",
                    (event.installation_id,),
                ).fetchone()[0]
            )
            if pending_count >= _MAX_PENDING_PER_INSTALLATION:
                raise ValueError("usage sync pending queue capacity exceeded")
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
        return True

    def pending(
        self,
        installation_id: str,
        *,
        limit: int = 100,
    ) -> tuple[UsageEvent, ...]:
        normalized = normalize_installation_id(installation_id)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 <= limit <= _MAX_BATCH:
            raise ValueError(f"limit must be an integer between 0 and {_MAX_BATCH}")
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT event_id, installation_id, kind, counters_json, created_at_utc "
                "FROM usage_events WHERE sync_state = 'pending' AND installation_id = ? "
                "ORDER BY created_at_utc, event_id LIMIT ?",
                (normalized, limit),
            ).fetchall()
        return tuple(self._row_to_event(row) for row in rows)

    def sync_pending(
        self,
        port: UsageSyncPort,
        policy: UsageAnalyticsPolicy,
        installation_id: str,
        *,
        limit: int = 100,
    ) -> int:
        normalized = normalize_installation_id(installation_id)
        if type(policy) is not UsageAnalyticsPolicy:
            raise ValueError("policy must be UsageAnalyticsPolicy")
        if not policy.allows_sync():
            return 0
        self.purge_expired(normalized, policy)
        events = self.pending(normalized, limit=limit)
        if not events:
            return 0
        try:
            raw_acknowledged = port.sync_events(events)
        except Exception:
            raise RuntimeError("aggregate usage sync provider failed") from None
        acknowledged = _snapshot_acknowledgements(
            raw_acknowledged,
            max_count=len(events),
        )
        batch_by_id = {event.event_id: event for event in events}
        if len(set(acknowledged)) != len(acknowledged):
            raise ValueError("sync adapter returned duplicate acknowledgements")
        if not set(acknowledged).issubset(batch_by_id):
            raise ValueError("sync adapter acknowledged an event outside this batch")
        if not acknowledged:
            return 0
        with self._connection() as connection:
            for event_id in acknowledged:
                sent = batch_by_id[event_id]
                counters_json = json.dumps(
                    dict(sent.counters),
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                )
                cursor = connection.execute(
                    "UPDATE usage_events SET sync_state = 'synced' "
                    "WHERE event_id = ? AND installation_id = ? AND kind = ? "
                    "AND counters_json = ? AND created_at_utc = ? AND sync_state = 'pending'",
                    (
                        sent.event_id,
                        sent.installation_id,
                        sent.kind,
                        counters_json,
                        sent.created_at_utc,
                    ),
                )
                if cursor.rowcount == 1:
                    continue
                current = connection.execute(
                    "SELECT installation_id, kind, counters_json, created_at_utc, sync_state "
                    "FROM usage_events WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
                if current is None:
                    continue
                current_identity = (
                    current["installation_id"],
                    current["kind"],
                    current["counters_json"],
                    current["created_at_utc"],
                )
                sent_identity = (
                    sent.installation_id,
                    sent.kind,
                    counters_json,
                    sent.created_at_utc,
                )
                if current_identity == sent_identity and current["sync_state"] == "synced":
                    continue
                raise RuntimeError(
                    "aggregate usage queue changed during provider acknowledgement"
                )
        return len(acknowledged)

    def export_for_installation(self, installation_id: str) -> dict[str, object]:
        normalized = normalize_installation_id(installation_id)
        with self._connection() as connection:
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
        normalized = normalize_installation_id(installation_id)
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM usage_events WHERE installation_id = ?",
                (normalized,),
            )
            return int(cursor.rowcount)

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> UsageEvent:
        raw_counters = row["counters_json"]
        counters = _decode_stored_counters(raw_counters)
        event = UsageEvent(
            event_id=row["event_id"],
            installation_id=row["installation_id"],
            kind=row["kind"],
            counters=counters,
            created_at_utc=row["created_at_utc"],
        )
        canonical = json.dumps(
            dict(event.counters), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        if raw_counters != canonical:
            raise ValueError("stored aggregate counters are not canonical")
        return event
