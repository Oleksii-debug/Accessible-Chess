from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from acs.usage_sync import UsageAnalyticsPolicy, UsageEvent, UsageEventQueue, UsageSyncPort


ENABLED = UsageAnalyticsPolicy(analytics_enabled=True)
NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)


def make_queue(path: Path) -> UsageEventQueue:
    return UsageEventQueue(path, now=lambda: NOW)



class FakeUsageSync(UsageSyncPort):
    def __init__(self, acknowledgements: tuple[str, ...] | None = None) -> None:
        self.calls: list[tuple[UsageEvent, ...]] = []
        self.acknowledgements = acknowledgements

    def sync_events(self, events: tuple[UsageEvent, ...]) -> tuple[str, ...]:
        batch = tuple(events)
        self.calls.append(batch)
        if self.acknowledgements is None:
            return tuple(event.event_id for event in batch)
        return self.acknowledgements


class RaisingUsageSync(UsageSyncPort):
    def sync_events(self, events: tuple[UsageEvent, ...]) -> tuple[str, ...]:
        raise RuntimeError("SECRET provider details")


class InvalidUsageSync(UsageSyncPort):
    def sync_events(self, events: tuple[UsageEvent, ...]):  # type: ignore[no-untyped-def]
        return "event-1"


def event(
    event_id: str = "event-1",
    *,
    installation_id: str = "install-1",
    kind: str = "feature",
    counters: dict[str, int] | None = None,
    created_at_utc: str = "2026-08-16T10:00:00Z",
) -> UsageEvent:
    return UsageEvent.create(
        installation_id,
        kind,
        counters or {"feature_uses": 1},
        created_at_utc,
        event_id=event_id,
    )


