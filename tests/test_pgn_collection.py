import unittest

from acs.pgn_collection import (
    DuplicatePolicy,
    audit_references,
    collection_digest,
    export_pages,
    merge_text,
    search_page,
)
from acs.pgn_workspace import PgnQuery, PgnWorkspace


GAME_A = '''[Event "A"]
[White "Alpha"]
[Black "Beta"]
[Result "1-0"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0
'''

GAME_B = '''[Event "B"]
[White "Gamma"]
[Black "Delta"]
[Result "*"]

1. d4 d5 (1... Nf6 2. c4 e6) 2. c4 e6 *
'''

BAD = '''[Event "Bad"]
[SetUp "1"]
[Result "2-0"]

1. e4 *
'''


class PgnCollectionTests(unittest.TestCase):
    def test_merge_is_atomic_and_does_not_mutate_original_workspace(self):
        original = PgnWorkspace.from_text(GAME_A)
        digest_before = collection_digest(original)
        merged, report = merge_text(original, GAME_B)
        self.assertEqual(len(original), 1)
        self.assertEqual(collection_digest(original), digest_before)
        self.assertEqual(len(merged), 2)
        self.assertEqual(report.before_count, 1)
        self.assertEqual(report.after_count, 2)
        self.assertEqual(report.added, 1)
        self.assertEqual(report.decisions[0].assigned_source_index, 1)

    def test_skip_existing_duplicate_uses_canonical_fingerprint(self):
        original = PgnWorkspace.from_text(GAME_A)
        merged, report = merge_text(original, GAME_A, duplicate_policy=DuplicatePolicy.SKIP_EXISTING)
        self.assertEqual(len(merged), 1)
        self.assertEqual(report.added, 0)
        self.assertEqual(report.skipped_duplicate, 1)
        self.assertEqual(report.decisions[0].duplicate_of, 0)

    def test_keep_policy_retains_existing_duplicate_as_new_source_identity(self):
        original = PgnWorkspace.from_text(GAME_A)
        merged, report = merge_text(original, GAME_A, duplicate_policy=DuplicatePolicy.KEEP)
        self.assertEqual(len(merged), 2)
        self.assertEqual(report.added, 1)
        self.assertEqual(merged.game(1).tags["Event"], "A")
        self.assertEqual(merged.duplicate_groups(), ((0, 1),))

    def test_skip_all_collapses_duplicates_inside_one_incoming_batch(self):
        merged, report = merge_text(PgnWorkspace(), GAME_A + "\n" + GAME_A, duplicate_policy=DuplicatePolicy.SKIP_ALL)
        self.assertEqual(len(merged), 1)
        self.assertEqual(report.added, 1)
        self.assertEqual(report.skipped_duplicate, 1)
        self.assertEqual(report.decisions[1].duplicate_of, 0)

    def test_usable_only_rejects_semantically_broken_records_without_partial_merge(self):
        original = PgnWorkspace.from_text(GAME_A)
        merged, report = merge_text(original, BAD + "\n" + GAME_B, usable_only=True)
        self.assertEqual(len(original), 1)
        self.assertEqual(len(merged), 2)
        self.assertEqual(report.skipped_unusable, 1)
        self.assertEqual(report.added, 1)
        rejected = [item for item in report.decisions if item.action == "skipped_unusable"]
        self.assertEqual(len(rejected), 1)
        self.assertGreater(rejected[0].error_count, 0)

    def test_search_page_is_deterministic_and_bounded(self):
        records = []
        for i in range(2500):
            records.append(
                f'[Event "Corpus {i}"]\n[Site "Site {i % 25}"]\n[White "White {i % 100}"]\n[Black "Black {i % 80}"]\n[Result "*"]\n\n1. e4 e5 2. Nf3 Nc6 *\n'
            )
        workspace = PgnWorkspace.from_text("\n".join(records))
        page1 = search_page(workspace, PgnQuery(site="Site 7"), offset=0, limit=40)
        page2 = search_page(workspace, PgnQuery(site="Site 7"), offset=40, limit=40)
        self.assertEqual(page1.total, 100)
        self.assertEqual(len(page1.hits), 40)
        self.assertEqual(page1.next_offset, 40)
        self.assertEqual(len(page2.hits), 40)
        self.assertEqual(page2.next_offset, 80)
        self.assertTrue(set(h.source_index for h in page1.hits).isdisjoint(h.source_index for h in page2.hits))
        with self.assertRaises(ValueError):
            search_page(workspace, PgnQuery(), offset=-1)
        with self.assertRaises(ValueError):
            search_page(workspace, PgnQuery(), limit=1001)

    def test_export_pages_preserves_all_games_and_order(self):
        records = [f'[Event "G{i}"]\n[Result "*"]\n\n1. e4 *\n' for i in range(2105)]
        workspace = PgnWorkspace.from_text("\n".join(records))
        chunks = export_pages(workspace, games_per_page=1000)
        self.assertEqual(len(chunks), 3)
        reparsed = []
        for chunk in chunks:
            reparsed.extend(PgnWorkspace.from_text(chunk).games)
        self.assertEqual(len(reparsed), 2105)
        self.assertEqual(reparsed[0].tags["Event"], "G0")
        self.assertEqual(reparsed[-1].tags["Event"], "G2104")

    def test_collection_digest_is_content_and_order_sensitive(self):
        ab = PgnWorkspace.from_text(GAME_A + "\n" + GAME_B)
        ba = PgnWorkspace.from_text(GAME_B + "\n" + GAME_A)
        same = PgnWorkspace.from_text(ab.export_text())
        self.assertNotEqual(collection_digest(ab), collection_digest(ba))
        self.assertEqual(collection_digest(ab), collection_digest(same))

    def test_reference_audit_covers_nested_variations_and_positions(self):
        report = audit_references(PgnWorkspace.from_text(GAME_A + "\n" + GAME_B))
        self.assertEqual(report.games, 2)
        self.assertEqual(report.moves, 13)
        self.assertGreaterEqual(report.positions, report.moves + report.games)
        self.assertEqual(report.variations, 3)

    def test_large_five_thousand_game_merge_dedup_and_page_cycle(self):
        records = []
        for i in range(5000):
            records.append(
                f'[Event "Scale {i}"]\n[Site "S{i % 50}"]\n[White "W{i % 200}"]\n[Black "B{i % 150}"]\n[Result "*"]\n\n1. e4 e5 (1... c5 2. Nf3 d6) 2. Nf3 Nc6 *\n'
            )
        merged, report = merge_text(PgnWorkspace(), "\n".join(records), duplicate_policy=DuplicatePolicy.SKIP_ALL)
        self.assertEqual(report.added, 5000)
        self.assertEqual(len(merged), 5000)
        self.assertEqual(len(export_pages(merged, games_per_page=750)), 7)
        page = search_page(merged, PgnQuery(site="S17"), limit=100)
        self.assertEqual(page.total, 100)
        self.assertEqual(len(page.hits), 100)
        self.assertIsNone(page.next_offset)
        merged.assert_round_trip()


if __name__ == "__main__":
    unittest.main()
