from __future__ import annotations

import os
import tempfile
import unittest

from acs.acsdb import AcsDatabase
from acs.gametree import PgnGame, VariationLine
from acs.library_import_service import LibraryImportService
from acs.library_source_service import (
    LibrarySourceCatalogService,
    SourceCatalogCancelledError,
    SourceCatalogControlError,
    SourceCatalogQuery,
)


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


def game(index: int, *, warning: bool = False, event: str | None = None) -> PgnGame:
    return PgnGame(
        tags={
            "Event": event or f"Catalog {index}",
            "White": f"White {index}",
            "Black": f"Black {index}",
            "Result": "*",
        },
        line=VariationLine(result="*"),
        source_index=index,
        warnings=["fixture warning"] if warning else [],
    )


class V2LibrarySourceCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = AcsDatabase(":memory:")
        self.importer = LibraryImportService(self.db)
        self.catalog = LibrarySourceCatalogService(self.db)

    def tearDown(self) -> None:
        self.db.close()

    def _import(
        self,
        digest: str,
        *,
        source_name: str,
        source_format: str = "pgn",
        games: tuple[PgnGame, ...] | None = None,
        source_warning_count: int = 0,
    ):
        return self.importer.import_games(
            games or (game(0),),
            source_name=source_name,
            source_format=source_format,
            source_sha256=digest,
            source_warning_count=source_warning_count,
        )

    def test_repeated_source_is_one_catalog_item_with_attempt_provenance(self) -> None:
        games = (game(0), game(1, warning=True), game(2))
        first = self._import(
            DIGEST_A,
            source_name="original.pgn",
            source_format="PGN",
            games=games,
        )
        repeated = self._import(
            DIGEST_A.upper(),
            source_name="renamed-copy.pgn",
            source_format="pgn",
            games=games,
            source_warning_count=2,
        )
        self.assertTrue(repeated.reused)
        self.assertEqual(repeated.source_id, first.source_id)

        page = self.catalog.list_sources()
        self.assertFalse(page.has_more)
        self.assertIsNone(page.next_after_source_id)
        self.assertEqual(len(page.items), 1)
        item = page.items[0]
        self.assertEqual(item.source_id, first.source_id)
        self.assertEqual(item.source_name, "original.pgn")
        self.assertEqual(item.source_format, "pgn")
        self.assertEqual(item.source_sha256, DIGEST_A)
        self.assertEqual(item.game_count, 3)
        self.assertEqual(item.full_game_count, 2)
        self.assertEqual(item.warning_game_count, 1)
        self.assertEqual(item.partial_game_count, 0)
        self.assertEqual(item.damaged_game_count, 0)
        self.assertEqual(item.first_game_id, first.first_game_id)
        self.assertEqual(item.last_game_id, first.last_game_id)
        self.assertEqual(item.attempt_count, 2)
        self.assertEqual(item.latest_attempt_id, repeated.attempt_id)
        self.assertEqual(item.latest_attempt_status, "warning")

        attempts = self.db.list_import_attempts(limit=10)
        self.assertEqual(
            [row["source_name"] for row in attempts],
            ["renamed-copy.pgn", "original.pgn"],
        )

    def test_status_rollup_and_empty_raw_source_are_explicit(self) -> None:
        full = self._import(DIGEST_A, source_name="full.pgn", games=(game(0), game(1)))
        warning = self._import(
            DIGEST_B,
            source_name="warning.pgn",
            games=(game(0, warning=True), game(1, warning=True)),
        )
        empty_source = self.db.add_source("empty-source.pgn", "pgn", DIGEST_C)

        items = {item.source_id: item for item in self.catalog.list_sources().items}
        self.assertEqual(items[full.source_id].game_count, 2)
        self.assertEqual(items[full.source_id].full_game_count, 2)
        self.assertEqual(items[full.source_id].attempt_count, 1)
        self.assertEqual(items[warning.source_id].warning_game_count, 2)
        self.assertEqual(items[warning.source_id].full_game_count, 0)
        self.assertEqual(items[warning.source_id].attempt_count, 1)

        empty = items[empty_source]
        self.assertEqual(empty.game_count, 0)
        self.assertEqual(empty.full_game_count, 0)
        self.assertEqual(empty.warning_game_count, 0)
        self.assertEqual(empty.partial_game_count, 0)
        self.assertEqual(empty.damaged_game_count, 0)
        self.assertIsNone(empty.first_game_id)
        self.assertIsNone(empty.last_game_id)
        self.assertEqual(empty.attempt_count, 0)
        self.assertIsNone(empty.latest_attempt_id)
        self.assertIsNone(empty.latest_attempt_status)

    def test_format_filter_is_exact_case_insensitive_and_blank_means_all(self) -> None:
        first = self._import(DIGEST_A, source_name="one.pgn", source_format="PGN")
        second = self._import(DIGEST_B, source_name="two.cbh", source_format="cbh")
        self.assertEqual(
            [item.source_id for item in self.catalog.list_sources(SourceCatalogQuery(source_format=" pGn ")).items],
            [first.source_id],
        )
        self.assertEqual(
            [item.source_id for item in self.catalog.list_sources(SourceCatalogQuery(source_format="CBH")).items],
            [second.source_id],
        )
        self.assertEqual(
            [item.source_id for item in self.catalog.list_sources(SourceCatalogQuery(source_format="   ")).items],
            [first.source_id, second.source_id],
        )

    def test_keyset_paging_is_stable_when_new_source_is_appended(self) -> None:
        first = self._import(DIGEST_A, source_name="one.pgn")
        second = self._import(DIGEST_B, source_name="two.pgn")
        third = self._import(DIGEST_C, source_name="three.pgn")

        page1 = self.catalog.list_sources(SourceCatalogQuery(limit=2))
        self.assertEqual([item.source_id for item in page1.items], [first.source_id, second.source_id])
        self.assertTrue(page1.has_more)
        self.assertEqual(page1.next_after_source_id, second.source_id)

        fourth = self._import("d" * 64, source_name="four.pgn")
        page2 = self.catalog.list_sources(
            SourceCatalogQuery(after_source_id=page1.next_after_source_id, limit=2)
        )
        self.assertEqual([item.source_id for item in page2.items], [third.source_id, fourth.source_id])
        self.assertFalse(page2.has_more)
        self.assertIsNone(page2.next_after_source_id)
        self.assertTrue(
            set(item.source_id for item in page1.items).isdisjoint(
                item.source_id for item in page2.items
            )
        )

    def test_get_source_returns_detached_aggregate_or_none(self) -> None:
        result = self._import(DIGEST_A, source_name="one.pgn", games=(game(0), game(1)))
        item = self.catalog.get_source(result.source_id)
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.game_count, 2)
        self.assertEqual(item.attempt_count, 1)
        self.assertIsNone(self.catalog.get_source(result.source_id + 100))

    def test_source_games_delegates_canonical_game_search_and_keyset_paging(self) -> None:
        result = self._import(
            DIGEST_A,
            source_name="games.pgn",
            games=tuple(game(i) for i in range(5)),
        )
        first = self.catalog.source_games(result.source_id, limit=2)
        self.assertEqual(len(first.items), 2)
        self.assertTrue(first.has_more)
        self.assertIsNotNone(first.next_after_game_id)
        self.assertTrue(all(item.source_id == result.source_id for item in first.items))

        second = self.catalog.source_games(
            result.source_id,
            after_game_id=first.next_after_game_id,
            limit=2,
        )
        third = self.catalog.source_games(
            result.source_id,
            after_game_id=second.next_after_game_id,
            limit=2,
        )
        ids = [
            *(item.game_id for item in first.items),
            *(item.game_id for item in second.items),
            *(item.game_id for item in third.items),
        ]
        self.assertEqual(len(ids), 5)
        self.assertEqual(len(set(ids)), 5)
        self.assertFalse(third.has_more)
        self.assertIsNone(third.next_after_game_id)

    def test_catalog_remains_canonical_when_search_projection_is_dirty_but_source_games_fails_closed(self) -> None:
        result = self._import(DIGEST_A, source_name="dirty.pgn", games=(game(0),))
        game_id = result.first_game_id
        with self.db.conn:
            self.db.conn.execute("DELETE FROM game_search_fold WHERE game_id=?", (game_id,))

        source = self.catalog.get_source(result.source_id)
        self.assertIsNotNone(source)
        assert source is not None
        self.assertEqual(source.game_count, 1)
        with self.assertRaisesRegex(RuntimeError, "search projection integrity"):
            self.catalog.source_games(result.source_id)

    def test_query_scalars_fail_closed_before_sql(self) -> None:
        with self.assertRaises(TypeError):
            SourceCatalogQuery(after_source_id=True).normalized()
        with self.assertRaises(ValueError):
            SourceCatalogQuery(after_source_id=0).normalized()
        with self.assertRaises(TypeError):
            SourceCatalogQuery(limit=False).normalized()
        with self.assertRaises(ValueError):
            SourceCatalogQuery(limit=201).normalized()
        with self.assertRaises(TypeError):
            SourceCatalogQuery(source_format=3).normalized()
        with self.assertRaises(ValueError):
            SourceCatalogQuery(source_format="x" * 65).normalized()
        with self.assertRaises(ValueError):
            SourceCatalogQuery(source_format="pg\x00n").normalized()
        with self.assertRaises(TypeError):
            self.catalog.get_source(True)
        with self.assertRaises(ValueError):
            self.catalog.get_source(0)
        with self.assertRaises(TypeError):
            self.catalog.source_games(False)

    def test_immediate_cancel_and_callback_contract_are_sanitized_and_connection_recovers(self) -> None:
        self._import(DIGEST_A, source_name="one.pgn")
        with self.assertRaises(SourceCatalogCancelledError):
            self.catalog.list_sources(cancel_check=lambda: True)
        with self.assertRaises(TypeError):
            self.catalog.list_sources(cancel_check=True)  # type: ignore[arg-type]
        with self.assertRaisesRegex(SourceCatalogControlError, "must return a boolean"):
            self.catalog.list_sources(cancel_check=lambda: 1)  # type: ignore[return-value]

        def broken() -> bool:
            raise RuntimeError("private callback detail")

        with self.assertRaisesRegex(SourceCatalogControlError, "cancellation check failed") as caught:
            self.catalog.list_sources(cancel_check=broken)
        self.assertNotIn("private callback detail", str(caught.exception))
        self.assertEqual(len(self.catalog.list_sources().items), 1)

    def test_in_query_cancellation_cleans_sqlite_progress_handler(self) -> None:
        # Build enough canonical child rows that SQLite must enter the VM progress
        # hook while aggregating a bounded page.  Publication uses owned DB APIs;
        # the source catalog itself remains read-only.
        for source_no in range(80):
            source = self.db.add_source(
                f"source-{source_no}.pgn",
                "pgn",
                f"{source_no:064x}",
            )
            for ply in range(12):
                self.db.store_game(game(ply), source)

        polls = 0

        def cancel_during_sql() -> bool:
            nonlocal polls
            polls += 1
            return polls >= 3

        with self.assertRaises(SourceCatalogCancelledError):
            self.catalog.list_sources(
                SourceCatalogQuery(limit=80),
                cancel_check=cancel_during_sql,
            )
        self.assertGreaterEqual(polls, 3)
        self.assertEqual(len(self.catalog.list_sources(SourceCatalogQuery(limit=80)).items), 80)

    def test_close_reopen_preserves_catalog_and_repeated_attempt_aggregate(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".acsdb")
        os.close(fd)
        try:
            with AcsDatabase(path) as database:
                importer = LibraryImportService(database)
                first = importer.import_games(
                    tuple(game(i, warning=(i == 2)) for i in range(6)),
                    source_name="persist.pgn",
                    source_format="pgn",
                    source_sha256=DIGEST_A,
                )
                repeated = importer.import_games(
                    tuple(game(i, warning=(i == 2)) for i in range(6)),
                    source_name="renamed-persist.pgn",
                    source_format="PGN",
                    source_sha256=DIGEST_A.upper(),
                )
                self.assertTrue(repeated.reused)
                before = LibrarySourceCatalogService(database).get_source(first.source_id)
                self.assertIsNotNone(before)
                self.assertEqual(database.verify_integrity(), database.schema_version)

            with AcsDatabase(path) as reopened:
                after = LibrarySourceCatalogService(reopened).get_source(first.source_id)
                self.assertEqual(after, before)
                assert after is not None
                self.assertEqual(after.game_count, 6)
                self.assertEqual(after.warning_game_count, 1)
                self.assertEqual(after.attempt_count, 2)
                self.assertEqual(after.latest_attempt_id, repeated.attempt_id)
                self.assertEqual(reopened.verify_integrity(), reopened.schema_version)
        finally:
            if os.path.exists(path):
                os.unlink(path)


if __name__ == "__main__":
    unittest.main()