class UsageSyncTests(unittest.TestCase):
    def test_queue_is_versioned_reopenable_and_idempotent_by_stable_event_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "usage-sync.sqlite"
            queued = event(
                kind="session",
                counters={"sessions_started": 1, "active_seconds": 45},
            )
            queue = make_queue(path)
            self.assertTrue(queue.enqueue(queued, ENABLED))
            self.assertTrue(queue.enqueue(queued, ENABLED))
            reopened = make_queue(path)
            self.assertEqual(reopened.pending("install-1"), (queued,))
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            finally:
                connection.close()

    def test_collection_is_opt_in_and_minor_collection_requires_consent_retention(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = make_queue(Path(tmp) / "usage-sync.sqlite")
            queued = event(kind="training", counters={"exercises_attempted": 1})
            self.assertFalse(queue.enqueue(queued, UsageAnalyticsPolicy()))
            self.assertFalse(
                queue.enqueue(
                    queued,
                    UsageAnalyticsPolicy(
                        analytics_enabled=True,
                        consent_state="denied",
                    ),
                )
            )
            self.assertFalse(
                queue.enqueue(
                    queued,
                    UsageAnalyticsPolicy(analytics_enabled=True, is_minor=True),
                )
            )
            self.assertFalse(
                queue.enqueue(
                    queued,
                    UsageAnalyticsPolicy(
                        analytics_enabled=True,
                        is_minor=True,
                        consent_state="granted",
                    ),
                )
            )
            self.assertEqual(queue.pending("install-1"), ())
            minor_allowed = UsageAnalyticsPolicy(
                analytics_enabled=True,
                is_minor=True,
                consent_state="granted",
                retention_days=30,
            )
            self.assertTrue(queue.enqueue(queued, minor_allowed))
            self.assertEqual(queue.pending("install-1"), (queued,))

    def test_policy_is_strict_and_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            UsageAnalyticsPolicy(analytics_enabled=1)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "consent state must be text"):
            UsageAnalyticsPolicy(consent_state=True)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            UsageAnalyticsPolicy(consent_state="maybe")
        with self.assertRaises(ValueError):
            UsageAnalyticsPolicy(retention_days=0)
        with self.assertRaises(ValueError):
            UsageAnalyticsPolicy(retention_days=3651)

    def test_policy_subclass_cannot_override_collection_or_sync_boundary(self) -> None:
        class BypassPolicy(UsageAnalyticsPolicy):
            def allows_collection(self) -> bool:
                return True

            def allows_sync(self) -> bool:
                return True

        bypass = BypassPolicy()
        with tempfile.TemporaryDirectory() as tmp:
            queue = make_queue(Path(tmp) / "usage-sync.sqlite")
            queued = event()
            with self.assertRaisesRegex(ValueError, "policy must be UsageAnalyticsPolicy"):
                queue.enqueue(queued, bypass)
            self.assertEqual(queue.pending("install-1"), ())

            self.assertTrue(queue.enqueue(queued, ENABLED))
            with self.assertRaisesRegex(ValueError, "policy must be UsageAnalyticsPolicy"):
                queue.sync_pending(FakeUsageSync(), bypass, "install-1")
            self.assertEqual(queue.pending("install-1"), (queued,))

    def test_same_event_id_cannot_silently_overwrite_different_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = make_queue(Path(tmp) / "usage-sync.sqlite")
            self.assertTrue(
                queue.enqueue(
                    event(kind="game", counters={"games_started": 1}),
                    ENABLED,
                )
            )
            with self.assertRaisesRegex(ValueError, "different aggregate data"):
                queue.enqueue(
                    event(kind="game", counters={"games_completed": 1}),
                    ENABLED,
                )

    def test_ordinary_analytics_rejects_raw_or_unbounded_content_fields(self) -> None:
        for name in (
            "pgn",
            "fen",
            "book",
            "database",
            "chat",
            "audio",
            "video",
            "file",
            "clipboard",
        ):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "not allowed"):
                event(event_id=f"event-{name}", counters={name: 1})
        with self.assertRaisesRegex(ValueError, "UTC timestamp"):
            event(event_id="event-time", created_at_utc="local time")
        with self.assertRaises(ValueError):
            event(event_id="event-id", installation_id="../install")

    def test_remote_sync_requires_enabled_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = make_queue(Path(tmp) / "usage-sync.sqlite")
            queued = event()
            self.assertTrue(queue.enqueue(queued, ENABLED))
            port = FakeUsageSync()
            self.assertEqual(queue.sync_pending(port, UsageAnalyticsPolicy(), "install-1"), 0)
            self.assertEqual(port.calls, [])
            self.assertEqual(queue.sync_pending(port, ENABLED, "install-1"), 1)
            self.assertEqual(len(port.calls), 1)
            self.assertEqual(queue.pending("install-1"), ())

    def test_sync_rejects_duplicate_or_foreign_acknowledgements_and_bounds_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = make_queue(Path(tmp) / "usage-sync.sqlite")
            self.assertTrue(queue.enqueue(event("event-0"), ENABLED))
            self.assertTrue(
                queue.enqueue(
                    event("event-1", created_at_utc="2026-08-16T10:00:01Z"),
                    ENABLED,
                )
            )
            with self.assertRaisesRegex(ValueError, "outside this batch"):
                queue.sync_pending(FakeUsageSync(("event-0", "foreign-event")), ENABLED, "install-1")
            oversized = tuple(f"event-{index}" for index in range(251))
            with self.assertRaisesRegex(ValueError, "outside this batch"):
                queue.sync_pending(FakeUsageSync(oversized), ENABLED, "install-1")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                queue.sync_pending(FakeUsageSync(("event-0", "event-0")), ENABLED, "install-1")
            with self.assertRaisesRegex(ValueError, "between 0 and 250"):
                queue.pending("install-1", limit=251)
            self.assertEqual(len(queue.pending("install-1")), 2)

    def test_export_delete_are_installation_scoped_and_content_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = make_queue(Path(tmp) / "usage-sync.sqlite")
            self.assertTrue(
                queue.enqueue(
                    event(
                        kind="classroom",
                        counters={"classroom_joins": 1, "classroom_seconds": 300},
                    ),
                    ENABLED,
                )
            )
            self.assertTrue(
                queue.enqueue(
                    event(
                        "event-2",
                        installation_id="install-2",
                        kind="assignment",
                        counters={"assignments_completed": 1},
                        created_at_utc="2026-08-16T10:00:01Z",
                    ),
                    ENABLED,
                )
            )
            exported = queue.export_for_installation("install-1")
            encoded = json.dumps(exported, sort_keys=True).lower()
            for forbidden in ("pgn", "fen", "chat", "audio", "video", "clipboard"):
                self.assertNotIn(forbidden, encoded)
            self.assertEqual(
                [item["event_id"] for item in exported["events"]],
                ["event-1"],
            )
            self.assertEqual(queue.delete_for_installation("install-1"), 1)
            self.assertEqual(queue.export_for_installation("install-1")["events"], [])
            self.assertEqual(
                [
                    item["event_id"]
                    for item in queue.export_for_installation("install-2")["events"]
                ],
                ["event-2"],
            )

    def test_provider_failures_and_invalid_ack_shape_are_bounded_without_state_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = make_queue(Path(tmp) / "usage-sync.sqlite")
            queued = event()
            self.assertTrue(queue.enqueue(queued, ENABLED))
            with self.assertRaisesRegex(RuntimeError, "^aggregate usage sync provider failed$"):
                queue.sync_pending(RaisingUsageSync(), ENABLED, "install-1")
            with self.assertRaisesRegex(ValueError, "acknowledgements must be a sequence"):
                queue.sync_pending(InvalidUsageSync(), ENABLED, "install-1")
            self.assertEqual(queue.pending("install-1"), (queued,))

    def test_usage_event_rejects_non_mapping_counters(self) -> None:
        with self.assertRaisesRegex(ValueError, "counters must be a mapping"):
            UsageEvent(
                event_id="event-1",
                installation_id="install-1",
                kind="feature",
                counters=[],  # type: ignore[arg-type]
                created_at_utc="2026-08-16T10:00:00Z",
            )

    def test_event_identity_and_counter_payload_are_fail_closed_after_validation(self) -> None:
        with self.assertRaisesRegex(ValueError, "event_id must be"):
            UsageEvent(
                event_id=1,  # type: ignore[arg-type]
                installation_id="install-1",
                kind="feature",
                counters={"feature_uses": 1},
                created_at_utc="2026-08-16T10:00:00Z",
            )
        with self.assertRaisesRegex(ValueError, "installation_id must be"):
            UsageEvent(
                event_id="event-1",
                installation_id=True,  # type: ignore[arg-type]
                kind="feature",
                counters={"feature_uses": 1},
                created_at_utc="2026-08-16T10:00:00Z",
            )
        with self.assertRaisesRegex(ValueError, "event kind must be text"):
            UsageEvent(
                event_id="event-1",
                installation_id="install-1",
                kind=1,  # type: ignore[arg-type]
                counters={"feature_uses": 1},
                created_at_utc="2026-08-16T10:00:00Z",
            )
        with self.assertRaisesRegex(ValueError, "UTC timestamp"):
            UsageEvent(
                event_id="event-1",
                installation_id="install-1",
                kind="feature",
                counters={"feature_uses": 1},
                created_at_utc=1,  # type: ignore[arg-type]
            )
        with self.assertRaisesRegex(ValueError, "event_id must be"):
            UsageEvent.create(
                "install-1",
                "feature",
                {"feature_uses": 1},
                "2026-08-16T10:00:00Z",
                event_id="",
            )
        with self.assertRaisesRegex(ValueError, "counter names must be unique"):
            UsageEvent(
                event_id="event-1",
                installation_id="install-1",
                kind="feature",
                counters={"FEATURE_USES": 1, "feature_uses": 2},
                created_at_utc="2026-08-16T10:00:00Z",
            )

        validated = event()
        with self.assertRaises(TypeError):
            validated.counters["pgn"] = 1  # type: ignore[index]
        self.assertEqual(dict(validated.counters), {"feature_uses": 1})

    def test_sync_rejects_non_text_acknowledgement_even_if_coercion_would_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = make_queue(Path(tmp) / "usage-sync.sqlite")
            queued = event("1")
            self.assertTrue(queue.enqueue(queued, ENABLED))
            port = FakeUsageSync((1,))  # type: ignore[arg-type]
            with self.assertRaisesRegex(ValueError, "event_id must be"):
                queue.sync_pending(port, ENABLED, "install-1")
            self.assertEqual(queue.pending("install-1"), (queued,))

    def test_sync_is_installation_scoped_and_never_batches_another_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            q = make_queue(Path(tmp) / "usage-sync.sqlite")
            self.assertTrue(q.enqueue(event("event-a"), ENABLED))
            self.assertTrue(
                q.enqueue(
                    event(
                        "event-b",
                        installation_id="install-2",
                        created_at_utc="2026-08-16T10:00:01Z",
                    ),
                    ENABLED,
                )
            )
            port = FakeUsageSync()
            self.assertEqual(q.sync_pending(port, ENABLED, "install-1"), 1)
            self.assertEqual([e.installation_id for e in port.calls[0]], ["install-1"])
            self.assertEqual([e.event_id for e in q.pending("install-2")], ["event-b"])

    def test_future_timestamp_cannot_bypass_retention(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            q = make_queue(Path(tmp) / "usage-sync.sqlite")
            policy = UsageAnalyticsPolicy(
                analytics_enabled=True,
                is_minor=True,
                consent_state="granted",
                retention_days=30,
            )
            future = event(
                "future",
                created_at_utc="2026-08-20T12:00:01Z",
            )
            with self.assertRaisesRegex(ValueError, "timestamp cannot be in the future"):
                q.enqueue(future, policy)
            self.assertEqual(q.pending("install-1"), ())

    def test_retention_rejects_expired_collection_and_purges_on_next_operation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            q = make_queue(Path(tmp) / "usage-sync.sqlite")
            policy = UsageAnalyticsPolicy(analytics_enabled=True, retention_days=3)
            expired = event("old", created_at_utc="2026-08-16T11:59:59Z")
            fresh = event("fresh", created_at_utc="2026-08-18T12:00:00Z")
            self.assertFalse(q.enqueue(expired, policy))
            self.assertTrue(q.enqueue(fresh, policy))
            self.assertEqual([e.event_id for e in q.pending("install-1")], ["fresh"])

            later = UsageEventQueue(
                Path(tmp) / "usage-sync.sqlite",
                now=lambda: datetime(2026, 8, 23, 12, 0, 1, tzinfo=timezone.utc),
            )
            self.assertEqual(later.purge_expired("install-1", policy), 1)
            self.assertEqual(later.pending("install-1"), ())

    def test_unversioned_foreign_usage_table_and_versioned_missing_table_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            foreign = Path(tmp) / "foreign.sqlite"
            connection = sqlite3.connect(foreign)
            try:
                connection.execute("CREATE TABLE usage_events(event_id TEXT PRIMARY KEY)")
                connection.commit()
            finally:
                connection.close()
            with self.assertRaisesRegex(ValueError, "preexisting usage_events"):
                make_queue(foreign)

            incomplete = Path(tmp) / "incomplete.sqlite"
            connection = sqlite3.connect(incomplete)
            try:
                connection.execute("PRAGMA user_version = 1")
                connection.commit()
            finally:
                connection.close()
            with self.assertRaisesRegex(ValueError, "schema is incomplete"):
                make_queue(incomplete)

    def test_versioned_wrong_table_shape_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wrong.sqlite"
            connection = sqlite3.connect(path)
            try:
                connection.execute(
                    "CREATE TABLE usage_events("
                    "event_id TEXT PRIMARY KEY, installation_id TEXT NOT NULL, kind TEXT NOT NULL, "
                    "counters_json TEXT NOT NULL, created_at_utc TEXT NOT NULL, sync_state TEXT NOT NULL)"
                )
                connection.execute("PRAGMA user_version = 1")
                connection.commit()
            finally:
                connection.close()
            with self.assertRaisesRegex(ValueError, "state constraint is missing"):
                make_queue(path)

    def test_future_schema_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "usage-sync.sqlite"
            connection = sqlite3.connect(path)
            try:
                connection.execute("PRAGMA user_version = 99")
                connection.commit()
            finally:
                connection.close()
            with self.assertRaisesRegex(
                ValueError,
                "unsupported usage sync database schema",
            ):
                make_queue(path)


if __name__ == "__main__":
    unittest.main()
