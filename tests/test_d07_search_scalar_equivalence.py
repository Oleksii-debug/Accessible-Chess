from __future__ import annotations

import unittest

from acs.acsdb import AcsDatabase
from acs.search_service import GameSearchQuery, GameSearchService


class D07SearchScalarEquivalenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = AcsDatabase()
        self.source_one = self.db.add_source("one.pgn", "pgn")
        self.source_two = self.db.add_source("two.pgn", "pgn")
        rows = [
            (self.source_one, 1, "full", "[]", "E1", "Kyiv", "2026.08.23", "1", "A", "B", "1-0", "C20", "O1", None, "*"),
            (self.source_one, 2, "full", "[]", "E2", "Kyiv", "2026.08.23", "2", "C", "D", "0-1", "C21", "O2", None, "*"),
            (self.source_two, 1, "full", "[]", "E3", "Kyiv", "2026.08.23", "3", "E", "F", "1/2-1/2", "C22", "O3", None, "*"),
            (self.source_two, 2, "full", "[]", "E4", "Kyiv", "2026.08.23", "4", "G", "H", "*", "C23", "O4", None, "*"),
        ]
        with self.db.conn:
            self.db.conn.executemany(
                """INSERT INTO games(
                    source_id, source_index, import_status, warnings_json,
                    event, site, game_date, round, white, black, result,
                    eco, opening, start_fen, pgn_text
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )
        self.service = GameSearchService(self.db)

    def tearDown(self) -> None:
        self.db.close()

    def _direct_ids(self, **kwargs) -> list[int]:
        return [int(row["id"]) for row in self.db.search_games(**kwargs)]

    def _service_ids(self, **kwargs) -> list[int]:
        return [
            item.game_id
            for item in self.service.search(GameSearchQuery(**kwargs)).items
        ]

    def _assert_same_error(self, direct_kwargs, service_kwargs, error_type, message: str) -> None:
        with self.assertRaisesRegex(error_type, message):
            self.db.search_games(**direct_kwargs)
        with self.assertRaisesRegex(error_type, message):
            self.service.search(GameSearchQuery(**service_kwargs))

    def test_source_id_scalar_contract_is_identical(self) -> None:
        for value in (True, 1.0, "1"):
            with self.subTest(value=value, kind="type"):
                self._assert_same_error(
                    {"source_id": value},
                    {"source_id": value},
                    TypeError,
                    "source_id must be an integer",
                )
        for value in (0, -1):
            with self.subTest(value=value, kind="positive"):
                self._assert_same_error(
                    {"source_id": value},
                    {"source_id": value},
                    ValueError,
                    "source_id must be a positive integer",
                )
        too_large = 1 << 63
        self._assert_same_error(
            {"source_id": too_large},
            {"source_id": too_large},
            ValueError,
            "source_id exceeds SQLite integer range",
        )

    def test_result_scalar_contract_is_identical(self) -> None:
        for value in ("", "win", 1):
            with self.subTest(value=value):
                self._assert_same_error(
                    {"result": value},
                    {"result": value},
                    ValueError,
                    "Unsupported chess result:",
                )

    def test_search_limit_contracts_remain_layer_specific_and_bounded(self) -> None:
        with self.assertRaisesRegex(TypeError, "limit must be an integer"):
            self.db.search_games(limit=True)
        with self.assertRaisesRegex(TypeError, "limit must be an integer"):
            self.service.search(GameSearchQuery(limit=True))

        self.assertEqual(self._direct_ids(limit=0), [1])
        self.assertEqual(self._direct_ids(limit=201), [1, 2, 3, 4])
        self.assertEqual(self._direct_ids(limit=100000), [1, 2, 3, 4])

        for value in (0, -1, 201, 1000):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    ValueError,
                    "Search limit must be between 1 and 200",
                ):
                    self.service.search(GameSearchQuery(limit=value))

    def test_valid_source_result_and_explicit_page_limits_match(self) -> None:
        cases = [
            ({"source_id": self.source_one, "limit": 200}, [1, 2]),
            ({"source_id": self.source_two, "result": "*", "limit": 2}, [4]),
            ({"result": "1-0", "limit": 1}, [1]),
            ({"result": "0-1", "limit": 200}, [2]),
            ({"result": "1/2-1/2", "limit": 200}, [3]),
        ]
        for kwargs, expected in cases:
            with self.subTest(kwargs=kwargs):
                direct = self._direct_ids(**kwargs)
                service = self._service_ids(**kwargs)
                self.assertEqual(direct, expected)
                self.assertEqual(direct, service)


if __name__ == "__main__":
    unittest.main()
