from __future__ import annotations

from pathlib import Path
import unittest

from acs.gametree_navigation import GameTreeCursor, VariationStep, resolve_line
from acs.pgn_document import PgnDocumentSession
from acs.version2_pgn_commands import Version2PgnCommands


def command_target(session: PgnDocumentSession) -> dict[str, object]:
    workspace = session.workspace
    view = workspace.view()
    cursor = workspace.cursor
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


class CompletePgnEditingUserFlowTests(unittest.TestCase):
    def test_empty_game_can_be_continued_with_legal_moves(self):
        session = PgnDocumentSession.from_text('[Event "New game"]\n[Result "*"]\n\n*')
        commands = Version2PgnCommands(lambda: session)

        payload = {**command_target(session), "text": "e4 e5 Nf3"}
        commands("pgn.append_moves", payload)

        game = session.workspace.current_game()
        self.assertEqual([move.san for move in game.line.moves], ["e4", "e5", "Nf3"])
        self.assertEqual(session.workspace.cursor, GameTreeCursor((), 3))
        self.assertTrue(session.workspace.dirty)

    def test_append_rejects_illegal_moves_without_mutation(self):
        session = PgnDocumentSession.from_text("1. e4 e5 *")
        session.workspace.line_end()
        commands = Version2PgnCommands(lambda: session)
        before = session.workspace.to_text()
        revision = session.workspace.content_revision

        with self.assertRaises(ValueError):
            commands("pgn.append_moves", {**command_target(session), "text": "e9"})

        self.assertEqual(session.workspace.to_text(), before)
        self.assertEqual(session.workspace.content_revision, revision)

    def test_append_requires_end_of_current_line(self):
        session = PgnDocumentSession.from_text("1. e4 e5 2. Nf3 Nc6 *")
        session.workspace.set_cursor(GameTreeCursor((), 2))
        commands = Version2PgnCommands(lambda: session)
        before = session.workspace.to_text()

        with self.assertRaises(ValueError):
            commands("pgn.append_moves", {**command_target(session), "text": "Bc4"})

        self.assertEqual(session.workspace.to_text(), before)

    def test_adds_variation_and_nested_subvariation_from_exact_origin(self):
        session = PgnDocumentSession.from_text("1. e4 e5 2. Nf3 Nc6 *")
        workspace = session.workspace
        commands = Version2PgnCommands(lambda: session)

        workspace.set_cursor(GameTreeCursor((), 2))
        commands(
            "pgn.variation_add",
            {**command_target(session), "text": "c5 Nf3"},
        )
        root = workspace.current_game().line
        self.assertEqual([m.san for m in root.moves[1].variations[0].moves], ["c5", "Nf3"])

        child_path = (VariationStep(1, 0),)
        workspace.set_cursor(GameTreeCursor(child_path, 2))
        commands(
            "pgn.variation_add",
            {**command_target(session), "text": "Nc3"},
        )
        child = resolve_line(workspace.current_game(), child_path)
        self.assertEqual(
            [m.san for m in child.moves[1].variations[0].moves],
            ["Nc3"],
        )

    def test_illegal_variation_is_atomic(self):
        session = PgnDocumentSession.from_text("1. e4 e5 2. Nf3 *")
        session.workspace.set_cursor(GameTreeCursor((), 2))
        commands = Version2PgnCommands(lambda: session)
        before = session.workspace.to_text()

        with self.assertRaises(ValueError):
            commands(
                "pgn.variation_add",
                {**command_target(session), "text": "e9"},
            )

        self.assertEqual(session.workspace.to_text(), before)

    def test_nag_edit_and_clear_round_trip(self):
        session = PgnDocumentSession.from_text("1. e4 e5 *")
        session.workspace.set_cursor(GameTreeCursor((), 1))
        commands = Version2PgnCommands(lambda: session)

        commands(
            "pgn.nag_edit",
            {**command_target(session), "text": "$1 ?!"},
        )
        self.assertEqual(
            session.workspace.current_game().line.moves[0].nags,
            ["$1", "?!"],
        )

        commands(
            "pgn.nag_edit",
            {**command_target(session), "text": ""},
        )
        self.assertEqual(session.workspace.current_game().line.moves[0].nags, [])

    def test_tag_edit_result_and_delete_are_atomic(self):
        session = PgnDocumentSession.from_text(
            '[Event "Old"]\n[White "Alpha"]\n[Black "Beta"]\n[Result "*"]\n\n1. e4 *'
        )
        commands = Version2PgnCommands(lambda: session)

        commands(
            "pgn.tag_edit",
            {**command_target(session), "name": "Event", "value": "New event"},
        )
        self.assertEqual(session.workspace.current_game().tags["Event"], "New event")

        commands(
            "pgn.tag_edit",
            {**command_target(session), "name": "Result", "value": "1-0"},
        )
        game = session.workspace.current_game()
        self.assertEqual(game.tags["Result"], "1-0")
        self.assertEqual(game.line.result, "1-0")

        commands(
            "pgn.tag_delete",
            {**command_target(session), "name": "Event"},
        )
        self.assertNotIn("Event", session.workspace.current_game().tags)

    def test_position_tags_remain_owned_by_position_workflow(self):
        session = PgnDocumentSession.from_text("1. e4 *")
        commands = Version2PgnCommands(lambda: session)
        before = session.workspace.to_text()

        for name in ("SetUp", "FEN"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                commands(
                    "pgn.tag_edit",
                    {**command_target(session), "name": name, "value": "1"},
                )
            self.assertEqual(session.workspace.to_text(), before)

    def test_search_crosses_games_and_targets_move_comment(self):
        session = PgnDocumentSession.from_text(
            '[Event "First"]\n[Result "*"]\n\n1. e4 e5 *\n\n'
            '[Event "Second"]\n[Result "*"]\n\n1. d4 {Needle comment} d5 *'
        )
        commands = Version2PgnCommands(lambda: session)

        commands(
            "pgn.search",
            {**command_target(session), "text": "needle comment"},
        )

        self.assertEqual(session.workspace.selected_game_index, 1)
        self.assertEqual(session.workspace.cursor, GameTreeCursor((), 1))
        self.assertFalse(session.workspace.dirty)

    def test_search_finds_tags_from_root_without_requiring_a_tree_selection(self):
        session = PgnDocumentSession.from_text(
            '[Event "Unique Event"]\n[Result "*"]\n\n*'
        )
        commands = Version2PgnCommands(lambda: session)

        commands(
            "pgn.search",
            {**command_target(session), "text": "unique event"},
        )

        self.assertEqual(session.workspace.selected_game_index, 0)
        self.assertEqual(session.workspace.cursor, GameTreeCursor())
        self.assertFalse(session.workspace.dirty)

    def test_accessible_pgn_surface_contains_complete_editing_dialogs(self):
        js = (
            Path(__file__).resolve().parents[1] / "web" / "full_product_pgn.js"
        ).read_text(encoding="utf-8")
        for marker in (
            '"pgn.search"',
            '"pgn.append_moves"',
            '"pgn.tag_edit"',
            '"pgn.tag_delete"',
            '"pgn.nag_edit"',
            '"pgn.variation_add"',
            'id: "pgn-search-dialog"',
            'id: "pgn-append-dialog"',
            'dialog.id = "pgn-tag-dialog"',
            'id: "pgn-nag-dialog"',
            'id: "pgn-variation-dialog"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, js)


if __name__ == "__main__":
    unittest.main()
