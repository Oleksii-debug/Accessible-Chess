from __future__ import annotations

import sqlite3
import tempfile
import unittest
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from acs.usage_sync import UsageAnalyticsPolicy, UsageEventQueue


NOW = datetime(2026, 10, 4, 16, 0, 0, tzinfo=timezone.utc)
ENABLED = UsageAnalyticsPolicy(analytics_enabled=True)


def make_queue(path: Path) -> UsageEventQueue:
    return UsageEventQueue(path, now=lambda: NOW)


def inject_pending(
    path: Path,
    *,
    event_id: str,
    counters_json: str,
    installation_id: str = "install-1",
    created_at_utc: str = "2026-10-04T15:00:00Z",
) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "INSERT INTO usage_events("
            "event_id, installation_id, kind, counters_json, created_at_utc, sync_state"
            ") VALUES (?, ?, 'feature', ?, ?, 'pending')",
            (event_id, installation_id, counters_json, created_at_utc),
        )
        connection.commit()
    finally:
        connection.close()


class ReplacingAckPort:
    def __init__(self, path: Path) -> None:
        self.path = path

    def sync_events(self, events):  # type: ignore[no-untyped-def]
        event_id = events[0].event_id
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("DELETE FROM usage_events WHERE event_id = ?", (event_id,))
            connection.execute(
                "INSERT INTO usage_events("
                "event_id, installation_id, kind, counters_json, created_at_utc, sync_state"
                ") VALUES (?, 'install-2', 'feature', '{\"feature_uses\":9}', "
                "'2026-10-04T15:00:01Z', 'pending')",
                (event_id,),
            )
            connection.commit()
        finally:
            connection.close()
        return (event_id,)


class DeletingAckPort:
    def __init__(self, path: Path) -> None:
        self.path = path

    def sync_events(self, events):  # type: ignore[no-untyped-def]
        event_id = events[0].event_id
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("DELETE FROM usage_events WHERE event_id = ?", (event_id,))
            connection.commit()
        finally:
            connection.close()
        return (event_id,)


class ConcurrentSyncAckPort:
    def __init__(self, path: Path) -> None:
        self.path = path

    def sync_events(self, events):  # type: ignore[no-untyped-def]
        event_id = events[0].event_id
        connection = sqlite3.connect(self.path)
        try:
            connection.execute(
                "UPDATE usage_events SET sync_state = 'synced' WHERE event_id = ?",
                (event_id,),
            )
            connection.commit()
        finally:
            connection.close()
        return (event_id,)


class UnderreportedAckSequence(Sequence[str]):
    def __len__(self) -> int:
        return 0

    def __getitem__(self, index: int) -> str:
        if index == 0:
            return "underreported"
        if index == 1:
            return "foreign"
        raise IndexError


class UnderreportingAckPort:
    def sync_events(self, events):  # type: ignore[no-untyped-def]
        return UnderreportedAckSequence()


class ExplodingAckSequence(Sequence[str]):
    def __len__(self) -> int:
        return 1

    def __getitem__(self, index: int) -> str:
        raise RuntimeError("SECRET adapter iterator detail")


class ExplodingAckPort:
    def sync_events(self, events):  # type: ignore[no-untyped-def]
        return ExplodingAckSequence()


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

    def test_stale_provider_ack_cannot_sync_reused_event_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "usage-sync.sqlite"
            queue = make_queue(path)
            inject_pending(
                path,
                event_id="reused",
                counters_json='{"feature_uses":1}',
            )

            with self.assertRaisesRegex(
                RuntimeError, "queue changed during provider acknowledgement"
            ):
                queue.sync_pending(ReplacingAckPort(path), ENABLED, "install-1")

            replacement = queue.pending("install-2")
            self.assertEqual(len(replacement), 1)
            self.assertEqual(replacement[0].event_id, "reused")
            self.assertEqual(dict(replacement[0].counters), {"feature_uses": 9})

    def test_local_deletion_during_provider_call_is_not_resurrected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "usage-sync.sqlite"
            queue = make_queue(path)
            inject_pending(
                path,
                event_id="deleted",
                counters_json='{"feature_uses":1}',
            )

            self.assertEqual(queue.sync_pending(DeletingAckPort(path), ENABLED, "install-1"), 1)
            self.assertEqual(queue.pending("install-1"), ())

    def test_concurrent_exact_sync_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "usage-sync.sqlite"
            queue = make_queue(path)
            inject_pending(
                path,
                event_id="already-synced",
                counters_json='{"feature_uses":1}',
            )

            self.assertEqual(
                queue.sync_pending(ConcurrentSyncAckPort(path), ENABLED, "install-1"),
                1,
            )
            self.assertEqual(queue.pending("install-1"), ())

    def test_ack_sequence_iteration_is_bounded_even_if_len_underreports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "usage-sync.sqlite"
            queue = make_queue(path)
            inject_pending(
                path,
                event_id="underreported",
                counters_json='{"feature_uses":1}',
            )

            with self.assertRaisesRegex(ValueError, "outside this batch"):
                queue.sync_pending(UnderreportingAckPort(), ENABLED, "install-1")
            self.assertEqual(
                [item.event_id for item in queue.pending("install-1")],
                ["underreported"],
            )

    def test_ack_sequence_iteration_failure_is_redacted_and_preserves_pending_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "usage-sync.sqlite"
            queue = make_queue(path)
            inject_pending(
                path,
                event_id="iterator-failure",
                counters_json='{"feature_uses":1}',
            )

            with self.assertRaisesRegex(
                ValueError, "^sync adapter acknowledgements could not be read$"
            ):
                queue.sync_pending(ExplodingAckPort(), ENABLED, "install-1")
            self.assertEqual(
                [item.event_id for item in queue.pending("install-1")],
                ["iterator-failure"],
            )


if __name__ == "__main__":
    unittest.main()
