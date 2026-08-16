from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from acs.usage_sync import (
    MinorAnalyticsPolicy,
    ProfileEnrollmentPort,
    ProfileEnrollmentRequest,
    ProfileEnrollmentResult,
    UsageEvent,
    UsageEventQueue,
    UsageSyncPort,
)


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


class FakeEnrollment(ProfileEnrollmentPort):
    def enroll(self, request: ProfileEnrollmentRequest) -> ProfileEnrollmentResult:
        return ProfileEnrollmentResult(
            server_profile_id=f"server-{request.installation_id}",
            access_token="short-lived-token",
            expires_at_utc="2026-08-16T12:00:00Z",
        )


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
            with sqlite3.connect(path) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)

    def test_same_event_id_cannot_silently_overwrite_different_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = UsageEventQueue(Path(tmp) / "usage-sync.sqlite")
            queue.enqueue(
                UsageEvent.create(
                    "install-1", "game", {"games_started": 1}, "2026-08-16T10:00:00Z", event_id="event-1"
                )
            )
            with self.assertRaisesRegex(ValueError, "different aggregate data"):
                queue.enqueue(
                    UsageEvent.create(
                        "install-1", "game", {"games_completed": 1}, "2026-08-16T10:00:00Z", event_id="event-1"
                    )
                )

    def test_ordinary_analytics_rejects_raw_or_unbounded_content_fields(self) -> None:
        forbidden = (
            "pgn",
            "fen",
            "book",
            "database",
            "chat",
            "audio",
            "video",
            "file",
            "clipboard",
        )
        for name in forbidden:
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "not allowed"):
                    UsageEvent.create(
                        "install-1",
                        "feature",
                        {name: 1},
                        "2026-08-16T10:00:00Z",
                        event_id=f"event-{name}",
                    )

    def test_minor_sync_fails_closed_until_consent_and_retention_are_explicit(self) -> None:
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
            self.assertEqual(queue.sync_pending(port, MinorAnalyticsPolicy(is_minor=True)), 0)
            self.assertEqual(port.calls, [])
            self.assertEqual(
                queue.sync_pending(
                    port,
                    MinorAnalyticsPolicy(is_minor=True, consent_state="granted", retention_days=None),
                ),
                0,
            )
            self.assertEqual(port.calls, [])
            self.assertEqual(
                queue.sync_pending(
                    port,
                    MinorAnalyticsPolicy(is_minor=True, consent_state="granted", retention_days=30),
                ),
                1,
            )
            self.assertEqual(len(port.calls), 1)
            self.assertEqual(queue.pending(), ())

    def test_sync_is_idempotent_and_rejects_acknowledgements_outside_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "usage-sync.sqlite"
            queue = UsageEventQueue(path)
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
            bad = FakeUsageSync(("event-0", "foreign-event"))
            with self.assertRaisesRegex(ValueError, "outside this batch"):
                queue.sync_pending(bad, MinorAnalyticsPolicy(is_minor=False))
            self.assertEqual(len(queue.pending()), 2)

            good = FakeUsageSync(("event-0",))
            self.assertEqual(queue.sync_pending(good, MinorAnalyticsPolicy(is_minor=False)), 1)
            self.assertEqual(tuple(event.event_id for event in queue.pending()), ("event-1",))

    def test_export_and_delete_hooks_are_installation_scoped_and_content_bounded(self) -> None:
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
            self.assertEqual([event["event_id"] for event in exported["events"]], ["event-1"])
            self.assertEqual(queue.delete_for_installation("install-1"), 1)
            self.assertEqual(queue.export_for_installation("install-1")["events"], [])
            self.assertEqual([event["event_id"] for event in queue.export_for_installation("install-2")["events"]], ["event-2"])

    def test_profile_enrollment_contract_carries_no_display_name_or_static_admin_secret(self) -> None:
        request = ProfileEnrollmentRequest("INSTALL-1")
        self.assertEqual(request.installation_id, "install-1")
        result = FakeEnrollment().enroll(request)
        self.assertEqual(result.server_profile_id, "server-install-1")
        self.assertEqual(result.access_token, "short-lived-token")
        self.assertFalse(hasattr(request, "display_name"))
        self.assertFalse(hasattr(request, "admin_secret"))


if __name__ == "__main__":
    unittest.main()
