import os
import sqlite3
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.gametree import PgnGame, VariationLine
from acs.library_import_service import (
    LibraryImportCancelledError,
    LibraryImportControlError,
    LibraryImportProgress,
    LibraryImportService,
    LibraryImportStorageError,
)


DIGEST = "A" * 64


def game(index: int, *, warning: bool = False) -> PgnGame:
    return PgnGame(
        tags={
            "Event": f"Library {index}",
            "White": f"White {index}",
            "Black": f"Black {index}",
            "Result": "*",
        },
        line=VariationLine(result="*"),
        source_index=index,
        warnings=["fixture warning"] if warning else [],
    )


class D07LibraryImportServiceTests(unittest.TestCase):
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

    def test_immediate_cancellation_is_zero_mutation(self) -> None:
        with self.assertRaisesRegex(LibraryImportCancelledError, "Library import cancelled"):
            self.service.import_games(
                (game(0), game(1)),
                source_name="cancel.pgn",
                source_format="PGN",
                source_sha256=DIGEST,
                cancel_check=lambda: True,
            )
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_mid_batch_cancellation_rolls_back_source_and_every_game(self) -> None:
        calls = 0
        seen_progress: list[tuple[int, int]] = []

        def cancel() -> bool:
            nonlocal calls
            calls += 1
            return calls == 4

        def progress(item: LibraryImportProgress) -> None:
            seen_progress.append((item.processed_games, item.total_games))

        with self.assertRaisesRegex(LibraryImportCancelledError, "Library import cancelled"):
            self.service.import_games(
                tuple(game(i) for i in range(4)),
                source_name="cancel-mid.pgn",
                source_format="pgn",
                source_sha256=DIGEST,
                cancel_check=cancel,
                progress_callback=progress,
            )

        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 0)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 0)
        attempts = self.db.list_import_attempts()
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["status"], "failed")
        self.assertIsNone(attempts[0]["source_id"])
        self.assertEqual(attempts[0]["game_count"], 0)
        self.assertEqual(attempts[0]["error_message"], "Library import cancelled")
        self.assertEqual(seen_progress, [(0, 4), (1, 4)])

    def test_cancel_at_commit_boundary_still_rolls_back_complete_batch(self) -> None:
        calls = 0

        def cancel() -> bool:
            nonlocal calls
            calls += 1
            return calls == 4

        with self.assertRaises(LibraryImportCancelledError):
            self.service.import_games(
                (game(0),),
                source_name="boundary.pgn",
                source_format="pgn",
                source_sha256=DIGEST,
                cancel_check=cancel,
            )

        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 0)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 0)
        attempt = self.db.list_import_attempts()[0]
        self.assertEqual(attempt["status"], "failed")
        self.assertIsNone(attempt["source_id"])

    def test_progress_is_exact_count_based_and_success_result_is_bounded(self) -> None:
        seen: list[LibraryImportProgress] = []
        result = self.service.import_games(
            (game(0), game(1, warning=True), game(2)),
            source_name="counts.pgn",
            source_format="PGN",
            source_sha256=DIGEST,
            progress_callback=seen.append,
        )

        self.assertEqual(
            [(item.processed_games, item.total_games) for item in seen],
            [(0, 3), (1, 3), (2, 3), (3, 3)],
        )
        self.assertTrue(all(item.attempt_id == result.attempt_id for item in seen))
        self.assertEqual(result.game_count, 3)
        self.assertEqual(result.warning_count, 1)
        self.assertLessEqual(result.first_game_id, result.last_game_id)
        self.assertFalse(hasattr(result, "game_ids"))

        source = self.db.get_source(result.source_id)
        self.assertEqual(source["source_name"], "counts.pgn")
        self.assertEqual(source["source_format"], "pgn")
        self.assertEqual(source["sha256"], DIGEST.lower())
        attempt = self.db.get_import_attempt(result.attempt_id)
        self.assertEqual(attempt["status"], "warning")
        self.assertEqual(attempt["source_id"], result.source_id)
        self.assertEqual(attempt["game_count"], 3)
        self.assertEqual(attempt["warning_count"], 1)
        self.assertIsNone(attempt["error_message"])

    def test_progress_callback_failure_is_sanitized_and_atomic(self) -> None:
        def progress(item: LibraryImportProgress) -> None:
            if item.processed_games == 2:
                raise RuntimeError("C:/private/user/secret-progress-detail")

        with self.assertRaisesRegex(
            LibraryImportControlError,
            "Library import progress callback failed",
        ):
            self.service.import_games(
                (game(0), game(1), game(2)),
                source_name="callback.pgn",
                source_format="pgn",
                source_sha256=DIGEST,
                progress_callback=progress,
            )

        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 0)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 0)
        attempt = self.db.list_import_attempts()[0]
        self.assertEqual(attempt["status"], "failed")
        self.assertEqual(attempt["error_message"], "Library import progress callback failed")
        self.assertNotIn("private", attempt["error_message"])
        self.assertNotIn("secret", attempt["error_message"])

    def test_storage_failure_rolls_back_and_connection_remains_reusable(self) -> None:
        self.db.conn.execute(
            """
            CREATE TRIGGER fail_third_game
            BEFORE INSERT ON games
            WHEN NEW.source_index = 2
            BEGIN
                SELECT RAISE(ABORT, 'C:/private/storage-detail');
            END;
            """
        )
        with self.assertRaisesRegex(LibraryImportStorageError, "Library import failed"):
            self.service.import_games(
                tuple(game(i) for i in range(4)),
                source_name="storage-fail.pgn",
                source_format="pgn",
                source_sha256=DIGEST,
            )

        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 0)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 0)
        attempt = self.db.list_import_attempts()[0]
        self.assertEqual(attempt["status"], "failed")
        self.assertEqual(attempt["error_message"], "Library import failed")
        self.assertNotIn("private", attempt["error_message"])

        self.db.conn.execute("DROP TRIGGER fail_third_game")
        recovered = self.service.import_games(
            (game(10), game(11)),
            source_name="recovered.pgn",
            source_format="pgn",
            source_sha256="b" * 64,
        )
        self.assertEqual(recovered.game_count, 2)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 2)

    def test_input_and_callback_contracts_fail_before_durable_mutation(self) -> None:
        bad_index = game(0)
        bad_index.source_index = True
        cases = (
            (lambda: self.service.import_games((), source_name="x", source_format="pgn", source_sha256=DIGEST), ValueError),
            (lambda: self.service.import_games((bad_index,), source_name="x", source_format="pgn", source_sha256=DIGEST), TypeError),
            (lambda: self.service.import_games((game(0),), source_name=" ", source_format="pgn", source_sha256=DIGEST), ValueError),
            (lambda: self.service.import_games((game(0),), source_name="x", source_format=" ", source_sha256=DIGEST), ValueError),
            (lambda: self.service.import_games((game(0),), source_name="x", source_format="pgn", source_sha256="not-a-digest"), ValueError),
            (lambda: self.service.import_games((game(0),), source_name="x", source_format="pgn", source_sha256=DIGEST, cancel_check=1), TypeError),
            (lambda: self.service.import_games((game(0),), source_name="x", source_format="pgn", source_sha256=DIGEST, progress_callback=1), TypeError),
        )
        for invoke, error_type in cases:
            with self.subTest(error_type=error_type):
                with self.assertRaises(error_type):
                    invoke()
                self.assertEqual(self.counts(), (0, 0, 0))

    def test_cancel_callback_must_return_exact_bool_and_failure_is_sanitized(self) -> None:
        with self.assertRaisesRegex(LibraryImportControlError, "cancel_check must return a boolean"):
            self.service.import_games(
                (game(0),),
                source_name="shape.pgn",
                source_format="pgn",
                source_sha256=DIGEST,
                cancel_check=lambda: 1,
            )
        self.assertEqual(self.counts(), (0, 0, 0))

        def broken_cancel() -> bool:
            raise RuntimeError("C:/private/cancel-detail")

        with self.assertRaisesRegex(
            LibraryImportControlError,
            "Library import cancellation check failed",
        ):
            self.service.import_games(
                (game(0),),
                source_name="broken.pgn",
                source_format="pgn",
                source_sha256=DIGEST,
                cancel_check=broken_cancel,
            )
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_duplicate_source_indices_fail_closed_without_partial_source(self) -> None:
        first = game(7)
        second = game(7)
        with self.assertRaises(LibraryImportStorageError):
            self.service.import_games(
                (first, second),
                source_name="duplicate-index.pgn",
                source_format="pgn",
                source_sha256=DIGEST,
            )
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 0)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 0)
        attempt = self.db.list_import_attempts()[0]
        self.assertEqual(attempt["status"], "failed")
        self.assertIsNone(attempt["source_id"])

    def test_large_batch_reopens_without_unbounded_result_identity_list(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".acsdb")
        os.close(fd)
        try:
            with AcsDatabase(path) as database:
                service = LibraryImportService(database)
                parsed_games = tuple(game(i, warning=(i % 1000 == 0)) for i in range(5000))
                result = service.import_games(
                    parsed_games,
                    source_name="large-library.pgn",
                    source_format="pgn",
                    source_sha256="c" * 64,
                )
                self.assertEqual(result.game_count, 5000)
                self.assertEqual(result.warning_count, 5)
                self.assertFalse(hasattr(result, "game_ids"))
                self.assertEqual(database.get_game(result.first_game_id)["source_index"], 0)
                self.assertEqual(database.get_game(result.last_game_id)["source_index"], 4999)

            with AcsDatabase(path) as reopened:
                self.assertEqual(reopened.schema_version, 3)
                self.assertEqual(reopened.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 5000)
                source = reopened.conn.execute(
                    "SELECT id FROM sources WHERE source_name=?",
                    ("large-library.pgn",),
                ).fetchone()
                self.assertIsNotNone(source)
                attempt = reopened.list_import_attempts(limit=1)[0]
                self.assertEqual(attempt["status"], "warning")
                self.assertEqual(attempt["game_count"], 5000)
                self.assertEqual(attempt["warning_count"], 5)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_progress_dto_rejects_coercion_and_impossible_counts(self) -> None:
        for args, error_type in (
            ((True, 0, 1), TypeError),
            ((1, True, 1), TypeError),
            ((1, 0, True), TypeError),
            ((0, 0, 1), ValueError),
            ((1, -1, 1), ValueError),
            ((1, 2, 1), ValueError),
            ((1, 0, 0), ValueError),
        ):
            with self.subTest(args=args):
                with self.assertRaises(error_type):
                    LibraryImportProgress(*args)


if __name__ == "__main__":
    unittest.main()
