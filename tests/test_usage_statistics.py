from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from acs.usage_statistics import (
    AggregateUsageStatistics,
    UsageStatisticsSnapshot,
    UsageStatisticsStore,
)


class UsageStatisticsTests(unittest.TestCase):
    def test_counts_session_games_training_and_classroom_without_raw_content(self) -> None:
        stats = AggregateUsageStatistics(UsageStatisticsSnapshot("install-1"))
        stats.start_session()
        stats.add_session_seconds(120)
        stats.start_game()
        stats.complete_game()
        stats.attempt_exercise()
        stats.complete_exercise()
        stats.start_classroom()
        stats.add_classroom_seconds(90)
        snapshot = stats.snapshot
        self.assertEqual(snapshot.sessions_started, 1)
        self.assertEqual(snapshot.session_seconds, 120)
        self.assertEqual(snapshot.games_completed, 1)
        self.assertEqual(snapshot.exercises_completed, 1)
        self.assertEqual(snapshot.classroom_sessions, 1)
        self.assertEqual(snapshot.classroom_seconds, 90)
        forbidden = {"pgn", "fen", "book", "audio", "chat", "move_text"}
        self.assertTrue(forbidden.isdisjoint(snapshot.as_dict()))

    def test_cannot_complete_non_started_game_or_exercise(self) -> None:
        stats = AggregateUsageStatistics(UsageStatisticsSnapshot("install-1"))
        with self.assertRaises(ValueError):
            stats.complete_game()
        with self.assertRaises(ValueError):
            stats.complete_exercise()

    def test_store_round_trip_is_bound_to_installation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stats.json"
            store = UsageStatisticsStore(path)
            snapshot = UsageStatisticsSnapshot("install-1", sessions_started=2, session_seconds=50)
            store.save(snapshot)
            self.assertEqual(store.load("install-1"), snapshot)
            other = store.load("install-2")
            self.assertEqual(other.installation_id, "install-2")
            self.assertIsNotNone(store.warning)

    def test_negative_counters_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            UsageStatisticsSnapshot("install-1", games_started=-1)


if __name__ == "__main__":
    unittest.main()
