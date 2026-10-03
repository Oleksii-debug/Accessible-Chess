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
    @staticmethod
    def _navigation_target(workspace):
        view = workspace.view()
        cursor = view.cursor
        return {
            "game_index": view.selected_game_index,
            "line_path": tuple(
                (step.parent_move_index, step.variation_index)
                for step in cursor.line_path
            ),
            "move_index": cursor.next_move_index - 1 if cursor.next_move_index else None,
            "expected_record_digest": view.current_record_digest,
            "expected_content_digest": view.content_digest,
            "content_revision": view.content_revision,
        }

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

    def test_game_navigation_cas_rejects_concurrent_game_change_without_skipping(self):
        session = PgnDocumentSession.from_text(
            '[Event "One"]\n[Result "*"]\n\n1. e4 *\n\n'
            '[Event "Two"]\n[Result "*"]\n\n1. d4 *\n\n'
            '[Event "Three"]\n[Result "*"]\n\n1. c4 *\n'
        )
        workspace = session.workspace
        commands = Version2PgnCommands(lambda: session)
        stale = self._navigation_target(workspace)

        workspace.next_game()
        self.assertEqual(1, workspace.selected_game_index)

        with self.assertRaisesRegex(ValueError, "stale"):
            commands("pgn.next_game", stale)

        self.assertEqual(1, workspace.selected_game_index)
        current = self._navigation_target(workspace)
        commands("pgn.next_game", current)
        self.assertEqual(2, workspace.selected_game_index)

    def test_game_navigation_cas_accepts_root_without_weakening_export_selection(self):
        session = PgnDocumentSession.from_text(
            '[Event "One"]\n[Result "*"]\n\n1. e4 *\n\n'
            '[Event "Two"]\n[Result "*"]\n\n1. d4 *\n'
        )
        workspace = session.workspace
        commands = Version2PgnCommands(lambda: session)
        root_target = self._navigation_target(workspace)

        self.assertEqual((), root_target["line_path"])
        self.assertIsNone(root_target["move_index"])
        with self.assertRaisesRegex(ValueError, "selected game-tree item"):
            PgnSelectionExportRequest.from_payload(root_target)

        commands("pgn.next_game", root_target)
        self.assertEqual(1, workspace.selected_game_index)
        self.assertEqual(GameTreeCursor(), workspace.cursor)

        commands("pgn.previous_game", self._navigation_target(workspace))
        self.assertEqual(0, workspace.selected_game_index)
        self.assertEqual(GameTreeCursor(), workspace.cursor)

    def test_game_navigation_cas_rejects_replaced_document_with_same_current_game(self):
        original = PgnDocumentSession.from_text(
            '[Event "Same"]\n[Result "*"]\n\n1. e4 *\n\n'
            '[Event "Original next"]\n[Result "*"]\n\n1. d4 *\n'
        )
        replacement = PgnDocumentSession.from_text(
            '[Event "Same"]\n[Result "*"]\n\n1. e4 *\n\n'
            '[Event "Replacement next"]\n[Result "*"]\n\n1. c4 *\n'
        )
        stale = self._navigation_target(original.workspace)
        original_view = original.workspace.view()
        replacement_view = replacement.workspace.view()

        self.assertEqual(
            original_view.current_record_digest,
            replacement_view.current_record_digest,
        )
        self.assertEqual(
            original_view.selected_game_index,
            replacement_view.selected_game_index,
        )
        self.assertEqual(original_view.content_revision, replacement_view.content_revision)
        self.assertNotEqual(original_view.content_digest, replacement_view.content_digest)

        commands = Version2PgnCommands(lambda: replacement)
        with self.assertRaisesRegex(ValueError, "document is stale"):
            commands("pgn.next_game", stale)

        self.assertEqual(0, replacement.workspace.selected_game_index)
        self.assertEqual(GameTreeCursor(), replacement.workspace.cursor)

    def test_game_navigation_cas_rejects_concurrent_cursor_change(self):
        session = PgnDocumentSession.from_text(
            '[Event "One"]\n[Result "*"]\n\n1. e4 e5 *\n\n'
            '[Event "Two"]\n[Result "*"]\n\n1. d4 *\n'
        )
        workspace = session.workspace
        commands = Version2PgnCommands(lambda: session)
        stale = self._navigation_target(workspace)

        workspace.next_move()
        self.assertEqual(GameTreeCursor((), 1), workspace.cursor)

        with self.assertRaisesRegex(ValueError, "stale"):
            commands("pgn.next_game", stale)

        self.assertEqual(0, workspace.selected_game_index)
        self.assertEqual(GameTreeCursor((), 1), workspace.cursor)

    def test_cas_validation_and_game_navigation_use_one_session_snapshot(self):
        document = (
            '[Event "One"]\n[Result "*"]\n\n1. e4 *\n\n'
            '[Event "Two"]\n[Result "*"]\n\n1. d4 *\n'
        )
        primary = PgnDocumentSession.from_text(document)
        replacement = PgnDocumentSession.from_text(document)
        calls = []

        def get_session():
            calls.append(len(calls) + 1)
            return primary if len(calls) == 1 else replacement

        target = self._navigation_target(primary.workspace)
        commands = Version2PgnCommands(get_session)

        commands("pgn.next_game", target)

        self.assertEqual([1], calls)
        self.assertEqual(1, primary.workspace.selected_game_index)
        self.assertEqual(0, replacement.workspace.selected_game_index)

    def test_empty_host_game_navigation_payload_remains_supported(self):
        session = PgnDocumentSession.from_text(
            '[Event "One"]\n[Result "*"]\n\n1. e4 *\n\n'
            '[Event "Two"]\n[Result "*"]\n\n1. d4 *\n'
        )
        commands = Version2PgnCommands(lambda: session)

        commands("pgn.next_game", {})

        self.assertEqual(1, session.workspace.selected_game_index)

    def test_illegal_move_never_produces_a_board_position(self):
        session = PgnDocumentSession.from_text('1. e5 *')
        session.workspace.next_move()
        with self.assertRaises(ValueError): Version2PgnCommands(lambda: session).current_fen()


if __name__ == '__main__': unittest.main()
