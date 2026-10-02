from __future__ import annotations

import unittest

from acs import classroom_domain as cd
from acs import education_workspace as ew
from acs.chesscore import Board
from acs.prepared_position_authoring import (
    PreparedPositionAuthoringError,
    delete_authored_prepared_position,
    save_authored_prepared_position,
    source_from_board,
    source_from_book,
    source_from_database,
    source_from_fen,
    source_from_pgn,
)
from acs.teaching_session import PositionSourceKind


FEN = "8/8/8/8/8/8/4K3/6k1 w - -"
OTHER_FEN = "8/8/8/8/8/3k4/8/4K3 b - -"


class PreparedPositionAuthoringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = ew.EducationWorkspace.empty(cd.ClassroomSnapshot())

    def test_current_or_editor_board_snapshot_is_exact_and_non_mutating(self) -> None:
        board = Board(FEN)
        before_fen = board.fen()
        before_undo = tuple(board.undo_stack)
        before_redo = tuple(board.redo_stack)
        before_last = board.last_move

        source = source_from_board(board)

        self.assertEqual(source.kind, PositionSourceKind.FEN)
        self.assertEqual(source.fen, before_fen)
        self.assertEqual(board.fen(), before_fen)
        self.assertEqual(tuple(board.undo_stack), before_undo)
        self.assertEqual(tuple(board.redo_stack), before_redo)
        self.assertEqual(board.last_move, before_last)

    def test_board_capture_requires_exact_canonical_board(self) -> None:
        with self.assertRaisesRegex(
            PreparedPositionAuthoringError,
            "canonical Chess Core Board",
        ):
            source_from_board(object())

    def test_fen_authoring_delegates_normalization_to_chess_core(self) -> None:
        source = source_from_fen(FEN)
        self.assertEqual(source.kind, PositionSourceKind.FEN)
        self.assertEqual(source.fen, Board(FEN).fen())
        self.assertEqual(source.fen.split()[-2:], ["0", "1"])

    def test_invalid_fen_is_sanitized_at_authoring_boundary(self) -> None:
        with self.assertRaisesRegex(
            PreparedPositionAuthoringError,
            "FEN is invalid",
        ):
            source_from_fen("not a FEN")

    def test_pgn_anchor_preserves_exact_position_and_provenance(self) -> None:
        source = source_from_pgn(
            fen=FEN,
            source_ref="game-42",
            source_index=17,
        )
        self.assertEqual(source.kind, PositionSourceKind.PGN)
        self.assertEqual(source.fen, Board(FEN).fen())
        self.assertEqual(source.source_ref, "game-42")
        self.assertEqual(source.source_index, 17)

    def test_book_and_database_anchors_preserve_owner_references(self) -> None:
        book = source_from_book(fen=FEN, source_ref="book:chapter-3:diagram-5")
        database = source_from_database(
            fen=OTHER_FEN,
            source_ref="acsdb:game-99:ply-14",
        )
        self.assertEqual(book.kind, PositionSourceKind.BOOK)
        self.assertEqual(book.source_ref, "book:chapter-3:diagram-5")
        self.assertIsNone(book.source_index)
        self.assertEqual(database.kind, PositionSourceKind.DATABASE)
        self.assertEqual(database.source_ref, "acsdb:game-99:ply-14")
        self.assertIsNone(database.source_index)
        self.assertEqual(database.fen, Board(OTHER_FEN).fen())

    def test_invalid_external_provenance_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            PreparedPositionAuthoringError,
            "provenance is invalid",
        ):
            source_from_pgn(
                fen=FEN,
                source_ref="bad ref with spaces",
                source_index=0,
            )
        with self.assertRaisesRegex(
            PreparedPositionAuthoringError,
            "provenance is invalid",
        ):
            source_from_book(
                fen=FEN,
                source_ref="",
            )

    def test_authored_save_reuses_d10_identity_metadata_and_cas(self) -> None:
        source = source_from_board(Board(FEN))
        changed = save_authored_prepared_position(
            self.workspace,
            position_id="prep-board",
            source=source,
            expected_position_revision=0,
            title="Opposition",
            student_prompt="Whose move matters here?",
            tags=("endgame", "king"),
            order_index=2,
            teacher_notes="Ask before demonstrating the key square.",
        )
        item = ew.get_prepared_position(changed, "prep-board")

        self.assertEqual(item.source, source)
        self.assertEqual(item.title, "Opposition")
        self.assertEqual(item.student_prompt, "Whose move matters here?")
        self.assertEqual(item.tags, ("endgame", "king"))
        self.assertEqual(item.order_index, 2)
        self.assertEqual(item.revision, 0)
        self.assertFalse(hasattr(item, "board"))

        retry = save_authored_prepared_position(
            changed,
            position_id="prep-board",
            source=source,
            expected_position_revision=0,
        )
        self.assertIs(retry, changed)

    def test_authored_save_does_not_hide_canonical_stale_cas_failure(self) -> None:
        first = save_authored_prepared_position(
            self.workspace,
            position_id="prep-cas",
            source=source_from_fen(FEN),
            expected_position_revision=0,
        )
        updated = save_authored_prepared_position(
            first,
            position_id="prep-cas",
            source=source_from_fen(OTHER_FEN),
            expected_position_revision=0,
        )
        self.assertEqual(
            ew.get_prepared_position(updated, "prep-cas").revision,
            1,
        )
        with self.assertRaisesRegex(
            ew.EducationWorkspaceError,
            "stale prepared position revision",
        ):
            save_authored_prepared_position(
                updated,
                position_id="prep-cas",
                source=source_from_fen(FEN),
                expected_position_revision=0,
            )

    def test_authoring_delete_uses_same_d10_cas_boundary(self) -> None:
        saved = save_authored_prepared_position(
            self.workspace,
            position_id="prep-delete",
            source=source_from_fen(FEN),
            expected_position_revision=0,
            title="Delete me",
        )
        deleted = delete_authored_prepared_position(
            saved,
            position_id="prep-delete",
            expected_position_revision=0,
        )
        self.assertEqual(deleted.prepared_positions, ())
        with self.assertRaisesRegex(
            ew.EducationWorkspaceError,
            "unknown or ambiguous prepared position",
        ):
            delete_authored_prepared_position(
                deleted,
                position_id="prep-delete",
                expected_position_revision=0,
            )

    def test_authoring_sources_do_not_mutate_workspace_until_explicit_save(self) -> None:
        before = self.workspace.to_json()
        source_from_fen(FEN)
        source_from_pgn(
            fen=FEN,
            source_ref="game-1",
            source_index=1,
        )
        source_from_book(fen=FEN, source_ref="book:one")
        source_from_database(fen=FEN, source_ref="db:one")
        self.assertEqual(self.workspace.to_json(), before)


if __name__ == "__main__":
    unittest.main()
