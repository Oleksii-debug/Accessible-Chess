from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from acs.usage_statistics import (
    ActiveSessionClock,
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

    def test_active_session_clock_excludes_suspended_time_and_does_not_double_count_resume(self) -> None:
        current_ns = 0

        def now_ns() -> int:
            return current_ns

        stats = AggregateUsageStatistics(UsageStatisticsSnapshot("install-1"))
        clock = ActiveSessionClock(now_ns=now_ns)
        self.assertTrue(clock.resume())
        self.assertFalse(clock.resume())

        current_ns += 5_600_000_000
        self.assertEqual(clock.checkpoint(stats), 5)
        self.assertEqual(stats.snapshot.session_seconds, 5)

        current_ns += 700_000_000
        self.assertEqual(clock.suspend(stats), 1)
        self.assertFalse(clock.is_active)
        self.assertEqual(stats.snapshot.session_seconds, 6)

        current_ns += 100_000_000_000
        self.assertEqual(clock.suspend(stats), 0)
        self.assertEqual(stats.snapshot.session_seconds, 6)

        self.assertTrue(clock.resume())
        current_ns += 800_000_000
        self.assertEqual(clock.suspend(stats), 1)
        self.assertEqual(stats.snapshot.session_seconds, 7)

    def test_active_session_clock_fails_closed_on_regression_without_losing_active_state(self) -> None:
        current_ns = 10_000

        def now_ns() -> int:
            return current_ns

        stats = AggregateUsageStatistics(UsageStatisticsSnapshot("install-1"))
        clock = ActiveSessionClock(now_ns=now_ns)
        self.assertTrue(clock.resume())
        current_ns = 9_999
        with self.assertRaisesRegex(ValueError, "moved backwards"):
            clock.suspend(stats)
        self.assertTrue(clock.is_active)
        self.assertEqual(stats.snapshot.session_seconds, 0)

        current_ns = 1_000_010_000
        self.assertEqual(clock.suspend(stats), 1)
        self.assertFalse(clock.is_active)
        self.assertEqual(stats.snapshot.session_seconds, 1)

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

    def test_partial_snapshot_recovers_fail_closed_instead_of_zero_filling_missing_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stats.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "installation_id": "install-1",
                        "sessions_started": 2,
                    }
                ),
                encoding="utf-8",
            )
            store = UsageStatisticsStore(path)
            recovered = store.load("install-1")
            self.assertEqual(recovered, UsageStatisticsSnapshot("install-1"))
            self.assertTrue(store.recovered_invalid_data)

    def test_concurrent_saves_use_independent_atomic_temp_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stats.json"
            store = UsageStatisticsStore(path)
            first = UsageStatisticsSnapshot("install-1", sessions_started=1)
            second = UsageStatisticsSnapshot("install-1", sessions_started=2)
            real_replace = os.replace
            first_replace_entered = threading.Event()
            release_first_replace = threading.Event()
            count_lock = threading.Lock()
            replace_count = 0
            errors: list[BaseException] = []

            def controlled_replace(source: object, target: object) -> None:
                nonlocal replace_count
                with count_lock:
                    replace_count += 1
                    current = replace_count
                if current == 1:
                    first_replace_entered.set()
                    if not release_first_replace.wait(5):
                        raise TimeoutError("timed out waiting to release first statistics publication")
                real_replace(source, target)

            def save(snapshot: UsageStatisticsSnapshot) -> None:
                try:
                    store.save(snapshot)
                except BaseException as exc:  # preserve exact cross-thread failure for assertion
                    errors.append(exc)

            with patch("acs.usage_statistics.os.replace", side_effect=controlled_replace):
                first_thread = threading.Thread(target=save, args=(first,))
                first_thread.start()
                self.assertTrue(first_replace_entered.wait(5))

                second_thread = threading.Thread(target=save, args=(second,))
                second_thread.start()
                second_thread.join(5)
                self.assertFalse(second_thread.is_alive())

                release_first_replace.set()
                first_thread.join(5)
                self.assertFalse(first_thread.is_alive())

            self.assertEqual(errors, [])
            self.assertEqual(replace_count, 2)
            self.assertEqual(store.load("install-1"), first)
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_save_confirms_parent_directory_durability_after_replace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stats.json"
            store = UsageStatisticsStore(path)
            snapshot = UsageStatisticsSnapshot("install-1", sessions_started=1)
            events: list[str] = []
            real_replace = os.replace

            def tracked_replace(source: object, target: object) -> None:
                events.append("replace")
                real_replace(source, target)

            def tracked_directory_sync(parent: Path) -> None:
                self.assertEqual(parent, path.parent)
                events.append("directory-fsync")

            with (
                patch("acs.usage_statistics.os.replace", side_effect=tracked_replace),
                patch("acs.usage_statistics._fsync_directory", side_effect=tracked_directory_sync),
            ):
                store.save(snapshot)

            self.assertEqual(events, ["replace", "directory-fsync"])
            self.assertEqual(store.load("install-1"), snapshot)

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic-link support is required")
    def test_save_rejects_redirected_parent_before_creating_outside_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside"
            outside.mkdir()
            redirected = root / "redirected"
            try:
                os.symlink(outside, redirected, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"directory symlink creation is unavailable: {exc}")

            path = redirected / "nested" / "stats.json"
            store = UsageStatisticsStore(path)
            snapshot = UsageStatisticsSnapshot("install-1", sessions_started=1)

            with self.assertRaisesRegex(OSError, "direct non-reparse directory"):
                store.save(snapshot)

            self.assertFalse((outside / "nested").exists())
            self.assertEqual(list(outside.iterdir()), [])

    def test_save_rejects_temp_path_substitution_without_deleting_foreign_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stats.json"
            store = UsageStatisticsStore(path)
            snapshot = UsageStatisticsSnapshot("install-1", sessions_started=1)
            real_replace = os.replace
            foreign_bytes = b"FOREIGN-STATISTICS-TEMP"
            substituted_path: Path | None = None
            owned_path: Path | None = None

            def substitute_before_publication(source: object, target: object) -> None:
                nonlocal substituted_path, owned_path
                source_path = Path(source)
                target_path = Path(target)
                if target_path == path:
                    owned_path = source_path.with_name(source_path.name + ".owned")
                    real_replace(source_path, owned_path)
                    source_path.write_bytes(foreign_bytes)
                    substituted_path = source_path
                    raise OSError("simulated statistics publication interruption")
                real_replace(source, target)

            with patch(
                "acs.usage_statistics.os.replace",
                side_effect=substitute_before_publication,
            ):
                with self.assertRaisesRegex(OSError, "simulated statistics publication"):
                    store.save(snapshot)

            assert substituted_path is not None
            assert owned_path is not None
            self.assertFalse(path.exists())
            self.assertEqual(substituted_path.read_bytes(), foreign_bytes)
            self.assertTrue(owned_path.is_file())

    def test_save_rejects_published_inode_substitution_before_durability_ack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stats.json"
            store = UsageStatisticsStore(path)
            snapshot = UsageStatisticsSnapshot("install-1", sessions_started=1)
            real_replace = os.replace
            owned_publication = path.with_name("stats-owned-publication.json")
            foreign_bytes = b"FOREIGN-PUBLISHED-BYTES"

            def substitute_after_publication(source: object, target: object) -> None:
                real_replace(source, target)
                if Path(target) == path:
                    real_replace(path, owned_publication)
                    path.write_bytes(foreign_bytes)

            with patch(
                "acs.usage_statistics.os.replace",
                side_effect=substitute_after_publication,
            ):
                with self.assertRaisesRegex(OSError, "changed before durability confirmation"):
                    store.save(snapshot)

            self.assertEqual(path.read_bytes(), foreign_bytes)
            self.assertTrue(owned_publication.is_file())

    @unittest.skipUnless(hasattr(os, "link"), "hard-link support is required")
    def test_save_rejects_hard_linked_publication_before_durability_ack(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stats.json"
            store = UsageStatisticsStore(path)
            snapshot = UsageStatisticsSnapshot("install-1", sessions_started=1)
            alias = Path(tmp) / "stats-alias.json"
            real_replace = os.replace

            def hard_link_before_publication(source: object, target: object) -> None:
                if Path(target) == path:
                    os.link(source, alias)
                real_replace(source, target)

            with patch(
                "acs.usage_statistics.os.replace",
                side_effect=hard_link_before_publication,
            ):
                with self.assertRaisesRegex(OSError, "private regular file"):
                    store.save(snapshot)

            self.assertTrue(path.is_file())
            self.assertTrue(alias.is_file())
            self.assertTrue(os.path.samefile(path, alias))

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

    def test_oversized_or_duplicate_key_payload_recovers_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stats.json"
            store = UsageStatisticsStore(path)

            path.write_bytes(b"{" + b"x" * (64 * 1024) + b"}")
            recovered = store.load("install-1")
            self.assertEqual(recovered, UsageStatisticsSnapshot("install-1"))
            self.assertTrue(store.recovered_invalid_data)

            path.write_text(
                '{"schema_version":1,"installation_id":"install-1",'
                '"installation_id":"install-1"}',
                encoding="utf-8",
            )
            recovered = store.load("install-1")
            self.assertEqual(recovered, UsageStatisticsSnapshot("install-1"))
            self.assertTrue(store.recovered_invalid_data)

    def test_identifiers_counters_and_overflow_are_bounded(self) -> None:
        for invalid in (None, True, 1):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                UsageStatisticsSnapshot(invalid)  # type: ignore[arg-type]
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

    def test_statistics_objects_are_closed_world_at_runtime_boundaries(self) -> None:
        class ForeignSnapshot:
            def as_dict(self) -> dict[str, object]:
                return {"installation_id": "install-1", "pgn": "SECRET"}

        with self.assertRaisesRegex(ValueError, "snapshot must be UsageStatisticsSnapshot"):
            AggregateUsageStatistics(ForeignSnapshot())  # type: ignore[arg-type]

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stats.json"
            store = UsageStatisticsStore(path)
            with self.assertRaisesRegex(ValueError, "snapshot must be UsageStatisticsSnapshot"):
                store.save(ForeignSnapshot())  # type: ignore[arg-type]
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
