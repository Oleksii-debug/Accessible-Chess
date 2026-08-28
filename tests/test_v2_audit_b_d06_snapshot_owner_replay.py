from __future__ import annotations

import hashlib
import unittest

from acs.acsdb import AcsDatabase
from acs.book_training import BookTrainingError, build_book_training_material
from acs.bookdocument import BookDocument, Exercise
from acs.chesscore import Board
from acs.duplicate_detection import detect_pgn_duplicates
from acs.game_identity import identity_for_game
from acs.gametree import parse_games
from acs.gametree_snapshot import (
    GAMETREE_SNAPSHOT_SCHEMA_VERSION,
    GameTreeSnapshot,
    GameTreeSnapshotCode,
    GameTreeSnapshotError,
    restore_game,
    snapshot_from_record,
    snapshot_game,
    snapshot_to_record,
)
from acs.pgn_roundtrip import (
    MAX_PGN_TAG_VALUE_CHARS,
    PgnRoundTripError,
    PgnRoundTripErrorCode,
    parse_pgn_text,
    serialize_pgn_text,
)


# Exact semantic seed used by PR #350's independently proven
# DIVERGENT_NON_STRICT_RESTORE probe.
ATTACHED_NAG_PGN = '[Event "NAG equivalence"]\n[Result "*"]\n\n1. e4?! *\n'


class D06SnapshotOwnerReplayTests(unittest.TestCase):
    def _original_external_snapshot(self) -> tuple[object, GameTreeSnapshot]:
        structural = parse_games(ATTACHED_NAG_PGN)
        self.assertEqual(len(structural), 1)
        game = structural[0]
        identity = identity_for_game(game)
        snapshot = GameTreeSnapshot(
            schema_version=GAMETREE_SNAPSHOT_SCHEMA_VERSION,
            pgn_text=ATTACHED_NAG_PGN,
            pgn_digest=hashlib.sha256(ATTACHED_NAG_PGN.encode("utf-8")).hexdigest(),
            tree_digest=identity.tree_digest,
            record_digest=identity.record_digest,
            source_index=game.source_index,
            warnings=tuple(game.warnings),
        )
        return game, snapshot_from_record(snapshot_to_record(snapshot))

    def test_original_external_noncanonical_snapshot_now_fails_closed(self) -> None:
        _, external = self._original_external_snapshot()
        with self.assertRaises(GameTreeSnapshotError) as caught:
            restore_game(external)
        self.assertEqual(caught.exception.code, GameTreeSnapshotCode.IDENTITY_MISMATCH)

    def test_noncanonical_structural_graph_cannot_be_published_as_snapshot(self) -> None:
        game, _ = self._original_external_snapshot()
        with self.assertRaises(GameTreeSnapshotError) as caught:
            snapshot_game(game)
        self.assertEqual(caught.exception.code, GameTreeSnapshotCode.INVALID_SNAPSHOT)

    def test_adjacent_d07_and_d08_controls_remain_divergent(self) -> None:
        # These are deliberate anti-weakening controls. #360 owns only D06
        # snapshot semantics; the other three #350 divergences must not vanish
        # merely because this audit changed its expectations.
        oversized = "X" * (MAX_PGN_TAG_VALUE_CHARS + 1)
        oversized_pgn = f'[Event "{oversized}"]\n[Result "*"]\n\n*\n'
        with self.assertRaises(PgnRoundTripError) as canonical:
            parse_pgn_text(oversized_pgn, strict=True)
        self.assertEqual(canonical.exception.code, PgnRoundTripErrorCode.TAG_SIZE_LIMIT)
        with AcsDatabase() as database:
            report = database.import_pgn_text(oversized_pgn, "oversized-event.pgn")
            self.assertEqual(report.total, 1)

        canonical_games = parse_pgn_text(ATTACHED_NAG_PGN, strict=True)
        canonical_text = serialize_pgn_text(canonical_games)
        with AcsDatabase() as database:
            database.import_pgn_text(canonical_text, "canonical.pgn")
            duplicate_report = detect_pgn_duplicates(database, ATTACHED_NAG_PGN)
        self.assertFalse(
            any(match.kind in {"record", "tree"} for match in duplicate_report.matches)
        )

        exercise = Exercise(
            fen=Board.START,
            prompt="QA attached annotation",
            solution_pgn=ATTACHED_NAG_PGN,
            block_id="qa-attached-nag",
        )
        book = BookDocument("QA", blocks=[exercise])
        try:
            build_book_training_material(book, "block:qa-attached-nag")
        except BookTrainingError as exc:  # pragma: no cover - repair would flip this control
            self.fail(f"D08 adjacent control unexpectedly failed closed: {exc.code.value}")


if __name__ == "__main__":
    unittest.main()
