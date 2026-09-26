from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from acs.usage_sync import UsageAnalyticsPolicy, UsageEvent, UsageEventQueue, UsageSyncPort


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


class UsageSyncTests(unittest.TestCase):
    def test_queue_is_versioned_reopenable_and_idempotent_by_stable_event_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "usage-sync.sqlite"
            event = UsageEvent.create(
                "install-1",
                "session",
                {"sessions_started": 1, "active_seconds": 45},
                "2026-08-16T10:00:00Z",
                event_id="event-1",
            )
            queue = UsageEventQueue(path)
            queue.enqueue(event)
            queue.enqueue(event)
            reopened = UsageEventQueue(path)
            self.assertEqual(reopened.pending(), (event,))
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            finally:
                connection.close()

    def test_same_event_id_cannot_silently_overwrite_different_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = UsageEventQueue(Path(tmp) / "usage-sync.sqlite")
            queue.enqueue(
                UsageEvent.create(
                    "install-1",
                    "game",
                    {"games_started": 1},
                    "2026-08-16T10:00:00Z",
                    event_id="event-1",
                )
            )
            with self.assertRaisesRegex(ValueError, "different aggregate data"):
                queue.enqueue(
                    UsageEvent.create(
                        "install-1",
                        "game",
                        {"games_completed": 1},
                        "2026-08-16T10:00:00Z",
                        event_id="event-1",
                    )
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
                UsageEvent.create(
                    "install-1",
                    "feature",
                    {name: 1},
                    "2026-08-16T10:00:00Z",
                    event_id=f"event-{name}",
                )
        with self.assertRaisesRegex(ValueError, "UTC timestamp"):
            UsageEvent.create(
                "install-1",
                "feature",
                {"feature_uses": 1},
                "local time",
                event_id="event-time",
            )
        with self.assertRaises(ValueError):
            UsageEvent.create(
                "../install",
                "feature",
                {"feature_uses": 1},
                "2026-08-16T10:00:00Z",
                event_id="event-id",
            )

    def test_remote_sync_is_opt_in_and_minor_sync_requires_consent_and_retention(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = UsageEventQueue(Path(tmp) / "usage-sync.sqlite")
            queue.enqueue(
                UsageEvent.create(
                    "install-1",
                    "training",
                    {"exercises_attempted": 1},
                    "2026-08-16T10:00:00Z",
                    event_id="event-1",
                )
            )
            port = FakeUsageSync()
            self.assertEqual(queue.sync_pending(port, UsageAnalyticsPolicy()), 0)
            self.assertEqual(
                queue.sync_pending(
                    port,
                    UsageAnalyticsPolicy(analytics_enabled=True, is_minor=True),
                ),
                0,
            )
            self.assertEqual(
                queue.sync_pending(
                    port,
                    UsageAnalyticsPolicy(
                        analytics_enabled=True,
                        is_minor=True,
                        consent_state="granted",
                    ),
                ),
                0,
            )
            self.assertEqual(port.calls, [])
            self.assertEqual(
                queue.sync_pending(
                    port,
                    UsageAnalyticsPolicy(
                        analytics_enabled=True,
                        is_minor=True,
                        consent_state="granted",
                        retention_days=30,
                    ),
                ),
                1,
            )
            self.assertEqual(len(port.calls), 1)
            self.assertEqual(queue.pending(), ())

    def test_adult_sync_still_requires_explicit_enable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = UsageEventQueue(Path(tmp) / "usage-sync.sqlite")
            queue.enqueue(
                UsageEvent.create(
                    "install-1",
                    "feature",
                    {"feature_uses": 1},
                    "2026-08-16T10:00:00Z",
                    event_id="event-1",
                )
            )
            port = FakeUsageSync()
            self.assertEqual(
                queue.sync_pending(port, UsageAnalyticsPolicy(is_minor=False)),
                0,
            )
            self.assertEqual(
                queue.sync_pending(
                    port,
                    UsageAnalyticsPolicy(analytics_enabled=True),
                ),
                1,
            )

    def test_sync_rejects_duplicate_or_foreign_acknowledgements_and_bounds_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = UsageEventQueue(Path(tmp) / "usage-sync.sqlite")
            for index in range(2):
                queue.enqueue(
                    UsageEvent.create(
                        "install-1",
                        "feature",
                        {"feature_uses": 1},
                        f"2026-08-16T10:00:0{index}Z",
                        event_id=f"event-{index}",
                    )
                )
            enabled = UsageAnalyticsPolicy(analytics_enabled=True)
            with self.assertRaisesRegex(ValueError, "outside this batch"):
                queue.sync_pending(
                    FakeUsageSync(("event-0", "foreign-event")),
                    enabled,
                )
            with self.assertRaisesRegex(ValueError, "duplicate"):
                queue.sync_pending(
                    FakeUsageSync(("event-0", "event-0")),
                    enabled,
                )
            with self.assertRaisesRegex(ValueError, "between 0 and 250"):
                queue.pending(limit=251)
            self.assertEqual(len(queue.pending()), 2)

    def test_export_delete_are_installation_scoped_and_content_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = UsageEventQueue(Path(tmp) / "usage-sync.sqlite")
            queue.enqueue(
                UsageEvent.create(
                    "install-1",
                    "classroom",
                    {"classroom_joins": 1, "classroom_seconds": 300},
                    "2026-08-16T10:00:00Z",
                    event_id="event-1",
                )
            )
            queue.enqueue(
                UsageEvent.create(
                    "install-2",
                    "assignment",
                    {"assignments_completed": 1},
                    "2026-08-16T10:00:01Z",
                    event_id="event-2",
                )
            )
            exported = queue.export_for_installation("install-1")
            encoded = json.dumps(exported, sort_keys=True).lower()
            for forbidden in ("pgn", "fen", "chat", "audio", "video", "clipboard"):
                self.assertNotIn(forbidden, encoded)
            self.assertEqual(
                [event["event_id"] for event in exported["events"]],
                ["event-1"],
            )
            self.assertEqual(queue.delete_for_installation("install-1"), 1)
            self.assertEqual(
                queue.export_for_installation("install-1")["events"],
                [],
            )
            self.assertEqual(
                [
                    event["event_id"]
                    for event in queue.export_for_installation("install-2")["events"]
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
