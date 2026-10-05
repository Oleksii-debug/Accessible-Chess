from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from acs.usage_sync import UsageAnalyticsPolicy, UsageEvent, UsageEventQueue, UsageSyncPort


NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)
ENABLED = UsageAnalyticsPolicy(analytics_enabled=True)


def event(
    *,
    kind: str = "feature",
    counters: dict[str, int] | None = None,
) -> UsageEvent:
    return UsageEvent.create(
        "install-1",
        kind,
        counters or {"feature_uses": 1},
        "2026-08-16T10:00:00Z",
        event_id="event-1",
    )


class ReplacingAckPort(UsageSyncPort):
    def __init__(self, queue: UsageEventQueue) -> None:
        self.queue = queue
        self.sent: tuple[UsageEvent, ...] = ()

    def sync_events(self, events: tuple[UsageEvent, ...]) -> tuple[str, ...]:
        self.sent = tuple(events)
        self.queue.delete_for_installation("install-1")
        self.queue.enqueue(
            event(kind="game", counters={"games_started": 1}),
            ENABLED,
        )
        return ("event-1",)


class DeletingAckPort(UsageSyncPort):
    def __init__(self, queue: UsageEventQueue) -> None:
        self.queue = queue

    def sync_events(self, events: tuple[UsageEvent, ...]) -> tuple[str, ...]:
        self.queue.delete_for_installation("install-1")
        return tuple(item.event_id for item in events)


class UsageSyncAckSnapshotTests(unittest.TestCase):
    def test_provider_ack_cannot_mark_reused_event_id_with_different_data_synced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = UsageEventQueue(
                Path(tmp) / "usage-sync.sqlite",
                now=lambda: NOW,
            )
            original = event()
            self.assertTrue(queue.enqueue(original, ENABLED))
            port = ReplacingAckPort(queue)

            with self.assertRaisesRegex(
                ValueError,
                "usage event changed after provider acknowledgement",
            ):
                queue.sync_pending(port, ENABLED, "install-1")

            self.assertEqual(port.sent, (original,))
            pending = queue.pending("install-1")
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0].event_id, "event-1")
            self.assertEqual(pending[0].kind, "game")
            self.assertEqual(dict(pending[0].counters), {"games_started": 1})

    def test_provider_ack_cannot_succeed_after_event_was_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            queue = UsageEventQueue(
                Path(tmp) / "usage-sync.sqlite",
                now=lambda: NOW,
            )
            self.assertTrue(queue.enqueue(event(), ENABLED))

            with self.assertRaisesRegex(
                ValueError,
                "usage event changed after provider acknowledgement",
            ):
                queue.sync_pending(DeletingAckPort(queue), ENABLED, "install-1")

            self.assertEqual(queue.pending("install-1"), ())


if __name__ == "__main__":
    unittest.main()
