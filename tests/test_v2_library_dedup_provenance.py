from __future__ import annotations

import os
import tempfile
import threading
import unittest

from acs.acsdb import AcsDatabase
from acs.gametree import PgnGame, VariationLine
from acs.library_import_service import (
    LibraryImportCancelledError,
    LibraryImportConflictError,
    LibraryImportProgress,
    LibraryImportService,
)


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def game(index: int, *, event: str | None = None, warning: bool = False) -> PgnGame:
    return PgnGame(
        tags={
            "Event": event or f"Dedupe {index}",
            "White": f"White {index}",
            "Black": f"Black {index}",
            "Result": "*",
        },
        line=VariationLine(result="*"),
        source_index=index,
        warnings=["fixture warning"] if warning else [],
    )


class V2LibraryDedupProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = AcsDatabase(":memory:")
        self.service = LibraryImportService(self.db)

    def tearDown(self) -> None:
        self.db.close()

    def counts(self) -> tuple[int, int, int]:
        return tuple(
            int(self.db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("sources", "games", "import_attempts")
        )

    def test_exact_repeat_reuses_source_and_games_but_preserves_attempt_provenance(self) -> None:
        games = tuple(game(i) for i in range(3))
        first = self.service.import_games(
            games,
            source_name="first-name.pgn",
            source_format="PGN",
            source_sha256=DIGEST_A.upper(),
        )
        second = self.service.import_games(
            games,
            source_name="renamed-copy.pgn",
            source_format="pgn",
            source_sha256=DIGEST_A,
        )

        self.assertFalse(first.reused)
        self.assertTrue(second.reused)
        self.assertEqual(second.source_id, first.source_id)
        self.assertEqual(second.first_game_id, first.first_game_id)
        self.assertEqual(second.last_game_id, first.last_game_id)
        self.assertEqual(self.counts(), (1, 3, 2))

        attempts = self.db.list_import_attempts(limit=10)
        self.assertEqual([row["source_name"] for row in attempts], ["renamed-copy.pgn", "first-name.pgn"])
        self.assertTrue(all(row["source_id"] == first.source_id for row in attempts))
        self.assertTrue(all(row["status"] == "full" for row in attempts))

    def test_reuse_emits_zero_staged_progress_only(self) -> None:
        games = (game(0), game(1))
        self.service.import_games(
            games,
            source_name="original.pgn",
            source_format="pgn",
            source_sha256=DIGEST_A,
        )
        seen: list[LibraryImportProgress] = []
        result = self.service.import_games(
            games,
            source_name="copy.pgn",
            source_format="pgn",
            source_sha256=DIGEST_A,
            progress_callback=seen.append,
        )
        self.assertTrue(result.reused)
        self.assertEqual([(item.processed_games, item.total_games) for item in seen], [(0, 2)])

    def test_same_name_different_bytes_is_distinct_source(self) -> None:
        first = self.service.import_games(
            (game(0),),
            source_name="database.pgn",
            source_format="pgn",
            source_sha256=DIGEST_A,
        )
        second = self.service.import_games(
            (game(0, event="changed bytes and semantics"),),
            source_name="database.pgn",
            source_format="pgn",
            source_sha256=DIGEST_B,
        )
        self.assertNotEqual(first.source_id, second.source_id)
        self.assertFalse(second.reused)
        self.assertEqual(self.counts(), (2, 2, 2))

    def test_same_digest_different_format_is_distinct_source(self) -> None:
        first = self.service.import_games(
            (game(0),),
            source_name="database.pgn",
            source_format="pgn",
            source_sha256=DIGEST_A,
        )
        second = self.service.import_games(
            (game(0),),
            source_name="database.cbh",
            source_format="cbh",
            source_sha256=DIGEST_A,
        )
        self.assertNotEqual(first.source_id, second.source_id)
        self.assertFalse(second.reused)
        self.assertEqual(self.counts(), (2, 2, 2))

    def test_same_immutable_identity_with_canonical_drift_fails_closed(self) -> None:
        first = self.service.import_games(
            (game(0), game(1)),
            source_name="stable.pgn",
            source_format="pgn",
            source_sha256=DIGEST_A,
        )
        original_rows = [dict(row) for row in self.db.conn.execute(
            "SELECT id, source_index, pgn_text FROM games ORDER BY id"
        )]

        with self.assertRaisesRegex(
            LibraryImportConflictError,
            "canonical content differs",
        ):
            self.service.import_games(
                (game(0), game(1, event="decoder drift")),
                source_name="stable.pgn",
                source_format="pgn",
                source_sha256=DIGEST_A,
            )

        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 1)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 2)
        self.assertEqual(
            [dict(row) for row in self.db.conn.execute("SELECT id, source_index, pgn_text FROM games ORDER BY id")],
            original_rows,
        )
        failed = self.db.list_import_attempts(limit=1)[0]
        self.assertEqual(failed["status"], "failed")
        self.assertIsNone(failed["source_id"])
        self.assertEqual(failed["error_message"], "Library source conflicts with existing canonical import")
        self.assertEqual(self.db.get_source(first.source_id)["source_name"], "stable.pgn")

    def test_same_identity_with_warning_drift_fails_closed(self) -> None:
        self.service.import_games(
            (game(0),),
            source_name="stable.pgn",
            source_format="pgn",
            source_sha256=DIGEST_A,
        )
        with self.assertRaises(LibraryImportConflictError):
            self.service.import_games(
                (game(0, warning=True),),
                source_name="stable.pgn",
                source_format="pgn",
                source_sha256=DIGEST_A,
            )
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 1)

    def test_legacy_multiple_identity_candidates_fail_without_merging_or_deleting(self) -> None:
        with self.db.conn:
            first_id = self.db._insert_source("legacy-a.pgn", "pgn", DIGEST_A)
            second_id = self.db._insert_source("legacy-b.pgn", "pgn", DIGEST_A.upper())
            self.db._insert_game(game(0), first_id)
            self.db._insert_game(game(0), second_id)

        with self.assertRaisesRegex(LibraryImportConflictError, "identity is ambiguous"):
            self.service.import_games(
                (game(0),),
                source_name="third-copy.pgn",
                source_format="PGN",
                source_sha256=DIGEST_A,
            )
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 2)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 2)
        self.assertEqual(self.db.list_import_attempts(limit=1)[0]["status"], "failed")

    def test_failed_cancelled_import_remains_retryable(self) -> None:
        should_cancel = False

        def cancel() -> bool:
            return should_cancel

        def progress(item: LibraryImportProgress) -> None:
            nonlocal should_cancel
            if item.processed_games == 1:
                should_cancel = True

        with self.assertRaises(LibraryImportCancelledError):
            self.service.import_games(
                (game(0), game(1), game(2)),
                source_name="retry.pgn",
                source_format="pgn",
                source_sha256=DIGEST_A,
                cancel_check=cancel,
                progress_callback=progress,
            )
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 0)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 0)

        result = self.service.import_games(
            (game(0), game(1), game(2)),
            source_name="retry.pgn",
            source_format="pgn",
            source_sha256=DIGEST_A,
        )
        self.assertFalse(result.reused)
        self.assertEqual(self.counts(), (1, 3, 2))
        statuses = [row["status"] for row in self.db.list_import_attempts(limit=10)]
        self.assertEqual(statuses, ["full", "failed"])

    def test_reuse_records_current_source_warning_count_without_mutating_source(self) -> None:
        first = self.service.import_games(
            (game(0),),
            source_name="original.pgn",
            source_format="pgn",
            source_sha256=DIGEST_A,
        )
        second = self.service.import_games(
            (game(0),),
            source_name="copy.pgn",
            source_format="pgn",
            source_sha256=DIGEST_A,
            source_warning_count=2,
        )
        self.assertTrue(second.reused)
        self.assertEqual(second.warning_count, 2)
        attempt = self.db.get_import_attempt(second.attempt_id)
        self.assertEqual(attempt["status"], "warning")
        self.assertEqual(attempt["warning_count"], 2)
        self.assertEqual(attempt["source_id"], first.source_id)
        self.assertEqual(self.db.get_source(first.source_id)["source_name"], "original.pgn")

    def test_close_reopen_repeat_is_idempotent(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".acsdb")
        os.close(fd)
        try:
            with AcsDatabase(path) as database:
                first = LibraryImportService(database).import_games(
                    tuple(game(i) for i in range(32)),
                    source_name="persisted.pgn",
                    source_format="pgn",
                    source_sha256=DIGEST_A,
                )
            with AcsDatabase(path) as reopened:
                second = LibraryImportService(reopened).import_games(
                    tuple(game(i) for i in range(32)),
                    source_name="persisted-copy.pgn",
                    source_format="PGN",
                    source_sha256=DIGEST_A.upper(),
                )
                self.assertTrue(second.reused)
                self.assertEqual(second.source_id, first.source_id)
                self.assertEqual(reopened.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 1)
                self.assertEqual(reopened.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 32)
                self.assertEqual(reopened.conn.execute("SELECT COUNT(*) FROM import_attempts").fetchone()[0], 2)
                self.assertEqual(reopened.verify_integrity(), reopened.schema_version)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_large_repeat_does_not_publish_second_batch(self) -> None:
        games = tuple(game(i, warning=(i % 1000 == 0)) for i in range(5000))
        first = self.service.import_games(
            games,
            source_name="large.pgn",
            source_format="pgn",
            source_sha256=DIGEST_A,
        )
        second = self.service.import_games(
            games,
            source_name="large-copy.pgn",
            source_format="pgn",
            source_sha256=DIGEST_A,
        )
        self.assertFalse(first.reused)
        self.assertTrue(second.reused)
        self.assertEqual(second.game_count, 5000)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 1)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 5000)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM import_attempts").fetchone()[0], 2)

    def test_two_connections_concurrently_publish_one_source_and_one_game_batch(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".acsdb")
        os.close(fd)
        try:
            with AcsDatabase(path):
                pass

            barrier = threading.Barrier(2)
            results: list[tuple[int, bool]] = []
            errors: list[BaseException] = []
            lock = threading.Lock()

            def worker(name: str) -> None:
                try:
                    with AcsDatabase(path) as database:
                        service = LibraryImportService(database)
                        barrier.wait(timeout=5)
                        result = service.import_games(
                            tuple(game(i) for i in range(64)),
                            source_name=name,
                            source_format="pgn",
                            source_sha256=DIGEST_A,
                        )
                        with lock:
                            results.append((result.source_id, result.reused))
                except BaseException as exc:  # retained only for assertion below
                    with lock:
                        errors.append(exc)

            threads = [
                threading.Thread(target=worker, args=("concurrent-a.pgn",)),
                threading.Thread(target=worker, args=("concurrent-b.pgn",)),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=15)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            self.assertEqual(len(results), 2)
            self.assertEqual(len({source_id for source_id, _ in results}), 1)
            self.assertEqual(sorted(reused for _, reused in results), [False, True])

            with AcsDatabase(path) as reopened:
                self.assertEqual(reopened.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 1)
                self.assertEqual(reopened.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 64)
                self.assertEqual(reopened.conn.execute("SELECT COUNT(*) FROM import_attempts").fetchone()[0], 2)
                self.assertTrue(all(
                    row["status"] == "full" and row["source_id"] is not None
                    for row in reopened.list_import_attempts(limit=10)
                ))
                self.assertEqual(reopened.verify_integrity(), reopened.schema_version)
        finally:
            if os.path.exists(path):
                os.unlink(path)


if __name__ == "__main__":
    unittest.main()
