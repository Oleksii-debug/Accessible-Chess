from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from acs.lesson_plan import ClassroomPairing
from acs.lesson_session_storage import (
    LessonSessionConflictError,
    LessonSessionSQLiteStore,
    LessonSessionStorageError,
)


START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def pair(pairing_id: str, white: str, black: str, *, base: int = 600, inc: int = 5) -> ClassroomPairing:
    return ClassroomPairing(pairing_id, white, black, base, inc, START_FEN)


class LessonSessionSQLiteStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "teaching.sqlite3"
        self.store = LessonSessionSQLiteStore(self.db_path)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_schema_is_versioned_and_reopen_is_idempotent(self) -> None:
        with sqlite3.connect(self.db_path) as db:
            self.assertEqual(
                db.execute(
                    "SELECT value FROM classroom_schema_meta WHERE key='pairing_schema_version'"
                ).fetchone()[0],
                1,
            )
        LessonSessionSQLiteStore(self.db_path).integrity_check()

    def test_pairing_batch_round_trip_preserves_order_colors_time_and_exact_fen(self) -> None:
        exact_fen = START_FEN + "  "
        pairings = (
            ClassroomPairing("pair-1", "student-a", "student-b", 300, 2, exact_fen),
            ClassroomPairing("pair-2", "student-c", "student-d", 900, 10, None),
        )
        batch = self.store.record_pairing_batch(
            batch_id="pairing.batch.one",
            lesson_id="lesson.one",
            classroom_session_id="class.one",
            pairings=pairings,
            game_session_ids=("game.one", "game.two"),
        )
        self.assertEqual([r.pairing_id for r in batch.records], ["pair-1", "pair-2"])
        self.assertEqual([r.game_session_id for r in batch.records], ["game.one", "game.two"])
        self.assertEqual(batch.records[0].white_participant_id, "student-a")
        self.assertEqual(batch.records[0].black_participant_id, "student-b")
        self.assertEqual(batch.records[0].base_seconds, 300)
        self.assertEqual(batch.records[0].increment_seconds, 2)
        self.assertEqual(batch.records[0].start_fen, exact_fen)
        self.assertEqual(self.store.load_pairing_batch("pairing.batch.one"), batch)

    def test_reconnect_replay_is_exactly_idempotent(self) -> None:
        pairings = (pair("pair-1", "student-a", "student-b"),)
        first = self.store.record_pairing_batch(
            batch_id="pairing.reconnect",
            lesson_id="lesson.one",
            classroom_session_id="class.reconnect",
            pairings=pairings,
            game_session_ids=("game.reconnect",),
        )
        second = self.store.record_pairing_batch(
            batch_id="pairing.reconnect",
            lesson_id="lesson.one",
            classroom_session_id="class.reconnect",
            pairings=pairings,
            game_session_ids=("game.reconnect",),
        )
        self.assertEqual(second, first)
        self.assertEqual(self.store.session_pairings("class.reconnect"), first.records)

    def test_reused_batch_id_rejects_changed_participants_color_time_or_game_identity(self) -> None:
        original = (pair("pair-1", "student-a", "student-b"),)
        self.store.record_pairing_batch(
            batch_id="pairing.fixed",
            lesson_id="lesson.one",
            classroom_session_id="class.fixed",
            pairings=original,
            game_session_ids=("game.fixed",),
        )
        changed_cases = (
            (pair("pair-1", "student-b", "student-a"), "game.fixed"),
            (pair("pair-1", "student-a", "student-b", base=1200), "game.fixed"),
            (pair("pair-1", "student-a", "student-b"), "game.changed"),
        )
        for changed_pair, game_id in changed_cases:
            with self.subTest(changed_pair=changed_pair, game_id=game_id):
                with self.assertRaises(LessonSessionConflictError):
                    self.store.record_pairing_batch(
                        batch_id="pairing.fixed",
                        lesson_id="lesson.one",
                        classroom_session_id="class.fixed",
                        pairings=(changed_pair,),
                        game_session_ids=(game_id,),
                    )

    def test_game_session_identity_is_unique_across_batches_and_write_is_atomic(self) -> None:
        self.store.record_pairing_batch(
            batch_id="batch.first",
            lesson_id="lesson.one",
            classroom_session_id="class.one",
            pairings=(pair("pair-1", "student-a", "student-b"),),
            game_session_ids=("game.shared",),
        )
        with self.assertRaises(LessonSessionConflictError):
            self.store.record_pairing_batch(
                batch_id="batch.second",
                lesson_id="lesson.one",
                classroom_session_id="class.one",
                pairings=(
                    pair("pair-2", "student-c", "student-d"),
                    pair("pair-3", "student-e", "student-f"),
                ),
                game_session_ids=("game.new", "game.shared"),
            )
        self.assertIsNone(self.store.load_pairing_batch("batch.second"))
        self.assertIsNone(self.store.find_by_game_session("game.new"))
        self.assertIsNotNone(self.store.find_by_game_session("game.shared"))

    def test_lookup_by_game_session_returns_canonical_reference_without_board_state(self) -> None:
        self.store.record_pairing_batch(
            batch_id="batch.lookup",
            lesson_id="lesson.one",
            classroom_session_id="class.lookup",
            pairings=(pair("pair-1", "student-a", "student-b"),),
            game_session_ids=("game.lookup",),
        )
        record = self.store.find_by_game_session("game.lookup")
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.game_session_id, "game.lookup")
        self.assertFalse(hasattr(record, "board"))
        self.assertFalse(hasattr(record, "moves"))

    def test_empty_pairing_batch_is_persisted_and_reconnect_safe(self) -> None:
        first = self.store.record_pairing_batch(
            batch_id="batch.empty",
            lesson_id="lesson.one",
            classroom_session_id="class.empty",
            pairings=(),
            game_session_ids=(),
        )
        second = self.store.record_pairing_batch(
            batch_id="batch.empty",
            lesson_id="lesson.one",
            classroom_session_id="class.empty",
            pairings=(),
            game_session_ids=(),
        )
        self.assertEqual(first, second)
        self.assertEqual(first.records, ())

    def test_future_pairing_schema_fails_closed(self) -> None:
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "UPDATE classroom_schema_meta SET value=999 WHERE key='pairing_schema_version'"
            )
        with self.assertRaisesRegex(
            LessonSessionStorageError, "unsupported classroom pairing schema"
        ):
            LessonSessionSQLiteStore(self.db_path)
        with sqlite3.connect(self.db_path) as db:
            self.assertEqual(
                db.execute(
                    "SELECT value FROM classroom_schema_meta WHERE key='pairing_schema_version'"
                ).fetchone()[0],
                999,
            )


if __name__ == "__main__":
    unittest.main()
