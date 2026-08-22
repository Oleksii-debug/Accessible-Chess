import unittest

from acs.acsdb import AcsDatabase


class AcsDatabaseQueryPlanTests(unittest.TestCase):
    def setUp(self):
        self.db = AcsDatabase(":memory:")
        self.source_id = self.db.add_source("bulk.pgn", "pgn", "a" * 64)
        rows = []
        for index in range(5000):
            rows.append(
                (
                    self.source_id,
                    index,
                    "full",
                    "[]",
                    "Candidates" if index % 5 == 0 else "League",
                    f"White {index}",
                    f"Black {index}",
                    "1-0" if index % 2 == 0 else "0-1",
                    f"B{index % 100:02d}",
                    "Sicilian Defense" if index % 7 == 0 else "Other",
                    "*",
                )
            )
        with self.db.conn:
            self.db.conn.executemany(
                """INSERT INTO games(
                       source_id, source_index, import_status, warnings_json,
                       event, white, black, result, eco, opening, pgn_text
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )
            attempts = [
                (
                    f"source-{index}.pgn",
                    "pgn",
                    f"{index:064x}"[-64:],
                    f"2026-08-21T00:{index % 60:02d}:00+00:00",
                    "full" if index % 2 == 0 else "warning",
                    self.source_id,
                )
                for index in range(300)
            ]
            self.db.conn.executemany(
                """INSERT INTO import_attempts(
                       source_name, source_format, sha256, started_at, status, source_id
                   ) VALUES(?,?,?,?,?,?)""",
                attempts,
            )
            fen = "8/8/8/8/8/8/8/8 w - - 0 1"
            key = self.db.position_key(fen)
            self.db.conn.executemany(
                "INSERT INTO positions(game_id, ply, fen, position_key) VALUES(?,?,?,?)",
                [(game_id, game_id % 80, fen, key) for game_id in range(1, 5001)],
            )

    def tearDown(self):
        self.db.close()

    def _plan_for(self, call):
        statements = []

        def trace(sql):
            if sql.lstrip().upper().startswith("SELECT"):
                statements.append(sql)

        self.db.conn.set_trace_callback(trace)
        try:
            result = call()
        finally:
            self.db.conn.set_trace_callback(None)
        self.assertTrue(statements, "expected the public query to execute SELECT")
        plan = [
            row[3]
            for row in self.db.conn.execute(
                "EXPLAIN QUERY PLAN " + statements[-1]
            ).fetchall()
        ]
        return result, plan

    def assertNoTempSort(self, plan):
        self.assertFalse(
            any("USE TEMP B-TREE" in detail for detail in plan),
            "keyset/LIMIT query must not materialize a sorted result set: " + repr(plan),
        )

    def test_large_game_search_is_bounded_and_pages_without_offset(self):
        capped = self.db.search_games(limit=100000)
        self.assertEqual(len(capped), 1000)

        seen = []
        cursor = None
        while True:
            page = self.db.search_games(after_id=cursor, limit=137)
            if not page:
                break
            ids = [row["id"] for row in page]
            self.assertEqual(ids, sorted(ids))
            self.assertTrue(set(seen).isdisjoint(ids))
            seen.extend(ids)
            cursor = ids[-1]

        self.assertEqual(len(seen), 5000)
        self.assertEqual(seen, list(range(1, 5001)))

    def test_unfiltered_and_exact_filter_keyset_plans_avoid_temp_sort(self):
        _, unfiltered = self._plan_for(
            lambda: self.db.search_games(after_id=2000, limit=25)
        )
        self.assertTrue(
            any("INTEGER PRIMARY KEY" in detail and "rowid>?" in detail for detail in unfiltered),
            unfiltered,
        )
        self.assertNoTempSort(unfiltered)

        _, by_result = self._plan_for(
            lambda: self.db.search_games(result="1-0", after_id=2000, limit=25)
        )
        self.assertTrue(any("idx_games_result" in detail for detail in by_result), by_result)
        self.assertNoTempSort(by_result)

        _, by_source = self._plan_for(
            lambda: self.db.search_games(source_id=self.source_id, after_id=2000, limit=25)
        )
        self.assertTrue(any("idx_games_source" in detail for detail in by_source), by_source)
        self.assertNoTempSort(by_source)

    def test_eco_prefix_preserves_streaming_id_order_without_temp_sort(self):
        rows, plan = self._plan_for(
            lambda: self.db.search_games(eco="b2", after_id=1000, limit=25)
        )
        self.assertLessEqual(len(rows), 25)
        self.assertEqual([row["id"] for row in rows], sorted(row["id"] for row in rows))
        self.assertNoTempSort(plan)
        self.assertTrue(any("SEARCH g" in detail for detail in plan), plan)

    def test_import_attempt_keyset_filters_use_existing_indexes_without_temp_sort(self):
        _, by_status = self._plan_for(
            lambda: self.db.list_import_attempts(status="full", before_id=250, limit=25)
        )
        self.assertTrue(
            any("idx_import_attempts_status" in detail for detail in by_status), by_status
        )
        self.assertNoTempSort(by_status)

        digest = f"{200:064x}"[-64:]
        _, by_digest = self._plan_for(
            lambda: self.db.list_import_attempts(sha256=digest, before_id=250, limit=25)
        )
        self.assertTrue(
            any("idx_import_attempts_sha256" in detail for detail in by_digest), by_digest
        )
        self.assertNoTempSort(by_digest)

    def test_exact_position_plan_uses_composite_covering_index_and_stable_page(self):
        fen = "8/8/8/8/8/8/8/8 w - - 17 99"
        rows, plan = self._plan_for(
            lambda: self.db.search_position(
                fen,
                after_game_id=2000,
                after_ply=2000 % 80,
                limit=31,
            )
        )
        self.assertEqual(len(rows), 31)
        cursor_pairs = [(row["id"], row["matched_ply"]) for row in rows]
        self.assertEqual(cursor_pairs, sorted(cursor_pairs))
        self.assertTrue(
            any("idx_positions_key_game_ply" in detail for detail in plan), plan
        )
        self.assertNoTempSort(plan)


if __name__ == "__main__":
    unittest.main()
