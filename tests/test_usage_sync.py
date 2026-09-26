from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from acs.usage_sync import UsageAnalyticsPolicy, UsageEvent, UsageEventQueue, UsageSyncPort


ENABLED = UsageAnalyticsPolicy(analytics_enabled=True)


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
            queue = UsageEventQueue(path)
            self.assertTrue(queue.enqueue(queued, ENABLED))
            self.assertTrue(queue.enqueue(queued, ENABLED))
            reopened = UsageEventQueue(path)
            self.assertEqual(reopened.pending(), (queued,))
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            finally:
                connection.close()

    def test_collection_is_opt_in_and_minor_collection_requires_consent_retention(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = UsageEventQueue(Path(tmp) / "usage-sync.sqlite")
            queued = event(kind="training", counters={"exercises_attempted": 1})
            self.assertFalse(queue.enqueue(queued, UsageAnalyticsPolicy()))
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
            self.assertEqual(queue.pending(), ())
            minor_allowed = UsageAnalyticsPolicy(
                analytics_enabled=True,
                is_minor=True,
                consent_state="granted",
                retention_days=30,
            )
            self.assertTrue(queue.enqueue(queued, minor_allowed))
            self.assertEqual(queue.pending(), (queued,))

    def test_policy_is_strict_and_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            UsageAnalyticsPolicy(analytics_enabled=1)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            UsageAnalyticsPolicy(consent_state="maybe")
        with self.assertRaises(ValueError):
            UsageAnalyticsPolicy(retention_days=0)
        with self.assertRaises(ValueError):
            UsageAnalyticsPolicy(retention_days=3651)

    def test_same_event_id_cannot_silently_overwrite_different_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = UsageEventQueue(Path(tmp) / "usage-sync.sqlite")
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
            queue = UsageEventQueue(Path(tmp) / "usage-sync.sqlite")
            queued = event()
            self.assertTrue(queue.enqueue(queued, ENABLED))
            port = FakeUsageSync()
            self.assertEqual(queue.sync_pending(port, UsageAnalyticsPolicy()), 0)
            self.assertEqual(port.calls, [])
            self.assertEqual(queue.sync_pending(port, ENABLED), 1)
            self.assertEqual(len(port.calls), 1)
            self.assertEqual(queue.pending(), ())

    def test_sync_rejects_duplicate_or_foreign_acknowledgements_and_bounds_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = UsageEventQueue(Path(tmp) / "usage-sync.sqlite")
            self.assertTrue(queue.enqueue(event("event-0"), ENABLED))
            self.assertTrue(
                queue.enqueue(
                    event("event-1", created_at_utc="2026-08-16T10:00:01Z"),
                    ENABLED,
                )
            )
            with self.assertRaisesRegex(ValueError, "outside this batch"):
                queue.sync_pending(FakeUsageSync(("event-0", "foreign-event")), ENABLED)
            with self.assertRaisesRegex(ValueError, "duplicate"):
                queue.sync_pending(FakeUsageSync(("event-0", "event-0")), ENABLED)
            with self.assertRaisesRegex(ValueError, "between 0 and 250"):
                queue.pending(limit=251)
            self.assertEqual(len(queue.pending()), 2)

    def test_export_delete_are_installation_scoped_and_content_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = UsageEventQueue(Path(tmp) / "usage-sync.sqlite")
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
                UsageEventQueue(path)


if __name__ == "__main__":
    unittest.main()
