from __future__ import annotations

import unittest

from acs.acsdb import AcsDatabase
from acs.search_service import (
    GameSearchQuery,
    GameSearchService,
    SearchCancelledError,
    SearchControlError,
)


class D07LibrarySearchCancellationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = AcsDatabase()
        source_id = self.db.add_source("large-library.pgn", "pgn")
        rows = [
            (
                source_id,
                index,
                "full",
                "[]",
                f"Event {index % 17}",
                "Site",
                "2026.08.23",
                str(index),
                f"Player {index}",
                f"Opponent {index}",
                "1-0",
                "A00",
                "Opening",
                None,
                "*",
            )
            for index in range(1, 6001)
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

    def test_immediate_cancellation_fails_before_sql_and_preserves_database(self) -> None:
        before = self.db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
        calls = 0

        def cancelled() -> bool:
            nonlocal calls
            calls += 1
            return True

        with self.assertRaisesRegex(SearchCancelledError, "cancelled"):
            self.service.search(GameSearchQuery(player="Player"), cancel_check=cancelled)

        self.assertEqual(calls, 1)
        self.assertEqual(
            self.db.conn.execute("SELECT COUNT(*) FROM games").fetchone()[0],
            before,
        )

    def test_unicode_scan_is_cancelled_from_sqlite_progress_handler(self) -> None:
        calls = 0

        def cancel_during_scan() -> bool:
            nonlocal calls
            calls += 1
            # Call 1 is the preflight check. Requiring call 3 proves SQLite
            # invoked the VM progress handler rather than only pre/post polling.
            return calls >= 3

        with self.assertRaisesRegex(SearchCancelledError, "cancelled"):
            self.service.search(
                GameSearchQuery(player="not-present-in-any-row", limit=200),
                cancel_check=cancel_during_scan,
            )

        self.assertGreaterEqual(calls, 3)

    def test_cancelled_search_cleans_progress_handler_and_connection_is_reusable(self) -> None:
        calls = 0

        def cancel_during_scan() -> bool:
            nonlocal calls
            calls += 1
            return calls >= 3

        with self.assertRaises(SearchCancelledError):
            self.service.search(
                GameSearchQuery(player="not-present-in-any-row", limit=200),
                cancel_check=cancel_during_scan,
            )

        page = self.service.search(GameSearchQuery(player="Player 42", limit=20))
        self.assertTrue(any(item.white == "Player 42" for item in page.items))

    def test_cancellation_callback_must_be_callable_and_return_exact_bool(self) -> None:
        with self.assertRaisesRegex(TypeError, "cancel_check must be callable"):
            self.service.search(GameSearchQuery(), cancel_check=1)  # type: ignore[arg-type]

        def coercive_result():
            return 1

        with self.assertRaisesRegex(SearchControlError, "boolean"):
            self.service.search(GameSearchQuery(), cancel_check=coercive_result)

    def test_cancellation_callback_failure_is_sanitized_and_connection_recovers(self) -> None:
        calls = 0

        def broken_during_scan() -> bool:
            nonlocal calls
            calls += 1
            if calls >= 3:
                raise RuntimeError("secret callback implementation detail")
            return False

        with self.assertRaisesRegex(SearchControlError, "cancellation check failed") as captured:
            self.service.search(
                GameSearchQuery(player="not-present-in-any-row", limit=200),
                cancel_check=broken_during_scan,
            )
        self.assertNotIn("secret callback implementation detail", str(captured.exception))

        page = self.service.search(GameSearchQuery(after_game_id=5990, limit=20))
        self.assertEqual([item.game_id for item in page.items], list(range(5991, 6001)))

    def test_non_cancelled_search_preserves_paging_and_unicode_semantics(self) -> None:
        calls = 0

        def continue_searching() -> bool:
            nonlocal calls
            calls += 1
            return False

        first = self.service.search(
            GameSearchQuery(player="PLAYER", limit=17),
            cancel_check=continue_searching,
        )
        second = self.service.search(
            GameSearchQuery(
                player="PLAYER",
                limit=17,
                after_game_id=first.next_after_game_id,
            ),
            cancel_check=continue_searching,
        )

        self.assertTrue(first.has_more)
        self.assertTrue(second.has_more)
        self.assertEqual(len(first.items), 17)
        self.assertEqual(len(second.items), 17)
        self.assertTrue(
            {item.game_id for item in first.items}.isdisjoint(
                {item.game_id for item in second.items}
            )
        )
        self.assertGreater(calls, 2)


if __name__ == "__main__":
    unittest.main()
