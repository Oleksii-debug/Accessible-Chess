import unittest

from acs.game_references import GameReferenceError, MoveRef, PositionRef, VariationRef, child_variation
from acs.gametree import parse_games, structural_signature
from acs.pgn_workspace import PgnQuery, PgnWorkspace, PgnWorkspaceError, import_pgn


COMPLEX = r'''
[Event "Accessible Open"]
[Site "Uzhhorod"]
[Date "2026.08.16"]
[Round "1"]
[White "Alpha"]
[Black "Beta"]
[Result "1-0"]
[ECO "C50"]
[Annotator "A \"quoted\" name"]

1. e4 {main comment} e5 (1... c5 $1 {Sicilian} (1... e6!? 2. d4))
2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 6. Re1 b5
7. Bb3 d6 8. c3 O-O 9. h3 1-0

[Event "Promotion"]
[Site "Test"]
[Date "2026.08.16"]
[Round "2"]
[White "Gamma"]
[Black "Delta"]
[Result "1/2-1/2"]
[SetUp "1"]
[FEN "8/P7/8/8/8/8/7p/4K2k w - - 0 1"]

1. a8=Q+ h1=Q 2. Qxh1+ Qxh1 1/2-1/2
'''


class PgnWorkspaceTests(unittest.TestCase):
    def test_import_report_and_collection_stats_cover_recursive_content(self):
        workspace, report = import_pgn(COMPLEX)
        self.assertEqual(len(workspace), 2)
        self.assertEqual(report.stats.games, 2)
        self.assertGreater(report.stats.mainline_plies, 10)
        self.assertGreater(report.stats.recursive_plies, report.stats.mainline_plies)
        self.assertEqual(report.stats.variations, 2)
        self.assertGreaterEqual(report.stats.comments, 2)
        self.assertGreaterEqual(report.stats.nags, 2)
        self.assertEqual(report.usable_games, 2)
        self.assertEqual(report.rejected_games, 0)

    def test_metadata_search_player_text_result_eco_and_structure_filters(self):
        workspace = PgnWorkspace.from_text(COMPLEX)
        self.assertEqual([h.source_index for h in workspace.search(PgnQuery(player="alpha"))], [0])
        self.assertEqual([h.source_index for h in workspace.search(PgnQuery(event="promotion"))], [1])
        self.assertEqual([h.source_index for h in workspace.search(PgnQuery(eco="c50"))], [0])
        self.assertEqual([h.source_index for h in workspace.search(PgnQuery(result="1/2-1/2"))], [1])
        self.assertEqual([h.source_index for h in workspace.search(PgnQuery(text="sicilian"))], [0])
        self.assertEqual([h.source_index for h in workspace.search(PgnQuery(text="a8=Q+"))], [1])
        self.assertEqual([h.source_index for h in workspace.search(PgnQuery(has_variations=True))], [0])
        self.assertEqual([h.source_index for h in workspace.search(PgnQuery(has_comments=True))], [0])
        self.assertEqual(len(workspace.search(PgnQuery(date_prefix="2026.08"))), 2)

    def test_navigation_has_exact_nested_branch_enter_exit_context(self):
        workspace = PgnWorkspace.from_text(COMPLEX)
        items = workspace.navigation(0)
        kinds = [item.kind for item in items]
        self.assertIn("variation_enter", kinds)
        self.assertIn("variation_exit", kinds)
        enters = [item for item in items if item.kind == "variation_enter"]
        self.assertEqual(len(enters), 2)
        first = enters[0]
        self.assertIsNotNone(first.branch)
        self.assertEqual(first.branch.branch_base.ply_index, 1)
        self.assertEqual(first.branch.return_position.ply_index, 2)
        self.assertEqual(first.branch.attached_to.move_index, 1)
        nested = enters[1]
        self.assertEqual(len(nested.variation.path), 2)

    def test_workspace_resolves_game_variation_move_and_position_refs(self):
        workspace = PgnWorkspace.from_text(COMPLEX)
        root = VariationRef(0)
        child = child_variation(root, 1, 0)
        move = MoveRef(child, 0)
        pos = PositionRef(child, 1)
        self.assertEqual(workspace.resolve_move(move).san, "c5")
        self.assertIs(workspace.resolve_variation(child).moves[0], workspace.resolve_move(move))
        self.assertEqual(workspace.resolve_position(pos), pos)
        self.assertEqual(workspace.branch_context(child).attached_to, MoveRef(root, 1))
        with self.assertRaises(GameReferenceError):
            workspace.resolve_move(MoveRef(VariationRef(999), 0))

    def test_append_allocates_stable_non_colliding_source_indices(self):
        workspace = PgnWorkspace.from_text(COMPLEX)
        added = workspace.append_text('[Event "Third"]\n[Result "*"]\n\n1. d4 d5 *\n')
        self.assertEqual(added, (2,))
        self.assertEqual(workspace.game(2).tags["Event"], "Third")
        removed = workspace.remove(1)
        self.assertEqual(removed.tags["Event"], "Promotion")
        added2 = workspace.append_text('[Event "Fourth"]\n[Result "*"]\n\n1. c4 *\n')
        self.assertEqual(added2, (3,))

    def test_duplicate_groups_use_content_fingerprint_not_source_index(self):
        text = '[Event "Same"]\n[White "A"]\n[Black "B"]\n[Result "*"]\n\n1. e4 *\n'
        workspace = PgnWorkspace.from_text(text)
        workspace.append_text(text)
        self.assertEqual(workspace.duplicate_groups(), ((0, 1),))
        self.assertEqual(workspace.fingerprint(0), workspace.fingerprint(1))

    def test_selected_export_preserves_requested_order_and_reparses(self):
        workspace = PgnWorkspace.from_text(COMPLEX)
        exported = workspace.export_text([1, 0])
        games = parse_games(exported)
        self.assertEqual([g.tags["Event"] for g in games], ["Promotion", "Accessible Open"])

    def test_malformed_records_surface_typed_errors_without_dropping_game(self):
        bad = '[Event "Bad"]\n[SetUp "1"]\n[Result "2-0"]\n\n1. e4 (1... c5 {unterminated\n'
        workspace, report = import_pgn(bad)
        self.assertEqual(len(workspace), 1)
        self.assertEqual(report.stats.games, 1)
        self.assertGreater(report.games[0].error_count, 0)
        self.assertGreater(report.stats.warnings + report.stats.errors, 0)
        self.assertFalse(report.games[0].usable)
        self.assertTrue(workspace.export_text())

    def test_semicolon_and_escape_content_remain_loss_aware(self):
        text = '%escape record\n[Event "Comments"]\n[Result "*"]\n\n1. e4 ; line comment\n1... e5 {brace} *\n'
        workspace = PgnWorkspace.from_text(text)
        exported = workspace.export_text()
        self.assertIn('%escape record', exported)
        self.assertIn('line comment', exported)
        self.assertIn('brace', exported)
        reparsed = PgnWorkspace.from_text(exported)
        self.assertEqual(reparsed.game(0).line.moves[0].comments_after[0].text.strip(), 'line comment')
        workspace.assert_round_trip()

    def test_setup_fen_and_special_notation_are_preserved_structurally(self):
        workspace = PgnWorkspace.from_text(COMPLEX)
        game = workspace.game(1)
        self.assertEqual(game.tags["SetUp"], "1")
        self.assertTrue(game.tags["FEN"].startswith("8/P7"))
        sans = [m.san for m in game.line.moves]
        self.assertIn("a8=Q+", sans)
        self.assertIn("Qxh1+", sans)
        reparsed = parse_games(workspace.export_text())
        self.assertEqual(reparsed[1].tags["FEN"], game.tags["FEN"])
        self.assertEqual([m.san for m in reparsed[1].line.moves], sans)

    def test_large_thousand_game_collection_round_trip_and_search(self):
        records = []
        for i in range(1000):
            result = "1-0" if i % 3 == 0 else ("0-1" if i % 3 == 1 else "1/2-1/2")
            records.append(
                f'[Event "Corpus {i}"]\n'
                f'[Site "Site {i % 10}"]\n'
                f'[Date "2026.08.{(i % 28) + 1:02d}"]\n'
                f'[White "White {i % 50}"]\n'
                f'[Black "Black {i % 40}"]\n'
                f'[Result "{result}"]\n\n'
                f'1. e4 e5 (1... c5 2. Nf3 d6) 2. Nf3 Nc6 3. Bb5 a6 {result}\n'
            )
        text = "\n".join(records)
        workspace = PgnWorkspace.from_text(text)
        self.assertEqual(len(workspace), 1000)
        stats = workspace.stats()
        self.assertEqual(stats.games, 1000)
        self.assertEqual(stats.mainline_plies, 6000)
        self.assertEqual(stats.recursive_plies, 9000)
        self.assertEqual(stats.variations, 1000)
        self.assertEqual(len(workspace.search(PgnQuery(site="Site 3"))), 100)
        self.assertGreater(len(workspace.search(PgnQuery(player="White 7"))), 0)
        exported = workspace.export_text()
        reparsed = parse_games(exported)
        self.assertEqual(len(reparsed), 1000)
        for original, again in zip(workspace.games[::97], reparsed[::97]):
            self.assertEqual(structural_signature(original), structural_signature(again))

    def test_constructor_rejects_duplicate_source_identity(self):
        games = parse_games('[Result "*"]\n\n1. e4 *\n[Result "*"]\n\n1. d4 *\n')
        games[1].source_index = games[0].source_index
        with self.assertRaises(PgnWorkspaceError):
            PgnWorkspace(games)


if __name__ == "__main__":
    unittest.main()
