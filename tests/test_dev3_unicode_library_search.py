from __future__ import annotations

import unittest

from acs.acsdb import AcsDatabase
from acs.search_service import GameSearchQuery, GameSearchService


UNICODE_PGN = """[Event \"Český Pohár — Café\"]
[Site \"Košice SVK\"]
[Date \"2026.08.22\"]
[Round \"1\"]
[White \"Žofia Šachová\"]
[Black \"Олексій Дьордяй\"]
[Result \"1-0\"]
[ECO \"Č42\"]
[Opening \"Straße Attack\"]

1. e4 e5 2. Nf3 Nc6 1-0
"""


class UnicodeLibrarySearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = AcsDatabase(":memory:")
        self.db.import_pgn_text(UNICODE_PGN, source_name="Košice-ČESKÝ.pgn")
        self.service = GameSearchService(self.db)

    def tearDown(self) -> None:
        self.db.close()

    def _single(self, **kwargs):
        page = self.service.search(GameSearchQuery(**kwargs))
        self.assertEqual(len(page.items), 1)
        return page.items[0]

    def test_cyrillic_player_search_is_unicode_case_insensitive(self) -> None:
        item = self._single(player="ОЛЕКСІЙ")
        self.assertEqual(item.black, "Олексій Дьордяй")

    def test_accented_latin_player_event_and_source_search_ignore_case(self) -> None:
        self.assertEqual(self._single(player="žOFIA").white, "Žofia Šachová")
        self.assertEqual(self._single(event="ČESKÝ").event, "Český Pohár — Café")
        self.assertEqual(self._single(source_name="KOŠICE-český").source_name, "Košice-ČESKÝ.pgn")

    def test_casefold_handles_multi_character_unicode_equivalence(self) -> None:
        item = self._single(opening="STRASSE")
        self.assertEqual(item.opening, "Straße Attack")

    def test_nfkc_normalization_handles_canonically_equivalent_query_text(self) -> None:
        decomposed_cafe = "CAFE\u0301"
        item = self._single(event=decomposed_cafe)
        self.assertEqual(item.event, "Český Pohár — Café")

    def test_unicode_eco_prefix_and_keyset_contract_remain_stable(self) -> None:
        item = self._single(eco="č4")
        self.assertEqual(item.eco, "Č42")

        first = self.service.search(GameSearchQuery(limit=1))
        self.assertEqual(len(first.items), 1)
        self.assertFalse(first.has_more)
        self.assertIsNone(first.next_after_game_id)

    def test_normalization_length_bound_applies_after_nfkc(self) -> None:
        # Full-width Latin letters normalize to ASCII before the existing 256-char
        # search-resource limit is checked.
        normalized = GameSearchQuery(player="Ａ" * 256).normalized()
        self.assertEqual(normalized.player, "A" * 256)
        with self.assertRaisesRegex(ValueError, "maximum search term length"):
            GameSearchQuery(player="Ａ" * 257).normalized()


if __name__ == "__main__":
    unittest.main()
