from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from acs.chesscore import Board
from acs.game_identity import identity_for_game
from acs.gametree_navigation import GameTreeCursor, VariationStep
from acs.pgn_document import PgnDocumentSession
from acs.pgn_service import open_pgn
from acs.version2_pgn_commands import Version2PgnCommands
from acs.version2_windows_pgn_export import PgnSelectionExportRequest


class PgnCommandsTests(unittest.TestCase):
    def test_nested_variation_export_preserves_origin_annotations_and_source(self):
        session = PgnDocumentSession.from_text('1. e4 e5 2. Nf3 (2. Bc4 {comment} $1 Nf6 (2... Bc5)) Nc6 *')
        workspace = session.workspace
        path = (VariationStep(2, 0), VariationStep(1, 0))
        workspace.set_cursor(GameTreeCursor(path, 1))
        view = workspace.view()
        request = PgnSelectionExportRequest(0, ((2, 0), (1, 0)), 0, view.current_record_digest, view.content_revision)
        commands = Version2PgnCommands(lambda: session)
        before = workspace.to_text()
        expected = Board()
        for move in ('e4', 'e5', 'Bc4'): expected.push_text(move)
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / 'variation.pgn'
            commands.export_selected(request, destination)
            exported = open_pgn(destination).games[0]
        self.assertEqual(exported.tags['FEN'], expected.fen())
        self.assertEqual(exported.line.moves[0].san, 'Bc5')
        self.assertEqual(workspace.to_text(), before)
        expected.push_text('Bc5')
        self.assertEqual(commands.current_fen(), expected.fen())

    def test_stale_selection_cannot_publish_file(self):
        session = PgnDocumentSession.from_text('1. e4 *')
        session.workspace.next_move()
        view = session.workspace.view()
        request = PgnSelectionExportRequest(0, (), 0, view.current_record_digest, view.content_revision)
        commands = Version2PgnCommands(lambda: session)
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / 'stale.pgn'
            with self.assertRaises(ValueError): commands.export_selected(replace(request, content_revision=view.content_revision + 1), destination)
            self.assertFalse(destination.exists())

    def test_illegal_move_never_produces_a_board_position(self):
        session = PgnDocumentSession.from_text('1. e5 *')
        session.workspace.next_move()
        with self.assertRaises(ValueError): Version2PgnCommands(lambda: session).current_fen()


if __name__ == '__main__': unittest.main()
