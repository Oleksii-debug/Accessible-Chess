from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from acs.usage_sync import UsageEventQueue


NOW = datetime(2026, 10, 4, 16, 0, 0, tzinfo=timezone.utc)


def make_queue(path: Path) -> UsageEventQueue:
    return UsageEventQueue(path, now=lambda: NOW)


def inject_pending(path: Path, *, event_id: str, counters_json: str) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "INSERT INTO usage_events("
            "event_id, installation_id, kind, counters_json, created_at_utc, sync_state"
            ") VALUES (?, 'install-1', 'feature', ?, '2026-10-04T15:00:00Z', 'pending')",
            (event_id, counters_json),
        )
        connection.commit()
    finally:
        connection.close()


class PersistedUsageCounterBoundaryTests(unittest.TestCase):
    def test_duplicate_json_key_fails_closed_without_mutating_persisted_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "usage-sync.sqlite"
            queue = make_queue(path)
            raw = '{"feature_uses":1,"feature_uses":2}'
            inject_pending(path, event_id="duplicate", counters_json=raw)

            with self.assertRaisesRegex(ValueError, "duplicate object keys"):
                queue.pending("install-1")

            connection = sqlite3.connect(path)
            try:
                stored = connection.execute(
                    "SELECT counters_json FROM usage_events WHERE event_id = 'duplicate'"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(stored, raw)

    def test_normalization_collision_and_noncanonical_json_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "usage-sync.sqlite"
            queue = make_queue(path)
            inject_pending(
                path,
                event_id="normalized-duplicate",
                counters_json='{"FEATURE_USES":1,"feature_uses":2}',
            )
            with self.assertRaisesRegex(ValueError, "counter names must be unique"):
                queue.pending("install-1")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "usage-sync.sqlite"
            queue = make_queue(path)
            inject_pending(
                path,
                event_id="noncanonical",
                counters_json='{ "feature_uses" : 1 }',
            )
            with self.assertRaisesRegex(ValueError, "not canonical"):
                queue.pending("install-1")

    def test_oversized_persisted_json_is_rejected_before_json_decode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "usage-sync.sqlite"
            queue = make_queue(path)
            raw = '{"feature_uses":1,"padding":"' + ("x" * 5000) + '"}'
            inject_pending(path, event_id="oversized", counters_json=raw)

            with self.assertRaisesRegex(ValueError, "JSON size limit"):
                queue.pending("install-1")

    def test_canonical_writer_shape_remains_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "usage-sync.sqlite"
            queue = make_queue(path)
            inject_pending(
                path,
                event_id="canonical",
                counters_json='{"feature_uses":1}',
            )

            events = queue.pending("install-1")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].event_id, "canonical")
            self.assertEqual(dict(events[0].counters), {"feature_uses": 1})


if __name__ == "__main__":
    unittest.main()
