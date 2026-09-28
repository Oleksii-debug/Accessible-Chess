from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from acs.usage_statistics import (
    AggregateUsageStatistics,
    UsageStatisticsSnapshot,
    UsageStatisticsStore,
)


class UsageStatisticsTests(unittest.TestCase):
    def test_counts_only_aggregate_product_activity(self) -> None:
        stats = AggregateUsageStatistics(UsageStatisticsSnapshot("install-1"))
        stats.start_session()
        stats.add_session_seconds(120)
        stats.start_game()
        stats.complete_game()
        stats.attempt_exercise()
        stats.complete_exercise()
        stats.start_classroom()
        stats.add_classroom_seconds(90)
        stats.record_feature_use()
        snapshot = stats.snapshot
        self.assertEqual(snapshot.sessions_started, 1)
        self.assertEqual(snapshot.session_seconds, 120)
        self.assertEqual(snapshot.games_completed, 1)
        self.assertEqual(snapshot.exercises_completed, 1)
        self.assertEqual(snapshot.classroom_sessions, 1)
        self.assertEqual(snapshot.classroom_seconds, 90)
        self.assertEqual(snapshot.feature_uses, 1)
        forbidden = {"pgn", "fen", "book", "database", "chat", "audio", "video", "file", "clipboard"}
        self.assertTrue(forbidden.isdisjoint(snapshot.as_dict()))

    def test_cannot_complete_non_started_game_or_exercise(self) -> None:
        stats = AggregateUsageStatistics(UsageStatisticsSnapshot("install-1"))
        with self.assertRaises(ValueError):
            stats.complete_game()
        with self.assertRaises(ValueError):
            stats.complete_exercise()

    def test_store_round_trip_is_atomic_and_bound_to_installation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stats.json"
            store = UsageStatisticsStore(path)
            snapshot = UsageStatisticsSnapshot("INSTALL-1", sessions_started=2, session_seconds=50)
            store.save(snapshot)
            self.assertEqual(store.load("install-1"), snapshot)
            self.assertFalse(store.recovered_invalid_data)
            other = store.load("install-2")
            self.assertEqual(other.installation_id, "install-2")
            self.assertTrue(store.recovered_invalid_data)
            self.assertFalse(path.with_name(path.name + ".tmp").exists())

    def test_corrupt_or_unknown_local_payload_recovers_without_content_leak(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stats.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "installation_id": "install-1",
                        "pgn": "SECRET",
                    }
                ),
                encoding="utf-8",
            )
            store = UsageStatisticsStore(path)
            recovered = store.load("install-1")
            self.assertEqual(recovered, UsageStatisticsSnapshot("install-1"))
            self.assertTrue(store.recovered_invalid_data)

    def test_identifiers_counters_and_overflow_are_bounded(self) -> None:
        with self.assertRaises(ValueError):
            UsageStatisticsSnapshot("../profile")
        with self.assertRaises(ValueError):
            UsageStatisticsSnapshot("install-1", games_started=-1)
        with self.assertRaises(ValueError):
            UsageStatisticsSnapshot("install-1", session_seconds=2**63)
        stats = AggregateUsageStatistics(
            UsageStatisticsSnapshot("install-1", feature_uses=2**63 - 1)
        )
        with self.assertRaisesRegex(ValueError, "overflow"):
            stats.record_feature_use()


if __name__ == "__main__":
    unittest.main()
