import unittest

from acs.acsdb_catalog import AcsCatalogDatabase
from acs.gametree import serialize_game
from acs.pgn_collection import DuplicatePolicy, audit_references, merge_text, search_page
from acs.pgn_workspace import PgnQuery, PgnWorkspace


class FutureDataVerticalIntegrationTests(unittest.TestCase):
    def test_workspace_merge_to_catalog_search_and_exact_tree_retrieval(self):
        source_a = '''[Event "Vertical A"]
[Site "Kyiv"]
[White "Alpha"]
[Black "Beta"]
[Annotator "Coach"]
[Opening "Sicilian"]
[Result "*"]

1. e4 c5 (1... e5 2. Nf3 Nc6) 2. Nf3 d6 *
'''
        source_b = '''[Event "Vertical B"]
[Site "Uzhhorod"]
[White "Gamma"]
[Black "Delta"]
[Annotator "Coach"]
[Opening "Queen's Gambit"]
[Result "1-0"]

1. d4 d5 2. c4 e6 3. Nc3 Nf6 1-0
'''
        workspace, first = merge_text(PgnWorkspace(), source_a, duplicate_policy=DuplicatePolicy.SKIP_ALL)
        workspace, second = merge_text(workspace, source_b, duplicate_policy=DuplicatePolicy.SKIP_ALL)
        self.assertEqual(first.added + second.added, 2)
        audit = audit_references(workspace)
        self.assertEqual(audit.games, 2)
        self.assertGreater(audit.moves, 0)

        db = AcsCatalogDatabase()
        outcome = db.import_collection_atomic(workspace.export_text(), source_name="vertical.pgn")
        self.assertEqual(outcome.inserted, 2)
        hits = db.search_catalog(annotator="coach")
        self.assertEqual(len(hits), 2)
        sicilian = db.search_catalog(opening="sicilian")
        self.assertEqual(len(sicilian), 1)

        game_id = sicilian[0]["id"]
        restored = db.retrieve_game_tree(game_id)
        expected = workspace.game(0)
        self.assertEqual(serialize_game(restored), serialize_game(expected))
        integrity = db.integrity_report()
        self.assertEqual(integrity["quick_check"], "ok")
        self.assertEqual(integrity["foreign_key_errors"], [])
        self.assertEqual(integrity["games"], 2)
        self.assertEqual(integrity["indexed_games"], 2)
        db.close()

    def test_duplicate_policy_stays_consistent_across_workspace_and_catalog(self):
        game = '''[Event "Duplicate"]
[White "Same"]
[Black "Same2"]
[Result "*"]

1. e4 e5 *
'''
        workspace, report = merge_text(PgnWorkspace(), game + "\n" + game, duplicate_policy=DuplicatePolicy.SKIP_ALL)
        self.assertEqual(report.added, 1)
        self.assertEqual(report.skipped_duplicate, 1)

        db = AcsCatalogDatabase()
        first = db.import_collection_atomic(workspace.export_text(), source_name="one.pgn")
        second = db.import_collection_atomic(workspace.export_text(), source_name="two.pgn")
        self.assertEqual(first.inserted, 1)
        self.assertEqual(second.inserted, 0)
        self.assertEqual(second.duplicates, 1)
        db.close()

    def test_large_1200_game_vertical_slice(self):
        records = []
        for i in range(1200):
            records.append(
                f'[Event "Vertical {i}"]\n'
                f'[Site "Site {i % 12}"]\n'
                f'[White "Player {i % 100}"]\n'
                f'[Black "Opponent {i % 90}"]\n'
                f'[Annotator "Annotator {i % 10}"]\n'
                f'[Opening "Opening {i % 20}"]\n'
                '[Result "*"]\n\n'
                '1. e4 e5 (1... c5 2. Nf3 d6) 2. Nf3 Nc6 *\n'
            )
        workspace, report = merge_text(PgnWorkspace(), "\n".join(records), duplicate_policy=DuplicatePolicy.SKIP_ALL)
        self.assertEqual(report.added, 1200)
        page = search_page(workspace, PgnQuery(site="Site 3"), limit=100)
        self.assertEqual(page.total, 100)

        db = AcsCatalogDatabase()
        outcome = db.import_collection_atomic(workspace.export_text(), source_name="large-vertical.pgn")
        self.assertEqual(outcome.inserted, 1200)
        hits = db.search_catalog(opening="Opening 7", limit=5000)
        self.assertEqual(len(hits), 60)
        restored = db.retrieve_game_tree(hits[0]["id"])
        self.assertIn("Opening 7", serialize_game(restored))
        integrity = db.integrity_report()
        self.assertEqual(integrity["quick_check"], "ok")
        self.assertEqual(integrity["games"], 1200)
        self.assertEqual(integrity["indexed_games"], 1200)
        db.close()


if __name__ == "__main__":
    unittest.main()
